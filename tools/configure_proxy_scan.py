"""Set the saved ESPHome scan option through HA's public options flow."""
import json,sys
from ha_recovery import rest,PROVIDER,ROOT
result=rest('/api/config/config_entries/options/flow',{'handler':PROVIDER})
fields=result.get('data_schema',[])
print('Options step:',result.get('step_id'),flush=True)
for field in fields:
    if 'bluetooth' in field.get('name','').lower() or 'scan' in field.get('name','').lower():
        print(json.dumps(field),flush=True)
(ROOT/'.private/proxy-options-flow.json').write_text(json.dumps(result),encoding='utf-8')
if '--active' in sys.argv:
    match=[item for item in fields if 'bluetooth' in item.get('name','').lower() or 'scan' in item.get('name','').lower()]
    if len(match)!=1:raise RuntimeError('Bluetooth mode field not uniquely identified')
    values={item['name']:item['default'] for item in fields if 'default' in item}
    values[match[0]['name']]='active'
    reply=rest('/api/config/config_entries/options/flow/'+result['flow_id'],values)
    print('Saved scan mode result:',reply.get('type'),reply.get('errors'),flush=True)
