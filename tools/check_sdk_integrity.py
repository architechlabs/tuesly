"""Compare installed transport source with wheel RECORD and official tagged source."""
import base64,hashlib,importlib.metadata,json,urllib.request
from pathlib import Path
dist=importlib.metadata.distribution('esphome')
result={'version':dist.version,'files':[]}
targets={'bluetooth_proxy.cpp','esp32_ble_tracker.cpp','bluetooth_connection_bluedroid.cpp',
         'api_connection.cpp','api_connection.h','api_server.cpp','application.cpp'}
for item in dist.files:
    if item.name not in targets:continue
    data=item.locate().read_bytes()
    expected=item.hash
    actual=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
    row={'file':item.name,'wheel_record_matches':bool(expected and expected.value==actual)}
    url='https://raw.githubusercontent.com/esphome/esphome/'+dist.version+'/'+str(item).replace('\\','/')
    try:
        official=urllib.request.urlopen(url,timeout=10).read()
        row['official_tag_matches']=official==data
    except Exception as exc:row['fetch_error']=type(exc).__name__
    result['files'].append(row)
print(json.dumps(result,indent=2))
