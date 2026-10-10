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
from tuesly_mesh.exceptions import MeshConnectionError
from tuesly_mesh.sig_mesh_protocol import (
    encrypt_network_pdu, decrypt_network_pdu, generic_onoff_get, generic_onoff_set,
)
from tuesly_mesh.sig_lighting import (
    parse_element_models, select_lighting_channel, lightness_get, lightness_set,
    temperature_get, temperature_set, parse_lightness_status, parse_temperature_status,
)
from .mesh_store import get_journal
from .radio import get_radio
import logging
import inspect

_LOGGER = logging.getLogger(__name__)
_SESSION_TIMEOUT = 50
_CONNECTION_TIMEOUT = 25


class MeshSetupError(Exception):
    """An explicitly authored, credential-free setup failure safe for HA's UI."""


class MeshLinkClosedError(MeshConnectionError):
    """The connected bearer closed before a requested reply was received."""


def transport(hass):
    def resolve(address):
        return bluetooth.async_ble_device_from_address(hass, address, connectable=True)

    async def connect(device, *, disconnected_callback=None):
        return await establish_connection(BleakClientWithServiceCache, device, 'Tuesly SIG Mesh',
                                          disconnected_callback=disconnected_callback,
                                          use_services_cache=False, max_attempts=1,
                                          ble_device_callback=lambda: resolve(device.address) or device)
    return resolve, connect


class ManagedMeshDevice(SIGMeshDevice):
    def __init__(self, *args, journal, **kwargs):
        super().__init__(*args, **kwargs)
        self.journal = journal
        self._defer_composition = True
        self._access_callbacks = []
        self._write_lock = asyncio.Lock()
        self.filter_future = None
        self._response_waiters = set()
        self._endpoint_mac=self._address
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

    def set_endpoint(self,mac,node):
        self._endpoint_mac=mac
        self._target_addr=node['address']
        self._keys.dev_key=bytes.fromhex(node['dev_key'])

    async def _next_seqs(self, n):
        return await self.journal.allocate_sequences(n)

    async def send_configuration(self, payload):
        """Send a short foundation command authenticated with this node's key."""
        from tuesly_mesh.sig_mesh_protocol import make_access_unsegmented
        keys = self._keys
        sequence = await self._next_seq()
        lower = make_access_unsegmented(keys.dev_key, self._our_addr, self._target_addr,
            sequence, keys.iv_index, payload, akf=0, aid=0)
        packet = encrypt_network_pdu(keys.enc_key, keys.priv_key, keys.nid, ctl=0, ttl=5,
            seq=sequence, src=self._our_addr, dst=self._target_addr,
            transport_pdu=lower, iv_index=keys.iv_index)
        await self._write_proxy(b'\x00'+packet)

    async def _write_proxy(self, pdu):
        from tuesly_mesh.sig_bearer import frames
        async with self._write_lock:
            parts=frames(pdu,23)
            for index,part in enumerate(parts):
                if index:
                    await asyncio.sleep(0.02)
                await self._client.write_gatt_char(self._proxy_data_in,part,response=False)

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
            if not await self.journal.accept_received(self._endpoint_mac, packet.src, packet.seq):
                return
            await super()._process_notify(data)

    async def configure_filter(self):
        # Empty reject list permits all destinations. Authenticated Filter Status
        # proves this is our mesh before configuration/access messages are sent.
        k = self._keys
        self.filter_future = asyncio.get_running_loop().create_future()
        try:
            for attempt in range(3):
                seq=await self._next_seq()
                packet=encrypt_network_pdu(k.enc_key,k.priv_key,k.nid,ctl=1,ttl=0,
                    seq=seq,src=self._our_addr,dst=0,transport_pdu=b'\x00\x01',iv_index=k.iv_index,proxy_config=True)
                await self._write_proxy(b'\x02'+packet)
                try:
                    await asyncio.wait_for(asyncio.shield(self.filter_future),4)
                    return
                except TimeoutError:
                    if attempt==2:
                        raise
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
        interval=max(30,len(journal.state['nodes'])*2)
        super().__init__(hass,_LOGGER,config_entry=entry,name='Tuesly SIG light',update_interval=timedelta(seconds=interval))
        self.mac, self.journal = mac, journal
        self.node = journal.state['nodes'][mac]
        self.device = None
        self.models = None
        self.configured = False
        self.minimum_kelvin = self.maximum_kelvin = None
        self.relative_temperature = False
        self.lock=get_radio(hass)
        self.radio = hass.data['tuesly_mesh_controller']
        self.tid = 0
        self.stage = 'initializing'
        self.product_type=entry.data.get('mesh_product_type') if entry else None
        self._command_values={}
        self._command_waiters=[]
        self._command_task=None

    def _make_device(self, *, anchor_mac=None):
        state = self.journal.state
        anchor_mac = anchor_mac or self.mac
        node = state['nodes'][anchor_mac]
        address = node['address']
        secrets = DictSecretsManager({'ha-net-key/password': state['net_key'],
                                      'ha-app-key/password': state['app_key'],
                                      f'ha-dev-key-{address:04x}/password': node['dev_key']})
        resolve, connect = transport(self.hass)
        device = ManagedMeshDevice(anchor_mac, address, 1, secrets, op_item_prefix='ha',
                                   iv_index=state['iv_index'], journal=self.journal,
                                   ble_device_callback=resolve, ble_connect_callback=connect)
        device._node_primary = address
        return device

    async def _open_bearer(self):
        """Try the target, then one reachable saved node in this same mesh."""
        resolve, _ = transport(self.hass)
        candidates=[self.mac]
        for mac,node in self.journal.state['nodes'].items():
            if (mac != self.mac and node.get('dev_key') and node.get('status') == 'ready'
                    and resolve(mac) is not None):
                candidates.append(mac)
                break
        for index,mac in enumerate(candidates):
            self.device=self._make_device() if mac == self.mac else self._make_device(anchor_mac=mac)
            try:
                self.stage='connecting to GATT proxy'
                await asyncio.wait_for(self.device.connect(timeout=15,max_retries=1),_CONNECTION_TIMEOUT)
                self.stage='authenticating proxy filter'
                await self.device.configure_filter()
                return
            except (MeshConnectionError,TimeoutError):
                await self._close_device()
                if index+1 == len(candidates):
                    raise
                self.radio['owner']=self

    async def _request(self, payload, opcode, address, *, composition=False, configuration=False):
        future = asyncio.get_running_loop().create_future()
        self.device._response_waiters.add(future)
        def received(src, actual_opcode, params):
            if src == address and actual_opcode == opcode and not future.done():
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
        raw = await self._request(b'', 0x02, primary, composition=True)
        if len(raw) < 11 or raw[0] != 0:
            raise MeshSetupError('Composition Page 0 is required')
        elements = parse_element_models(raw[11:], primary)
        self.is_tuya = int.from_bytes(raw[1:3],'little') == 0x07D0
        _LOGGER.info('SIG composition for %s: element count=%d; models=%s', self.mac,
                     len(elements), [(e.address, [f'{model:04X}' for model in e.sig_models]) for e in elements])
        if len(elements) != self.node['elements']:
            raise MeshSetupError('Composition element count differs from provisioning capabilities')
        self.models = select_lighting_channel(elements)
        if self.product_type in (1,3,4):
            self.models=type(self.models)(self.models.onoff,self.models.lightness,(),self.models.ctl)
        if not self.models.onoff:
            raise MeshSetupError('This node does not expose a standard OnOff light model')
        if any(len(items) > 1 for items in (self.models.onoff, self.models.lightness, self.models.temperature, self.models.ctl)):
            raise MeshSetupError('Multiple lighting channels require a device-specific profile')
        if self.models.temperature and not self.models.ctl:
            raise MeshSetupError('Temperature server found without a CTL server to report its Kelvin range')
        # Node Identity advertising is temporary. Model binding alone does not
        # guarantee that a node's persistent GATT Proxy state is enabled.
        if int.from_bytes(raw[9:11], 'little') & 2 and not self.journal.state['nodes'][self.mac].get('proxy_enabled'):
            self.stage = 'checking persistent GATT proxy state'
            proxy = await self._request(b'\x80\x12', 0x8014, primary, configuration=True)
            if proxy == b'\x00':
                self.stage = 'enabling persistent GATT proxy'
                proxy = await self._request(b'\x80\x13\x01', 0x8014, primary, configuration=True)
            if proxy != b'\x01':
                raise MeshSetupError('Node did not confirm its GATT Proxy feature is enabled')
            await self.journal.update(self.mac, proxy_enabled=True)
        # Older releases marked nodes ready before binding CTL Server. Upgrade
        # those saved nodes idempotently; preserve their provisioned credentials.
        if self.node['status'] != 'ready' or self.node.get('binding_revision', 0) < 3:
            self.stage = 'installing application key'
            key = bytes.fromhex(self.journal.state['app_key'])
            if not await self.device.send_config_appkey_add(key):
                raise MeshSetupError('Node rejected application key')
            for element in elements:
                for company,model in element.vendor_models:
                    if company==0x07D0 and model in (4,5):
                        self.stage=f'binding Tuya vendor model {model:04X}'
                        if not await self.device.send_config_model_app_bind(element.address,0,model,company_id=company):
                            raise MeshSetupError('Node rejected Tuya vendor binding')
            for addresses, model in ((self.models.onoff, 0x1000), (self.models.lightness, 0x1300),
                                     (self.models.temperature, 0x1306), (self.models.ctl, 0x1303)):
                for address in addresses:
                    self.stage = f'binding model {model:04X} at element {address:04X}'
                    if not await self.device.send_config_model_app_bind(address, 0, model):
                        raise MeshSetupError('Node rejected lighting model binding')
            if self.is_tuya:
                for element in elements:
                    for model in element.sig_models:
                        if model in (0,1) or (model,element.address) in {(0x1000,a) for a in self.models.onoff}|{(0x1300,a) for a in self.models.lightness}|{(0x1306,a) for a in self.models.temperature}|{(0x1303,a) for a in self.models.ctl}:
                            continue
                        self.stage=f'completing Tuya model {model:04X} at {element.address:04X}'
                        if not await self.device.send_config_model_app_bind(element.address,0,model):
                            raise MeshSetupError('Node rejected advertised application model binding')
            await self.journal.update(self.mac, status='ready', binding_revision=3)
            self.node = self.journal.state['nodes'][self.mac]
        if bindings_only:
            return
        if self.models.temperature:
            signature=raw[:7].hex()
            cached=self.journal.state['nodes'][self.mac].get('temperature_profile')
            if cached and cached.get('composition')==signature:
                self.minimum_kelvin,self.maximum_kelvin=cached['minimum'],cached['maximum']
                self.relative_temperature=cached['relative']
                if self.minimum_kelvin==self.maximum_kelvin:
                    self.models=type(self.models)(self.models.onoff,self.models.lightness,(),self.models.ctl)
                return
            async def save_profile():
                await self.journal.update(self.mac,temperature_profile={'composition':signature,
                    'minimum':self.minimum_kelvin,'maximum':self.maximum_kelvin,'relative':self.relative_temperature})
            self.stage = 'reading temperature range'
            try:
                result = await self._request(bytes.fromhex('8262'), 0x8263, self.models.ctl[0])
            except TimeoutError:
                if self.is_tuya:
                    # Tuya documents CTL values 800..20000 as its control scale.
                    # Confirm this model responds, then expose relative warm/cool
                    # instead of pretending these are measured fixture Kelvins.
                    status=parse_temperature_status(await self._request(temperature_get(),0x8266,self.models.temperature[0]))
                    if not 800 <= status.present_kelvin <= 20000:
                        raise MeshSetupError('Invalid Tuya white-temperature value')
                    self.minimum_kelvin,self.maximum_kelvin=800,20000
                    self.relative_temperature=True
                    await save_profile()
                    return
                _LOGGER.warning('Driver %s did not report its temperature range; exposing on/off and brightness',self.mac)
                self.models=type(self.models)(self.models.onoff,self.models.lightness,(),self.models.ctl)
                return
            if len(result) != 5 or result[0] != 0:
                raise MeshSetupError('Node did not supply a valid temperature range')
            minimum, maximum = struct.unpack('<HH', result[1:])
            if not 800 <= minimum <= maximum <= 20000:
                raise MeshSetupError('Invalid reported temperature range')
            if minimum==maximum:
                self.minimum_kelvin,self.maximum_kelvin=minimum,maximum
                await save_profile()
                self.models=type(self.models)(self.models.onoff,self.models.lightness,(),self.models.ctl)
                return
            self.minimum_kelvin, self.maximum_kelvin = minimum, maximum
            await save_profile()

    async def _read(self):
        self.stage = 'reading OnOff status'
        params = await self._request(generic_onoff_get(), 0x8204, self.models.onoff[0])
        if len(params) not in (1, 3) or params[0] not in (0, 1):
            raise MeshSetupError('Invalid OnOff status')
        result = {'on': bool(params[0])}
        if self.models.lightness:
            self.stage = 'reading lightness status'
            result['brightness'] = round(parse_lightness_status(await self._request(
                lightness_get(), 0x824e, self.models.lightness[0])).present * 255 / 65535)
        if self.models.temperature:
            self.stage = 'reading temperature status'
            value=parse_temperature_status(await self._request(temperature_get(),0x8266,self.models.temperature[0])).present_kelvin
            if not self.minimum_kelvin <= value <= self.maximum_kelvin:
                raise MeshSetupError('Temperature status outside the configured control scale')
            result['temperature_percent']=round(100*(value-self.minimum_kelvin)/(self.maximum_kelvin-self.minimum_kelvin))
            if not self.relative_temperature:
                result['kelvin']=value
        return result

    async def _session(self, operation=None):
        # Nested library retries previously outlasted HA's entry setup deadline.
        # Bound the complete session, including waiting for the shared radio.
        async with asyncio.timeout(_SESSION_TIMEOUT):
            return await self._run_session(operation)

    async def _run_session(self, operation=None):
        scope=self.lock.priority(0 if operation else 2) if hasattr(self.lock,'priority') else self.lock
        async with scope:
            owner = self.radio.get('owner')
            if owner is not None and owner is not self:
                owned_device=getattr(owner,'device',None)
                if owned_device and owned_device.is_connected and getattr(owner,'journal',None) is self.journal:
                    self.device,owner.device=owner.device,None
                else:
                    await owner._close_device()
            if self.device and not self.device.is_connected:
                await self._close_device()
            self.radio['owner'] = self
            try:
                scan = getattr(bluetooth, 'async_request_active_scan', None)
                if self.device is None and inspect.iscoroutinefunction(scan):
                    self.stage = 'refreshing Bluetooth discovery'
                    await scan(self.hass, duration=4)
                if self.device is None:
                    await self._open_bearer()
                self.device.set_endpoint(self.mac,self.journal.state['nodes'][self.mac])
                if not self.configured:
                    await self._configure()
                    self.configured = True
                if operation:
                    await operation()
                return await self._read()
            except BaseException:
                await self._close_device()
                raise

    async def _close_device(self):
        device, self.device = self.device, None
        try:
            if device is not None:
                await asyncio.wait_for(device.disconnect(),5)
        except Exception as exc:
            _LOGGER.warning('SIG cleanup failed at %s (%s)',self.stage,type(exc).__name__)
        finally:
            if self.radio.get('owner') is self:
                self.radio.pop('owner',None)

    async def _async_update_data(self):
        try:
            return await self._session()
        except TimeoutError as exc:
            raise UpdateFailed(f'Mesh session timed out at {self.stage}; reload the ESPHome proxy entry and check driver reachability') from exc
        except MeshSetupError as exc:
            raise UpdateFailed(f'SIG setup failed at {self.stage}: {exc}') from exc
        except MeshLinkClosedError as exc:
            raise UpdateFailed(f'Bluetooth disconnected during {self.stage}; mesh response was not received') from exc
        except Exception as exc:
            _LOGGER.debug('SIG operation failed at %s (%s)', self.stage, type(exc).__name__, exc_info=True)
            raise UpdateFailed(f'SIG Mesh response failed at {self.stage} ({type(exc).__name__}); enable debug logging for the traceback') from exc

    async def command(self, *, on=None, brightness=None, kelvin=None,temperature_percent=None):
        values={'on':on,'brightness':brightness,'kelvin':kelvin,'temperature_percent':temperature_percent}
        values={key:value for key,value in values.items() if value is not None}
        if not values:
            return
        if len(self._command_waiters)>=128:
            raise MeshSetupError('Too many pending controls; retry the latest setting')
        self._command_values.update(values)
        future=asyncio.get_running_loop().create_future()
        future.add_done_callback(lambda done:None if done.cancelled() else done.exception())
        self._command_waiters.append(future)
        if self._command_task is None:
            self._command_task=asyncio.create_task(self._drain_commands())
        await asyncio.shield(future)

    async def _drain_commands(self):
        batch=[]
        try:
            while self._command_values:
                # A dragged slider replaces pending values rather than filling
                # the radio queue with stale intermediate settings.
                await asyncio.sleep(0.075)
                values,self._command_values=self._command_values,{}
                batch,self._command_waiters=self._command_waiters,[]
                try:
                    async with asyncio.timeout(45):
                        for attempt in range(2):
                            try:
                                await self._execute_command(**values)
                                break
                            except (TimeoutError,MeshConnectionError):
                                if attempt:
                                    raise
                                await asyncio.sleep(0.3)
                except Exception as exc:
                    self.async_set_update_error(UpdateFailed('Driver did not confirm the command'))
                    for future in batch:
                        if not future.done():future.set_exception(exc)
                else:
                    for future in batch:
                        if not future.done():future.set_result(None)
                batch=[]
        finally:
            for future in [*batch,*self._command_waiters]:
                if not future.done():future.cancel()
            self._command_waiters=[]
            self._command_values={}
            self._command_task=None

    async def _execute_command(self, *, on=None,brightness=None,kelvin=None,temperature_percent=None):
        async def operation():
            # Persist the TID before transmission; restart cannot repeat the latest transaction.
            self.node = self.journal.state['nodes'][self.mac]
            self.tid = (self.node.get('tid', 0) + 1) & 255
            await self.journal.update(self.mac, tid=self.tid)
            if brightness is not None and self.models.lightness:
                await self._request(lightness_set(round(brightness*65535/255), self.tid),
                                    0x824e, self.models.lightness[0])
            target_temperature=kelvin
            if temperature_percent is not None:
                if not 0 <= temperature_percent <= 100:
                    raise ValueError('White temperature must be between 0 and 100 percent')
                target_temperature=round(self.minimum_kelvin+(self.maximum_kelvin-self.minimum_kelvin)*temperature_percent/100)
            if target_temperature is not None and self.models.temperature:
                kelvin_value=target_temperature
                if not self.minimum_kelvin <= kelvin_value <= self.maximum_kelvin:
                    raise ValueError('Temperature is outside the driver-reported range')
                await self._request(temperature_set(kelvin_value,self.tid),0x8266,self.models.temperature[0])
            if on is not None:
                await self._request(generic_onoff_set(on,self.tid),0x8204,self.models.onoff[0])
        try:
            self.async_set_updated_data(await self._session(operation))
        except Exception:
            self.async_set_update_error(UpdateFailed('Driver did not confirm the command'))
            raise

    async def async_stop(self):
        await self.async_shutdown()
        if self._command_task is not None:
            self._command_task.cancel()
            await asyncio.gather(self._command_task,return_exceptions=True)
        async with self.lock:
            await self._close_device()


async def setup_controller(hass, entry):
    from homeassistant.exceptions import ConfigEntryNotReady
    journal = await get_journal(hass)
    mac = entry.data['mac_address']
    if not journal.state['nodes'].get(mac, {}).get('dev_key'):
        raise ConfigEntryNotReady('Mesh credentials missing; restore the Tuesly mesh storage backup')
    coordinator = SIGLightCoordinator(hass, mac, journal, entry)
    cancel_scan = bluetooth.async_register_callback(
        hass, lambda service_info, change: None, {'address': mac, 'connectable': True},
        bluetooth.BluetoothScanningMode.ACTIVE)
    cancelled = False
    def unregister_scan():
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            cancel_scan()
    entry.async_on_unload(unregister_scan)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry,['light','number'])
    except BaseException:
        unregister_scan()
        try:
            await coordinator.async_stop()
        except Exception as exc:
            _LOGGER.warning('Failed setup cleanup (%s)',type(exc).__name__)
        raise
    return True
