"""Read HA runtime and native BlueZ connection state without taking a BLE slot."""
import asyncio,json,shlex
import paramiko
from ha_recovery import PRIVATE,rest,ws,refresh_session,PROVIDER,TARGET

async def main():
    refresh_session()
    entries=await ws({'type':'config_entries/get'})
    print('RADIO ENTRIES:',json.dumps([{k:e.get(k) for k in ('entry_id','domain','title','state','disabled_by','reason')}
        for e in entries if e['domain'] in ('esphome','bluetooth','tuesly')],indent=2),flush=True)
    registry=await ws({'type':'config/entity_registry/list'})
    states=rest('/api/states')
    entry_map={e['entry_id']:e for e in entries if e['domain']=='esphome'}
    ids={r['entity_id']:r['config_entry_id'] for r in registry if r.get('config_entry_id') in entry_map}
    print('PROXY LIVE STATES:',json.dumps([{'entry':entry_map[ids[s['entity_id']]]['title'],
        **{k:s.get(k) for k in ('entity_id','state','last_reported')}} for s in states if s['entity_id'] in ids
        and any(k in s['entity_id'] for k in ('ip_address','uptime','gateway_online'))],indent=2),flush=True)
    credentials=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
    client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.4.198',username=credentials['username'],password=credentials['password'],look_for_keys=False,allow_agent=False,timeout=10)
    code="""import asyncio,json
from dbus_fast.aio import MessageBus
from dbus_fast import Message,BusType
async def main():
 bus=await MessageBus(bus_type=BusType.SYSTEM).connect()
 result=await bus.call(Message(destination='org.bluez',path='/',interface='org.freedesktop.DBus.ObjectManager',member='GetManagedObjects'))
 records=[]
 for path,interfaces in result.body[0].items():
  device=interfaces.get('org.bluez.Device1',{})
  if device.get('Address') and device['Address'].value=='DC:23:52:81:60:BB':
   records.append({'path':path,**{key:device[key].value for key in ('AddressType','Connected','ServicesResolved','Paired','UUIDs') if key in device}})
 print(json.dumps(records,indent=2));bus.disconnect()
asyncio.run(main())
"""
    _,stdout,stderr=client.exec_command('sudo -n docker exec homeassistant python3 -c '+shlex.quote(code))
    print('NATIVE BLUEZ TARGET:',stdout.read().decode().strip(),flush=True)
    if stdout.channel.recv_exit_status():print('BlueZ query failed')
    client.close()
    try:
        data=rest('/api/diagnostics/config_entry/'+PROVIDER,timeout=15)
        (PRIVATE/'proxy-diagnostics-current.json').write_text(json.dumps(data),encoding='utf-8')
        print('Proxy diagnostics saved privately; top-level keys:',list(data))
    except Exception as exc:print('Proxy diagnostics:',type(exc).__name__)

if __name__=='__main__':asyncio.run(main())
