"""Controller regressions with a fake HA storage/transport boundary."""
import asyncio
import copy
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_transport import load_ha_module
from tuesly_mesh.sig_bearer import frames, Reassembler
from tuesly_mesh.sig_mesh_protocol import MeshKeys, encrypt_network_pdu, decrypt_network_pdu
from tuesly_mesh.sig_mesh_device import SIGMeshDevice

MAC = 'DC:23:52:81:60:BB'


def controller_modules():
    components = types.ModuleType('homeassistant.components')
    components.bluetooth = MagicMock()
    helpers = types.ModuleType('homeassistant.helpers')
    updater = types.ModuleType('homeassistant.helpers.update_coordinator')
    class Coordinator:
        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
        def async_set_updated_data(self, data):
            self.data = data
        def async_set_update_error(self, error):
            self.error = error
    updater.DataUpdateCoordinator = Coordinator
    updater.UpdateFailed = RuntimeError
    sys.modules.update({'homeassistant.components': components,
                        'homeassistant.helpers': helpers,
                        'homeassistant.helpers.update_coordinator': updater})
    load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
    controller = load_ha_module('custom_components.tuesly.sig_controller', 'sig_controller.py')
    commission = load_ha_module('custom_components.tuesly.sig_commission', 'sig_commission.py')
    return controller, commission


class Store:
    def __init__(self):
        self.saved = None
        self.fail = False
    async def async_load(self):
        return copy.deepcopy(self.saved)
    async def async_save(self, state):
        if self.fail:
            raise OSError('storage failure')
        self.saved = copy.deepcopy(state)


class JournalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        self.cls = module.MeshJournal
        self.store = Store()
        self.journal = await self.cls(self.store).load()

    async def test_restart_discards_unused_sequence_lease(self):
        self.assertEqual(await self.journal.allocate_sequences(2), 0)
        restarted = await self.cls(self.store).load()
        self.assertEqual(await restarted.allocate_sequences(), 256)

    async def test_concurrent_nodes_share_unique_sequences(self):
        allocated = await asyncio.gather(*(self.journal.allocate_sequences() for _ in range(300)))
        self.assertEqual(len(set(allocated)), 300)
        self.assertEqual(self.store.saved['sequence_high'], 512)

    async def test_failed_save_cannot_issue_sequence(self):
        self.store.fail = True
        with self.assertRaises(OSError):
            await self.journal.allocate_sequences()
        self.assertEqual(self.journal.next_seq, 0)

    async def test_reservations_never_overlap_or_reuse_failed_ranges(self):
        first = await self.journal.reserve(MAC)
        second = await self.journal.reserve('another')
        self.assertEqual(second['address'] - first['address'], 255)
        self.assertEqual(await self.journal.reserve(MAC), first)

    async def test_credentials_and_pending_configuration_survive_restart(self):
        await self.journal.reserve(MAC)
        await self.journal.update(MAC, dev_key='11'*16, elements=2, status='configuration_pending')
        restarted = await self.cls(self.store).load()
        self.assertEqual(restarted.state['nodes'][MAC]['status'], 'configuration_pending')

    async def test_exhaustion_never_wraps(self):
        self.journal.state['sequence_high'] = 0x1000000
        with self.assertRaises(RuntimeError):
            await self.journal.allocate_sequences()

    async def test_replay_window_survives_restart_and_accepts_reordered_segments(self):
        await self.journal.reserve(MAC)
        await self.journal.update(MAC, elements=2)
        self.assertTrue(await self.journal.accept_received(MAC, 2, 10000))
        self.assertTrue(await self.journal.accept_received(MAC, 2, 9999))
        self.assertFalse(await self.journal.accept_received(MAC, 2, 9999))
        restarted = await self.cls(self.store).load()
        self.assertFalse(await restarted.accept_received(MAC, 2, 10000))
        self.assertFalse(await restarted.accept_received(MAC, 4, 10001))


class BearerTests(unittest.TestCase):
    def test_all_component_python_compiles(self):
        from test_transport import COMPONENT
        for path in COMPONENT.rglob('*.py'):
            compile(path.read_text(encoding='utf-8'), str(path), 'exec')

    def test_mtu23_framing_and_reassembly(self):
        payload = b'\x00' + bytes(range(60))
        parts = frames(payload)
        self.assertTrue(all(len(part) <= 20 for part in parts))
        self.assertEqual([p[0] >> 6 for p in parts], [1, 2, 2, 3])
        assembler = Reassembler()
        results = [assembler.feed(part) for part in parts]
        self.assertEqual(results, [None, None, None, payload])

    def test_cross_type_and_orphan_fragments_are_rejected(self):
        assembler = Reassembler()
        self.assertIsNone(assembler.feed(b'\x80data'))
        assembler.feed(b'\x40start')
        self.assertIsNone(assembler.feed(b'\xc2wrong'))

    def test_proxy_nonce_is_distinct_from_network_nonce(self):
        keys = MeshKeys('11'*16, '22'*16, '33'*16)
        packet = encrypt_network_pdu(keys.enc_key, keys.priv_key, keys.nid, ctl=1, ttl=0,
                                     seq=13, src=1, dst=0, transport_pdu=b'\x00\x01', proxy_config=True)
        self.assertIsNone(decrypt_network_pdu(keys.enc_key, keys.priv_key, keys.nid, packet))
        result = decrypt_network_pdu(keys.enc_key, keys.priv_key, keys.nid, packet, proxy_config=True)
        self.assertEqual(result.transport_pdu, b'\x00\x01')


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller, self.commission = controller_modules()

    async def test_setup_without_confirmation_sends_no_provisioning(self):
        flow = MagicMock()
        flow._discovery_info = {'address': MAC}
        flow.async_set_unique_id = AsyncMock()
        flow.async_show_form.side_effect = lambda **kw: kw
        journal = MagicMock(state={'nodes': {}})
        with patch.object(self.commission, 'get_journal', AsyncMock(return_value=journal)), \
             patch.object(self.commission, 'SIGMeshProvisioner') as provisioner:
            result = await self.commission.setup(flow, {'reset_confirmed': False})
        provisioner.assert_not_called()
        self.assertEqual(result['errors'], {'base': 'reset_required'})

    async def test_saved_keys_resume_without_reprovisioning(self):
        flow = MagicMock()
        flow._discovery_info = {'address': MAC}
        flow.async_set_unique_id = AsyncMock()
        flow.async_create_entry.side_effect = lambda **kw: kw
        journal = MagicMock(state={'nodes': {MAC: {'dev_key': '11'*16}}})
        with patch.object(self.commission, 'get_journal', AsyncMock(return_value=journal)), \
             patch.object(self.commission, 'SIGMeshProvisioner') as provisioner:
            result = await self.commission.setup(flow, {})
        provisioner.assert_not_called()
        self.assertEqual(result['data'], {'mac_address': MAC, 'device_type': 'sig_light'})
        self.assertNotIn('dev_key', result['data'])

    async def test_response_from_other_element_does_not_resolve_request(self):
        journal = MagicMock(state={'nodes': {MAC: {'address': 2}}})
        coord = self.controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        coord.device = MagicMock(_target_addr=2, _access_callbacks=[])
        coord.device.send_vendor_command = AsyncMock()
        task = asyncio.create_task(coord._request(b'\x82\x01', 0x8204, 2))
        await asyncio.sleep(0)
        callback = coord.device._access_callbacks[0]
        callback(3, 0x8204, b'\x01')
        self.assertFalse(task.done())
        callback(2, 0x8204, b'\x01')
        self.assertEqual(await task, b'\x01')
        self.assertFalse(coord.device._access_callbacks)

    async def test_config_status_from_another_node_is_ignored(self):
        device = SIGMeshDevice(MAC, 2, 1, MagicMock())
        future = asyncio.get_running_loop().create_future()
        device._pending_responses[(0x8003, 1)] = future
        await device._dispatch_access_payload_unlocked(3, 0x8003, b'\x00'*4)
        self.assertFalse(future.done())
        await device._dispatch_access_payload_unlocked(2, 0x8003, b'\x00'*4)
        self.assertEqual(await future, b'\x00'*4)

    async def test_session_always_releases_connection_on_error(self):
        journal = MagicMock(state={'nodes': {MAC: {'address': 2}}})
        coord = self.controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        device = MagicMock()
        device.connect = AsyncMock()
        device.configure_filter = AsyncMock(side_effect=RuntimeError('filter timeout'))
        device.disconnect = AsyncMock()
        coord._make_device = MagicMock(return_value=device)
        with self.assertRaises(RuntimeError):
            await coord._session()
        device.disconnect.assert_awaited_once()
        self.assertIsNone(coord.device)

    async def test_connection_timeout_releases_client_and_becomes_retryable_update_failure(self):
        journal = MagicMock(state={'nodes': {MAC: {'address': 2}}})
        coord = self.controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        device = MagicMock()
        async def wait_forever(**kwargs):
            await asyncio.Event().wait()
        device.connect = AsyncMock(side_effect=wait_forever)
        device.disconnect = AsyncMock()
        coord._make_device = MagicMock(return_value=device)
        with patch.object(self.controller, '_CONNECTION_TIMEOUT', .01):
            with self.assertRaisesRegex(RuntimeError, 'reload the ESPHome proxy'):
                await coord._async_update_data()
        device.disconnect.assert_awaited_once()
        self.assertIsNone(coord.device)

    async def test_wait_for_busy_radio_is_bounded(self):
        journal = MagicMock(state={'nodes': {MAC: {'address': 2}}})
        coord = self.controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        await coord.lock.acquire()
        try:
            with patch.object(self.controller, '_SESSION_TIMEOUT', .01):
                with self.assertRaises(TimeoutError):
                    await coord._session()
            self.assertIsNone(coord.device)
        finally:
            coord.lock.release()

    async def test_authored_setup_reason_is_visible_without_exposing_unknown_exception_text(self):
        journal = MagicMock(state={'nodes': {MAC: {'address': 2}}})
        coord = self.controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        coord.stage = 'reading temperature range'
        coord._session = AsyncMock(side_effect=self.controller.MeshSetupError('Invalid reported temperature range'))
        with self.assertRaisesRegex(RuntimeError, 'reading temperature range: Invalid reported temperature range'):
            await coord._async_update_data()
        coord._session = AsyncMock(side_effect=ValueError('private exception text'))
        with self.assertRaises(RuntimeError) as raised:
            await coord._async_update_data()
        self.assertNotIn('private exception text', str(raised.exception))
        self.assertIn('reading temperature range (ValueError)', str(raised.exception))

    def test_intentional_disconnect_does_not_emit_failure_warning(self):
        device = SIGMeshDevice(MAC, 2, 1, MagicMock())
        device._intentional_disconnect = True
        with patch('tuesly_mesh.sig_mesh_device_segments._LOGGER') as logger:
            device._on_ble_disconnect(None)
        logger.warning.assert_not_called()
        logger.debug.assert_called_once()

    def test_unexpected_disconnect_still_warns(self):
        device = SIGMeshDevice(MAC, 2, 1, MagicMock())
        with patch('tuesly_mesh.sig_mesh_device_segments._LOGGER') as logger:
            device._on_ble_disconnect(None)
        logger.warning.assert_called_once()
