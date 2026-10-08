"""On-demand SIG lighting controller using HA's managed Bluetooth transport."""
from __future__ import annotations
import asyncio
import struct
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from tuesly_mesh.secrets import DictSecretsManager
from tuesly_mesh.sig_mesh_device import SIGMeshDevice
from tuesly_mesh.sig_mesh_protocol import (
    encrypt_network_pdu, decrypt_network_pdu, generic_onoff_get, generic_onoff_set,
)
from tuesly_mesh.sig_lighting import (
    parse_element_models, discover_lighting_models, lightness_get, lightness_set,
    temperature_get, temperature_set, parse_lightness_status, parse_temperature_status,
)
from .mesh_store import get_journal
import logging

_LOGGER = logging.getLogger(__name__)


def transport(hass):
    def resolve(address):
        return bluetooth.async_ble_device_from_address(hass, address, connectable=True)

    async def connect(device, *, disconnected_callback=None):
        return await establish_connection(BleakClientWithServiceCache, device, 'Tuesly SIG Mesh',
                                          disconnected_callback=disconnected_callback,
                                          use_services_cache=False, max_attempts=3)
    return resolve, connect


class ManagedMeshDevice(SIGMeshDevice):
    def __init__(self, *args, journal, **kwargs):
        super().__init__(*args, **kwargs)
        self.journal = journal
        self._access_callbacks = []
        self._write_lock = asyncio.Lock()
        self.filter_future = None

    async def _next_seq(self):
        return await self.journal.allocate_sequences()

    async def _next_seqs(self, n):
        return await self.journal.allocate_sequences(n)

    async def _write_proxy(self, pdu):
        async with self._write_lock:
            await super()._write_proxy(pdu)

    async def _process_notify(self, data):
        if data and data[0] == 2 and self._keys:
            k = self._keys
            packet = decrypt_network_pdu(k.enc_key, k.priv_key, k.nid, data[1:],
                                         k.iv_index, proxy_config=True)
            if (packet and packet.ctl == 1 and packet.ttl == 0 and packet.dst == 0
                    and packet.src == self._node_primary and packet.transport_pdu[:2] == b'\x03\x01'
                    and len(packet.transport_pdu) == 4 and self.filter_future
                    and not self.filter_future.done()):
                self.filter_future.set_result(packet.transport_pdu)
            return
        if data and data[0] == 0:
            k = self._keys
            if k is None:
                return
            packet = decrypt_network_pdu(k.enc_key, k.priv_key, k.nid, data[1:], k.iv_index)
            if packet is None or packet.ctl or packet.dst != self._our_addr:
                return
            if not await self.journal.accept_received(self._address, packet.src, packet.seq):
                return
            await super()._process_notify(data)

    async def configure_filter(self):
        # Empty reject list permits all destinations. Authenticated Filter Status
        # proves this is our mesh before configuration/access messages are sent.
        k = self._keys
        self.filter_future = asyncio.get_running_loop().create_future()
        try:
            seq = await self._next_seq()
            packet = encrypt_network_pdu(k.enc_key, k.priv_key, k.nid, ctl=1, ttl=0,
                                         seq=seq, src=self._our_addr, dst=0,
                                         transport_pdu=b'\x00\x01', iv_index=k.iv_index,
                                         proxy_config=True)
            await self._write_proxy(b'\x02' + packet)
            await asyncio.wait_for(self.filter_future, 10)
        finally:
            self.filter_future = None

    async def _ack_segments(self, buf):
        k = self._keys
        seq = await self._next_seq()
        ack = b'\x00' + struct.pack('>HI', buf.seq_zero << 2, (1 << (buf.seg_n+1))-1)
        packet = encrypt_network_pdu(k.enc_key, k.priv_key, k.nid, ctl=1, ttl=5,
                                     seq=seq, src=self._our_addr, dst=buf.src,
                                     transport_pdu=ack, iv_index=k.iv_index)
        await self._write_proxy(b'\x00' + packet)


class SIGLightCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, mac, journal, entry=None):
        super().__init__(hass, _LOGGER, config_entry=entry, name='Tuesly SIG light', update_interval=timedelta(seconds=30))
        self.mac, self.journal = mac, journal
        self.node = journal.state['nodes'][mac]
        self.device = None
        self.models = None
        self.configured = False
        self.minimum_kelvin = self.maximum_kelvin = None
        self.lock = hass.data.setdefault('tuesly_mesh_controller', {}).setdefault('radio_lock', asyncio.Lock())
        self.tid = 0

    def _make_device(self):
        state, node = self.journal.state, self.node
        address = node['address']
        secrets = DictSecretsManager({'ha-net-key/password': state['net_key'],
                                      'ha-app-key/password': state['app_key'],
                                      f'ha-dev-key-{address:04x}/password': node['dev_key']})
        resolve, connect = transport(self.hass)
        device = ManagedMeshDevice(self.mac, address, 1, secrets, op_item_prefix='ha',
                                   iv_index=state['iv_index'], journal=self.journal,
                                   ble_device_callback=resolve, ble_connect_callback=connect)
        device._node_primary = address
        return device

    async def _request(self, payload, opcode, address, *, composition=False):
        future = asyncio.get_running_loop().create_future()
        def received(src, actual_opcode, params):
            if src == address and actual_opcode == opcode and not future.done():
                future.set_result(params)
        self.device._access_callbacks.append(received)
        previous = self.device._target_addr
        try:
            self.device._target_addr = address
            if composition:
                await self.device.request_composition_data()
            else:
                await self.device.send_vendor_command(payload)
            return await asyncio.wait_for(future, 12)
        finally:
            self.device._target_addr = previous
            self.device._access_callbacks.remove(received)

    async def _configure(self):
        primary = self.node['address']
        raw = await self._request(b'', 0x02, primary, composition=True)
        if len(raw) < 11 or raw[0] != 0:
            raise ValueError('Composition Page 0 is required')
        elements = parse_element_models(raw[11:], primary)
        if len(elements) != self.node['elements']:
            raise ValueError('Composition element count differs from provisioning capabilities')
        self.models = discover_lighting_models(elements)
        if not self.models.onoff:
            raise ValueError('This node does not expose a standard OnOff light model')
        if any(len(items) > 1 for items in (self.models.onoff, self.models.lightness, self.models.temperature)):
            raise ValueError('Multiple lighting channels require a device-specific profile')
        if self.node['status'] != 'ready':
            key = bytes.fromhex(self.journal.state['app_key'])
            if not await self.device.send_config_appkey_add(key):
                raise ValueError('Node rejected application key')
            for addresses, model in ((self.models.onoff, 0x1000), (self.models.lightness, 0x1300),
                                     (self.models.temperature, 0x1306)):
                for address in addresses:
                    if not await self.device.send_config_model_app_bind(address, 0, model):
                        raise ValueError('Node rejected lighting model binding')
            await self.journal.update(self.mac, status='ready')
            self.node = self.journal.state['nodes'][self.mac]
        if self.models.temperature:
            result = await self._request(bytes.fromhex('8262'), 0x8263, self.models.temperature[0])
            if len(result) != 5 or result[0] != 0:
                raise ValueError('Node did not supply a valid temperature range')
            minimum, maximum = struct.unpack('<HH', result[1:])
            if not 800 <= minimum <= maximum <= 20000:
                raise ValueError('Invalid reported temperature range')
            self.minimum_kelvin, self.maximum_kelvin = minimum, maximum

    async def _read(self):
        params = await self._request(generic_onoff_get(), 0x8204, self.models.onoff[0])
        if len(params) not in (1, 3) or params[0] not in (0, 1):
            raise ValueError('Invalid OnOff status')
        result = {'on': bool(params[0])}
        if self.models.lightness:
            result['brightness'] = round(parse_lightness_status(await self._request(
                lightness_get(), 0x824e, self.models.lightness[0])).present * 255 / 65535)
        if self.models.temperature:
            result['kelvin'] = parse_temperature_status(await self._request(
                temperature_get(), 0x8266, self.models.temperature[0])).present_kelvin
        return result

    async def _session(self, operation=None):
        async with self.lock:
            self.device = self._make_device()
            try:
                await self.device.connect(timeout=20, max_retries=3)
                await self.device.configure_filter()
                if not self.configured:
                    await self._configure()
                    self.configured = True
                if operation:
                    await operation()
                return await self._read()
            finally:
                await self.device.disconnect()
                self.device = None

    async def _async_update_data(self):
        try:
            return await self._session()
        except Exception as exc:
            raise UpdateFailed(f'SIG Mesh response failed ({type(exc).__name__}); check driver power and proxy') from exc

    async def command(self, *, on, brightness=None, kelvin=None):
        async def operation():
            # Persist the TID before transmission; restart cannot repeat the latest transaction.
            self.node = self.journal.state['nodes'][self.mac]
            self.tid = (self.node.get('tid', 0) + 1) & 255
            await self.journal.update(self.mac, tid=self.tid)
            if brightness is not None and self.models.lightness:
                await self._request(lightness_set(round(brightness*65535/255), self.tid),
                                    0x824e, self.models.lightness[0])
            if kelvin is not None and self.models.temperature:
                if not self.minimum_kelvin <= kelvin <= self.maximum_kelvin:
                    raise ValueError('Temperature is outside the driver-reported range')
                await self._request(temperature_set(kelvin, self.tid), 0x8266, self.models.temperature[0])
            await self._request(generic_onoff_set(on, self.tid), 0x8204, self.models.onoff[0])
        try:
            self.async_set_updated_data(await self._session(operation))
        except Exception:
            self.async_set_update_error(UpdateFailed('Driver did not confirm the command'))
            raise

    async def async_stop(self):
        await self.async_shutdown()
        async with self.lock:
            if self.device:
                await self.device.disconnect()


async def setup_controller(hass, entry):
    from homeassistant.exceptions import ConfigEntryNotReady
    journal = await get_journal(hass)
    mac = entry.data['mac_address']
    if not journal.state['nodes'].get(mac, {}).get('dev_key'):
        raise ConfigEntryNotReady('Mesh credentials missing; restore the Tuesly mesh storage backup')
    coordinator = SIGLightCoordinator(hass, mac, journal, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ['light'])
    return True
