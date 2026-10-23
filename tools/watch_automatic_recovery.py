"""Observe the running service; no reset, pairing or timing trigger from chat."""
import json,shlex
from deploy_recovery_addon import ssh
from ha_recovery import ROOT
PROGRAM='''import asyncio,json,time
from pathlib import Path
from service import HA
async def main():
 options=json.loads(Path('/data/options.json').read_text());ha=HA(options)
 deadline=time.monotonic()+600;previous=None;checks=[];started=time.time()
 print('AUTOMATIC_SERVICE_OBSERVER_READY',flush=True)
 while time.monotonic()<deadline:
  status=json.loads(Path('/data/status.json').read_text())
  state=await ha.rest('/api/states/'+options['enrolled'][0]['entity_id'])
  row={'phase':status['phase'],'phase_at':status['updated_at'],'light':state['state'],'at':time.time()}
  signature=(row['phase'],row['light'])
  if signature!=previous:
   print(json.dumps(row),flush=True);checks.append(row);previous=signature
  if status['updated_at']>=started and status['phase']=='recovered' and state['state'] in ('on','off'):
   print(json.dumps({'finished':True,'automatic_recovery_passed':True,'checks':checks}),flush=True);return
  await asyncio.sleep(3)
 print(json.dumps({'finished':True,'automatic_recovery_passed':False,'checks':checks}),flush=True)
asyncio.run(main())
'''
remote=ssh();report=[]
try:
    _,out,err=remote.exec_command('sudo -n docker exec app_local_tuesly_recovery python -u -c '+shlex.quote(PROGRAM),timeout=680)
    for line in out:
        line=line.strip()
        print(line,flush=True)
        if line.startswith('{'):report.append(json.loads(line))
    if out.channel.recv_exit_status():print('Observer exited before completion')
finally:
    remote.close()
    (ROOT/'reports/automatic-recovery-observation.json').write_text(json.dumps(report,indent=2))
