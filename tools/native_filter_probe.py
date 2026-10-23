"""Read authenticated proxy identity through native BlueZ; never provision."""
import asyncio,json,sys,types
import paramiko
from ha_recovery import ROOT,PRIVATE,ws,refresh_session,TARGET

async def main():
    refresh_session();entries=await ws({'type':'config_entries/get'})
    original_disabled=next(e['disabled_by'] for e in entries if e['entry_id']==TARGET)
    try:
        await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'})
        from inspect_mesh import modules,PrivateStore,SOURCE
        modules()
        from custom_components.tuesly.mesh_store import MeshJournal
        original=json.loads((PRIVATE/'ha-mesh.json').read_text())['data']
        journal=await MeshJournal(PrivateStore(original)).load()
        sequence=await journal.allocate_sequences()
        # This is the existing reserved diagnostic sender, not HA's sender.
        remote_values=json.dumps({'net_key':original['net_key'],'sequence':sequence,'source':SOURCE,'iv_index':original['iv_index']})
        program="""import asyncio,json,sys,types
sys.path.insert(0,'/config/custom_components/tuesly/lib')
package=types.ModuleType('tuesly_mesh');package.__path__=['/config/custom_components/tuesly/lib/tuesly_mesh'];sys.modules['tuesly_mesh']=package
from bleak import BleakClient
from bleak.exc import BleakError
from tuesly_mesh.sig_mesh_crypto import k2,k3
from tuesly_mesh.sig_mesh_protocol import encrypt_network_pdu,decrypt_network_pdu
from tuesly_mesh.sig_bearer import Reassembler,frames
VALUES=__VALUES__
async def run():
 report={'transport':'native BlueZ','authenticated_mesh':False,'stage':'connecting'};client=BleakClient('DC:23:52:81:60:BB',timeout=15);future=asyncio.get_running_loop().create_future();rx=Reassembler();counts={}
 try:
  await asyncio.wait_for(client.connect(),20)
  report['mesh_services']=[s.uuid for s in client.services if s.uuid.startswith(('00001827','00001828'))]
  service=client.services.get_service('00001828-0000-1000-8000-00805f9b34fb')
  if service is None:report['stage']='proxy_service_missing';return
  out=service.get_characteristic('00002ade-0000-1000-8000-00805f9b34fb');inp=service.get_characteristic('00002add-0000-1000-8000-00805f9b34fb')
  nid,enc,priv=k2(bytes.fromhex(VALUES['net_key']),b'\\x00')
  def notified(sender,data):
   assembled=rx.feed(bytes(data))
   if not assembled:return
   kind=assembled[0];counts[str(kind)]=counts.get(str(kind),0)+1
   if kind==2:
    packet=decrypt_network_pdu(enc,priv,nid,assembled[1:],VALUES['iv_index'],proxy_config=True)
    if packet and packet.ctl==1 and packet.dst==0 and packet.transport_pdu[:1]==b'\\x03' and not future.done():
     future.set_result({'primary':packet.src,'filter_type':packet.transport_pdu[1],'filter_list_size':int.from_bytes(packet.transport_pdu[2:4],'big')})
  await client.start_notify(out,notified)
  pdu=encrypt_network_pdu(enc,priv,nid,ctl=1,ttl=0,seq=VALUES['sequence'],src=VALUES['source'],dst=0,transport_pdu=b'\\x00\\x01',iv_index=VALUES['iv_index'],proxy_config=True)
  for part in frames(b'\\x02'+pdu,23):await client.write_gatt_char(inp,part,response=False)
  report['stage']='filter_status'
  report.update(await asyncio.wait_for(future,15));report['authenticated_mesh']=True
 except Exception as exc:
  report['failure_type']=type(exc).__name__
  if isinstance(exc,BleakError):report['reason']=str(exc)[:240]
 finally:
  report['notification_counts']=counts
  try:await asyncio.wait_for(client.disconnect(),5)
  except Exception:pass
  print(json.dumps(report),flush=True)
asyncio.run(run())
""".replace('__VALUES__',remote_values)
        credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
        client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
        stdin,stdout,stderr=client.exec_command('sudo -n docker exec -i homeassistant python3 -',timeout=55)
        stdin.write(program);stdin.flush();stdin.channel.shutdown_write()
        output=await asyncio.to_thread(stdout.read)
        result=json.loads(output.decode())
        (ROOT/'reports/native-proxy-identity.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True);client.close()
    finally:
        await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':original_disabled})

if __name__=='__main__':asyncio.run(main())
