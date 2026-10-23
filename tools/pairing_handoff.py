"""Prepare before physical reset; submit only after its confirmation."""
import asyncio,json,sys,runpy
from ha_recovery import ROOT,PRIVATE,ws,rest,refresh_session,TARGET,PROVIDER

FILE=PRIVATE/'prepared-pairing.json'
COMPETITORS=('01M4AZ160HZRX3N2AT8QKWEWG8','01M4G0VZNTVVFHR46EYDNB2RQ4')

async def restore(saved):
    for entry in (PROVIDER,TARGET,*COMPETITORS):
        if entry in saved:
            await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':saved[entry]})

async def main():
    refresh_session()
    if sys.argv[1]=='prepare':
        entries=await ws({'type':'config_entries/get'})
        saved={e['entry_id']:e['disabled_by'] for e in entries if e['entry_id'] in (TARGET,PROVIDER,*COMPETITORS)}
        FILE.write_text(json.dumps({'restore':saved}))
        try:
            for entry in (TARGET,*COMPETITORS):
                await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':'user'})
            await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':None})
            flow=await asyncio.to_thread(rest,'/api/config/config_entries/flow',{'handler':'tuesly','entry_id':TARGET})
            if flow.get('step_id')!='sig_repair':raise RuntimeError('Repair flow unavailable')
            FILE.write_text(json.dumps({'flow_id':flow['flow_id'],'restore':saved}))
            print('READY FOR RESET: receivers enabled; commissioning has NOT started',flush=True)
        except BaseException:
            await restore(saved);raise
    elif sys.argv[1]=='restore':
        await restore(json.loads(FILE.read_text())['restore']);print('Entries restored')
    elif sys.argv[1]=='finish':
        saved=json.loads(FILE.read_text());report={}
        try:
            result=await asyncio.to_thread(rest,'/api/config/config_entries/flow/'+saved['flow_id'],
                {'recommission':True,'reset_confirmed':True},timeout=180)
            report['paired']=result.get('reason')=='reconfigure_successful'
            report['errors']=result.get('errors')
            print(json.dumps(report),flush=True)
            await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':None})
            if report['paired']:
                await asyncio.to_thread(runpy.run_path,str(ROOT/'tools/validate_ha_controls.py'))
        finally:
            (ROOT/'reports/prepared-pairing-result.json').write_text(json.dumps(report,indent=2))
            await restore(saved['restore'])

if __name__=='__main__':asyncio.run(main())
