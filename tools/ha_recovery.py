"""Private operator helper for this authorized recovery. Never outputs credentials."""
import asyncio,json,sys,time,urllib.request,urllib.parse,shlex,hashlib
from pathlib import Path
import websockets,paramiko
ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'.private'
SESSION=PRIVATE/'ha-session.json'
TARGET='01M4DRBE9VWBYYA9DKWHT8GNX1'
PROVIDER='01M4D4HS7WFT5F91S7609SQ9VD'
def session():
    return json.loads(SESSION.read_text(encoding='utf-8'))
def rest(path,data=None):
    s=session()
    request=urllib.request.Request(s['base']+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+s['access_token'],'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=70) as response:
        return json.load(response)
async def ws(command):
    s=session()
    async with websockets.connect(s['base'].replace('http:','ws:')+'/api/websocket') as connection:
        await connection.recv()
        await connection.send(json.dumps({'type':'auth','access_token':s['access_token']}))
        if json.loads(await connection.recv())['type']!='auth_ok':
            raise RuntimeError('Private session requires refreshing')
        await connection.send(json.dumps({'id':1,**command}))
        while True:
            result=json.loads(await connection.recv())
            if result.get('id')==1:
                if not result.get('success'):
                    raise RuntimeError('HA operation failed: '+str(result.get('error',{}).get('code')))
                return result['result']
def deploy():
    credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text(encoding='utf-8'))['options']['ssh']
    client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
    backup='/config/.tuesly-support-backup-'+time.strftime('%Y%m%d-%H%M%S')
    _,stdout,stderr=client.exec_command('sudo -n cp -a /config/custom_components/tuesly '+backup)
    if stdout.channel.recv_exit_status()!=0:raise RuntimeError('Component backup failed')
    component=ROOT/'custom_components/tuesly'
    count=0
    for file in component.rglob('*'):
        if not file.is_file() or '__pycache__' in file.parts or file.suffix=='.pyc':continue
        relative=file.relative_to(component).as_posix()
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/.@' for c in relative):raise RuntimeError('Unexpected deployment path')
        remote='/config/custom_components/tuesly/'+relative
        stdin,stdout,stderr=client.exec_command("sudo -n sh -c 'mkdir -p "+remote.rsplit('/',1)[0]+' && cat > '+remote+'.support-tmp && mv '+remote+'.support-tmp '+remote+"'")
        stdin.write(file.read_bytes());stdin.flush();stdin.channel.shutdown_write()
        if stdout.channel.recv_exit_status()!=0:raise RuntimeError('Component deployment failed')
        count+=1
    client.close();print('Component backed up and deployed:',count,'files')
async def main():
    action=sys.argv[1]
    if action=='deploy':deploy()
    elif action=='verify-deployment':
        credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text(encoding='utf-8'))['options']['ssh']
        client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
        _,stdout,_=client.exec_command('cat /config/custom_components/tuesly/manifest.json')
        version=json.loads(stdout.read())['version']
        _,stdout,_=client.exec_command('cat /config/custom_components/tuesly/sig_controller.py')
        same=hashlib.sha256(stdout.read()).digest()==hashlib.sha256((ROOT/'custom_components/tuesly/sig_controller.py').read_bytes()).digest()
        client.close();print('Installed version:',version,'controller matches validated source:',same)
    elif action=='refresh':
        s=session()
        request=urllib.request.Request(s['base']+'/auth/token',data=urllib.parse.urlencode({'grant_type':'refresh_token','refresh_token':s['refresh_token'],'client_id':s['base']+'/'}).encode())
        with urllib.request.urlopen(request,timeout=15) as response:
            s.update(json.load(response))
        SESSION.write_text(json.dumps(s),encoding='utf-8');print('Private HA session refreshed')
    elif action=='clear-device-cache':
        credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text(encoding='utf-8'))['options']['ssh']
        client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
        code="import asyncio\nfrom dbus_fast.aio import MessageBus\nfrom dbus_fast import Message,BusType\nasync def run():\n bus=await MessageBus(bus_type=BusType.SYSTEM).connect()\n result=await bus.call(Message(destination='org.bluez',path='/org/bluez/hci0',interface='org.bluez.Adapter1',member='RemoveDevice',signature='o',body=['/org/bluez/hci0/dev_DC_23_52_81_60_BB']))\n print(result.message_type.name,result.error_name)\n bus.disconnect()\nasyncio.run(run())"
        _,stdout,stderr=client.exec_command('sudo -n docker exec homeassistant python3 -c '+shlex.quote(code))
        print('Target Bluetooth cache cleared:',stdout.read().decode().strip(),'exit',stdout.channel.recv_exit_status())
        client.close()
    elif action=='restart':
        rest('/api/services/homeassistant/restart',{});print('HA restart requested')
    elif action in ('enable','pause','register'):
        ids=[TARGET] if action=='register' else [PROVIDER,TARGET]
        for entry_id in ids:
            await ws({'type':'config_entries/disable','entry_id':entry_id,'disabled_by':'user' if action=='pause' else None})
        print('Entry operation completed:',action)
    elif action=='pause-target':
        await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'});print('Target paused')
    elif action=='import':
        sys.path.insert(0,str(ROOT/'custom_components/tuesly/lib'))
        from tuesly_mesh.sig_mesh_crypto import k3
        state=json.loads((PRIVATE/'ha-mesh.json').read_text(encoding='utf-8'))['data']
        node=state['nodes']['DC:23:52:81:60:BB']
        rest('/api/services/tuesly/import_commissioning',{'address':'DC:23:52:81:60:BB','device_key':node['dev_key'],'network_id':k3(bytes.fromhex(state['net_key'])).hex(),'primary':node['address'],'elements':node['elements'],'sequence_high':state['sequence_high']})
        print('Recovered node imported through HA Store service')
    elif action=='status':
        entries=await ws({'type':'config_entries/get'})
        print(json.dumps([{k:e.get(k) for k in ('entry_id','title','domain','state','disabled_by','reason')} for e in entries if e['entry_id'] in (TARGET,PROVIDER)],indent=2))
        states=rest('/api/states')
        print(json.dumps([s for s in states if s['entity_id'].startswith('light.') and ('tuesly' in s['entity_id'] or '81_60' in s['entity_id'])],indent=2))
    elif action=='poll-state':
        before=rest('/api/states/light.tuesly_light_81_60_bb')
        rest('/api/services/homeassistant/update_entity',{'entity_id':'light.tuesly_light_81_60_bb'})
        state=rest('/api/states/light.tuesly_light_81_60_bb')
        public={'checked_at':time.time(),'entity_id':state['entity_id'],'state':state['state'],'brightness':state['attributes'].get('brightness'),'last_reported':state['last_reported']}
        path=ROOT/'reports/ha-live-validation.json'
        report=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version':'0.2.5','checks':[]}
        report['checks'].append(public);path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(public,indent=2))
    elif action=='debug-off':
        rest('/api/services/logger/set_level',{'custom_components.tuesly':'warning','tuesly_mesh':'warning','habluetooth.wrappers':'warning'})
        print('Temporary debug logging disabled')
    elif action=='logs':
        logs=await ws({'type':'system_log/list'})
        result=[{'name':r.get('name'),'message':r.get('message'),'exception':r.get('exception'),'timestamp':r.get('timestamp')} for r in logs if 'tuesly' in str(r.get('name','')).lower()]
        print(json.dumps(result,indent=2))
    elif action=='transport-log':
        credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text(encoding='utf-8'))['options']['ssh']
        client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
        _,stdout,stderr=client.exec_command('sudo -n docker exec hassio_cli ha core logs --lines 5000')
        output=stdout.read().decode(errors='replace')+stderr.read().decode(errors='replace')
        lines=[line for line in output.splitlines() if 'tuesly' in line.lower() or 'DC:23:52:81:60:BB' in line]
        print('\n'.join(lines[-65:]) if lines else ('No matching runtime logs; command exit '+str(stdout.channel.recv_exit_status())+'; '+output[:300]));client.close()
    elif action=='debug':
        rest('/api/services/logger/set_level',{'custom_components.tuesly':'debug','tuesly_mesh':'debug','habluetooth.wrappers':'debug'})
        print('Targeted Bluetooth/controller diagnostics enabled')
    elif action=='reload':
        rest('/api/config/config_entries/entry/'+TARGET+'/reload',{});print('Target reload completed')
    elif action=='control':
        entity=sys.argv[2];service=sys.argv[3]
        data={'entity_id':entity}
        if len(sys.argv)>4:data['brightness']=int(sys.argv[4])
        rest('/api/services/light/'+service,data)
        print(json.dumps(rest('/api/states/'+entity),indent=2))
if __name__=='__main__':asyncio.run(main())
