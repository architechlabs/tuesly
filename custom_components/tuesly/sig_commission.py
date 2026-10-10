"""Explicit opt-in commissioning and recovery of HA-owned SIG mesh nodes."""
import asyncio
import logging
import voluptuous as vol
from tuesly_mesh.sig_mesh_provisioner import SIGMeshProvisioner
from .mesh_store import get_journal
from .sig_controller import transport,SIGLightCoordinator
from .radio import get_radio

_LOGGER = logging.getLogger(__name__)


async def configure_bearer(hass, mac, journal, client, result):
    """Bind application models before the provisioner releases this bearer."""
    coordinator = SIGLightCoordinator(hass, mac, journal)
    device = coordinator._make_device()
    async def use_connected(ble_device, *, disconnected_callback=None):
        if callback := getattr(client, 'set_disconnected_callback', None):
            callback(disconnected_callback)
        return client
    if client is not None:
        device._ble_connect_callback = use_connected
    coordinator.device = device
    try:
        await device.connect(max_retries=1)
        await device.configure_filter()
        await coordinator._configure(bindings_only=True)
        await asyncio.sleep(2)
    finally:
        await coordinator._close_device()


async def repair(flow, entry, user_input=None):
    """Retry configuration or explicitly replace a physically reset node."""
    from homeassistant.components import bluetooth
    import copy
    journal = await get_journal(flow.hass)
    mac = entry.data['mac_address'].upper()
    errors = {}
    if user_input is not None:
        if not user_input.get('recommission'):
            async with get_radio(flow.hass):
                await journal.update(mac, status='configuration_pending')
            await flow.hass.config_entries.async_reload(entry.entry_id)
            return flow.async_abort(reason='reconfigure_successful')
        if not user_input.get('reset_confirmed'):
            errors['base'] = 'reset_required'
        else:
            info = bluetooth.async_last_service_info(flow.hass, mac, connectable=True)
            if info is None or '00001827-0000-1000-8000-00805f9b34fb' not in info.service_uuids:
                errors['base'] = 'device_not_found'
            else:
                # Stop this entry's controls first; commissioning owns the radio.
                if not await flow.hass.config_entries.async_unload(entry.entry_id):
                    errors['base'] = 'cannot_connect_ble'
                else:
                    previous = copy.deepcopy(journal.state['nodes'][mac])
                    try:
                        async with get_radio(flow.hass):
                            owner = flow.hass.data['tuesly_mesh_controller'].get('owner')
                            if owner:
                                await owner._close_device()
                            node = await journal.reserve(mac, replace=True)
                            resolve, connect = transport(flow.hass)
                            provisioner = SIGMeshProvisioner(
                                bytes.fromhex(journal.state['net_key']), bytes.fromhex(journal.state['app_key']),
                                node['address'], iv_index=journal.state['iv_index'],
                                ble_device_callback=resolve, ble_connect_callback=connect)
                            async def persist(key, elements):
                                await journal.update(mac, dev_key=key.hex(), elements=elements,
                                                     status='configuration_pending')
                            provisioner.journal_callback = persist
                            async def configure(client, result):
                                await configure_bearer(flow.hass, mac, journal, client, result)
                            provisioner.configuration_callback = configure
                            await asyncio.wait_for(provisioner.provision(mac), 90)
                    except Exception as exc:
                        if not journal.state['nodes'][mac].get('dev_key'):
                            await journal.restore_node(mac, previous)
                        _LOGGER.warning('SIG repair stopped at %s (%s)',
                                        getattr(locals().get('provisioner'), 'stage', 'reserving'), type(exc).__name__)
                        delivered=getattr(locals().get('provisioner'),'_provisioning_data_attempted',False) is True
                        errors['base'] = 'configuration_incomplete' if delivered else 'commissioning_failed'
                    finally:
                        if entry.disabled_by is None:
                            await flow.hass.config_entries.async_reload(entry.entry_id)
                    if not errors:
                        return flow.async_abort(reason='reconfigure_successful')
    return flow.async_show_form(step_id='sig_repair', errors=errors,
        description_placeholders={'address': mac},
        data_schema=vol.Schema({vol.Required('recommission', default=False): bool,
                               vol.Required('reset_confirmed', default=False): bool}))


async def setup(flow, user_input=None):
    mac = flow._discovery_info['address'].upper()
    await flow.async_set_unique_id(mac)
    flow._abort_if_unique_id_configured()
    journal = await get_journal(flow.hass)
    node = journal.state['nodes'].get(mac)
    errors = {}
    if user_input is not None:
        if node and node.get('dev_key'):
            # Never repeat provisioning after handing keys to a node. Runtime
            # configuration resumes using the saved credentials instead.
            return await create(flow, mac)
        if not user_input.get('reset_confirmed'):
            errors['base'] = 'reset_required'
        else:
            node = await journal.reserve(mac)
            resolve, connect = transport(flow.hass)
            provisioner = SIGMeshProvisioner(
                bytes.fromhex(journal.state['net_key']), bytes.fromhex(journal.state['app_key']),
                node['address'], iv_index=journal.state['iv_index'],
                ble_device_callback=resolve, ble_connect_callback=connect)
            async def save_credentials(dev_key, elements):
                if not 1 <= elements <= 255:
                    raise ValueError('Invalid element count')
                await journal.update(mac, dev_key=dev_key.hex(), elements=elements,
                                     status='configuration_pending')
            provisioner.journal_callback = save_credentials
            async def configure_connected(client,result):
                await configure_bearer(flow.hass,mac,journal,client,result)
            provisioner.configuration_callback=configure_connected
            try:
                # No automatic reset command is sent. The user confirms the
                # physical reset only after reviewing the consequences below.
                radio_lock=get_radio(flow.hass)
                async with radio_lock:
                    owner=flow.hass.data['tuesly_mesh_controller'].get('owner')
                    if owner:
                        await owner._close_device()
                    await asyncio.wait_for(provisioner.provision(mac), 90)
            except Exception as exc:
                _LOGGER.warning('SIG commissioning failed for %s at %s (%s)',
                                mac, getattr(provisioner, 'stage', 'connecting'), type(exc).__name__)
                if journal.state['nodes'][mac].get('dev_key'):
                    # Keep a repairable entry if provisioning completed but the
                    # final acknowledgement was lost. Do not discard its keys.
                    return await create(flow, mac)
                errors['base'] = 'commissioning_failed'
            else:
                return await create(flow, mac)
    schema = vol.Schema({vol.Required('reset_confirmed', default=False): bool}) if not (
        node and node.get('dev_key')) else vol.Schema({})
    return flow.async_show_form(step_id='sig_setup', data_schema=schema, errors=errors,
                               description_placeholders={'address': mac})


async def create(flow, mac):
    await flow.async_set_unique_id(mac)
    flow._abort_if_unique_id_configured()
    data={'mac_address':mac,'device_type':'sig_light'}
    if profile := flow._discovery_info.get('profile'):
        data['mesh_product_type']=profile['product_type']
    return flow.async_create_entry(title=f'Tuesly Light {mac[-8:]}',data=data)
