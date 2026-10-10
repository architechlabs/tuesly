"""Real P-256/CMAC/CCM exchange against an in-process PB-GATT node."""
import asyncio
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_transport import load_ha_module
from tuesly_mesh.sig_mesh_provisioner import SIGMeshProvisioner
from tuesly_mesh.sig_mesh_crypto import s1, k1, aes_cmac, mesh_aes_ccm_decrypt
from tuesly_mesh.sig_bearer import frames, Reassembler
from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1, ECDH, EllipticCurvePublicNumbers


class Node:
    mtu_size = 23
    def __init__(self, test, journal, fail_save=False):
        self.test, self.journal = test, journal
        self.services = MagicMock()
        self.sar = Reassembler()
        self.private = generate_private_key(SECP256R1())
        numbers = self.private.public_key().public_numbers()
        self.public = numbers.x.to_bytes(32,'big') + numbers.y.to_bytes(32,'big')
        self.random = b'\xaa' * 16
        self.caps = b'\x02\x00\x01' + b'\x00' * 8
        self.data_received = False
        self.messages = []

    async def start_notify(self, characteristic, callback):
        self.notify = callback

    def reply(self, pdu):
        # Replies arrive before write_gatt_char returns. Fragmented PublicKey
        # also arrives while the provisioner is sleeping between TX writes.
        for part in frames(b'\x03' + pdu, 23):
            self.notify(None, bytearray(part))

    async def write_gatt_char(self, characteristic, data, **kwargs):
        complete = self.sar.feed(data)
        if complete is None:
            return
        pdu = complete[1:]
        self.messages.append(pdu[0])
        if pdu[0] == 0:
            self.invite = pdu[1:]
            self.reply(b'\x01' + self.caps)
        elif pdu[0] == 2:
            self.start = pdu[1:]
        elif pdu[0] == 3:
            prov_public = pdu[1:]
            public = EllipticCurvePublicNumbers(int.from_bytes(prov_public[:32],'big'),
                                                int.from_bytes(prov_public[32:],'big'), SECP256R1()).public_key()
            self.shared = self.private.exchange(ECDH(), public)
            self.salt = s1(self.invite + self.caps + self.start + prov_public + self.public)
            self.confirm_key = k1(self.shared, self.salt, b'prck')
            self.reply(b'\x03' + self.public)
        elif pdu[0] == 5:
            self.prov_confirmation = pdu[1:]
            self.reply(b'\x05' + aes_cmac(self.confirm_key, self.random + b'\x00'*16))
        elif pdu[0] == 6:
            self.prov_random = pdu[1:]
            self.test.assertEqual(self.prov_confirmation, aes_cmac(self.confirm_key, self.prov_random+b'\x00'*16))
            self.reply(b'\x06' + self.random)
        elif pdu[0] == 7:
            self.test.assertIsNotNone(self.journal.saved['nodes']['node'].get('dev_key'))
            self.data_received = True
            salt = s1(self.salt + self.prov_random + self.random)
            plaintext = mesh_aes_ccm_decrypt(k1(self.shared,salt,b'prsk'),
                                            k1(self.shared,salt,b'prsn')[3:], pdu[1:], 8)
            self.test.assertEqual(plaintext[:16].hex(), self.journal.saved['net_key'])
            self.test.assertEqual(int.from_bytes(plaintext[-2:],'big'), 2)
            self.test.assertEqual(self.journal.saved['nodes']['node']['dev_key'], k1(self.shared,salt,b'prdk').hex())
            self.reply(b'\x08')


class ProvisioningTests(unittest.IsolatedAsyncioTestCase):
    async def test_reusing_delivered_provisioner_cannot_repeat_network_delivery(self):
        from tuesly_mesh.exceptions import ProvisioningError
        provisioner,_=await self.make_exchange()
        provisioner._provisioning_data_attempted=True
        provisioner._connect=AsyncMock()
        with self.assertRaisesRegex(ProvisioningError,'resume saved credentials'):
            await provisioner.provision('DC:23:52:81:60:BB')
        provisioner._connect.assert_not_awaited()
    async def test_disconnected_provisioning_link_aborts_wait_without_full_timeout(self):
        from tuesly_mesh.exceptions import ProvisioningLinkClosedError
        provisioner,node=await self.make_exchange()
        provisioner._provisioning_link_closed=asyncio.Event()
        node.reply=lambda pdu:provisioner._provisioning_link_closed.set()
        with self.assertRaises(ProvisioningLinkClosedError):
            await asyncio.wait_for(provisioner._run_exchange(node),.5)
        self.assertFalse(node.data_received)

    async def test_peer_already_closed_after_complete_can_transition_without_cccd_write(self):
        provisioner,_=await self.make_exchange()
        client=types.SimpleNamespace(is_connected=False,stop_notify=AsyncMock(),write_gatt_descriptor=AsyncMock())
        await provisioner._finish_provisioning_bearer(client)
        client.stop_notify.assert_not_awaited()
        client.write_gatt_descriptor.assert_not_awaited()
    async def test_public_key_timeout_retries_with_new_ephemeral_key(self):
        from tuesly_mesh.exceptions import ProvisioningTimeoutError
        provisioner, _ = await self.make_exchange()
        client = MagicMock(stop_notify=AsyncMock(),disconnect=AsyncMock())
        provisioner._cleanup_stale_connections = AsyncMock()
        provisioner._connect = AsyncMock(return_value=client)
        public_keys=[]
        async def exchange(connected):
            public_keys.append(provisioner._our_pub_key_bytes)
            if len(public_keys)==1:
                provisioner.stage='public_key'
                raise ProvisioningTimeoutError('Timeout waiting for PublicKey')
            return 'complete'
        provisioner._run_exchange=AsyncMock(side_effect=exchange)
        with patch('tuesly_mesh.sig_mesh_provisioner._BLE_SLOT_RELEASE_DELAY',0):
            self.assertEqual(await provisioner.provision('DC:23:52:81:60:BB'),'complete')
        self.assertEqual(provisioner._connect.await_count,2)
        self.assertNotEqual(public_keys[0],public_keys[1])

    async def test_lost_complete_after_possible_data_delivery_never_reprovisions(self):
        from tuesly_mesh.exceptions import ProvisioningTimeoutError
        provisioner, _ = await self.make_exchange()
        client = MagicMock(stop_notify=AsyncMock(),disconnect=AsyncMock())
        provisioner._cleanup_stale_connections=AsyncMock()
        provisioner._connect=AsyncMock(return_value=client)
        async def exchange(connected):
            provisioner._provisioning_data_attempted=True
            raise ProvisioningTimeoutError('Timeout waiting for Complete')
        provisioner._run_exchange=AsyncMock(side_effect=exchange)
        with patch('tuesly_mesh.sig_mesh_provisioner._BLE_SLOT_RELEASE_DELAY',0):
            with self.assertRaises(ProvisioningTimeoutError):
                await provisioner.provision('DC:23:52:81:60:BB')
        provisioner._connect.assert_awaited_once()

    async def test_credential_storage_failure_is_not_automatically_retried(self):
        provisioner, _ = await self.make_exchange()
        client=MagicMock(stop_notify=AsyncMock(),disconnect=AsyncMock())
        provisioner._cleanup_stale_connections=AsyncMock()
        provisioner._connect=AsyncMock(return_value=client)
        provisioner._run_exchange=AsyncMock(side_effect=OSError('storage failure'))
        with patch('tuesly_mesh.sig_mesh_provisioner._BLE_SLOT_RELEASE_DELAY',0):
            with self.assertRaises(OSError):
                await provisioner.provision('DC:23:52:81:60:BB')
        provisioner._connect.assert_awaited_once()

    async def test_handoff_disables_peer_cccd_before_unregistering_notifications(self):
        provisioner, _ = await self.make_exchange()
        provisioner._prov_data_out = types.SimpleNamespace(descriptors=[types.SimpleNamespace(
            uuid='00002902-0000-1000-8000-00805f9b34fb',handle=21)])
        events=[]
        client=types.SimpleNamespace(
            write_gatt_descriptor=AsyncMock(side_effect=lambda handle,data:events.append((handle,data))),
            stop_notify=AsyncMock(side_effect=lambda characteristic:events.append('stop_notify')))
        await provisioner._finish_provisioning_bearer(client)
        self.assertEqual(events,[(21,b'\x00\x00'),'stop_notify'])

    async def test_configuration_opens_fresh_proxy_after_provisioning_disconnect(self):
        provisioner, _ = await self.make_exchange()
        events = []
        client = MagicMock()
        client.stop_notify = AsyncMock(side_effect=lambda *args: events.append('unsubscribe'))
        client.disconnect = AsyncMock(side_effect=lambda: events.append('disconnect'))
        provisioner._cleanup_stale_connections = AsyncMock()
        provisioner._connect = AsyncMock(return_value=client)
        provisioner._run_exchange = AsyncMock(return_value='result')
        async def configure(connected, result):
            self.assertIsNone(connected)
            self.assertEqual(result,'result')
            self.assertIn('disconnect',events)
            events.append('configured')
        provisioner.configuration_callback = configure
        with patch('tuesly_mesh.sig_mesh_provisioner._BLE_SLOT_RELEASE_DELAY',0):
            self.assertEqual(await provisioner.provision('DC:23:52:81:60:BB'), 'result')
        self.assertEqual(events,['unsubscribe','disconnect','configured','unsubscribe','disconnect'])

    async def make_exchange(self, fail=False):
        from test_mesh_controller import Store
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        store = Store()
        journal = await module.MeshJournal(store).load()
        await journal.reserve('node')
        provisioner = SIGMeshProvisioner(bytes.fromhex(journal.state['net_key']),
                                         bytes.fromhex(journal.state['app_key']), 2,
                                         ble_connect_callback=lambda: None)
        async def persist(key, elements):
            store.fail = fail
            await journal.update('node', dev_key=key.hex(), elements=elements)
        provisioner.journal_callback = persist
        return provisioner, Node(self, store)

    async def test_fast_fragmented_replies_and_credentials_before_delivery(self):
        provisioner, node = await self.make_exchange()
        with patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_START_PDU_DELAY', 0), \
             patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_COMPLETE_DELAY', 0):
            result = await asyncio.wait_for(provisioner._run_exchange(node), 5)
        self.assertTrue(node.data_received)
        self.assertEqual(result.num_elements, 2)
        self.assertEqual(node.messages, [0, 2, 3, 5, 6, 7])

    async def test_real_crypto_exchange_recovers_from_first_lost_public_key(self):
        provisioner, first=await self.make_exchange()
        second=Node(self,first.journal)
        original_reply=first.reply
        first.reply=lambda pdu:None if pdu[0]==3 else original_reply(pdu)
        for node in (first,second):
            node.stop_notify=AsyncMock()
            node.disconnect=AsyncMock()
        provisioner._cleanup_stale_connections=AsyncMock()
        provisioner._connect=AsyncMock(side_effect=[first,second])
        with patch('tuesly_mesh.sig_mesh_provisioner_exchange.PROVISIONING_PUBLIC_KEY_TIMEOUT',.01), \
             patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_START_PDU_DELAY',0), \
             patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_COMPLETE_DELAY',0), \
             patch('tuesly_mesh.sig_mesh_provisioner._BLE_SLOT_RELEASE_DELAY',0):
            result=await provisioner.provision('DC:23:52:81:60:BB')
        self.assertEqual(result.num_elements,2)
        self.assertFalse(first.data_received)
        self.assertTrue(second.data_received)

    async def test_real_lost_complete_keeps_delivered_keys_and_delivery_marker(self):
        from tuesly_mesh.exceptions import ProvisioningTimeoutError
        provisioner,node=await self.make_exchange()
        original_reply=node.reply
        node.reply=lambda pdu:None if pdu[0]==8 else original_reply(pdu)
        with patch('tuesly_mesh.sig_mesh_provisioner_exchange.PROVISIONING_COMPLETE_TIMEOUT',.01), \
             patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_START_PDU_DELAY',0):
            with self.assertRaises(ProvisioningTimeoutError):
                await provisioner._run_exchange(node)
        self.assertTrue(node.data_received)
        self.assertTrue(provisioner._provisioning_data_attempted)
        self.assertIn('dev_key',node.journal.saved['nodes']['node'])

    async def test_failed_credential_save_prevents_network_delivery(self):
        provisioner, node = await self.make_exchange(fail=True)
        with patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_START_PDU_DELAY', 0):
            with self.assertRaises(OSError):
                await asyncio.wait_for(provisioner._run_exchange(node), 5)
        self.assertFalse(node.data_received)
