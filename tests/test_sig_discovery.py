import asyncio,types,unittest
from unittest.mock import MagicMock,patch
from test_mesh_controller import controller_modules
from test_transport import load_ha_module

class PairingDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        controller_modules()
        self.module=load_ha_module('custom_components.tuesly.sig_discovery','sig_discovery.py')
        self.hass=types.SimpleNamespace(bus=types.SimpleNamespace(async_fire=MagicMock()))

    async def test_fresh_provisioning_advertisement_unblocks_without_stale_cache(self):
        cancel=MagicMock();callbacks=[]
        def register(hass,callback,matcher,mode):
            callbacks.append(callback);return cancel
        with patch.object(self.module.bluetooth,'async_register_callback',side_effect=register):
            task=asyncio.create_task(self.module.wait_for_pairing(self.hass,'MAC','entry',timeout=1))
            await asyncio.sleep(0)
            callbacks[0](types.SimpleNamespace(service_uuids=['00001828-0000-1000-8000-00805f9b34fb']),None)
            self.assertFalse(task.done())
            callbacks[0](types.SimpleNamespace(service_uuids=[self.module.PROVISIONING_UUID],time=0),None)
            self.assertFalse(task.done())
            info=types.SimpleNamespace(service_uuids=[self.module.PROVISIONING_UUID])
            callbacks[0](info,None)
            self.assertIs(await task,info)
        cancel.assert_called_once()
        self.hass.bus.async_fire.assert_called_once_with('tuesly_pairing_armed',{'entry_id':'entry'})

    async def test_timeout_unregisters_callback(self):
        cancel=MagicMock()
        with patch.object(self.module.bluetooth,'async_register_callback',return_value=cancel):
            with self.assertRaises(TimeoutError):
                await self.module.wait_for_pairing(self.hass,'MAC','entry',timeout=.01)
        cancel.assert_called_once()

    async def test_measured_tuya_ad03_frame_identifies_reachability_but_not_pairing_readiness(self):
        cancel=MagicMock();callbacks=[]
        def register(hass,callback,*args):callbacks.append(callback);return cancel
        mac='DC:23:52:81:60:BB'
        raw=bytes.fromhex('40dc23528160bb626c6274746267791edc2859a5ecbe71060070')
        uuids=[f'0000{int.from_bytes(raw[i:i+2],"little"):04x}-0000-1000-8000-00805f9b34fb'
               for i in range(0,len(raw),2)]
        info=types.SimpleNamespace(service_uuids=uuids)
        self.assertNotIn(self.module.PROVISIONING_UUID,uuids)
        self.assertTrue(self.module.is_tuya_mesh_advertisement(info,mac))
        self.assertFalse(self.module.is_tuya_mesh_advertisement(info,'DC:23:52:81:60:BC'))
        with patch.object(self.module.bluetooth,'async_register_callback',side_effect=register):
            task=asyncio.create_task(self.module.wait_for_pairing(self.hass,mac,'entry',timeout=1))
            await asyncio.sleep(0);callbacks[0](info,None)
            self.assertFalse(task.done())
            ready=types.SimpleNamespace(service_uuids=[self.module.PROVISIONING_UUID])
            callbacks[0](ready,None)
            self.assertIs(await task,ready)
        cancel.assert_called_once()

    async def test_cancellation_unregisters_callback(self):
        cancel=MagicMock()
        with patch.object(self.module.bluetooth,'async_register_callback',return_value=cancel):
            task=asyncio.create_task(self.module.wait_for_pairing(self.hass,'MAC','entry'))
            await asyncio.sleep(0);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        cancel.assert_called_once()
