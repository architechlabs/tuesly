"""Read only the enrolled driver's native BlueZ connection properties."""
import shlex
from deploy_recovery_addon import ssh
PROGRAM='''import asyncio,json
from dbus_fast.aio import MessageBus
from dbus_fast import Message,BusType
async def main():
 bus=await MessageBus(bus_type=BusType.SYSTEM).connect()
 reply=await bus.call(Message(destination='org.bluez',path='/',interface='org.freedesktop.DBus.ObjectManager',member='GetManagedObjects'))
 for path,interfaces in reply.body[0].items():
  props=interfaces.get('org.bluez.Device1',{})
  if props.get('Address') and props['Address'].value.upper()=='DC:23:52:81:60:BB':
   print(json.dumps({key:props[key].value for key in ('Connected','ServicesResolved','Paired','Blocked','AddressType','RSSI') if key in props}))
 bus.disconnect()
asyncio.run(main())
'''
remote=ssh()
try:
 _,out,err=remote.exec_command('sudo -n docker exec homeassistant python -c '+shlex.quote(PROGRAM),timeout=30)
 print(out.read().decode().strip() or 'Target is not cached in native BlueZ')
 if out.channel.recv_exit_status():print('BlueZ check failed')
finally:remote.close()
