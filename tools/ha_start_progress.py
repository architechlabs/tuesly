"""Read Core container startup status without accessing HA private files."""
import json,paramiko,sys
from ha_recovery import PRIVATE
options=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.4.198',username=options['username'],password=options['password'],look_for_keys=False,allow_agent=False,timeout=10)
_,out,_=client.exec_command("sudo -n docker inspect --format '{{.State.Status}} {{.State.StartedAt}} {{.State.FinishedAt}}' homeassistant")
print(out.read().decode().strip())
_,out,_=client.exec_command('sudo -n docker exec hassio_cli ha core logs --lines 200')
lines=out.read().decode(errors='replace').splitlines()
print('\n'.join(line for line in lines if '[homeassistant.core]' in line or '[homeassistant.bootstrap]' in line or 'Unable to install package' in line or 'Failed to restart' in line))
if '--help-restart' in sys.argv:
    _,out,_=client.exec_command('sudo -n docker exec hassio_cli ha core restart --help')
    print(out.read().decode())
client.close()
