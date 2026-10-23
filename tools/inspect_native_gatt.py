"""Read cached native GATT service/characteristic UUIDs, without a connection."""
import json,paramiko,shlex
from ha_recovery import PRIVATE
options=json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text())['options']['ssh']
client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.4.198',username=options['username'],password=options['password'],look_for_keys=False,allow_agent=False,timeout=10)
code='''import asyncio,json
from dbus_fast.aio import MessageBus
from dbus_fast import Message,BusType
async def main():
 bus=await MessageBus(bus_type=BusType.SYSTEM).connect()
 result=await bus.call(Message(destination='org.bluez',path='/',interface='org.freedesktop.DBus.ObjectManager',member='GetManagedObjects'))
 rows=[]
 for path,interfaces in result.body[0].items():
  if '/dev_DC_23_52_81_60_BB/' not in path:continue
  for kind in ('org.bluez.GattService1','org.bluez.GattCharacteristic1'):
   if props:=interfaces.get(kind):
    rows.append({'kind':kind.rsplit('.',1)[-1],'path':path,**{k:props[k].value for k in ('UUID','Service','Flags','Notifying') if k in props}})
 print(json.dumps(rows,indent=2));bus.disconnect()
asyncio.run(main())
'''
_,out,_=client.exec_command('sudo -n docker exec homeassistant python3 -c '+shlex.quote(code))
print(out.read().decode());client.close()
