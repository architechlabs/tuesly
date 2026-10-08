"""Explicit opt-in commissioning and recovery of HA-owned SIG mesh nodes."""
import asyncio
import logging
import voluptuous as vol
from tuesly_mesh.sig_mesh_provisioner import SIGMeshProvisioner
from .mesh_store import get_journal
from .sig_controller import transport

_LOGGER = logging.getLogger(__name__)


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
            try:
                # No automatic reset command is sent. The user confirms the
                # physical reset only after reviewing the consequences below.
                radio_lock = flow.hass.data.setdefault('tuesly_mesh_controller', {}).setdefault('radio_lock', asyncio.Lock())
                async with radio_lock:
                    await asyncio.wait_for(provisioner.provision(mac), 90)
                    await asyncio.sleep(6)
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
    return flow.async_create_entry(title=f'Tuesly Light {mac[-8:]}',
                                   data={'mac_address': mac, 'device_type': 'sig_light'})
