"""Bounded DP33 read through Pi Bluetooth, with the HA light entry paused.

Uses a separate durable sender sequence journal. Never provisions or resets.
"""
import asyncio,json,paramiko,shlex,sys,inspect,yaml
from ha_recovery import PRIVATE,ws,TARGET,PROVIDER,refresh_session
PROGRAM=r'''
import asyncio,json,sys,types,copy
from pathlib import Path
base=Path('/config/custom_components/tuesly')
sys.path.insert(0,str(base/'lib'))
package=types.ModuleType('custom_components.tuesly');package.__path__=[str(base)]
sys.modules['custom_components.tuesly']=package
from custom_components.tuesly.sig_controller import ManagedMeshDevice
from custom_components.tuesly.mesh_store import MeshJournal
from tuesly_mesh.secrets import DictSecretsManager
from bleak import BleakClient
config=json.load(sys.stdin)
MAC='DC:23:52:81:60:BB';SOURCE=1 if config.get('ha_source') else 0x7ffd
original=json.loads(Path('/config/.storage/tuesly.mesh').read_text())['data']
assert SOURCE==1 or original['address_next']<SOURCE
class Store:
 path=Path('/config/.storage/tuesly.dp33-source1' if SOURCE==1 else '/config/.storage/tuesly.dp33-diagnostic')
 async def async_load(self):
  state=copy.deepcopy(original);state['sequence_high']=original['sequence_high'] if SOURCE==1 else 0
  if self.path.exists():
   old=json.loads(self.path.read_text())
   assert old['net_key']==state['net_key']
   if SOURCE==1:
    assert old['sequence_high']<=state['sequence_high']
   else:state['sequence_high']=old['sequence_high']
  return state
 async def async_save(self,state):
  temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(state));temporary.replace(self.path)
async def main():
 if SOURCE==1:
  # Reserve a disjoint lease through HA's existing admin service. The service
  # durably advances HA's sender and discards its RAM lease before this probe
  # transmits. HA resumes above this probe's entire range, never below it.
  import urllib.request
  from tuesly_mesh.sig_mesh_crypto import k3
  n=original['nodes'][MAC];end=original['sequence_high']+256
  assert end<0x1000000
  payload={'address':MAC,'device_key':n['dev_key'],'network_id':k3(bytes.fromhex(original['net_key'])).hex(),
      'primary':n['address'],'elements':n['elements'],'sequence_high':end}
  def reserve():
   request=urllib.request.Request(config['ha_base']+'/api/services/tuesly/import_commissioning',
       data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+config['ha_token'],'Content-Type':'application/json'})
   with urllib.request.urlopen(request,timeout=15) as response:response.read()
  await asyncio.to_thread(reserve)
  print(json.dumps({'ha_sender_lease_reserved':True}),flush=True)
 journal=await MeshJournal(Store()).load();node=journal.state['nodes'][MAC]
 secrets=DictSecretsManager({'probe-net-key/password':original['net_key'],'probe-app-key/password':original['app_key'],f'probe-dev-key-{node["address"]:04x}/password':node['dev_key']})
 async def connect(ble_device,disconnected_callback=None):
  client=BleakClient(MAC,disconnected_callback=disconnected_callback,timeout=12)
  await client.connect();return client
 api=None
 if config.get('esp_key'):
  from aioesphomeapi import APIClient
  api=APIClient('192.168.20.181',6053,noise_psk=config['esp_key'],client_info='tuesly-dp33-read-only-probe')
  await asyncio.wait_for(api.connect(login=True),10)
  info=await api.device_info()
  assert info.mac_address.upper()=='44:1D:64:F6:B5:FC'
  capabilities=await api.device_capabilities_compat(info)
  from aioesphomeapi.model import BluetoothScannerMode
  api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
  target=int(MAC.replace(':',''),16)
  seen=asyncio.Event()
  cancel_ads=api.subscribe_bluetooth_le_raw_advertisements(lambda message:seen.set() if any(adv.address==target for adv in message.advertisements) else None)
  try:
   await asyncio.wait_for(seen.wait(),6)
   print(json.dumps({'stage':'fresh_gateway_advertisement'}),flush=True)
  except TimeoutError:print(json.dumps({'stage':'connecting_known_enrolled_address'}),flush=True)
  # HA's target entry is paused. Release only a stale link to this enrolled
  # driver, never reboot the gateway or disconnect unrelated BLE devices.
  try:await api.bluetooth_device_disconnect(target,timeout=5)
  except Exception:pass
  await asyncio.sleep(1)
  await api.bluetooth_device_connect(target,lambda *args:None,timeout=12,feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=0)
  services=await api.bluetooth_gatt_get_services(target)
  adapter=GATTAdapter(api,target,services)
  async def connect(ble_device,disconnected_callback=None):
   adapter.disconnected=disconnected_callback
   return adapter
 device=ManagedMeshDevice(MAC,node['address'],SOURCE,secrets,op_item_prefix='probe',iv_index=original['iv_index'],journal=journal,ble_device_callback=lambda address:types.SimpleNamespace(address=address),ble_connect_callback=connect)
 device._node_primary=node['address']
 device._status_destinations=set(range(0xc000,0xff00))
 original_notify=device._process_notify
 async def trace(data):
  if data and data[0]==0 and device._keys:
   from tuesly_mesh.sig_mesh_protocol import decrypt_network_pdu
   k=device._keys;p=decrypt_network_pdu(k.enc_key,k.priv_key,k.nid,data[1:],k.iv_index)
   if p and p.src==node['address']:print(json.dumps({'packet_src':p.src,'packet_dst':p.dst,'ctl':p.ctl}),flush=True)
  await original_notify(data)
 device._process_notify=trace
 try:
  async with asyncio.timeout(35):
   await device.connect(timeout=12,max_retries=1);await device.configure_filter()
   print(json.dumps({'stage':'authenticated_proxy'}),flush=True)
   future=asyncio.get_running_loop().create_future()
   onoff=asyncio.get_running_loop().create_future()
   power_up=asyncio.get_running_loop().create_future()
   def received(src,opcode,params):
    if src==node['address'] and opcode>0xffff:print(json.dumps({'vendor_opcode':hex(opcode),'params':params.hex()}),flush=True)
    if src==node['address'] and opcode==0xcdd007 and not future.done():future.set_result(params)
    if src==node['address'] and opcode==0x8204 and not onoff.done():onoff.set_result(params)
    if src==node['address'] and opcode==0x8212 and not power_up.done():power_up.set_result(params)
   device._access_callbacks.append(received)
   await device.send_vendor_command(bytes.fromhex('ccd007010122' if config.get('dnd_only') else 'ccd00701022122'))
   try:
    params=await asyncio.wait_for(future,5)
    print(json.dumps({'dp33_response':params.hex()}),flush=True)
   except TimeoutError:print(json.dumps({'dp33_read':'no_reply'}),flush=True)
   await device.send_vendor_command(bytes.fromhex('8201'))
   params=await asyncio.wait_for(onoff,5)
   print(json.dumps({'onoff_response':params.hex()}),flush=True)
   await device.send_vendor_command(bytes.fromhex('8211'))
   try:print(json.dumps({'generic_power_up':(await asyncio.wait_for(power_up,3)).hex()}),flush=True)
   except TimeoutError:print(json.dumps({'generic_power_up':'no_reply'}),flush=True)
   if config.get('dnd_only'):
    # Isolate the short, unsegmented DND setting from the RAW memory DP.
    # Preserve DP33 and all brightness/temperature fields.
    for name,payload in [('dnd_write','c9d00701220101'),('dnd_readback','ccd007010122')]:
     future=asyncio.get_running_loop().create_future()
     await device.send_vendor_command(bytes.fromhex(payload))
     try:print(json.dumps({name:(await asyncio.wait_for(future,5)).hex()}),flush=True)
     except TimeoutError:print(json.dumps({name:'no_reply'}),flush=True)
    onoff=asyncio.get_running_loop().create_future()
    from tuesly_mesh.sig_mesh_protocol import generic_onoff_set
    tid=(node.get('tid',0)+1)&255
    await journal.update(MAC,tid=tid)
    await device.send_vendor_command(generic_onoff_set(False,tid))
    print(json.dumps({'off_confirmed':(await asyncio.wait_for(onoff,5)).hex()}),flush=True)
   if config.get('apply_memory'):
    from tuesly_mesh.sig_power_memory import write_power_policy,READ_POWER_POLICY
    # Mode Restore ignores custom HSV/brightness/temperature fields. This
    # applies the requested policy, not a custom lighting state or LED command.
    payload,_=write_power_policy(bytes(12),True)
    future=asyncio.get_running_loop().create_future()
    await device.send_vendor_command(payload)
    try:print(json.dumps({'policy_write_reply':(await asyncio.wait_for(future,6)).hex()}),flush=True)
    except TimeoutError:print(json.dumps({'policy_write':'not_acknowledged'}),flush=True)
    future=asyncio.get_running_loop().create_future()
    await device.send_vendor_command(READ_POWER_POLICY)
    try:print(json.dumps({'policy_readback':(await asyncio.wait_for(future,6)).hex()}),flush=True)
    except TimeoutError:print(json.dumps({'policy_readback':'no_reply'}),flush=True)
 except Exception as exc:print(json.dumps({'probe_failed':type(exc).__name__}),flush=True)
 finally:
  try:await asyncio.wait_for(device.disconnect(),8)
  except Exception:pass
  if api:await api.disconnect(force=True)
asyncio.run(asyncio.wait_for(main(),65))
'''
async def main():
 refresh_session()
 entries=await ws({'type':'config_entries/get'})
 original=next(e['disabled_by'] for e in entries if e['entry_id']==TARGET)
 provider_original=next(e['disabled_by'] for e in entries if e['entry_id']==PROVIDER)
 provider_paused=False
 r=None
 try:
  c=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
  r=paramiko.SSHClient();r.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  await asyncio.to_thread(r.connect,'192.168.4.198',username=c['username'],password=c['password'],look_for_keys=False,allow_agent=False,timeout=15,banner_timeout=30,auth_timeout=15)
  await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'})
  if '--esp' in sys.argv:
   await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':'user'})
   provider_paused=True
  program=PROGRAM;config={'apply_memory':'--apply-memory' in sys.argv,'dnd_only':'--dnd-only' in sys.argv}
  if '--ha-source' in sys.argv:
   from ha_recovery import session
   s=session();config.update(ha_source=True,ha_base=s['base'],ha_token=s['access_token'])
  if '--esp' in sys.argv:
   from inspect_mesh import GATTAdapter
   from ha_recovery import ROOT
   config['esp_key']=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())['tuya_api_encryption_key']
   program=program.replace('asyncio.run(asyncio.wait_for(main(),65))',inspect.getsource(GATTAdapter)+'\nasyncio.run(asyncio.wait_for(main(),65))')
  inp,out,err=r.exec_command('sudo -n docker exec -i homeassistant python3 -u -c '+shlex.quote(program),timeout=85)
  inp.write(json.dumps(config));inp.flush();inp.channel.shutdown_write()
  chunks=[]
  while True:
   line=await asyncio.to_thread(out.readline)
   if not line:break
   print(line.strip(),flush=True);chunks.append(line.encode())
  output=b''.join(chunks)
  if out.channel.recv_exit_status():print((await asyncio.to_thread(err.read)).decode(errors='replace')[-1800:])
  (PRIVATE/'dp33-probe-result.txt').write_bytes(output)
 finally:
  if r:r.close()
  try:
   if provider_paused:await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':provider_original})
  finally:await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':original})
if __name__=='__main__':asyncio.run(main())
