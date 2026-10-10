"""Private, authenticated hardware diagnostic; does not provision or control lights.

HA's target/provider entries must be paused. Uses a separate diagnostic source
address and durable sequence journal, so HA's sender nonce state is untouched.
Reload/re-enable ESPHome afterward to restore the Bluetooth subscriber.
"""
import asyncio
import copy
import importlib
import json
import logging
import sys
import types
from pathlib import Path
import yaml
from aioesphomeapi import APIClient

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT/'custom_components/tuesly'
PRIVATE = ROOT/'.private'
MAC = 'DC:23:52:81:60:BB'
SOURCE = 0x7fff
CONFIGURE = '--configure' in sys.argv


def modules():
    # Import the actual mesh bearer without instantiating HA's coordinator.
    sys.path.insert(0, str(COMPONENT/'lib'))
    for name in ['custom_components', 'custom_components.tuesly', 'homeassistant',
                 'homeassistant.components', 'homeassistant.helpers']:
        module = types.ModuleType(name)
        module.__path__ = [str(COMPONENT)]
        sys.modules[name] = module
    bluetooth = types.ModuleType('homeassistant.components.bluetooth')
    sys.modules[bluetooth.__name__] = bluetooth
    update = types.ModuleType('homeassistant.helpers.update_coordinator')
    class Coordinator:
        def __init__(self, hass, *args, **kwargs):
            self.hass = hass
        def async_set_updated_data(self, data):
            self.data = data
        def async_set_update_error(self, error):
            self.error = error
    update.DataUpdateCoordinator = Coordinator
    update.UpdateFailed = RuntimeError
    sys.modules[update.__name__] = update
    return importlib.import_module('custom_components.tuesly.sig_controller')


class PrivateStore:
    def __init__(self, original):
        self.path = PRIVATE/'diagnostic-journal.json'
        self.original = original

    async def async_load(self):
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if state['net_key'] != self.original['net_key']:
                raise RuntimeError('Diagnostic journal belongs to another mesh')
            previous=state['nodes']
            state['nodes']=copy.deepcopy(self.original['nodes'])
            for mac,node in state['nodes'].items():
                old=previous.get(mac,{})
                if old.get('dev_key')==node.get('dev_key') and old.get('address')==node.get('address'):
                    for field in ('status','binding_revision','temperature_profile','received','tid','proxy_enabled'):
                        if field in old:node[field]=copy.deepcopy(old[field])
            return state
        state = copy.deepcopy(self.original)
        state['sequence_high'] = 0
        return state

    async def async_save(self, state):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state), encoding='utf-8')
        temporary.replace(self.path)


class GATTAdapter:
    mtu_size = 23
    def __init__(self, api, target, services):
        self.api, self.target = api, target
        self.is_connected = True
        self.disconnected = None
        self.notifications = {}
        self.services = self
        self.table = services.services

    def __iter__(self):
        return iter(self.table)

    def get_service(self, uuid):
        for service in self.table:
            if service.uuid.lower() == uuid.lower():
                return types.SimpleNamespace(get_characteristic=lambda uuid, service=service:
                    next((char for char in service.characteristics if char.uuid.lower() == uuid.lower()), None))
        return None

    async def start_notify(self, characteristic, callback):
        self.notifications[characteristic.handle] = await self.api.bluetooth_gatt_start_notify(
            self.target, characteristic.handle, callback)
        cccd = next((descriptor for descriptor in characteristic.descriptors
                     if descriptor.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb'), None)
        if cccd is None:
            raise RuntimeError('Notification CCCD is missing')
        await self.api.bluetooth_gatt_write_descriptor(self.target, cccd.handle, b'\x01\x00')

    async def stop_notify(self, characteristic):
        callbacks = self.notifications.pop(characteristic.handle, None)
        if callbacks:
            cccd = next((descriptor for descriptor in characteristic.descriptors
                         if descriptor.uuid.lower() == '00002902-0000-1000-8000-00805f9b34fb'), None)
            if cccd is not None and self.is_connected:
                await self.api.bluetooth_gatt_write_descriptor(self.target, cccd.handle, b'\x00\x00')
            await callbacks[0]()

    async def write_gatt_char(self, characteristic, data, *, response=False):
        await self.api.bluetooth_gatt_write(self.target, characteristic.handle, data, response)

    async def write_gatt_descriptor(self, handle, data):
        await self.api.bluetooth_gatt_write_descriptor(self.target, handle, data)

    async def disconnect(self):
        await self.api.bluetooth_device_disconnect(self.target, timeout=5)
        self.is_connected = False

    async def set_connection_params(self,minimum,maximum,latency,timeout):
        await self.api.bluetooth_device_set_connection_params(self.target,minimum,maximum,latency,timeout)


async def inspect():
    controller = modules()
    from custom_components.tuesly.mesh_store import MeshJournal
    from tuesly_mesh.secrets import DictSecretsManager
    from tuesly_mesh.sig_lighting import parse_element_models
    original = json.loads((PRIVATE/'ha-mesh.json').read_text(encoding='utf-8'))['data']
    if original['address_next'] > SOURCE or any(
        node['address'] <= SOURCE < node['address'] + node.get('elements', 255)
        for node in original['nodes'].values()):
        raise RuntimeError('Diagnostic source address is not available')
    journal = await MeshJournal(PrivateStore(original)).load()
    node = journal.state['nodes'][MAC]
    prefix = 'diag'
    secrets = DictSecretsManager({
        f'{prefix}-net-key/password': original['net_key'],
        f'{prefix}-app-key/password': original['app_key'],
        f'{prefix}-dev-key-{node["address"]:04x}/password': node['dev_key']})
    config = yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text(encoding='utf-8'))
    api = APIClient('192.168.20.181', 6053, noise_psk=config['tuya_api_encryption_key'],
                    client_info='tuesly-authenticated-inspection')
    target = int(MAC.replace(':', ''), 16)
    device = None
    adapter = None
    cancel_advertisements = cancel_connection = None
    report = {'stage': 'api', 'authenticated_mesh': False}
    try:
        await asyncio.wait_for(api.connect(login=True), 12)
        info = await api.device_info()
        capabilities = await api.device_capabilities_compat(info)
        from tuesly_mesh.sig_mesh_crypto import k3
        network_id = k3(bytes.fromhex(original['net_key']))
        seen = asyncio.Event()
        def advertisement(message):
            for adv in message.advertisements:
                if adv.address != target:
                    continue
                report['address_type'] = adv.address_type
                (PRIVATE/'latest-advertisement.hex').write_text(bytes(adv.data).hex(),encoding='utf-8')
                seen.set()
                data, offset = bytes(adv.data), 0
                while offset < len(data):
                    size = data[offset]
                    if size == 0 or offset+size+1 > len(data):
                        break
                    if data[offset+1] == 0x16:
                        service = data[offset+2:offset+1+size]
                        if service[:2] == b'\x28\x18' and len(service) >= 3:
                            report['proxy_advertisement_type'] = service[2]
                            if service[2] == 0 and len(service) == 11:
                                report['advertised_network_matches_saved_key'] = service[3:] == network_id
                                report['advertised_network_matches_reversed_id'] = service[3:] == network_id[::-1]
                    offset += size+1
        cancel_advertisements = api.subscribe_bluetooth_le_raw_advertisements(advertisement)
        report['stage']='waiting_for_target_advertisement'
        if '--wait-for-power-cycle' in sys.argv:
            print('Ready: waiting 180 seconds for driver restart advertisement',flush=True)
        if '--connect-known-address' in sys.argv:
            report['address_type'] = 0
            report['connection_without_fresh_advertisement'] = True
        else:
            await asyncio.wait_for(seen.wait(), 180 if '--wait-for-power-cycle' in sys.argv else 12)
        if '--advertisements-only' in sys.argv:
            report['stage'] = 'network_identity_checked'
            return report
        report['stage'] = 'gatt'
        def state(connected, mtu, error):
            if not connected and adapter is not None:
                adapter.is_connected = False
                if adapter.disconnected:
                    adapter.disconnected(adapter)
        cancel_connection = await api.bluetooth_device_connect(target, state, timeout=20,
            feature_flags=capabilities.bluetooth_proxy.feature_flags, has_cache=False, address_type=report['address_type'])
        services = await api.bluetooth_gatt_get_services(target)
        adapter = GATTAdapter(api, target, services)
        async def connected(ble_device, *, disconnected_callback=None):
            adapter.disconnected = disconnected_callback
            return adapter
        device = controller.ManagedMeshDevice(MAC, node['address'], SOURCE, secrets,
            op_item_prefix=prefix, iv_index=original['iv_index'], journal=journal,
            ble_device_callback=lambda address: types.SimpleNamespace(address=address),
            ble_connect_callback=connected)
        device._node_primary = node['address']
        if CONFIGURE:
            async def connect_existing(ble_device, *, disconnected_callback=None):
                if not adapter.is_connected:
                    await api.bluetooth_device_connect(target,state,timeout=20,
                        feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=report['address_type'])
                    adapter.table=(await api.bluetooth_gatt_get_services(target)).services
                    adapter.is_connected=True
                adapter.disconnected = disconnected_callback
                return adapter
            controller.transport = lambda hass: (lambda address:types.SimpleNamespace(address=address),connect_existing)
            coordinator = controller.SIGLightCoordinator(types.SimpleNamespace(data={}),MAC,journal)
            make_device = coordinator._make_device
            def make_diagnostic_device():
                managed = make_device()
                managed._our_addr = SOURCE
                managed._access_callbacks.append(lambda src, opcode, params: report.setdefault('access_responses', []).append({'source':src,'opcode':f'{opcode:04X}','parameters':params.hex() if opcode != 2 else f'{len(params)} bytes'}))
                process = managed._process_notify
                report['notifications'] = []
                async def capture(data):
                    from tuesly_mesh.sig_mesh_protocol import decrypt_network_pdu
                    record = {'kind':data[0] if data else None,'length':len(data)}
                    if len(data)==23 and data[:2]==b'\x01\x01':
                        record['beacon_network_matches_saved_key']=data[3:11]==network_id
                    keys = managed._keys
                    if keys and data and data[0] in (0,2):
                        packet=decrypt_network_pdu(keys.enc_key,keys.priv_key,keys.nid,data[1:],keys.iv_index,proxy_config=data[0]==2)
                        record['network_authenticated'] = packet is not None
                        if packet:
                            record.update(source=packet.src,destination=packet.dst)
                            if data[0]==2:
                                record['filter_status']=packet.transport_pdu.hex()
                    report['notifications'].append(record)
                    await process(data)
                managed._process_notify = capture
                return managed
            coordinator._make_device = make_diagnostic_device
            if '--probe-access' in sys.argv:
                configure = coordinator._configure
                async def probe_configuration():
                    try:
                        await configure()
                    except TimeoutError:
                        if coordinator.stage != 'reading temperature range':
                            raise
                    report['probes'] = []
                    for request, opcode in [('8201',0x8204),('824b',0x824e),('8261',0x8266)]:
                        try:
                            result=await coordinator._request(bytes.fromhex(request),opcode,node['address'])
                            report['probes'].append({'request':request,'response':result.hex()})
                        except TimeoutError:
                            report['probes'].append({'request':request,'timeout':True})
                    raise controller.MeshSetupError('Diagnostic probe completed')
                coordinator._configure=probe_configuration
            report['stage'] = 'configuration'
            try:
                async def controls():
                    from tuesly_mesh.sig_mesh_protocol import generic_onoff_set
                    from tuesly_mesh.sig_lighting import lightness_set
                    original_state = await coordinator._read()
                    report['state']=dict(original_state)
                    report['control_checks'] = []
                    for on, brightness in [(False,None),(True,128),(True,220)]:
                        tid=(journal.state['nodes'][MAC].get('tid',0)+1)&255
                        await journal.update(MAC,tid=tid)
                        if brightness is not None:
                            await coordinator._request(lightness_set(round(brightness*65535/255),tid),0x824e,node['address'])
                        await coordinator._request(generic_onoff_set(on,tid),0x8204,node['address'])
                        report['control_checks'].append(await coordinator._read())
                    tid=(tid+1)&255
                    await journal.update(MAC,tid=tid)
                    await coordinator._request(lightness_set(round(original_state['brightness']*65535/255),tid),0x824e,node['address'])
                    await coordinator._request(generic_onoff_set(original_state['on'],tid),0x8204,node['address'])
                    report['restored_state']=await coordinator._read()
                async def temperatures():
                    original=await coordinator._read()
                    report['temperature_checks']=[]
                    from tuesly_mesh.sig_lighting import temperature_set
                    for percent in (0,50,100,original['temperature_percent']):
                        tid=(journal.state['nodes'][MAC].get('tid',0)+1)&255
                        await journal.update(MAC,tid=tid)
                        value=round(coordinator.minimum_kelvin+(coordinator.maximum_kelvin-coordinator.minimum_kelvin)*percent/100)
                        await coordinator._request(temperature_set(value,tid),0x8266,node['address'])
                        report['temperature_checks'].append({'requested_percent':percent,'confirmed_state':await coordinator._read()})
                operation=temperatures if '--temperature' in sys.argv else (controls if '--control' in sys.argv else None)
                report['state'] = await coordinator._session(operation)
                report.update(stage='configuration_complete',authenticated_mesh=True,
                              configured=True,minimum_kelvin=coordinator.minimum_kelvin,
                              maximum_kelvin=coordinator.maximum_kelvin)
            except Exception as exc:
                report.update(stage=coordinator.stage,failure_type=type(exc).__name__)
                if isinstance(exc,controller.MeshSetupError):
                    report['reason'] = str(exc)
            return report
        original_notify = device._process_notify
        report['notifications'] = []
        async def observe(data):
            from tuesly_mesh.sig_mesh_protocol import decrypt_network_pdu
            record = {'kind': data[0] if data else None, 'length': len(data)}
            if data and data[0] in (0, 2) and device._keys:
                keys = device._keys
                packet = decrypt_network_pdu(keys.enc_key, keys.priv_key, keys.nid,
                                              data[1:], keys.iv_index, proxy_config=data[0] == 2)
                record['network_authenticated'] = packet is not None
                if packet:
                    record.update(source=packet.src, destination=packet.dst, control=packet.ctl)
                    if data[0] == 2:
                        record['filter_status'] = packet.transport_pdu.hex()
                        if ('--filter-only' in sys.argv and packet.ctl == 1 and packet.ttl == 0
                                and packet.dst == 0 and packet.transport_pdu[:2] == b'\x03\x01'
                                and len(packet.transport_pdu) == 4):
                            # Read the actual proxy source before assuming the
                            # driver's current primary matches the latest journal.
                            report['actual_proxy_primary'] = packet.src
                            device._node_primary = packet.src
            report['notifications'].append(record)
            await original_notify(data)
        device._process_notify = observe
        report['stage'] = 'notifications'
        await device.connect(max_retries=1)
        report['stage'] = 'proxy_authentication'
        try:
            await device.configure_filter()
            report['authenticated_mesh'] = True
        except TimeoutError:
            report['filter_timeout'] = True
        if '--filter-only' in sys.argv:
            report['stage']='filter_checked'
            return report
        report['stage'] = 'composition'
        response = asyncio.get_running_loop().create_future()
        def received(source, opcode, params):
            if source == node['address'] and opcode == 2 and not response.done():
                response.set_result(params)
        device._access_callbacks.append(received)
        device._response_waiters.add(response)
        await device.request_composition_data()
        raw = await asyncio.wait_for(response, 15)
        if len(raw) < 11 or raw[0] != 0:
            raise RuntimeError('Invalid Composition Page 0')
        elements = parse_element_models(raw[11:], node['address'])
        report['composition_page_zero'] = raw.hex()
        report['elements'] = [{'address': e.address, 'sig_models': [f'{m:04X}' for m in e.sig_models],
                               'vendor_models': e.vendor_models} for e in elements]
        report['stage'] = 'complete'
    except Exception as exc:
        report['failure_type'] = type(exc).__name__
    finally:
        if 'coordinator' in locals():
            try:
                await coordinator._close_device()
            except Exception:
                pass
        try:
            await api.bluetooth_device_disconnect(target,timeout=5)
        except Exception:
            pass
        if device:
            try:
                await asyncio.wait_for(device.disconnect(), 6)
            except Exception:
                pass
        if cancel_connection:
            cancel_connection()
        if cancel_advertisements:
            cancel_advertisements()
        await api.disconnect(force=True)
        if '--filter-only' in sys.argv:
            (ROOT/'reports/proxy-identity-hardware.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2),flush=True)
        if '--advertisements-only' in sys.argv:
            (ROOT/'reports/network-identity-hardware.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2),flush=True)
        if CONFIGURE:
            (ROOT/'reports/configured-hardware.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2),flush=True)
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports/authenticated-hardware.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(inspect())
