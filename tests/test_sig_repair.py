import asyncio
import copy
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_mesh_controller import controller_modules, Store, MAC
from test_transport import load_ha_module
from tuesly_mesh.exceptions import ProvisioningError


class RepairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.controller, self.module = controller_modules()
        store_module = load_ha_module('custom_components.tuesly.mesh_store','mesh_store.py')
        self.journal = await store_module.MeshJournal(Store()).load()
        await self.journal.reserve(MAC)
        await self.journal.update(MAC,dev_key='22'*16,elements=2,status='ready')
        self.entry = types.SimpleNamespace(data={'mac_address':MAC},entry_id='entry',disabled_by=None,
            setup_lock=asyncio.Lock(), async_cancel_retry_setup=MagicMock())
        self.flow = MagicMock()
        self.flow.hass = types.SimpleNamespace(data={},config_entries=types.SimpleNamespace(
            async_reload=AsyncMock(),async_unload=AsyncMock(return_value=True)))
        self.flow.async_show_form.side_effect = lambda **kwargs:kwargs
        self.flow.async_abort.side_effect = lambda **kwargs:kwargs

    async def test_retry_preserves_keys_and_does_not_provision(self):
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.module,'SIGMeshProvisioner') as provisioner:
            result = await self.module.repair(self.flow,self.entry,{'recommission':False})
        provisioner.assert_not_called()
        self.assertEqual(self.journal.state['nodes'][MAC]['dev_key'],'22'*16)
        self.assertEqual(result['reason'],'reconfigure_successful')

    async def test_replacement_requires_physical_reset_confirmation(self):
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.module,'SIGMeshProvisioner') as provisioner:
            result = await self.module.repair(self.flow,self.entry,{'recommission':True,'reset_confirmed':False})
        provisioner.assert_not_called()
        self.assertEqual(result['errors'],{'base':'reset_required'})
        self.flow.hass.config_entries.async_unload.assert_not_awaited()

    async def test_pairing_is_armed_only_after_running_setup_finishes_and_unloads(self):
        await self.entry.setup_lock.acquire()
        async def no_device(*args):
            self.assertTrue(self.entry.setup_lock.locked())
            self.flow.hass.config_entries.async_unload.assert_awaited_once_with('entry',_lock=False)
            raise TimeoutError
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.module,'wait_for_pairing',AsyncMock(side_effect=no_device)) as wait:
            task=asyncio.create_task(self.module.repair(self.flow,self.entry,
                {'recommission':True,'reset_confirmed':True}))
            await asyncio.sleep(0)
            wait.assert_not_awaited()
            self.flow.hass.config_entries.async_unload.assert_not_awaited()
            self.entry.setup_lock.release()
            result=await task
        self.assertEqual(result['errors'],{'base':'device_not_found'})
        self.assertEqual(self.journal.state['nodes'][MAC]['dev_key'],'22'*16)
        self.assertFalse(self.entry.setup_lock.locked())
        self.flow.hass.config_entries.async_reload.assert_awaited_once()

    async def test_cancel_while_pairing_releases_setup_lock_and_restores_runtime(self):
        entered=asyncio.Event()
        async def listen(*args):
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.module,'wait_for_pairing',AsyncMock(side_effect=listen)):
            task=asyncio.create_task(self.module.repair(self.flow,self.entry,
                {'recommission':True,'reset_confirmed':True}))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(self.entry.setup_lock.locked())
        self.flow.hass.config_entries.async_reload.assert_awaited_once()

    async def test_failure_after_possible_data_delivery_retains_new_keys_and_explains_resume(self):
        info=types.SimpleNamespace(service_uuids=['00001827-0000-1000-8000-00805f9b34fb'])
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.module,'wait_for_pairing',AsyncMock(return_value=info)), \
             patch.object(self.module,'SIGMeshProvisioner') as provisioner:
            provisioner.return_value._provisioning_data_attempted=True
            async def failed(address):
                await self.journal.update(MAC,dev_key='33'*16,elements=2,status='configuration_pending')
                raise ProvisioningError('Complete acknowledgement lost')
            provisioner.return_value.provision=AsyncMock(side_effect=failed)
            result=await self.module.repair(self.flow,self.entry,{'recommission':True,'reset_confirmed':True})
        self.assertEqual(result['errors'],{'base':'configuration_incomplete'})
        self.assertEqual(self.journal.state['nodes'][MAC]['dev_key'],'33'*16)
        self.flow.hass.config_entries.async_reload.assert_awaited_once()

    async def test_failure_before_data_preserves_prior_identity_but_consumes_new_range(self):
        before = copy.deepcopy(self.journal.state['nodes'][MAC])
        info = types.SimpleNamespace(service_uuids=['00001827-0000-1000-8000-00805f9b34fb'])
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.module,'wait_for_pairing',AsyncMock(return_value=info)), \
             patch.object(self.module,'SIGMeshProvisioner') as provisioner:
            provisioner.return_value.provision = AsyncMock(side_effect=ProvisioningError('No capabilities'))
            result = await self.module.repair(self.flow,self.entry,{'recommission':True,'reset_confirmed':True})
        self.assertEqual(result['errors'],{'base':'commissioning_failed'})
        self.assertEqual(self.journal.state['nodes'][MAC],before)
        self.assertEqual(self.journal.state['address_next'],512)
        self.flow.hass.config_entries.async_reload.assert_awaited_once()
