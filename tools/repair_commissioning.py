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


async def repair():
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
    target = int(MAC.replace(':',''),16)
    result = {'stage':'api','provisioned':False,'address':address}
    try:
        await asyncio.wait_for(api.connect(login=True),12)
        info = await api.device_info()
        capabilities = await api.device_capabilities_compat(info)
        fresh = asyncio.Event()
        def advertisement(message):
            for adv in message.advertisements:
                if adv.address != target:
                    continue
                raw, offset = bytes(adv.data), 0
                while offset < len(raw):
                    length = raw[offset]
                    if not length or offset+length+1 > len(raw):
                        break
                    value = raw[offset+2:offset+length+1]
                    if raw[offset+1] in (2,3,0x16) and value[:2] == b'\x27\x18':
                        fresh.set()
                    offset += length+1
        cancel_advertisements = api.subscribe_bluetooth_le_raw_advertisements(advertisement)
        result['stage'] = 'waiting_for_unprovisioned_advertisement'
        await asyncio.wait_for(fresh.wait(),30)
        # Never reserve/replace the HA record until actual reset-mode advertising
        # is observed; exposing 1827 in a GATT table alone is insufficient.
        await asyncio.to_thread(write_journal,document)
        result['stage'] = 'gatt'
        requested = True
        cancel_connection = await api.bluetooth_device_connect(target,lambda *args:None,timeout=20,
            feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=0)
        services = await api.bluetooth_gatt_get_services(target)
        adapter = GATTAdapter(api,target,services)
        await adapter.set_connection_params(24,40,0,800)
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
        # Keep this bearer open through model configuration. This Tuya driver
        # continued advertising 1827 after a provisioning-only disconnect.
        completion = await asyncio.wait_for(provisioner._run_exchange(adapter),75)
        result.update(stage='provisioning_complete',provisioned=True,elements=completion.num_elements)
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
            coordinator.device=coordinator._make_device()
            await coordinator.device.connect(max_retries=1)
            await coordinator.device.configure_filter()
            await asyncio.wait_for(coordinator._configure(bindings_only=True),24)
            result['binding_seconds']=round(time.monotonic()-configuration_started,2)
            result['bindings_complete']=True
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
        if not document['data']['nodes'][MAC].get('dev_key') and original['data']['nodes'][MAC].get('dev_key'):
            # No new Provisioning Data was delivered: retain the prior identity
            # while keeping the attempted address reservation out of reuse.
            document['data'].setdefault('failed_reservations',[]).append(address)
            document['data']['nodes'][MAC]=copy.deepcopy(original['data']['nodes'][MAC])
            await asyncio.to_thread(write_journal,document)
        error = getattr(exc, 'error', None)
        if error is not None:
            result['gatt_error'] = {name:getattr(error,name,None) for name in ['handle','error']}
    finally:
        if requested:
            try:
                await api.bluetooth_device_disconnect(target,timeout=5)
            except Exception:
                pass
        for cancel in (cancel_connection,cancel_advertisements):
            if cancel:
                cancel()
        await api.disconnect(force=True)
    (ROOT/'reports/recovery-provisioning.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset-confirmed',action='store_true',required=True)
    parser.parse_args()
    asyncio.run(repair())
