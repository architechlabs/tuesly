"""Print bounded Supervisor build progress and availability, never app options."""
from deploy_recovery_addon import ssh
remote=ssh()
try:
    _,out,_=remote.exec_command('sudo -n docker exec hassio_cli ha supervisor logs')
    lines=out.read().decode(errors='replace').splitlines()
    selected=[s for s in lines if 'tuesly' in s.lower() or ('build' in s.lower() and ('error' in s.lower() or 'local' in s.lower()))]
    print('\n'.join(selected[-12:]) or 'No app-specific Supervisor build entries yet')
finally:remote.close()
