# Generated from the tested integration by tools/build_recovery_addon.py.
from __future__ import annotations
import asyncio,copy,logging,secrets,struct
from tuesly_mesh.sig_mesh_device import SIGMeshDevice
from tuesly_mesh.exceptions import MeshConnectionError
from tuesly_mesh.sig_mesh_protocol import encrypt_network_pdu,decrypt_network_pdu,generic_onoff_get
from tuesly_mesh.sig_lighting import parse_element_models,select_lighting_channel,lightness_get,temperature_get,parse_lightness_status,parse_temperature_status
_LOGGER=logging.getLogger(__name__)
class MeshSetupError(Exception):pass
class MeshLinkClosedError(MeshConnectionError):pass
class MeshJournal:

    def __init__(self, store):
        self.store = store
        self.lock = asyncio.Lock()
        self.state = None
        self.next_seq = self.seq_end = 0

    async def load(self):
        async with self.lock:
            if self.state is None:
                self.state = await self.store.async_load()
                if self.state is None:
                    self.state = dict(net_key=secrets.token_hex(16), app_key=secrets.token_hex(16), iv_index=0, address_next=2, sequence_high=0, nodes={})
                    await self.store.async_save(copy.deepcopy(self.state))
                self.next_seq = self.seq_end = self.state['sequence_high']
        return self

    async def allocate_sequences(self, count=1):
        if not 1 <= count <= 32:
            raise ValueError('Invalid sequence reservation')
        async with self.lock:
            if self.next_seq + count > self.seq_end:
                start = self.state['sequence_high']
                end = start + max(256, count)
                if end > 16777216:
                    raise RuntimeError('Mesh sequence space exhausted; IV Update is required')
                candidate = copy.deepcopy(self.state)
                candidate['sequence_high'] = end
                await self.store.async_save(candidate)
                self.state = candidate
                self.next_seq, self.seq_end = (start, end)
            result = self.next_seq
            self.next_seq += count
            return result

    async def reserve(self, mac, *, replace=False):
        async with self.lock:
            if mac in self.state['nodes'] and (not replace):
                return copy.deepcopy(self.state['nodes'][mac])
            address = self.state['address_next']
            if address + 254 > 32767:
                raise RuntimeError('Mesh address space exhausted')
            candidate = copy.deepcopy(self.state)
            if mac in candidate['nodes']:
                candidate.setdefault('retired_nodes', []).append({'address': mac, 'record': candidate['nodes'][mac]})
            candidate['address_next'] = address + 255
            candidate['nodes'][mac] = dict(address=address, status='reserved')
            await self.store.async_save(candidate)
            self.state = candidate
            return copy.deepcopy(candidate['nodes'][mac])

    async def restore_node(self, mac, record):
        """Restore prior credentials after failure before Provisioning Data.

        Keep the new address reservation consumed because its outcome may be
        uncertain. Callers must never use this after handing over new keys.
        """
        async with self.lock:
            candidate = copy.deepcopy(self.state)
            candidate['nodes'][mac] = copy.deepcopy(record)
            await self.store.async_save(candidate)
            self.state = candidate

    async def update(self, mac, **fields):
        async with self.lock:
            candidate = copy.deepcopy(self.state)
            candidate['nodes'][mac].update(fields)
            await self.store.async_save(candidate)
            self.state = candidate

    async def accept_received(self, mac, source, sequence):
        """Persist a bounded replay window before delivering an authenticated packet."""
        async with self.lock:
            node = self.state['nodes'][mac]
            if not node['address'] <= source < node['address'] + node['elements']:
                return False
            previous = node.get('received', {}).get(str(source), [-1, 0])
            high, bitmap = previous
            if sequence > high:
                shift = sequence - high
                bitmap = 1 if shift >= 64 else (bitmap << shift | 1) & (1 << 64) - 1
                high = sequence
            else:
                distance = high - sequence
                if distance >= 64 or bitmap & 1 << distance:
                    return False
                bitmap |= 1 << distance
            candidate = copy.deepcopy(self.state)
            candidate['nodes'][mac].setdefault('received', {})[str(source)] = [high, bitmap]
            await self.store.async_save(candidate)
            self.state = candidate
            return True

class ManagedMeshDevice(SIGMeshDevice):

    def __init__(self, *args, journal, **kwargs):
        super().__init__(*args, **kwargs)
        self.journal = journal
        self._defer_composition = True
        self._access_callbacks = []
        self._write_lock = asyncio.Lock()
        self.filter_future = None
        self._response_waiters = set()
        self._endpoint_mac = self._address
        self.register_disconnect_callback(self._abort_waiters)

    def _abort_waiters(self):
        if self._intentional_disconnect:
            return
        waiters = [*self._response_waiters, *self._pending_responses.values()]
        if self.filter_future is not None:
            waiters.append(self.filter_future)
        for future in waiters:
            if not future.done():
                future.set_exception(MeshLinkClosedError('Bluetooth disconnected before the mesh reply'))

    async def _next_seq(self):
        return await self.journal.allocate_sequences()

    def set_endpoint(self, mac, node):
        self._endpoint_mac = mac
        self._target_addr = node['address']
        self._keys.dev_key = bytes.fromhex(node['dev_key'])

    async def _next_seqs(self, n):
        return await self.journal.allocate_sequences(n)

    async def send_configuration(self, payload):
        """Send a short foundation command authenticated with this node's key."""
        from tuesly_mesh.sig_mesh_protocol import make_access_unsegmented
        keys = self._keys
        sequence = await self._next_seq()
        lower = make_access_unsegmented(keys.dev_key, self._our_addr, self._target_addr, sequence, keys.iv_index, payload, akf=0, aid=0)
        packet = encrypt_network_pdu(keys.enc_key, keys.priv_key, keys.nid, ctl=0, ttl=5, seq=sequence, src=self._our_addr, dst=self._target_addr, transport_pdu=lower, iv_index=keys.iv_index)
        await self._write_proxy(b'\x00' + packet)

    async def _write_proxy(self, pdu):
        from tuesly_mesh.sig_bearer import frames
        async with self._write_lock:
            parts = frames(pdu, 23)
            for index, part in enumerate(parts):
                if index:
                    await asyncio.sleep(0.02)
                await self._client.write_gatt_char(self._proxy_data_in, part, response=False)

    async def _process_notify(self, data):
        if data and data[0] == 2 and self._keys:
            k = self._keys
            packet = decrypt_network_pdu(k.enc_key, k.priv_key, k.nid, data[1:], k.iv_index, proxy_config=True)
            if packet and packet.ctl == 1 and (packet.ttl == 0) and (packet.dst == 0) and (packet.src == self._node_primary) and (packet.transport_pdu[:2] == b'\x03\x01') and (len(packet.transport_pdu) == 4) and self.filter_future and (not self.filter_future.done()):
                self.filter_future.set_result(packet.transport_pdu)
            return
        if data and data[0] == 0:
            k = self._keys
            if k is None:
                return
            packet = decrypt_network_pdu(k.enc_key, k.priv_key, k.nid, data[1:], k.iv_index)
            if packet is None or packet.ctl or packet.dst != self._our_addr:
                return
            if not await self.journal.accept_received(self._endpoint_mac, packet.src, packet.seq):
                return
            await super()._process_notify(data)

    async def configure_filter(self):
        k = self._keys
        self.filter_future = asyncio.get_running_loop().create_future()
        try:
            for attempt in range(3):
                seq = await self._next_seq()
                packet = encrypt_network_pdu(k.enc_key, k.priv_key, k.nid, ctl=1, ttl=0, seq=seq, src=self._our_addr, dst=0, transport_pdu=b'\x00\x01', iv_index=k.iv_index, proxy_config=True)
                await self._write_proxy(b'\x02' + packet)
                try:
                    await asyncio.wait_for(asyncio.shield(self.filter_future), 4)
                    return
                except TimeoutError:
                    if attempt == 2:
                        raise
        finally:
            self.filter_future = None

    async def _ack_segments(self, buf):
        k = self._keys
        seq = await self._next_seq()
        ack = b'\x00' + struct.pack('>HI', buf.seq_zero << 2, (1 << buf.seg_n + 1) - 1)
        packet = encrypt_network_pdu(k.enc_key, k.priv_key, k.nid, ctl=1, ttl=5, seq=seq, src=self._our_addr, dst=buf.src, transport_pdu=ack, iv_index=k.iv_index)
        await self._write_proxy(b'\x00' + packet)

class NodeConfigurator:
    def __init__(self,mac,journal,device):
        self.mac,self.journal,self.device=mac,journal,device
        self.node=journal.state['nodes'][mac]
        self.models=None
        self.product_type=None
        self.minimum_kelvin=self.maximum_kelvin=None
        self.relative_temperature=False
        self.stage='initializing'

    async def _request(self, payload, opcode, address, *, composition=False, configuration=False):
        future = asyncio.get_running_loop().create_future()
        self.device._response_waiters.add(future)
    
        def received(src, actual_opcode, params):
            if src == address and actual_opcode == opcode and (not future.done()):
                future.set_result(params)
        self.device._access_callbacks.append(received)
        previous = self.device._target_addr
        try:
            self.device._target_addr = address
            if composition:
                await self.device.request_composition_data()
            elif configuration:
                await self.device.send_configuration(payload)
            else:
                await self.device.send_vendor_command(payload)
            return await asyncio.wait_for(future, 12)
        finally:
            self.device._target_addr = previous
            self.device._access_callbacks.remove(received)
            self.device._response_waiters.discard(future)

    async def _configure(self, *, bindings_only=False):
        primary = self.node['address']
        self.stage = 'reading Composition Page 0'
        raw = await self._request(b'', 2, primary, composition=True)
        if len(raw) < 11 or raw[0] != 0:
            raise MeshSetupError('Composition Page 0 is required')
        elements = parse_element_models(raw[11:], primary)
        self.is_tuya = int.from_bytes(raw[1:3], 'little') == 2000
        _LOGGER.info('SIG composition for %s: element count=%d; models=%s', self.mac, len(elements), [(e.address, [f'{model:04X}' for model in e.sig_models]) for e in elements])
        if len(elements) != self.node['elements']:
            raise MeshSetupError('Composition element count differs from provisioning capabilities')
        self.models = select_lighting_channel(elements)
        if self.product_type in (1, 3, 4):
            self.models = type(self.models)(self.models.onoff, self.models.lightness, (), self.models.ctl)
        if not self.models.onoff:
            raise MeshSetupError('This node does not expose a standard OnOff light model')
        if any((len(items) > 1 for items in (self.models.onoff, self.models.lightness, self.models.temperature, self.models.ctl))):
            raise MeshSetupError('Multiple lighting channels require a device-specific profile')
        if self.models.temperature and (not self.models.ctl):
            raise MeshSetupError('Temperature server found without a CTL server to report its Kelvin range')
        if int.from_bytes(raw[9:11], 'little') & 2 and (not self.journal.state['nodes'][self.mac].get('proxy_enabled')):
            self.stage = 'checking persistent GATT proxy state'
            proxy = await self._request(b'\x80\x12', 32788, primary, configuration=True)
            if proxy == b'\x00':
                self.stage = 'enabling persistent GATT proxy'
                proxy = await self._request(b'\x80\x13\x01', 32788, primary, configuration=True)
            if proxy != b'\x01':
                raise MeshSetupError('Node did not confirm its GATT Proxy feature is enabled')
            await self.journal.update(self.mac, proxy_enabled=True)
        if self.node['status'] != 'ready' or self.node.get('binding_revision', 0) < 3:
            self.stage = 'installing application key'
            key = bytes.fromhex(self.journal.state['app_key'])
            if not await self.device.send_config_appkey_add(key):
                raise MeshSetupError('Node rejected application key')
            for element in elements:
                for company, model in element.vendor_models:
                    if company == 2000 and model in (4, 5):
                        self.stage = f'binding Tuya vendor model {model:04X}'
                        if not await self.device.send_config_model_app_bind(element.address, 0, model, company_id=company):
                            raise MeshSetupError('Node rejected Tuya vendor binding')
            for addresses, model in ((self.models.onoff, 4096), (self.models.lightness, 4864), (self.models.temperature, 4870), (self.models.ctl, 4867)):
                for address in addresses:
                    self.stage = f'binding model {model:04X} at element {address:04X}'
                    if not await self.device.send_config_model_app_bind(address, 0, model):
                        raise MeshSetupError('Node rejected lighting model binding')
            if self.is_tuya:
                for element in elements:
                    for model in element.sig_models:
                        if model in (0, 1) or (model, element.address) in {(4096, a) for a in self.models.onoff} | {(4864, a) for a in self.models.lightness} | {(4870, a) for a in self.models.temperature} | {(4867, a) for a in self.models.ctl}:
                            continue
                        self.stage = f'completing Tuya model {model:04X} at {element.address:04X}'
                        if not await self.device.send_config_model_app_bind(element.address, 0, model):
                            raise MeshSetupError('Node rejected advertised application model binding')
            await self.journal.update(self.mac, status='ready', binding_revision=3)
            self.node = self.journal.state['nodes'][self.mac]
        if bindings_only:
            return
        if self.models.temperature:
            signature = raw[:7].hex()
            cached = self.journal.state['nodes'][self.mac].get('temperature_profile')
            if cached and cached.get('composition') == signature:
                self.minimum_kelvin, self.maximum_kelvin = (cached['minimum'], cached['maximum'])
                self.relative_temperature = cached['relative']
                if self.minimum_kelvin == self.maximum_kelvin:
                    self.models = type(self.models)(self.models.onoff, self.models.lightness, (), self.models.ctl)
                return
    
            async def save_profile():
                await self.journal.update(self.mac, temperature_profile={'composition': signature, 'minimum': self.minimum_kelvin, 'maximum': self.maximum_kelvin, 'relative': self.relative_temperature})
            self.stage = 'reading temperature range'
            try:
                result = await self._request(bytes.fromhex('8262'), 33379, self.models.ctl[0])
            except TimeoutError:
                if self.is_tuya:
                    status = parse_temperature_status(await self._request(temperature_get(), 33382, self.models.temperature[0]))
                    if not 800 <= status.present_kelvin <= 20000:
                        raise MeshSetupError('Invalid Tuya white-temperature value')
                    self.minimum_kelvin, self.maximum_kelvin = (800, 20000)
                    self.relative_temperature = True
                    await save_profile()
                    return
                _LOGGER.warning('Driver %s did not report its temperature range; exposing on/off and brightness', self.mac)
                self.models = type(self.models)(self.models.onoff, self.models.lightness, (), self.models.ctl)
                return
            if len(result) != 5 or result[0] != 0:
                raise MeshSetupError('Node did not supply a valid temperature range')
            minimum, maximum = struct.unpack('<HH', result[1:])
            if not 800 <= minimum <= maximum <= 20000:
                raise MeshSetupError('Invalid reported temperature range')
            if minimum == maximum:
                self.minimum_kelvin, self.maximum_kelvin = (minimum, maximum)
                await save_profile()
                self.models = type(self.models)(self.models.onoff, self.models.lightness, (), self.models.ctl)
                return
            self.minimum_kelvin, self.maximum_kelvin = (minimum, maximum)
            await save_profile()

    async def _read(self):
        self.stage = 'reading OnOff status'
        params = await self._request(generic_onoff_get(), 33284, self.models.onoff[0])
        if len(params) not in (1, 3) or params[0] not in (0, 1):
            raise MeshSetupError('Invalid OnOff status')
        result = {'on': bool(params[0])}
        if self.models.lightness:
            self.stage = 'reading lightness status'
            result['brightness'] = round(parse_lightness_status(await self._request(lightness_get(), 33358, self.models.lightness[0])).present * 255 / 65535)
        if self.models.temperature:
            self.stage = 'reading temperature status'
            value = parse_temperature_status(await self._request(temperature_get(), 33382, self.models.temperature[0])).present_kelvin
            if not self.minimum_kelvin <= value <= self.maximum_kelvin:
                raise MeshSetupError('Temperature status outside the configured control scale')
            result['temperature_percent'] = round(100 * (value - self.minimum_kelvin) / (self.maximum_kelvin - self.minimum_kelvin))
            if not self.relative_temperature:
                result['kelvin'] = value
        return result
