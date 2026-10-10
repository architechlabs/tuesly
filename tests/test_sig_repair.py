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
        self.entry = types.SimpleNamespace(data={'mac_address':MAC},entry_id='entry',disabled_by=None)
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

    async def test_failure_after_possible_data_delivery_retains_new_keys_and_explains_resume(self):
        info=types.SimpleNamespace(service_uuids=['00001827-0000-1000-8000-00805f9b34fb'])
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)), \
             patch.object(self.controller.bluetooth,'async_last_service_info',return_value=info), \
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
             patch.object(self.controller.bluetooth,'async_last_service_info',return_value=info), \
             patch.object(self.module,'SIGMeshProvisioner') as provisioner:
            provisioner.return_value.provision = AsyncMock(side_effect=ProvisioningError('No capabilities'))
            result = await self.module.repair(self.flow,self.entry,{'recommission':True,'reset_confirmed':True})
        self.assertEqual(result['errors'],{'base':'commissioning_failed'})
        self.assertEqual(self.journal.state['nodes'][MAC],before)
        self.assertEqual(self.journal.state['address_next'],512)
        self.flow.hass.config_entries.async_reload.assert_awaited_once()
