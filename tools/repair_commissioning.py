"""Recover the single HA node after an intentional physical factory reset.

Existing network/application keys and other node records are preserved. HA must
be paused, and the original journal is backed up privately before reservation.
Device credentials are journaled locally before Provisioning Data; import them
through HA Store after completed recovery.
"""
import argparse
import asyncio
import copy
import json
import time
from pathlib import Path
import paramiko
import yaml
from aioesphomeapi import APIClient
from aioesphomeapi.model import BluetoothScannerMode
from inspect_mesh import ROOT, PRIVATE, MAC, SOURCE, PrivateStore, GATTAdapter, modules


def open_ssh():
    config = json.loads((PRIVATE/'addon-a0d7b954_ssh.json').read_text(encoding='utf-8'))['options']['ssh']
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('192.168.4.198',username=config['username'],password=config['password'],
                   look_for_keys=False,allow_agent=False,timeout=10)
    return client


def write_journal(document):
    # Durable local recovery journal; HA imports this through its Store API.
    # Never replace HA's live internal-state files through SSH.
    import os
    destination = PRIVATE/'ha-mesh.json'
    temporary = destination.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(document))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(destination)


async def repair(*, clear_restorable_pairing=False, wait_seconds=180, connect_known_address=False, serial_trigger=False):
    freshness=PRIVATE/'recovery-journal-status.json'
    if freshness.exists() and json.loads(freshness.read_text(encoding='utf-8')).get('stale'):
        raise RuntimeError('Recovery snapshot predates HA commissioning; obtain a current HA Store export before replacing a node')
    controller = modules()
    from tuesly_mesh.sig_mesh_provisioner import SIGMeshProvisioner
    original = json.loads((PRIVATE/'ha-mesh.json').read_text(encoding='utf-8'))
    (PRIVATE/f'ha-mesh-before-repair-{int(time.time())}.json').write_text(json.dumps(original),encoding='utf-8')
    document = copy.deepcopy(original)
    state = document['data']
    address = state['address_next']
    if address+254 >= 0x7fff:
        raise RuntimeError('No safe node address range remains')
    state['address_next'] = address+255
    state['nodes'][MAC] = {'address': address, 'status': 'reserved'}
    config = yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text(encoding='utf-8'))
    api = APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],
                    client_info='tuesly-commissioning-recovery')
    adapter = None
    cancel_advertisements = cancel_connection = None
    requested = False
    reserved = False
    serial_connection = serial_task = None
    serial_confirmed = False
    target = int(MAC.replace(':',''),16)
    result = {'stage':'api','provisioned':False,'address':address}
    try:
        fresh = asyncio.Event()
        if serial_trigger:
            import serial
            serial_connection = serial.Serial(port=None,baudrate=115200,timeout=0.2)
            serial_connection.dtr = serial_connection.rts = False
            serial_connection.port = 'COM8'
            serial_connection.open()
            async def watch_serial():
                nonlocal serial_confirmed
                pending = ''
                heard_at = -100.0
                while True:
                    pending += (await asyncio.to_thread(serial_connection.read,4096)).decode('utf-8',errors='replace')
                    while '\n' in pending:
                        line,pending = pending.split('\n',1)
                        if f'Target {MAC} heard' in line:
                            heard_at = time.monotonic()
                        if ('Target advertised service: 0x1827' in line and
                                time.monotonic()-heard_at < 2):
                            serial_confirmed = True
                            fresh.set()
                            print('USB confirmed pairing service 1827; connecting immediately',flush=True)
            serial_task = asyncio.create_task(watch_serial())
            print('USB reset watcher armed; no chat reply is needed to start pairing',flush=True)
        advertisement_count = 0
        target_count = 0
        def advertisement(message):
            nonlocal advertisement_count, target_count
            advertisement_count += len(message.advertisements)
            for adv in message.advertisements:
                if adv.address != target:
                    continue
                target_count += 1
                raw, offset = bytes(adv.data), 0
                (PRIVATE/'latest-advertisement.hex').write_text(raw.hex(),encoding='utf-8')
                while offset < len(raw):
                    length = raw[offset]
                    if not length or offset+length+1 > len(raw):
                        break
                    value = raw[offset+2:offset+length+1]
                    if (raw[offset+1] in (2,3) and any(value[i:i+2] == b'\x27\x18' for i in range(0,len(value),2)) or
                            raw[offset+1] == 0x16 and value[:2] == b'\x27\x18'):
                        fresh.set()
                    offset += length+1
        result['stage'] = 'waiting_for_unprovisioned_advertisement'
        print('Connecting the ESP32 pairing listener',flush=True)
        deadline = asyncio.get_running_loop().time()+wait_seconds
        if connect_known_address:
            # Explicitly reset-confirmed operator recovery only. The real
            # Provisioning Invite/Capabilities exchange still must succeed
            # before any new credentials can be derived or delivered.
            await asyncio.wait_for(api.connect(login=True),12)
            info = await asyncio.wait_for(api.device_info(),8)
            capabilities = await asyncio.wait_for(api.device_capabilities_compat(info),8)
            # ESPHome routes GATT replies to its advertisement subscriber.
            # The direct-address path must own that subscription too.
            cancel_advertisements = api.subscribe_bluetooth_le_raw_advertisements(advertisement)
            api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
            fresh.set()
            result['connection_without_fresh_advertisement']=True
        while not connect_known_address:
            stopped = asyncio.Event()
            async def api_stopped(expected):
                stopped.set()
            waiters = []
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.wait_for(api.connect(login=True,on_stop=api_stopped),12)
                    info = await asyncio.wait_for(api.device_info(),8)
                    capabilities = await asyncio.wait_for(api.device_capabilities_compat(info),8)
                    cancel_advertisements = api.subscribe_bluetooth_le_raw_advertisements(advertisement)
                    api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
                    print(f'Listener connected: waiting for reset-mode advertising ({wait_seconds} seconds maximum)',flush=True)
                    waiters = [asyncio.create_task(fresh.wait()),asyncio.create_task(stopped.wait())]
                    while not fresh.is_set() and not stopped.is_set():
                        await asyncio.wait(waiters,timeout=20,return_when=asyncio.FIRST_COMPLETED)
                        if not fresh.is_set() and not stopped.is_set():
                            print(f'Scanning: {advertisement_count} advertisements; {target_count} from this driver',flush=True)
                    if stopped.is_set():
                        if not serial_confirmed:
                            fresh.clear()
                        raise ConnectionError('ESP32 API disconnected while scanning')
            except Exception as exc:
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError('No fresh provisioning advertisement before deadline') from exc
                print(f'ESP32 scan connection interrupted ({type(exc).__name__}); reconnecting',flush=True)
            finally:
                for waiter in waiters:
                    waiter.cancel()
                if waiters:
                    await asyncio.gather(*waiters,return_exceptions=True)
            if fresh.is_set():
                break
            if cancel_advertisements:
                cancel_advertisements()
                cancel_advertisements = None
            await api.disconnect(force=True)
            api = APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],
                            client_info='tuesly-commissioning-recovery')
            await asyncio.sleep(1)
        if serial_confirmed:
            # A stalled raw-advertisement stream must not delay the PB-GATT
            # attempt. Claim a fresh API session from the USB-confirmed event.
            if cancel_advertisements:
                cancel_advertisements()
            await api.disconnect(force=True)
            api = APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],
                            client_info='tuesly-commissioning-recovery')
            await asyncio.wait_for(api.connect(login=True),12)
            info = await asyncio.wait_for(api.device_info(),8)
            capabilities = await asyncio.wait_for(api.device_capabilities_compat(info),8)
            cancel_advertisements = api.subscribe_bluetooth_le_raw_advertisements(advertisement)
        # Never reserve/replace the HA record until actual reset-mode advertising
        # is observed; exposing 1827 in a GATT table alone is insufficient.
        await asyncio.to_thread(write_journal,document)
        reserved = True
        result['stage'] = 'gatt'
        print('Connecting to verify provisioning capabilities' if connect_known_address else
              'Reset-mode advertisement received; connecting',flush=True)
        requested = True
        def connection_state(connected,mtu,error):
            if not connected and adapter is not None:
                adapter.is_connected = False
                if adapter.disconnected:
                    adapter.disconnected(adapter)
        cancel_connection = await api.bluetooth_device_connect(target,connection_state,timeout=20,
            feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=0)
        services = await api.bluetooth_gatt_get_services(target)
        adapter = GATTAdapter(api,target,services)
        async def connected(ble_device, **kwargs):
            return adapter
        provisioner = SIGMeshProvisioner(bytes.fromhex(state['net_key']),bytes.fromhex(state['app_key']),
            address,iv_index=state['iv_index'],ble_device_callback=lambda addr:type('Device',(),{'address':addr})(),
            ble_connect_callback=connected)
        async def journal(key,elements):
            state['nodes'][MAC].update(dev_key=key.hex(),elements=elements,status='configuration_pending')
            await asyncio.to_thread(write_journal,document)
        provisioner.journal_callback = journal
        result['stage'] = 'provisioning'
        print('GATT connected; starting authenticated provisioning',flush=True)
        # Complete provisioning before transferring to a fresh Mesh Proxy bearer.
        completion = await asyncio.wait_for(provisioner._run_exchange(adapter),75)
        # End PB-GATT notification state before opening the Mesh Proxy bearer,
        # matching the production provisioner's configuration handoff.
        await provisioner._finish_provisioning_bearer(adapter)
        descriptor=next(item for item in provisioner._prov_data_out.descriptors
            if item.uuid.lower()=='00002902-0000-1000-8000-00805f9b34fb')
        result['provisioning_notifications_disabled']=bytes(await api.bluetooth_gatt_read_descriptor(target,descriptor.handle,timeout=5))==b'\x00\x00'
        if not result['provisioning_notifications_disabled']:
            raise RuntimeError('PB-GATT descriptor did not confirm the handoff')
        result['stage']='reconnecting_mesh_proxy'
        await adapter.disconnect()
        if cancel_connection:
            cancel_connection()
        reconnect_started=time.monotonic()
        cancel_connection=await api.bluetooth_device_connect(target,connection_state,timeout=15,
            feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=0)
        services=await api.bluetooth_gatt_get_services(target)
        adapter=GATTAdapter(api,target,services)
        result.update(bearer_transition='disconnect_then_mesh_proxy',
                      reconnect_seconds=round(time.monotonic()-reconnect_started,2))
        result.update(stage='provisioning_complete',provisioned=True,elements=completion.num_elements)
        print('Provisioning complete; configuring application models on the Mesh Proxy bearer',flush=True)
        from custom_components.tuesly.mesh_store import MeshJournal
        # Keep operator diagnostics on its independently persisted source
        # sequence lease; never reuse HA source 1 nonces from an old export.
        journal = await MeshJournal(PrivateStore(document['data'])).load()
        async def connect_existing(device, *, disconnected_callback=None):
            adapter.disconnected = disconnected_callback
            return adapter
        import types
        controller.transport = lambda hass: (lambda address: types.SimpleNamespace(address=address), connect_existing)
        coordinator = controller.SIGLightCoordinator(types.SimpleNamespace(data={}),MAC,journal)
        make_device=coordinator._make_device
        def diagnostic_device():
            device=make_device();device._our_addr=SOURCE;return device
        coordinator._make_device=diagnostic_device
        original_request = coordinator._request
        async def request(payload, opcode, address, **kwargs):
            response = await original_request(payload, opcode, address, **kwargs)
            if opcode == 2:
                result['composition_page_zero'] = response.hex()
                from tuesly_mesh.sig_lighting import parse_element_models
                if len(response) >= 11 and response[0] == 0:
                    result['elements_found'] = [{'address':e.address, 'models':[f'{m:04X}' for m in e.sig_models]}
                        for e in parse_element_models(response[11:],address)]
            return response
        coordinator._request = request
        result['stage'] = 'model_configuration'
        try:
            configuration_started=time.monotonic()
            async with asyncio.timeout_at(provisioner.configuration_deadline):
                coordinator.device=coordinator._make_device()
                await coordinator.device.connect(max_retries=1)
                await coordinator.device.configure_filter()
                await coordinator._configure(bindings_only=True)
            result['binding_seconds']=round(time.monotonic()-configuration_started,2)
            result['bindings_complete']=True
            if clear_restorable_pairing:
                # User has already intentionally removed/reset this driver.
                # An authenticated Node Reset clears the persistent node data,
                # unlike Tuya's reversible power-cycle reset mode.
                print('Clearing this driver\'s restorable pairing with authenticated Node Reset',flush=True)
                result['stage']='factory_reset_requested'
                try:
                    response=await coordinator._request(b'\x80\x49',0x804a,address,configuration=True)
                    result['factory_reset_acknowledged']=response==b''
                except (TimeoutError,controller.MeshLinkClosedError):
                    result['factory_reset_acknowledged']=False
                await journal.update(MAC,status='factory_reset_sent')
                document['data']['nodes'][MAC]['status']='factory_reset_sent'
                await asyncio.to_thread(write_journal,document)
                result.update(stage='factory_reset_sent',configured=False)
                return result
            await coordinator._configure()
            result['state']=await coordinator._read()
            result.update(stage='configuration_complete',configured=True)
        except Exception as exc:
            result.update(stage=coordinator.stage,configuration_error=type(exc).__name__)
            if isinstance(exc, controller.MeshSetupError):
                result['configuration_reason'] = str(exc)
            if coordinator.device and coordinator.device._composition:
                from tuesly_mesh.sig_lighting import parse_element_models
                result['elements_found'] = [{'address':e.address,'models':[f'{model:04X}' for model in e.sig_models]}
                    for e in parse_element_models(coordinator.device._composition.raw_elements,address)]
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        from tuesly_mesh.exceptions import ProvisioningError
        if isinstance(exc,ProvisioningError):
            result['provisioning_reason']=str(exc)
            if 'provisioner' in locals():
                result['stage']=getattr(provisioner,'stage',result['stage'])
        if reserved and not document['data']['nodes'][MAC].get('dev_key') and original['data']['nodes'][MAC].get('dev_key'):
            # No new Provisioning Data was delivered: retain the prior identity
            # while keeping the attempted address reservation out of reuse.
            document['data'].setdefault('failed_reservations',[]).append(address)
            document['data']['nodes'][MAC]=copy.deepcopy(original['data']['nodes'][MAC])
            await asyncio.to_thread(write_journal,document)
        error = getattr(exc, 'error', None)
        if error is not None:
            result['gatt_error'] = {name:getattr(error,name,None) for name in ['handle','error']}
    finally:
        if serial_task is not None:
            serial_task.cancel()
            await asyncio.gather(serial_task,return_exceptions=True)
        if serial_connection is not None:
            serial_connection.close()
        result['reset_confirmed_over_usb']=serial_confirmed
        result['advertisement_count']=locals().get('advertisement_count',0)
        result['target_count']=locals().get('target_count',0)
        if requested:
            try:
                await api.bluetooth_device_disconnect(target,timeout=5)
            except Exception:
                pass
        for cancel in (cancel_connection,cancel_advertisements):
            if cancel:
                cancel()
        await api.disconnect(force=True)
    name='factory-reset-result.json' if clear_restorable_pairing else 'recovery-provisioning.json'
    (ROOT/'reports'/name).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset-confirmed',action='store_true',required=True)
    parser.add_argument('--clear-restorable-pairing',action='store_true',help='Authenticated factory reset, then provision once more; requires the already authorized physical reset')
    parser.add_argument('--wait-seconds',type=int,default=180,choices=range(30,901),metavar='30..900')
    parser.add_argument('--connect-known-address',action='store_true',help='Try the known address after an explicitly confirmed reset; the provisioning capabilities exchange must still validate its mode')
    parser.add_argument('--serial-trigger',action='store_true',help='Also trigger immediately from this ESP32\'s USB 1827 advertisement log')
    arguments=parser.parse_args()
    async def run():
        result=await repair(clear_restorable_pairing=arguments.clear_restorable_pairing,wait_seconds=arguments.wait_seconds,connect_known_address=arguments.connect_known_address,serial_trigger=arguments.serial_trigger)
        if arguments.clear_restorable_pairing and result.get('stage')=='factory_reset_sent':
            (ROOT/'reports/factory-reset-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result,indent=2),flush=True)
            await asyncio.sleep(2)
            await repair()
    asyncio.run(run())
