"""Inspect actual GATT services with mesh control paused; never deliver keys."""
import asyncio,json,paramiko,sys
from ha_recovery import PRIVATE,ROOT,TARGET,ws,refresh_session
async def main():
 refresh_session()
 entries=await ws({'type':'config_entries/get'})
 original=next(e['disabled_by'] for e in entries if e['entry_id']==TARGET)
 try:
  await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'})
  options=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
  remote=paramiko.SSHClient();remote.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  remote.connect('192.168.4.198',username=options['username'],password=options['password'],look_for_keys=False,allow_agent=False,timeout=10)
  program='''import asyncio,json
from bleak import BleakClient,BleakScanner
async def main():
 client=None
 report={'services':[]}
 try:
  device='DC:23:52:81:60:BB'
  if WATCH:
   future=asyncio.get_running_loop().create_future()
   def heard(found,advertisement):
    if found.address.upper()==device and '00001827-0000-1000-8000-00805f9b34fb' in advertisement.service_uuids and not future.done():future.set_result(found)
   async with BleakScanner(detection_callback=heard):
    print('ARMED_NATIVE_GATT_CAPTURE',flush=True)
    device=await asyncio.wait_for(future,180)
  client=BleakClient(device,timeout=12)
  await asyncio.wait_for(client.connect(),20)
  for service in client.services:
   report['services'].append({'uuid':service.uuid,'handle':service.handle,'characteristics':[{'uuid':c.uuid,'handle':c.handle,'properties':c.properties} for c in service.characteristics]})
 except Exception as exc:
  report['failure_type']=type(exc).__name__;report['reason']=str(exc)[:220]
 finally:
  try:
   if client is not None:await asyncio.wait_for(client.disconnect(),5)
  except Exception:pass
  print(json.dumps(report))
asyncio.run(main())
'''.replace('WATCH',str('--watch' in sys.argv))
  inp,out,_=remote.exec_command('sudo -n docker exec -i homeassistant python3 -',timeout=215)
  inp.write(program);inp.flush();inp.channel.shutdown_write()
  if '--watch' in sys.argv:
   print((await asyncio.to_thread(out.readline)).strip(),flush=True)
  result=json.loads((await asyncio.to_thread(out.read)).decode())
  (ROOT/'reports/native-gatt-services.json').write_text(json.dumps(result,indent=2))
  print(json.dumps(result,indent=2),flush=True);remote.close()
 finally:
  await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':original})
asyncio.run(main())
