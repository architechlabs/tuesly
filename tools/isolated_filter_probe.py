"""Authenticate proxy identity with exclusive ESP transport; restore HA entries."""
import asyncio,sys,subprocess
from ha_recovery import ws,refresh_session,TARGET,PROVIDER,ROOT

async def main():
    refresh_session();entries=await ws({'type':'config_entries/get'})
    previous={e['entry_id']:e['disabled_by'] for e in entries if e['entry_id'] in (TARGET,PROVIDER)}
    try:
        for entry in (TARGET,PROVIDER):
            await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':'user'})
        flags=['--advertisements-only','--wait-for-power-cycle'] if '--startup' in sys.argv else ['--filter-only','--connect-known-address']
        await asyncio.to_thread(subprocess.run,[sys.executable,str(ROOT/'tools/inspect_mesh.py'),
            *flags,*(['--current-ha-snapshot'] if '--current-ha-snapshot' in sys.argv else [])],check=True,timeout=220)
    finally:
        for entry in (PROVIDER,TARGET):
            await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':previous[entry]})

if __name__=='__main__':asyncio.run(main())
