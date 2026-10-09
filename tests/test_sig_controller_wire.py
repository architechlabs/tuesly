"""Controller setup and light commands against a synthetic encrypted SIG node."""
import asyncio
import struct
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_mesh_controller import controller_modules, Store, MAC
from test_transport import load_ha_module
from tuesly_mesh.sig_bearer import frames, Reassembler
from tuesly_mesh.sig_mesh_protocol import (
    MeshKeys, encrypt_network_pdu, decrypt_network_pdu, make_access_segmented,
    make_access_unsegmented, decrypt_access_payload, reassemble_and_decrypt_segments,
    parse_segment_header, parse_access_opcode,
)


class ProxyNode:
    mtu_size = 23
    is_connected = True
    def __init__(self, state):
        self.keys = MeshKeys(state['net_key'], state['nodes'][MAC]['dev_key'], state['app_key'])
        self.seq = 10000  # Exercises full SeqAuth beyond the 13-bit SeqZero range.
        self.sar = Reassembler()
        self.segments = {}
        self.bindings = []
        self.on, self.lightness, self.kelvin = True, 32768, 4000
        self.services = MagicMock()
        self.services.get_service.return_value.get_characteristic.side_effect = lambda uuid: uuid
        self.disconnect_count = 0

    async def start_notify(self, characteristic, callback):
        self.notify = callback
    async def stop_notify(self, characteristic):
        pass
    async def disconnect(self):
        self.disconnect_count += 1

    def transmit(self, transport, sequence, *, source=2, ctl=0, dst=1, proxy=False):
        k = self.keys
        packet = encrypt_network_pdu(k.enc_key, k.priv_key, k.nid, ctl=ctl,
                                     ttl=0 if proxy else 5, seq=sequence, src=source, dst=dst,
                                     transport_pdu=transport, proxy_config=proxy)
        for part in frames(bytes([2 if proxy else 0])+packet):
            self.notify(None, bytearray(part))

    def reply(self, payload, *, source=2, device_key=False):
        k = self.keys
        if len(payload) > 11:
            transports = make_access_segmented(k.dev_key if device_key else k.app_key,
                                               source, 1, self.seq, 0, payload,
                                               akf=0 if device_key else 1, aid=0 if device_key else k.aid)
            self.seq += len(transports)
            for sequence, transport in transports:
                self.transmit(transport, sequence, source=source)
        else:
            transport = make_access_unsegmented(k.dev_key if device_key else k.app_key,
                                                source, 1, self.seq, 0, payload,
                                                akf=0 if device_key else 1, aid=0 if device_key else k.aid)
            self.transmit(transport, self.seq, source=source)
            self.seq += 1

    async def write_gatt_char(self, characteristic, data, **kwargs):
        complete = self.sar.feed(data)
        if complete is None:
            return
        k = self.keys
        packet = decrypt_network_pdu(k.enc_key, k.priv_key, k.nid, complete[1:], proxy_config=complete[0]==2)
        if complete[0] == 2:
            assert packet.transport_pdu == b'\x00\x01'
            self.transmit(b'\x03\x01\x00\x00', self.seq, ctl=1, dst=0, proxy=True)
            self.seq += 1
            return
        if packet.ctl:
            return
        access = decrypt_access_payload(k, packet.src, packet.dst, packet.seq, packet.transport_pdu)
        if access.seg:
            header = parse_segment_header(packet.transport_pdu)
            if not self.segments:
                self.segment_start = packet.seq
            self.segments[header.seg_o] = header.segment_data
            if len(self.segments) != header.seg_n+1:
                return
            payload = reassemble_and_decrypt_segments(k, packet.src, packet.dst, self.segments,
                                                      header.seg_n, header.szmic, self.segment_start, header.akf)
            self.segments = {}
        else:
            payload = access.access_payload
        opcode, params = parse_access_opcode(payload)
        if opcode == 0x8008:
            # Composition has OnOff/Lightness on primary and CTL Temp on secondary.
            raw = struct.pack('<HBBHHH', 0, 3, 0, 0x1000, 0x1300, 0x1303) + struct.pack('<HBBH', 0, 1, 0, 0x1306)
            self.reply(b'\x02\x00' + struct.pack('<HHHHH', 0x07d0, 1, 1, 16, 3) + raw, device_key=True)
        elif opcode == 0:
            self.reply(b'\x80\x03\x00' + params[:3], device_key=True)
        elif opcode == 0x803d:
            self.bindings.append(struct.unpack('<HHH', params))
            self.reply(b'\x80\x3e\x00' + params, device_key=True)
        elif opcode in (0x8201, 0x8202):
            if opcode == 0x8202:
                self.on = bool(params[0])
            self.reply(b'\x82\x04' + bytes([self.on]))
        elif opcode in (0x824b, 0x824c):
            if opcode == 0x824c:
                self.lightness = int.from_bytes(params[:2], 'little')
            self.reply(b'\x82\x4e' + struct.pack('<H', self.lightness))
        elif opcode == 0x8262:
            assert packet.dst == 2, 'Range Get belongs to CTL Server, not secondary Temperature Server'
            self.reply(b'\x82\x63\x00' + struct.pack('<HH', 2700, 6500), source=2)
        elif opcode in (0x8261, 0x8264):
            if opcode == 0x8264:
                self.kelvin = int.from_bytes(params[:2], 'little')
            self.reply(b'\x82\x66' + struct.pack('<Hh', self.kelvin, 0), source=3)
        else:
            raise AssertionError(f'Unexpected opcode {opcode:x}')


class WireControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_encrypted_configuration_secondary_element_and_confirmed_controls(self):
        controller, _ = controller_modules()
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        journal = await module.MeshJournal(Store()).load()
        await journal.reserve(MAC)
        await journal.update(MAC, dev_key='22'*16, elements=2, status='configuration_pending')
        node = ProxyNode(journal.state)
        hass = types.SimpleNamespace(data={})
        coordinator = controller.SIGLightCoordinator(hass, MAC, journal)
        resolve, connect = MagicMock(return_value=MagicMock(address=MAC)), AsyncMock(return_value=node)
        with patch.object(controller, 'transport', return_value=(resolve, connect)):
            result = await asyncio.wait_for(coordinator._session(), 5)
            self.assertEqual(result, {'on': True, 'brightness': 128, 'kelvin': 4000})
            self.assertEqual(node.bindings, [(2,0,0x1000), (2,0,0x1300), (3,0,0x1306), (2,0,0x1303)])
            self.assertEqual(journal.state['nodes'][MAC]['status'], 'ready')
            self.assertEqual((coordinator.minimum_kelvin, coordinator.maximum_kelvin), (2700,6500))
            await asyncio.wait_for(coordinator.command(on=True, brightness=200, kelvin=5000), 5)
            self.assertEqual(coordinator.data, {'on': True, 'brightness': 200, 'kelvin': 5000})
            await asyncio.wait_for(coordinator.command(on=False), 5)
            self.assertFalse(coordinator.data['on'])
        self.assertEqual(node.disconnect_count, 3)

    async def test_old_ready_node_gains_ctl_binding_without_reprovisioning(self):
        controller, _ = controller_modules()
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        journal = await module.MeshJournal(Store()).load()
        await journal.reserve(MAC)
        await journal.update(MAC, dev_key='22'*16, elements=2, status='ready')
        before_key = journal.state['nodes'][MAC]['dev_key']
        node = ProxyNode(journal.state)
        coordinator = controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        with patch.object(controller, 'transport', return_value=(MagicMock(), AsyncMock(return_value=node))):
            await asyncio.wait_for(coordinator._session(), 5)
        self.assertIn((2, 0, 0x1303), node.bindings)
        self.assertEqual(journal.state['nodes'][MAC]['dev_key'], before_key)
        self.assertEqual(journal.state['nodes'][MAC]['binding_revision'], 2)
