"""Private read-only copy of the exact mesh file explicitly authorized by user."""
import json,paramiko
from ha_recovery import PRIVATE
options=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.4.198',username=options['username'],password=options['password'],look_for_keys=False,allow_agent=False,timeout=10)
_,out,_=client.exec_command('sudo -n cat /config/.storage/tuesly.mesh')
raw=out.read();status=out.channel.recv_exit_status();client.close()
if status:raise RuntimeError('Authorized mesh snapshot could not be read')
data=json.loads(raw)
state=data['data']
path=PRIVATE/'ha-mesh-current.json'
path.write_bytes(raw)
print(json.dumps({'snapshot_saved_privately':True,'address_next':state['address_next'],'node_count':len(state['nodes'])}))
