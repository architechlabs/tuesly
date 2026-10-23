"""Identify only the two device paths observed occupying the proxy."""
import asyncio,json
from ha_recovery import ws,refresh_session
async def main():
    refresh_session();devices=await ws({'type':'config/device_registry/list'})
    entries={e['entry_id']:e for e in await ws({'type':'config_entries/get'})}
    for d in devices:
        addresses={str(c[1]).upper() for c in d.get('connections',[])}
        if addresses & {'B0:E9:FE:81:7A:EE','B0:E9:FE:F3:15:CD','DC:23:52:81:60:BB'}:
            print(json.dumps({'name':d.get('name_by_user') or d.get('name'),'manufacturer':d.get('manufacturer'),
                'entries':[{key:entries[e].get(key) for key in ('entry_id','domain','title','state')} for e in d['config_entries'] if e in entries]}))
if __name__=='__main__':asyncio.run(main())
