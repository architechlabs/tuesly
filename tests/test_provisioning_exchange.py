"""Real P-256/CMAC/CCM exchange against an in-process PB-GATT node."""
import asyncio
import types
import unittest
from unittest.mock import MagicMock, patch
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

    async def test_failed_credential_save_prevents_network_delivery(self):
        provisioner, node = await self.make_exchange(fail=True)
        with patch('tuesly_mesh.sig_mesh_provisioner_exchange._POST_START_PDU_DELAY', 0):
            with self.assertRaises(OSError):
                await asyncio.wait_for(provisioner._run_exchange(node), 5)
        self.assertFalse(node.data_received)
