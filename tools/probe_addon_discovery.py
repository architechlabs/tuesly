"""Find the local app mount and only this app's discovery information."""
import json,shlex
from deploy_recovery_addon import ssh
from ha_recovery import rest
remote=ssh()
try:
    _,out,_=remote.exec_command("sudo -n docker ps --format '{{.Names}}'")
    name=next(n for n in out.read().decode().splitlines() if 'a0d7b954_ssh' in n)
    _,out,_=remote.exec_command("sudo -n docker inspect "+shlex.quote(name)+" --format '{{json .Mounts}}'")
    mounts=json.loads(out.read())
    print(json.dumps([m for m in mounts if m['Destination']=='/addons']))
    _,out,_=remote.exec_command("sudo -n docker inspect app_local_tuesly_recovery --format '{{json .Mounts}}'")
    print(json.dumps([{'source':m['Source'],'destination':m['Destination'],'read_write':m['RW']} for m in json.loads(out.read())]))
finally:remote.close()
