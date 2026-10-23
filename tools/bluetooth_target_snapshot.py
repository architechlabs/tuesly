"""Read public Bluetooth diagnostics; print scanner status and mesh adverts only."""
import json,sys
from ha_recovery import rest,ROOT
entry='01JKB1JJXYFTSZR1M5XAK7XSR8'
if '--saved-keys' in sys.argv:
 data=json.loads((ROOT/'.private/bluetooth-current-diagnostics.json').read_text())
 for scanner in data['data']['manager']['scanners']:
  print('SCANNER FIELDS',scanner.get('source'),list(scanner))
  for key,value in scanner.items():
   if isinstance(value,dict) and 'DC:23:52:81:60:BB' in value:
    print('TARGET FIELD',key,str(value['DC:23:52:81:60:BB'])[:200])
 raise SystemExit(0)
data=rest('/api/diagnostics/config_entry/'+entry,timeout=15)
(ROOT/'.private/bluetooth-current-diagnostics.json').write_text(json.dumps(data))
def walk(value,path=''):
 if isinstance(value,dict):
  if 'service_uuids' in value:
   uuids=value['service_uuids']
   if any('00001827' in str(u) or '0000dc40' in str(u) for u in uuids):
    print(json.dumps({'path':path,**{k:value[k] for k in ('name','address','rssi','time','service_uuids','service_data') if k in value}}))
  if ('scanner' in path and ('scanning' in value or 'connectable' in value)):
   print(json.dumps({'path':path,**{k:value[k] for k in ('name','source','scanning','connectable','scan_mode','requested_mode','current_mode','last_detection') if k in value}}))
  for key,child in value.items():
   if any(s in key.lower() for s in ('password','token','key','secret')):continue
   if isinstance(child,(dict,list)):walk(child,path+'/'+key)
 elif isinstance(value,list):
  for i,child in enumerate(value):walk(child,path+'/'+str(i))
print('DATA FIELDS',list(data.get('data',{})))
manager=data.get('data',{}).get('manager',{})
print('MANAGER FIELDS',list(manager))
for key in ('scanners','allocations','slot_manager'):
 if key in manager and key!='scanners':print(key,json.dumps(manager[key])[:800])
for scanner in manager.get('scanners',[]):
 for device in scanner.get('discovered_devices_and_advertisement_data',[]):
  if device.get('address')=='DC:23:52:81:60:BB':print('TARGET RAW',json.dumps({'scanner':scanner.get('source'),'device':device}))
walk(data.get('data',data))
