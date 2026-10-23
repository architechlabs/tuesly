"""Exercise HA gateway reload and recovery, recording actual online transitions."""
import asyncio,json,time,runpy,sys
from ha_recovery import rest,ws,refresh_session,PROVIDER,ROOT

ONLINE='binary_sensor.lpg_ble_gateway_01_gateway_online'
UPTIME='sensor.lpg_ble_gateway_01_uptime'

def state():
    states={s['entity_id']:s for s in rest('/api/states')}
    return {'online':states[ONLINE]['state'],'uptime':states[UPTIME]['state']}

async def main():
    refresh_session();registry=await ws({'type':'config/entity_registry/list'})
    buttons=[r['entity_id'] for r in registry if r.get('config_entry_id')==PROVIDER and
        r['entity_id'].startswith('button.') and 'recover_bluetooth_gateway' in r['entity_id']]
    if len(buttons)!=1:raise RuntimeError('Recovery button is ambiguous')
    report=[]
    for action in ('reload','recover'):
        before=state();started=time.monotonic()
        if before['online']!='on':raise RuntimeError('Gateway is not online at baseline')
        if action=='reload':
            task=asyncio.create_task(asyncio.to_thread(rest,'/api/config/config_entries/entry/'+PROVIDER+'/reload',{}))
        else:
            task=asyncio.create_task(asyncio.to_thread(rest,'/api/services/button/press',{'entity_id':buttons[0]}))
        checks=[];healthy_since=None;offline=False;passed=False
        while time.monotonic()-started<75:
            current=await asyncio.to_thread(state);elapsed=round(time.monotonic()-started,1)
            checks.append({'seconds':elapsed,**current})
            if current['online']!='on':offline=True;healthy_since=None
            else:
                healthy_since=healthy_since or time.monotonic()
                rebooted=action=='reload' or float(current['uptime'])<float(before['uptime'])
                if task.done() and rebooted and time.monotonic()-healthy_since>=15:
                    passed=True;break
            await asyncio.sleep(2)
        result={'action':action,'passed':passed,'observed_offline':offline,'before':before,'checks':checks}
        try:await task
        except Exception as exc:result['action_error']=type(exc).__name__
        report.append(result)
        print(json.dumps({key:result[key] for key in ('action','passed','observed_offline')}),flush=True)
        if passed and '--controls' in sys.argv:
            await asyncio.to_thread(rest,'/api/services/homeassistant/update_entity',{'entity_id':'light.tuesly_light_81_60_bb'})
            await asyncio.to_thread(runpy.run_path,str(ROOT/'tools/validate_ha_controls.py'))
            version=json.loads((ROOT/'custom_components/tuesly/manifest.json').read_text())['version']
            result['ha_controls_passed']=json.loads((ROOT/'reports'/f'ha-controls-{version}.json').read_text()).get('passed',False)
        (ROOT/'reports/gateway-recovery-live.json').write_text(json.dumps(report,indent=2))
        if not passed:break

if __name__=='__main__':asyncio.run(main())
