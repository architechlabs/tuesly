"""Back up and atomically copy the exact 0.2.16 files; never restarts HA."""
import base64,hashlib,json,paramiko,shlex
from ha_recovery import ROOT,PRIVATE
FILES=('sig_controller.py','sig_light.py','select.py','lib/tuesly_mesh/sig_power_memory.py','manifest.json')
PROGRAM=r'''
import base64,hashlib,json,os,shutil,sys,time
from pathlib import Path
c=json.load(sys.stdin);root=Path('/config/custom_components/tuesly').resolve()
assert root.name=='tuesly' and root.parent.name=='custom_components'
old=json.loads((root/'manifest.json').read_text())['version']
assert old in ('0.2.15','0.2.16')
backup=Path('/config')/('.tuesly-before-0.2.16-'+str(time.time_ns()));backup.mkdir(mode=0o700)
changed=[]
try:
 for name,data in c['files'].items():
  target=(root/name).resolve();assert target.is_relative_to(root)
  original=target.exists()
  if original:
   saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
  changed.append((name,original))
  contents=base64.b64decode(data)
  assert hashlib.sha256(contents).hexdigest()==c['hashes'][name]
  temporary=target.with_name(target.name+'.state-sync-tmp')
  temporary.write_bytes(contents);os.replace(temporary,target)
  assert hashlib.sha256(target.read_bytes()).hexdigest()==c['hashes'][name]
 print(json.dumps({'installed_version':'0.2.16','files_verified':len(changed),'backup':str(backup),'core_restarted':False}))
except BaseException:
 for name,original in reversed(changed):
  if original:shutil.copy2(backup/name,root/name)
  elif (root/name).is_file():(root/name).unlink()
 raise
'''
c=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
r=paramiko.SSHClient();r.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
 r.connect('192.168.4.198',username=c['username'],password=c['password'],look_for_keys=False,allow_agent=False,timeout=10)
 contents={name:(ROOT/'custom_components/tuesly'/name).read_bytes() for name in FILES}
 payload={'files':{name:base64.b64encode(data).decode() for name,data in contents.items()},'hashes':{name:hashlib.sha256(data).hexdigest() for name,data in contents.items()}}
 inp,out,err=r.exec_command('sudo -n python3 -c '+shlex.quote(PROGRAM),timeout=30)
 inp.write(json.dumps(payload));inp.flush();inp.channel.shutdown_write()
 output=out.read().decode();code=out.channel.recv_exit_status()
 print(output,flush=True)
 if code:raise RuntimeError(err.read().decode(errors='replace')[-1200:])
 (PRIVATE/'state-sync-deployment.json').write_text(output)
finally:r.close()
