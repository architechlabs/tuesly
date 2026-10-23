"""Emulate incomplete HA setup, verify autonomous reboot, restore HA entries."""
import asyncio,json,time,yaml
from aioesphomeapi import APIClient
from aioesphomeapi.api_pb2 import LogLevel
from ha_recovery import ROOT,PRIVATE,TARGET,PROVIDER,ws,refresh_session

async def main():
 refresh_session();entries=await ws({'type':'config_entries/get'})
 originals={e['entry_id']:e['disabled_by'] for e in entries if e['entry_id'] in (TARGET,PROVIDER)}
 config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
 def client(name):return APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info=name)
 api=None;report={'passed':False,'firmware':'1.1.8'}
 try:
  for entry in (TARGET,PROVIDER):await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':'user'})
  api=client('Home Assistant Tuesly readiness validation')
  closed=asyncio.Event()
  async def stopped(expected):closed.set()
  start=time.monotonic()
  await asyncio.wait_for(api.connect(login=True,on_stop=stopped),12)
  info=await asyncio.wait_for(api.device_info(),5)
  if info.project_version!='1.1.8' or info.mac_address.upper()!='44:1D:64:F6:B5:FC':
   raise RuntimeError('Recovery validation target does not match')
  warnings=[]
  def logged(message):
   text=message.message.decode(errors='replace')
   if 'Home Assistant API setup did not finish' in text:warnings.append(text)
  api.subscribe_logs(logged,LogLevel.LOG_LEVEL_WARN)
  print('EMULATED_INCOMPLETE_HA_SETUP: waiting for the 90-second firmware recovery',flush=True)
  await asyncio.wait_for(closed.wait(),115)
  report['disconnect_seconds']=round(time.monotonic()-start,2)
  report['recovery_warning_received']=bool(warnings)
  await api.disconnect(force=True);api=None
  deadline=time.monotonic()+45
  while time.monotonic()<deadline:
   probe=client('tuesly-recovery-validation')
   try:
    await asyncio.wait_for(probe.connect(login=True),6)
    info=await asyncio.wait_for(probe.device_info(),4)
    entities,_=await asyncio.wait_for(probe.list_entities_services(),6)
    uptime_key=next(e.key for e in entities if e.name=='Uptime')
    uptime=asyncio.get_running_loop().create_future()
    def state(message):
     if getattr(message,'key',None)==uptime_key and not uptime.done():uptime.set_result(message.state)
    probe.subscribe_states(state)
    value=await asyncio.wait_for(uptime,6)
    report.update(entity_count=len(entities),post_recovery_uptime=value,
      passed=(info.project_version=='1.1.8' and len(entities)>=15 and value<30
              and 1<=report['disconnect_seconds']<=115
              and (report['recovery_warning_received'] or report['disconnect_seconds']>=75)))
    break
   except Exception as exc:report['last_probe_error']=type(exc).__name__
   finally:await probe.disconnect(force=True)
   await asyncio.sleep(3)
 except Exception as exc:report['failure_type']=type(exc).__name__
 finally:
  if api is not None:await api.disconnect(force=True)
  for entry in (PROVIDER,TARGET):
   try:await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':originals[entry]})
   except Exception as exc:report['restore_error']=type(exc).__name__
  (ROOT/'reports/api-readiness-recovery-1.1.8.json').write_text(json.dumps(report,indent=2))
  print(json.dumps(report,indent=2),flush=True)
asyncio.run(main())
