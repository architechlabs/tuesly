"""Read proxy/adapter entry identities and ESPHome errors, without credentials."""
import asyncio,json
from ha_recovery import ws,PROVIDER
async def main():
 entries=await ws({'type':'config_entries/get'})
 print(json.dumps([{k:e.get(k) for k in ('entry_id','domain','title','state','disabled_by','unique_id','reason')} for e in entries if e['domain'] in ('esphome','bluetooth')],indent=2))
 logs=await ws({'type':'system_log/list'})
 print(json.dumps([{'name':r.get('name'),'message':r.get('message'),'timestamp':r.get('timestamp')} for r in logs if 'esphome' in r.get('name','')][-8:],indent=2))
asyncio.run(main())
