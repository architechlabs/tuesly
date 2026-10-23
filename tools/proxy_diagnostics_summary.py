"""Summarize proxy runtime diagnostics without keys or connection credentials."""
import json
from ha_recovery import PRIVATE,rest,PROVIDER
data=rest('/api/diagnostics/config_entry/'+PROVIDER,timeout=15)
(PRIVATE/'proxy-diagnostics-current.json').write_text(json.dumps(data))
def walk(value,path=''):
    if isinstance(value,dict):
        print('FIELDS',path,list(value.keys()))
        for key,child in value.items():
            if any(secret in key.lower() for secret in ('key','password','token','ssid','bssid','secret')):continue
            if isinstance(child,dict):walk(child,path+'/'+key)
            elif any(part in key.lower() for part in ('connection','feature','scan','version','active','connect','bluetooth')):
                if not isinstance(child,list):print('VALUE',path+'/'+key,str(child)[:150])
walk(data.get('data',{}))
