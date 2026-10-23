"""Read-only contract check for HA's live Bluetooth websocket API."""
import asyncio,json,time
import websockets
from ha_recovery import session,refresh_session,ROOT
async def main():
 refresh_session();s=session();report={'subscribed':False,'events':0,'raw_events':0,'target_events':0}
 async with websockets.connect(s['base'].replace('http:','ws:')+'/api/websocket',max_size=8*1024*1024) as stream:
  await stream.recv();await stream.send(json.dumps({'type':'auth','access_token':s['access_token']}))
  if json.loads(await stream.recv()).get('type')!='auth_ok':raise RuntimeError('HA authentication failed')
  await stream.send(json.dumps({'id':1,'type':'bluetooth/subscribe_advertisements'}))
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   try:message=json.loads(await asyncio.wait_for(stream.recv(),deadline-time.monotonic()))
   except TimeoutError:break
   if message.get('type')=='result':report['subscribed']=bool(message.get('success'))
   for event in message.get('event',{}).get('add',[]):
    report['events']+=1;report['raw_events']+=bool(event.get('raw'))
    if event.get('address','').upper()=='DC:23:52:81:60:BB':
     report['target_events']+=1
     report['last_target']={key:event.get(key) for key in ('source','time','raw','connectable')}
 (ROOT/'reports/advertisement-stream-contract.json').write_text(json.dumps(report,indent=2))
 print(json.dumps(report))
asyncio.run(main())
