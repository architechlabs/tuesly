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
        self.composition = None
        self.temperature_source = 3
        self.primary = 2
        self.proxy_primary = 2
        self.mesh_nodes = None
        self.proxy_enabled = False

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

    def reply(self, payload, *, source=None, device_key=False):
        source = self.primary if source is None else source
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
            self.transmit(b'\x03\x01\x00\x00', self.seq, source=self.proxy_primary, ctl=1, dst=0, proxy=True)
            self.seq += 1
            return
        if packet.ctl:
            return
        if self.mesh_nodes is not None:
            for record in self.mesh_nodes.values():
                if record['address'] <= packet.dst < record['address']+record['elements']:
                    self.primary = record['address']
                    self.temperature_source = self.primary+1
                    k.dev_key = bytes.fromhex(record['dev_key'])
                    break
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
        if opcode in (0x8012,0x8013):
            assert access.akf == 0, 'Foundation commands require the device key'
            if opcode == 0x8013:
                self.proxy_enabled = bool(params[0])
            self.reply(b'\x80\x14'+bytes([self.proxy_enabled]),device_key=True)
        elif opcode == 0x8008:
            # Composition has OnOff/Lightness on primary and CTL Temp on secondary.
            raw = struct.pack('<HBBHHH', 0, 3, 0, 0x1000, 0x1300, 0x1303) + struct.pack('<HBBH', 0, 1, 0, 0x1306)
            self.reply((b'\x02'+self.composition) if self.composition else (b'\x02\x00' + struct.pack('<HHHHH', 0x07d0, 1, 1, 16, 3) + raw), device_key=True)
        elif opcode == 0:
            self.reply(b'\x80\x03\x00' + params[:3], device_key=True)
        elif opcode == 0x803d:
            self.bindings.append(struct.unpack('<'+'H'*(len(params)//2), params))
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
            assert packet.dst == self.primary, 'Range Get belongs to CTL Server, not secondary Temperature Server'
            self.reply(b'\x82\x63\x00' + struct.pack('<HH', 2700, 6500))
        elif opcode in (0x8261, 0x8264):
            if opcode == 0x8264:
                self.kelvin = int.from_bytes(params[:2], 'little')
            self.reply(b'\x82\x66' + struct.pack('<Hh', self.kelvin, 0), source=self.temperature_source)
        else:
            raise AssertionError(f'Unexpected opcode {opcode:x}')


class WireControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_without_direct_ble_path_uses_authenticated_saved_mesh_anchor(self):
        controller,_=controller_modules()
        module=load_ha_module('custom_components.tuesly.mesh_store','mesh_store.py')
        journal=await module.MeshJournal(Store()).load()
        anchor='DC:23:52:81:60:BC'
        for mac,key in ((MAC,'22'*16),(anchor,'44'*16)):
            await journal.reserve(mac)
            await journal.update(mac,dev_key=key,elements=2,status='ready')
        node=ProxyNode(journal.state)
        node.proxy_primary=journal.state['nodes'][anchor]['address']
        node.mesh_nodes=journal.state['nodes']
        coordinator=controller.SIGLightCoordinator(types.SimpleNamespace(data={}),MAC,journal)
        resolve=lambda mac:types.SimpleNamespace(address=mac) if mac==anchor else None
        connect=AsyncMock(return_value=node)
        with patch.object(controller,'transport',return_value=(resolve,connect)):
            result=await coordinator._session()
            self.assertTrue(result['on'])
            self.assertEqual(coordinator.device._address,anchor)
            self.assertEqual(coordinator.device._node_primary,journal.state['nodes'][anchor]['address'])
            self.assertEqual(coordinator.device._target_addr,journal.state['nodes'][MAC]['address'])
            self.assertEqual(coordinator.device._keys.dev_key,bytes.fromhex('22'*16))
            await coordinator.command(on=False,brightness=180)
            self.assertFalse(coordinator.data['on'])
            self.assertEqual(coordinator.data['brightness'],180)
        connect.assert_awaited_once()
        await coordinator._close_device()
    async def test_two_encrypted_nodes_share_one_bearer_and_use_their_own_device_keys(self):
        controller, _ = controller_modules()
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        journal = await module.MeshJournal(Store()).load()
        second_mac = 'DC:23:52:81:60:BC'
        for mac, key in ((MAC,'22'*16),(second_mac,'44'*16)):
            await journal.reserve(mac)
            await journal.update(mac, dev_key=key, elements=2, status='configuration_pending')
        node = ProxyNode(journal.state)
        node.mesh_nodes = journal.state['nodes']
        hass = types.SimpleNamespace(data={})
        first = controller.SIGLightCoordinator(hass, MAC, journal)
        second = controller.SIGLightCoordinator(hass, second_mac, journal)
        connect = AsyncMock(return_value=node)
        with patch.object(controller, 'transport', return_value=(MagicMock(),connect)):
            await first._session()
            await second._session()
            self.assertIsNone(first.device)
            self.assertEqual(second.device._keys.dev_key, bytes.fromhex('44'*16))
            self.assertEqual(second.device._node_primary,2)
            await second.command(on=False)
            self.assertFalse(second.data['on'])
            await first.command(on=True, brightness=190)
            self.assertTrue(first.data['on'])
            self.assertEqual(first.data['brightness'],190)
            self.assertEqual(first.device._keys.dev_key, bytes.fromhex('22'*16))
            self.assertIsNone(second.device)
        connect.assert_awaited_once()
        self.assertEqual(node.disconnect_count,0)
        await first._close_device()
        self.assertEqual(node.disconnect_count,1)

    async def test_measured_tuya_composition_binds_all_app_models_and_caches_relative_profile(self):
        controller, _ = controller_modules()
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        journal = await module.MeshJournal(Store()).load()
        await journal.reserve(MAC)
        await journal.update(MAC, dev_key='22'*16, elements=6, status='configuration_pending')
        node = ProxyNode(journal.state)
        node.composition = bytes.fromhex('00d007800233388001070000001102000002000300001001100013011302130313041306130513071308130a130b130913d0070400d0070500000001000010000001000010000001000010000001000010000001000010')
        node.temperature_source = 2
        coordinator = controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        real_request = coordinator._request
        range_requests = []
        async def request(payload, opcode, address, **kwargs):
            if opcode == 0x8263:
                range_requests.append(1)
                raise TimeoutError
            return await real_request(payload, opcode, address, **kwargs)
        coordinator._request = request
        with patch.object(controller, 'transport', return_value=(MagicMock(), AsyncMock(return_value=node))):
            await coordinator._session()
            self.assertIn((2,0,0x07d0,4), node.bindings)
            self.assertIn((2,0,0x07d0,5), node.bindings)
            self.assertEqual(len(node.bindings), 23)
            self.assertTrue(all(binding[-1] not in (0,1) for binding in node.bindings))
            self.assertTrue(coordinator.relative_temperature)
            await coordinator.command(temperature_percent=100)
            self.assertEqual(coordinator.data['temperature_percent'], 100)
            self.assertTrue(coordinator.data['on'])
            coordinator.configured = False
            await coordinator._session()
            self.assertEqual(len(range_requests), 1)
        await coordinator._close_device()

    async def test_slider_burst_sends_latest_value_and_one_transaction(self):
        controller,_=controller_modules()
        module=load_ha_module('custom_components.tuesly.mesh_store','mesh_store.py')
        journal=await module.MeshJournal(Store()).load()
        await journal.reserve(MAC)
        await journal.update(MAC,dev_key='22'*16,elements=2,status='configuration_pending')
        node=ProxyNode(journal.state)
        coordinator=controller.SIGLightCoordinator(types.SimpleNamespace(data={}),MAC,journal)
        connect=AsyncMock(return_value=node)
        with patch.object(controller,'transport',return_value=(MagicMock(),connect)):
            await coordinator._session()
            await asyncio.gather(*(coordinator.command(on=True,brightness=value) for value in range(200,250)))
        self.assertEqual(coordinator.data['brightness'],249)
        self.assertEqual(journal.state['nodes'][MAC]['tid'],1)
        connect.assert_awaited_once()
        await coordinator._close_device()
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
            self.assertEqual(result, {'on':True,'brightness':128,'kelvin':4000,'temperature_percent':34})
            self.assertEqual(node.bindings, [(2,0,0x1000), (2,0,0x1300), (3,0,0x1306), (2,0,0x1303)])
            self.assertEqual(journal.state['nodes'][MAC]['status'], 'ready')
            self.assertEqual((coordinator.minimum_kelvin, coordinator.maximum_kelvin), (2700,6500))
            await asyncio.wait_for(coordinator.command(on=True, brightness=200, kelvin=5000), 5)
            self.assertEqual(coordinator.data, {'on':True,'brightness':200,'kelvin':5000,'temperature_percent':61})
            await asyncio.wait_for(coordinator.command(on=False), 5)
            self.assertFalse(coordinator.data['on'])
        self.assertEqual(node.disconnect_count, 0)
        connect.assert_awaited_once()
        await coordinator._close_device()
        self.assertEqual(node.disconnect_count,1)

    async def test_radio_handoff_closes_previous_owner(self):
        controller, _ = controller_modules()
        module = load_ha_module('custom_components.tuesly.mesh_store','mesh_store.py')
        journal=await module.MeshJournal(Store()).load()
        await journal.reserve(MAC)
        await journal.update(MAC,dev_key='22'*16,elements=2,status='configuration_pending')
        old_owner=types.SimpleNamespace(_close_device=AsyncMock())
        hass=types.SimpleNamespace(data={'tuesly_mesh_controller':{'owner':old_owner}})
        coordinator=controller.SIGLightCoordinator(hass,MAC,journal)
        node=ProxyNode(journal.state)
        with patch.object(controller,'transport',return_value=(MagicMock(),AsyncMock(return_value=node))):
            await coordinator._session()
        old_owner._close_device.assert_awaited_once()
        self.assertIs(coordinator.radio['owner'],coordinator)
        await coordinator._close_device()
        self.assertNotIn('owner',coordinator.radio)

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
        self.assertEqual(journal.state['nodes'][MAC]['binding_revision'],3)

    async def test_missing_range_keeps_confirmed_brightness_available(self):
        controller, _ = controller_modules()
        module = load_ha_module('custom_components.tuesly.mesh_store', 'mesh_store.py')
        journal = await module.MeshJournal(Store()).load()
        await journal.reserve(MAC)
        await journal.update(MAC, dev_key='22'*16, elements=2, status='configuration_pending')
        node = ProxyNode(journal.state)
        coordinator = controller.SIGLightCoordinator(types.SimpleNamespace(data={}), MAC, journal)
        request = coordinator._request
        async def missing_range(payload, opcode, address, **kwargs):
            if opcode == 0x8263:
                raise TimeoutError
            return await request(payload,opcode,address,**kwargs)
        coordinator._request = missing_range
        with patch.object(controller, 'transport', return_value=(MagicMock(), AsyncMock(return_value=node))):
            result = await coordinator._session()
        self.assertEqual(result,{'on':True,'brightness':128,'temperature_percent':17})
        self.assertEqual(coordinator.models.temperature,(3,))
        self.assertTrue(coordinator.relative_temperature)
        self.assertEqual((coordinator.minimum_kelvin,coordinator.maximum_kelvin),(800,20000))
