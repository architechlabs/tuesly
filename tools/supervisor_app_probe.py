"""Probe the Supervisor app API route; print no option values."""
import asyncio,json
from ha_recovery import ws,refresh_session
async def main():
    refresh_session()
    for prefix in ('apps','addons'):
        try:
            data=await ws({'type':'supervisor/api','endpoint':f'/{prefix}/local_tuesly_recovery/info','method':'get'})
            print(json.dumps({'route':prefix,**{k:data.get(k) for k in ('state','version','boot','watchdog')},'schema_keys':list(data.get('schema',{}))}))
        except Exception as exc:print(prefix,type(exc).__name__)
asyncio.run(main())
