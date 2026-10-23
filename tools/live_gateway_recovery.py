"""Authorized bench recovery via HA public APIs; never opens USB serial."""
import asyncio,json,sys,time
from pathlib import Path
from ha_recovery import rest,ws,refresh_session,PROVIDER,TARGET

async def inventory():
    registry=await ws({'type':'config/entity_registry/list'})
    ids=[item['entity_id'] for item in registry if item.get('config_entry_id')==PROVIDER]
    states=rest('/api/states')
    selected=[s for s in states if s['entity_id'] in ids and any(key in s['entity_id'] for key in ('uptime','gateway_online','restart','ip_address','free_heap'))]
    return [{k:s.get(k) for k in ('entity_id','state','last_reported')} for s in selected]

async def main():
    refresh_session()
    action=sys.argv[1]
    if action=='inventory':print(json.dumps(await inventory(),indent=2));return
    if action=='resume':
        await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':None})
        flow=rest('/api/config/config_entries/flow',{'handler':'tuesly','entry_id':TARGET})
        print('Repair step:',flow.get('step_id'))
        if flow.get('step_id')!='sig_repair':raise RuntimeError('Unexpected repair step')
        result=rest('/api/config/config_entries/flow/'+flow['flow_id'],{'recommission':False,'reset_confirmed':False})
        print('Resume existing keys:',result.get('type'),result.get('reason'));return
    before=await inventory()
    if action=='reload':
        operation=asyncio.create_task(asyncio.to_thread(rest,'/api/config/config_entries/entry/'+PROVIDER+'/reload',{}))
    elif action=='restart':
        buttons=[s['entity_id'] for s in before if s['entity_id'].startswith('button.') and 'restart_gateway' in s['entity_id']]
        if len(buttons)!=1:raise RuntimeError('Restart button not uniquely identified')
        operation=asyncio.create_task(asyncio.to_thread(rest,'/api/services/button/press',{'entity_id':buttons[0]}))
    else:raise RuntimeError('Unknown action')
    checks=[]
    deadline=time.monotonic()+150
    while time.monotonic()<deadline:
        try:
            state=await inventory();entries=await ws({'type':'config_entries/get'})
            row={'elapsed':round(150-(deadline-time.monotonic()),1),'states':state,
                 'entries':[{k:e.get(k) for k in ('domain','state','reason')} for e in entries if e['entry_id'] in (PROVIDER,TARGET)]}
            checks.append(row);print(json.dumps(row),flush=True)
        except Exception as exc:print('Monitor:',type(exc).__name__,flush=True)
        await asyncio.sleep(5)
    try:print('Action result:',await operation)
    except Exception as exc:print('Action error:',type(exc).__name__)
    path=Path(__file__).resolve().parents[1]/'reports'/('live-gateway-'+action+'.json')
    path.write_text(json.dumps({'before':before,'checks':checks},indent=2),encoding='utf-8')

if __name__=='__main__':asyncio.run(main())
