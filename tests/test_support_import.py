import copy
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_mesh_controller import controller_modules, Store, MAC
from test_transport import load_ha_module
from tuesly_mesh.sig_mesh_crypto import k3


class ImportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        controller_modules()
        exceptions = sys.modules.setdefault('homeassistant.exceptions',types.ModuleType('homeassistant.exceptions'))
        if not isinstance(getattr(exceptions,'HomeAssistantError',None),type):
            exceptions.HomeAssistantError = type('HomeAssistantError',(Exception,),{})
        self.Error = exceptions.HomeAssistantError
        module = load_ha_module('custom_components.tuesly.mesh_store','mesh_store.py')
        self.journal = await module.MeshJournal(Store()).load()
        await self.journal.reserve(MAC)
        await self.journal.update(MAC,dev_key='22'*16,elements=2,status='ready',tid=10,
                                  received={'2':[100,1]})
        self.module = load_ha_module('custom_components.tuesly.support','support.py')
        self.entry = types.SimpleNamespace(data={'mac_address':MAC},disabled_by='user')
        self.hass = types.SimpleNamespace(data={},services=MagicMock(),
            auth=types.SimpleNamespace(async_get_user=AsyncMock(return_value=types.SimpleNamespace(is_admin=True))),
            config_entries=types.SimpleNamespace(async_entries=lambda domain:[self.entry]))
        self.hass.services.has_service.return_value=False
        await self.module.register(self.hass)
        args=self.hass.services.async_register.call_args
        self.handler=args.args[2]
        self.schema=args.kwargs['schema']

    async def call(self, **changes):
        values={'address':MAC,'device_key':'22'*16,
                'network_id':k3(bytes.fromhex(self.journal.state['net_key'])).hex(),
                'primary':2,'elements':2,'sequence_high':1024,**changes}
        call=types.SimpleNamespace(data=self.schema(values),context=types.SimpleNamespace(user_id='admin'))
        with patch.object(self.module,'get_journal',AsyncMock(return_value=self.journal)):
            await self.handler(call)

    async def test_same_identity_import_preserves_replay_tid_and_sequence_floor(self):
        await self.call(bindings_verified=True,proxy_verified=True,
                        temperature_profile={'composition':'00d00701000100','minimum':800,'maximum':20000,'relative':True})
        node=self.journal.state['nodes'][MAC]
        self.assertEqual(node['received'],{'2':[100,1]})
        self.assertEqual(node['tid'],10)
        self.assertTrue(node['proxy_enabled'])
        self.assertEqual(node['binding_revision'],3)
        self.assertEqual(await self.journal.allocate_sequences(),1024)
        self.assertNotIn('retired_nodes',self.journal.state)

    async def test_only_admin_and_paused_entry_can_import(self):
        self.hass.auth.async_get_user.return_value=types.SimpleNamespace(is_admin=False)
        with self.assertRaises(self.Error):
            await self.call()
        self.hass.auth.async_get_user.return_value=types.SimpleNamespace(is_admin=True)
        self.entry.disabled_by=None
        with self.assertRaises(self.Error):
            await self.call()

    async def test_bad_profile_is_rejected_without_mutation(self):
        before=copy.deepcopy(self.journal.state)
        with self.assertRaises(self.Error):
            await self.call(temperature_profile={'composition':'zz'*7,'minimum':800,'maximum':'bad','relative':True})
        self.assertEqual(self.journal.state,before)

    async def test_other_network_is_rejected_without_mutation(self):
        before=copy.deepcopy(self.journal.state)
        with self.assertRaises(self.Error):
            await self.call(network_id='00'*8)
        self.assertEqual(self.journal.state,before)
