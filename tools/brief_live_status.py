"""Print only relevant live entity state, without private configuration."""
import json
from ha_recovery import rest
for state in rest('/api/states'):
    if ('tuesly_light_81_60_bb' in state['entity_id'] or
        ('lpg_ble_gateway_01' in state['entity_id'] and any(part in state['entity_id']
         for part in ('gateway_online','driver','uptime','free_heap')))):
        print(json.dumps({key:state.get(key) for key in ('entity_id','state','last_reported')}))
