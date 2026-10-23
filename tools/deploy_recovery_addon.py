"""Deploy the independent recovery app without restarting Home Assistant."""
import asyncio,json,sys,shlex
import paramiko,yaml
from ha_recovery import ROOT,PRIVATE,session,refresh_session,ws,rest,TARGET,PROVIDER

def ssh():
    credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
    remote=paramiko.SSHClient();remote.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    remote.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
    return remote

async def main():
    action=sys.argv[1]
    if action=='update':
        refresh_session()
        await ws({'type':'supervisor/api','endpoint':'/store/addons/local_tuesly_recovery/update',
                  'method':'post','timeout':600,'data':{}})
        print('Recovery app update completed; Home Assistant was not restarted')
        return
    if action=='fix-store-path':
        remote=ssh()
        try:
            path='/addons/local/tuesly_recovery/config.yaml'
            _,out,_=remote.exec_command('sudo -n cat '+path)
            metadata=yaml.safe_load(out.read())
            if metadata.get('slug')!='tuesly_recovery' or metadata.get('version')!='0.1.0':
                raise RuntimeError('Unexpected obsolete app metadata; refusing to move it')
            _,out,_=remote.exec_command('sudo -n mv '+path+' '+path+'.disabled')
            if out.channel.recv_exit_status():raise RuntimeError('Could not retire duplicate app metadata')
            print('Retired duplicate metadata from the initial incorrect mount path')
        finally:remote.close()
    elif action=='files':
        remote=ssh();root=ROOT/'addons/tuesly_recovery';count=0
        try:
            for file in sorted(root.rglob('*')):
                if not file.is_file() or '__pycache__' in file.parts or file.suffix=='.pyc':continue
                relative=file.relative_to(root).as_posix()
                if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-/.@' for c in relative):raise RuntimeError('Unexpected addon path')
                # The SSH app's /addons mount already points at apps/local.
                path='/addons/tuesly_recovery/'+relative
                command='sudo -n sh -c '+shlex.quote('mkdir -p '+path.rsplit('/',1)[0]+' && cat > '+path+'.tmp && mv '+path+'.tmp '+path)
                inp,out,err=remote.exec_command(command)
                inp.write(file.read_bytes());inp.flush();inp.channel.shutdown_write()
                if out.channel.recv_exit_status():raise RuntimeError('Addon deployment failed')
                count+=1
            print('Recovery app files deployed:',count)
        finally:remote.close()
    elif action in ('reload','install','update','start','restart','stop','logs','info'):
        command={'reload':'ha store reload','install':'ha store apps install local_tuesly_recovery',
                 'update':'ha store apps update local_tuesly_recovery',
                 'start':'ha apps start local_tuesly_recovery','restart':'ha apps restart local_tuesly_recovery',
                 'stop':'ha apps stop local_tuesly_recovery','logs':'ha apps logs local_tuesly_recovery',
                 'info':'ha apps info local_tuesly_recovery'}[action]
        remote=ssh()
        try:
            _,out,err=remote.exec_command('sudo -n docker exec hassio_cli '+command,timeout=600)
            if action=='info':
                # Info may expose options credentials; return selected status only.
                output=out.read().decode();data=yaml.safe_load(output)
                print(json.dumps({k:data.get(k) for k in ('name','version','state','boot','watchdog','available','error')}))
            else:
                for line in out:
                    if any(word in line.lower() for word in ('password','token','proxy_key','device_key','net_key','app_key')):continue
                    print(line.rstrip(),flush=True)
            code=out.channel.recv_exit_status()
            if code:
                print('Supervisor app operation failed:',action,'exit',code)
                # CLI errors are credential-free; never print full app options.
                if action!='info':print(err.read().decode()[:1200])
        finally:remote.close()
    elif action=='configure':
        refresh_session()
        path=PRIVATE/'recovery-service-token.json'
        if path.exists():token=json.loads(path.read_text())['token']
        else:
            token=await ws({'type':'auth/long_lived_access_token','client_name':'Tuesly Automatic Recovery','lifespan':3650})
            path.write_text(json.dumps({'token':token}))
        secrets=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
        options={'ha_url':session()['base'],'ha_token':token,'proxy_ip':'192.168.20.181',
                 'proxy_key':secrets['tuya_api_encryption_key'],'provider_entry':PROVIDER,
                 'bluetooth_entry':'01JKB1JJXYFTSZR1M5XAK7XSR8','proxy_source':'44:1D:64:F6:B5:FE',
                 'enabled':True,'enrolled':[{'address':'DC:23:52:81:60:BB','uuid':'dc23528160bb5112626c627474626779',
                                           'entry_id':TARGET,'entity_id':'light.tuesly_light_81_60_bb'}]}
        # Only addon options change; HA credentials and mesh registry files do not.
        await ws({'type':'supervisor/api','endpoint':'/addons/local_tuesly_recovery/options','method':'post',
                  'data':{'options':options,'boot':'auto','watchdog':True}})
        print('App configured privately for the enrolled driver; automatic start and watchdog enabled')
    else:raise RuntimeError('Unknown action')
if __name__=='__main__':asyncio.run(main())
