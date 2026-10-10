"""Admin-only import of a completed commissioning recovery via HA Store."""
import asyncio
import copy
import hmac
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from tuesly_mesh.sig_mesh_crypto import k3
from .mesh_store import get_journal
from .radio import get_radio


async def register(hass):
    if hass.services.has_service('tuesly', 'import_commissioning'):
        return
    async def import_commissioning(call):
        user_id = call.context.user_id
        user = await hass.auth.async_get_user(user_id) if user_id else None
        if user is None or not user.is_admin:
            raise HomeAssistantError('Administrator authentication is required')
        values = call.data
        mac = values['address'].upper()
        entries = [entry for entry in hass.config_entries.async_entries('tuesly')
                   if entry.data.get('mac_address', '').upper() == mac]
        if len(entries) != 1 or entries[0].disabled_by is None:
            raise HomeAssistantError('Pause the existing target entry before importing commissioning')
        journal = await get_journal(hass)
        try:
            key = bytes.fromhex(values['device_key'])
            expected = bytes.fromhex(values['network_id'])
        except ValueError:
            raise HomeAssistantError('Invalid recovery credential encoding') from None
        if len(key) != 16 or len(expected) != 8:
            raise HomeAssistantError('Invalid recovery credential length')
        if not hmac.compare_digest(k3(bytes.fromhex(journal.state['net_key'])), expected):
            raise HomeAssistantError('Recovery belongs to a different mesh network')
        primary, count = values['primary'], values['elements']
        if not 1 <= primary <= 0x7ffe or not 1 <= count <= 255 or primary + 254 >= 0x7fff:
            raise HomeAssistantError('Invalid recovery address range')
        radio_lock=get_radio(hass)
        async with radio_lock, journal.lock:
            owner = hass.data['tuesly_mesh_controller'].get('owner')
            if owner is not None:
                await owner._close_device()
            for address, node in journal.state['nodes'].items():
                if address != mac and node['address'] < primary+255 and primary < node['address']+255:
                    raise HomeAssistantError('Recovery address overlaps an existing reservation')
            candidate = copy.deepcopy(journal.state)
            old = candidate['nodes'].get(mac)
            same_identity = bool(old and old.get('dev_key') == key.hex() and old.get('address') == primary)
            if old and not same_identity:
                candidate.setdefault('retired_nodes', []).append({'address': mac, 'record': old})
            candidate['nodes'][mac] = copy.deepcopy(old) if same_identity else {'address': primary, 'elements': count,
                                      'dev_key': key.hex(), 'status': 'configuration_pending'}
            if values['bindings_verified']:
                candidate['nodes'][mac].update(status='ready',binding_revision=3)
            if values['proxy_verified']:
                candidate['nodes'][mac]['proxy_enabled']=True
            if 'temperature_profile' in values:
                profile = values['temperature_profile']
                if (set(profile) != {'composition','minimum','maximum','relative'}
                    or not isinstance(profile.get('composition'),str)
                    or len(profile['composition'])!=14
                    or any(c not in '0123456789abcdefABCDEF' for c in profile['composition'])
                    or type(profile.get('relative')) is not bool
                    or type(profile.get('minimum')) is not int
                    or type(profile.get('maximum')) is not int
                    or not 800 <= profile['minimum'] < profile['maximum'] <= 20000):
                    raise HomeAssistantError('Invalid verified temperature profile')
                candidate['nodes'][mac]['temperature_profile']=profile
            candidate['address_next'] = max(candidate['address_next'], primary+255)
            high = values['sequence_high']
            if not 0 <= high < 0x1000000:
                raise HomeAssistantError('Invalid recovery sequence reservation')
            candidate['sequence_high'] = max(candidate['sequence_high'],high)
            # Discard any process-local lease used before this recovery.
            await journal.store.async_save(candidate)
            journal.state = candidate
            journal.next_seq = journal.seq_end = candidate['sequence_high']
    hass.services.async_register('tuesly', 'import_commissioning', import_commissioning,
        schema=vol.Schema({vol.Required('address'): str, vol.Required('device_key'): str,
                           vol.Required('network_id'): str, vol.Required('primary'): int,
                           vol.Required('elements'): int, vol.Required('sequence_high'): int,
                           vol.Optional('bindings_verified',default=False): bool,
                           vol.Optional('proxy_verified',default=False): bool,
                           vol.Optional('temperature_profile'): dict}))
