"""Show recent bearer-selection and provisioning stages only, not credentials."""
import json,paramiko
from ha_recovery import PRIVATE
credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
_,stdout,_=client.exec_command('sudo -n docker exec hassio_cli ha core logs --lines 6000')
lines=stdout.read().decode(errors='replace').splitlines();client.close()
selected=[]
for line in lines:
    if 'DC:23:52:81:60:BB' not in line and 'SIG repair stopped' not in line:continue
    if any(word in line for word in ('Connecting via','Connected via','Provisioning COMPLETE','Provisioning service','Provisioning capabilities','PB-GATT transmit','PB-GATT connected','Provisioning: Invite','Provisioning: Capabilities','Provisioning: PublicKey','Provisioning: Confirmation','SIG repair stopped','Retrying transient','Retrying interrupted')):
        selected.append(line)
print('\n'.join(selected[-16:]))
