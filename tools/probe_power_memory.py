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
MAC='DC:23:52:81:60:BB';SOURCE=0x7ffd
original=json.loads(Path('/config/.storage/tuesly.mesh').read_text())['data']
assert original['address_next']<SOURCE
class Store:
 path=Path('/config/.storage/tuesly.dp33-diagnostic')
 async def async_load(self):
  state=copy.deepcopy(original);state['sequence_high']=0
  if self.path.exists():
   old=json.loads(self.path.read_text())
   assert old['net_key']==state['net_key']
   state['sequence_high']=old['sequence_high']
  return state
 async def async_save(self,state):
  temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(state));temporary.replace(self.path)
async def main():
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
  target=int(MAC.replace(':',''),16)
  seen=asyncio.Event()
  cancel_ads=api.subscribe_bluetooth_le_advertisements(lambda message:seen.set() if any(adv.address==target for adv in message.advertisements) else None)
  await asyncio.wait_for(seen.wait(),8)
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
   future=asyncio.get_running_loop().create_future()
   def received(src,opcode,params):
    if src==node['address'] and opcode>0xffff:print(json.dumps({'vendor_opcode':hex(opcode),'params':params.hex()}),flush=True)
    if src==node['address'] and opcode==0xcdd007 and not future.done():future.set_result(params)
   device._access_callbacks.append(received)
   await device.send_vendor_command(bytes.fromhex('ccd007010121'))
   params=await asyncio.wait_for(future,8)
   print(json.dumps({'dp33_response':params.hex()}),flush=True)
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
  await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'})
  if '--esp' in sys.argv:
   await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':'user'})
   provider_paused=True
  c=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
  r=paramiko.SSHClient();r.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  await asyncio.to_thread(r.connect,'192.168.4.198',username=c['username'],password=c['password'],look_for_keys=False,allow_agent=False,timeout=10)
  program=PROGRAM;config={}
  if '--esp' in sys.argv:
   from inspect_mesh import GATTAdapter
   from ha_recovery import ROOT
   config['esp_key']=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())['tuya_api_encryption_key']
   program=program.replace('asyncio.run(asyncio.wait_for(main(),65))',inspect.getsource(GATTAdapter)+'\nasyncio.run(asyncio.wait_for(main(),65))')
  inp,out,err=r.exec_command('sudo -n docker exec -i homeassistant python3 -u -c '+shlex.quote(program),timeout=85)
  inp.write(json.dumps(config));inp.flush();inp.channel.shutdown_write()
  output=await asyncio.to_thread(out.read)
  print(output.decode(errors='replace'),flush=True)
  if out.channel.recv_exit_status():print((await asyncio.to_thread(err.read)).decode(errors='replace')[-1800:])
  (PRIVATE/'dp33-probe-result.txt').write_bytes(output)
 finally:
  if r:r.close()
  try:
   if provider_paused:await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':provider_original})
  finally:await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':original})
if __name__=='__main__':asyncio.run(main())
