"""Read the selected commissioning timeline without displaying credentials."""
import json,re
import paramiko
from ha_recovery import PRIVATE
credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
_,stdout,stderr=client.exec_command('sudo -n docker exec hassio_cli ha core logs --lines 6000')
output=stdout.read().decode(errors='replace');client.close()
for line in output.splitlines():
    if '2026-10-13 13:36:' not in line and '2026-10-13 13:37:' not in line:continue
    if 'tuesly' not in line.lower() and 'DC:23:52:81:60:BB' not in line:continue
    if any(key in line.lower() for key in ('secret loaded','keys derived','key/password','dev_key','net_key','app_key')):continue
    if any(key in line.lower() for key in ('provision','bind','composition','connecting via','connected via','configuration','temperature','finished fetching','not ready','connected to','disconnected from','filter','retry')):
        print(line)
