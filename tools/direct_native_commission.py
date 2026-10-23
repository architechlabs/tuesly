"""One native Pi attempt; journal through HA before delivering mesh credentials."""
import asyncio, json, os, shlex, time
import paramiko
from ha_recovery import PRIVATE, ROOT, TARGET, rest, ws, refresh_session

PROGRAM = r'''
import asyncio,json,sys,types
from bleak import BleakClient,BleakScanner
sys.path.insert(0,'/config/custom_components/tuesly/lib')
package=types.ModuleType('tuesly_mesh');package.__path__=['/config/custom_components/tuesly/lib/tuesly_mesh'];sys.modules['tuesly_mesh']=package
from tuesly_mesh.sig_mesh_provisioner import SIGMeshProvisioner
from tuesly_mesh.sig_mesh_crypto import k3
values=json.loads(sys.stdin.readline())
def emit(kind,**data):print(json.dumps({'kind':kind,**data}),flush=True)
async def main():
 found=asyncio.get_running_loop().create_future()
 def heard(device,advertisement):
  data=advertisement.service_data.get('00001827-0000-1000-8000-00805f9b34fb',b'')
  # A Tuya vendor frame or unprovisioned PB-ADV beacon alone does not
  # establish that the short, connectable PB-GATT window is open.
  if device.address.upper()=='DC:23:52:81:60:BB' and len(data)>=18 and not found.done():found.set_result(device)
 async with BleakScanner(detection_callback=heard,adapter='hci0'):
  emit('armed')
  device=await asyncio.wait_for(found,300)
  emit('fresh_device_received')
  async def connect(device,disconnected_callback=None):
   client=BleakClient(device,adapter='hci0',timeout=12,disconnected_callback=disconnected_callback)
   await asyncio.wait_for(client.connect(),15)
   emit('gatt_services',mesh=[s.uuid for s in client.services if s.uuid.startswith(('00001827','00001828'))])
   return client
  provisioner=SIGMeshProvisioner(bytes.fromhex(values['net_key']),bytes.fromhex(values['app_key']),values['address_next'],iv_index=values['iv_index'],ble_device_callback=lambda address:device,ble_connect_callback=connect)
  async def persist(key,elements):
   emit('private_journal',payload={'address':device.address.upper(),'device_key':key.hex(),'network_id':k3(bytes.fromhex(values['net_key'])).hex(),'primary':values['address_next'],'elements':elements,'sequence_high':values['sequence_high']})
   if await asyncio.to_thread(sys.stdin.readline)!='persisted\n':raise RuntimeError('HA journal did not acknowledge persistence')
  async def handoff(client,result):emit('provisioning_complete')
  provisioner.journal_callback=persist
  provisioner.configuration_callback=handoff
  try:
   await asyncio.wait_for(provisioner.provision(device.address,timeout=12,max_retries=1),90)
   emit('result',passed=True)
  except Exception as exc:
   cause=exc.__cause__ or exc
   emit('result',passed=False,failure_type=type(exc).__name__,cause_type=type(cause).__name__,reason=str(cause)[:240],stage=provisioner.stage,data_attempted=provisioner._provisioning_data_attempted)
try:asyncio.run(main())
except Exception as exc:emit('result',passed=False,failure_type=type(exc).__name__,reason=str(exc)[:240])
'''

async def main():
    refresh_session()
    entries=await ws({'type':'config_entries/get'})
    original=next(e['disabled_by'] for e in entries if e['entry_id']==TARGET)
    await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'})
    report={'transport':'native Pi BlueZ','passed':False}; remote=None
    try:
        # The exact current mesh snapshot was explicitly authorized by the user.
        state=json.loads((PRIVATE/'ha-mesh-current.json').read_text())['data']
        if state['address_next']+254>=0x7fff:raise RuntimeError('Address space exhausted')
        options=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
        remote=paramiko.SSHClient();remote.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        remote.connect('192.168.4.198',username=options['username'],password=options['password'],look_for_keys=False,allow_agent=False,timeout=10)
        inp,out,err=remote.exec_command('sudo -n docker exec -i homeassistant python3 -u -c '+shlex.quote(PROGRAM),timeout=410)
        inp.write(json.dumps({k:state[k] for k in ('net_key','app_key','address_next','iv_index','sequence_high')})+'\n');inp.flush()
        while line:=await asyncio.to_thread(out.readline):
            message=json.loads(line)
            if message['kind']=='private_journal':
                payload=message['payload']
                path=PRIVATE/f'commissioning-receipt-{int(time.time())}.json'
                with path.open('w') as stream:
                    json.dump(payload,stream);stream.flush();os.fsync(stream.fileno())
                await asyncio.to_thread(rest,'/api/services/tuesly/import_commissioning',payload,timeout=30)
                inp.write('persisted\n');inp.flush()
                print('Credentials saved through HA Store before network data delivery',flush=True)
            else:
                print(json.dumps(message),flush=True)
                if message['kind']=='result':
                    if 'kind' not in report:report.update(message)
                    else:report['cleanup_result']=message
        code=out.channel.recv_exit_status()
        if code:report['remote_exit']=code
    finally:
        if remote:remote.close()
        await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':original})
        (ROOT/'reports/direct-native-commissioning.json').write_text(json.dumps(report,indent=2))
    if report['passed']:
        await asyncio.sleep(4)
        print('HA runtime enabled; checking configured control separately',flush=True)

if __name__=='__main__':asyncio.run(main())
