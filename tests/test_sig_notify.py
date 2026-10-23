import types,unittest
from unittest.mock import MagicMock
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.descriptor import BleakGATTDescriptor
from test_transport import SIGMeshDevice
from tuesly_mesh.sig_notify import CCCD_UUID,enable_notifications,disable_notifications

class ESPBackend:
    __module__='bleak_esphome.backend.client'
    is_connected=True
    services=MagicMock()
    def __init__(self):self.events=[]
    async def start_notify(self,char,callback,**kwargs):self.events.append('start')
    async def stop_notify(self,char):self.events.append('stop')
    async def write_gatt_descriptor(self,descriptor,data):self.events.append((descriptor.handle,data))

class NotificationTests(unittest.IsolatedAsyncioTestCase):
    def client(self,backend):
        client=BleakClient.__new__(BleakClient);client._backend=backend
        descriptor=MagicMock(spec=BleakGATTDescriptor,uuid=CCCD_UUID,handle=30)
        char=MagicMock(spec=BleakGATTCharacteristic,handle=28,descriptors=[descriptor])
        return client,char,descriptor
    async def test_real_bleak3_guard_and_esphome_cleanup(self):
        backend=ESPBackend();client,char,descriptor=self.client(backend)
        with self.assertRaises(ValueError):await client.write_gatt_descriptor(descriptor,b'\x00\x00')
        await enable_notifications(client,char,lambda sender,data:None)
        await disable_notifications(client,char)
        self.assertEqual(backend.events,['start',(30,b'\x00\x00'),'stop'])
    async def test_ha_wrapper_delegates_descriptor_cleanup(self):
        backend=ESPBackend()
        wrapper=types.SimpleNamespace(_backend=backend,services=backend.services,is_connected=True,
            stop_notify=backend.stop_notify,write_gatt_descriptor=backend.write_gatt_descriptor)
        client,char,_=self.client(wrapper)
        await disable_notifications(client,char)
        self.assertEqual(backend.events,[(30,b'\x00\x00'),'stop'])
    async def test_native_backend_uses_stop_notify_without_direct_cccd(self):
        class Native(ESPBackend):__module__='bleak.backends.bluezdbus.client'
        backend=Native();client,char,_=self.client(backend)
        await disable_notifications(client,char)
        self.assertEqual(backend.events,['stop'])
