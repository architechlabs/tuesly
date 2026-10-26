"""Read-only bounded HA observer for a user-operated driver mains cycle."""
import json,time
from ha_recovery import rest,PRIVATE
end=time.monotonic()+240;rows=[];previous=None
print('READY: observing Off / warm-white 0 baseline and restart recovery',flush=True)
try:
 while time.monotonic()<end:
  try:
   states=rest('/api/states',timeout=8)
   ids=('light.tuesly_light_81_60_bb','number.tuesly_light_81_60_bb_white_temperature','select.tuesly_light_81_60_bb_power_on_behavior')
   snapshot={s['entity_id']:{'state':s['state'],'memory':s['attributes'].get('power_on_behavior_status'),'backend':s['attributes'].get('power_on_behavior_backend')} for s in states if s['entity_id'] in ids}
   row={'at':time.time(),'states':snapshot};rows.append(row)
   (PRIVATE/'power-policy-cycle-observation.json').write_text(json.dumps(rows,indent=2))
   if snapshot!=previous:print(json.dumps(row),flush=True);previous=snapshot
  except Exception as exc:print(type(exc).__name__,flush=True)
  time.sleep(3)
finally:print('Observation finished',flush=True)
