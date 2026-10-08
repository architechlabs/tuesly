"""Manual setup with protocol detection and explicit transport choices."""
from __future__ import annotations

import logging
from typing import Any
import voluptuous as vol

from custom_components.tuesly.config_flow_ble import validate_and_connect
from custom_components.tuesly.config_flow_validators import (
    _validate_mac, _validate_mesh_credential, _validate_vendor_id,
)
from custom_components.tuesly.const import (
    CONF_MAC_ADDRESS, CONF_DEVICE_TYPE, CONF_MESH_NAME, CONF_MESH_PASSWORD,
    CONF_VENDOR_ID, CONF_MESH_ADDRESS, DEFAULT_VENDOR_ID, DEFAULT_MESH_ADDRESS,
    DEVICE_TYPE_AUTO, DEVICE_TYPE_LIGHT, DEVICE_TYPE_PLUG, DEVICE_TYPE_SIG_PLUG,
    DEVICE_TYPE_TELINK_BRIDGE_LIGHT, DEVICE_TYPE_SIG_BRIDGE_PLUG, DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
ERROR_KEYS = {"device_not_found", "ble_adapter_busy", "cannot_connect_ble",
              "unknown_device_type", "device_type_mismatch", "timeout_validation",
              "pairing_failed", "verify_failed"}


async def async_step_user(flow: Any, user_input: dict[str, Any] | None = None):
    errors = {}
    if user_input is not None:
        mac = str(user_input.get(CONF_MAC_ADDRESS, "")).strip().upper()
        requested = user_input.get(CONF_DEVICE_TYPE, DEVICE_TYPE_AUTO)
        mac_error = _validate_mac(mac)
        if mac_error:
            errors[CONF_MAC_ADDRESS] = mac_error
        mesh_name = user_input.get(CONF_MESH_NAME) or "out_of_mesh"
        mesh_password = user_input.get(CONF_MESH_PASSWORD) or "123456"
        vendor = str(user_input.get(CONF_VENDOR_ID) or DEFAULT_VENDOR_ID)
        for field, value in ((CONF_MESH_NAME, mesh_name), (CONF_MESH_PASSWORD, mesh_password)):
            error = _validate_mesh_credential(value)
            if error:
                errors[field] = error
        vendor_error = _validate_vendor_id(vendor)
        if vendor_error:
            errors[CONF_VENDOR_ID] = vendor_error
        if not errors:
            for entry in flow.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_MAC_ADDRESS, "").upper() == mac:
                    return flow.async_abort(reason="already_configured")
            if requested in (DEVICE_TYPE_TELINK_BRIDGE_LIGHT, DEVICE_TYPE_SIG_BRIDGE_PLUG):
                flow._discovery_info = {"address": mac, "name": f"Mesh device {mac[-8:]}"}
                if requested == DEVICE_TYPE_TELINK_BRIDGE_LIGHT:
                    return await flow.async_step_telink_bridge(None)
                return await flow.async_step_sig_bridge(None)
            try:
                detected, details = await validate_and_connect(
                    flow.hass, mac, None if requested == DEVICE_TYPE_AUTO else requested,
                    mesh_name, mesh_password,
                )
            except ValueError as exc:
                key = str(exc).strip("'\"")
                errors["base"] = key if key in ERROR_KEYS else "cannot_connect_ble"
            except Exception as exc:
                # Never include submitted credentials or arbitrary exception text.
                _LOGGER.warning("Setup validation failed for %s (%s)", mac, type(exc).__name__)
                errors["base"] = "cannot_connect_ble"
            else:
                if detected == DEVICE_TYPE_SIG_PLUG:
                    flow._discovery_info = {"address": mac, "name": f"SIG Mesh device {mac[-8:]}", **details}
                    return await flow.async_step_sig_setup(None)
                await flow.async_set_unique_id(mac)
                flow._abort_if_unique_id_configured()
                return flow._finalize_entry(
                    mac=mac, device_type=detected, mesh_name=mesh_name,
                    mesh_password=mesh_password, vendor_id=vendor,
                    mesh_address=user_input.get(CONF_MESH_ADDRESS, DEFAULT_MESH_ADDRESS),
                )
    choices = {
        DEVICE_TYPE_AUTO: "Detect protocol (ESPHome proxy / HA Bluetooth)",
        DEVICE_TYPE_LIGHT: "Telink LED light (ESPHome proxy / HA Bluetooth)",
        DEVICE_TYPE_PLUG: "Telink relay (ESPHome proxy / HA Bluetooth)",
        DEVICE_TYPE_SIG_PLUG: "SIG Mesh device (ESPHome proxy / HA Bluetooth)",
    }
    if flow.show_advanced_options:
        choices[DEVICE_TYPE_TELINK_BRIDGE_LIGHT] = "Telink LED light via HTTP bridge daemon"
        choices[DEVICE_TYPE_SIG_BRIDGE_PLUG] = "SIG relay via HTTP bridge daemon"
    schema = {
        vol.Required(CONF_MAC_ADDRESS): str,
        vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_AUTO): vol.In(choices),
    }
    if flow.show_advanced_options:
        schema.update({
            vol.Optional(CONF_MESH_NAME, default="out_of_mesh"): str,
            vol.Optional(CONF_MESH_PASSWORD, default="123456"): str,
            vol.Optional(CONF_VENDOR_ID, default=DEFAULT_VENDOR_ID): str,
            vol.Optional(CONF_MESH_ADDRESS, default=DEFAULT_MESH_ADDRESS): int,
        })
    return flow.async_show_form(step_id="user", data_schema=vol.Schema(schema),
                                description_placeholders={}, errors=errors)


async def async_step_sig_setup(flow: Any, user_input: dict[str, Any] | None = None):
    """Do not commission an existing mesh or create a fake working light entry.

    The current release lacks verified SIG lighting commissioning/key import.
    Make that blocker explicit rather than silently switching to Telink login
    or attempting PB-GATT against an app-paired device.
    """
    info = flow._discovery_info or {}
    if info.get("sig_proxy_advertised"):
        return flow.async_abort(reason="sig_mesh_keys_required")
    return flow.async_abort(reason="sig_mesh_setup_unavailable")
