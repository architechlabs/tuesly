"""Import verified manual configuration through HA's existing admin service."""
import asyncio,json,sys
from ha_recovery import PRIVATE,ROOT,rest,ws,TARGET,PROVIDER
sys.path.insert(0,str(ROOT/'custom_components/tuesly/lib'))
from tuesly_mesh.sig_mesh_crypto import k3
async def main():
    state=json.loads((PRIVATE/'esp-repair-journal.json').read_text())['data']
    verified=json.loads((PRIVATE/'diagnostic-journal.json').read_text())
    node=state['nodes']['DC:23:52:81:60:BB'];ready=verified['nodes']['DC:23:52:81:60:BB']
    if (verified['net_key']!=state['net_key'] or ready.get('dev_key')!=node['dev_key']
            or ready.get('address')!=node['address'] or ready.get('status')!='ready'
            or ready.get('binding_revision')!=3):
        raise RuntimeError('The current repair does not have verified matching configuration')
    payload={'address':'DC:23:52:81:60:BB','device_key':node['dev_key'],
             'network_id':k3(bytes.fromhex(state['net_key'])).hex(),'primary':node['address'],
             'elements':node['elements'],'sequence_high':state['sequence_high'],
             'bindings_verified':True,'proxy_verified':bool(ready.get('proxy_enabled'))}
    if ready.get('temperature_profile'):payload['temperature_profile']=ready['temperature_profile']
    await asyncio.to_thread(rest,'/api/services/tuesly/import_commissioning',payload)
    await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':None})
    print('Verified configuration saved; ESPHome provider enabled',flush=True)
    await asyncio.sleep(4)
    await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':None})
    print('Tuesly runtime enabled with current keys and verified bindings',flush=True)
asyncio.run(main())
