"""Config flow for Tuesly integration.
This module routes config flow steps to specialized handlers:
- config_flow_ble: BLE discovery, validation, confirmation
- config_flow_sig: SIG Mesh provisioning
- config_flow_options: Bridge + reconfigure + reauth
- config_flow_validators: Validation helpers
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlow

# Import for test patching (used in config_flow_sig/config_flow_telink submodules)
try:
    from bleak import BleakScanner
    from tuesly_mesh.sig_mesh_bridge import SIGMeshBridgeDevice
    from tuesly_mesh.sig_mesh_device import SIGMeshDevice

    find_device_by_address = BleakScanner.find_device_by_address
except ImportError:
    SIGMeshBridgeDevice = None  # type: ignore[misc,assignment]
    SIGMeshDevice = None  # type: ignore[misc,assignment]
    find_device_by_address = None  # type: ignore[misc,assignment]

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.data_entry_flow import FlowResult

# Import handlers from specialized modules
from custom_components.tuesly.config_flow_ble import validate_and_connect
from custom_components.tuesly.config_flow_discovery import (
    async_step_bluetooth as ble_bluetooth_handler,
)
from custom_components.tuesly.config_flow_discovery import (
    async_step_confirm_impl,
)
from custom_components.tuesly.config_flow_options import TueslyOptionsFlow
from custom_components.tuesly.config_flow_options import (
    async_step_bridge_config as bridge_config_handler,
)
from custom_components.tuesly.config_flow_reconfigure import (
    async_step_reauth as reauth_handler,
)
from custom_components.tuesly.config_flow_reconfigure import (
    async_step_reauth_confirm as reauth_confirm_handler,
)
from custom_components.tuesly.config_flow_reconfigure import (
    async_step_reconfigure as reconfigure_handler,
)
from custom_components.tuesly.config_flow_sig import (
    async_step_sig_bridge as sig_bridge_handler,
)
from custom_components.tuesly.config_flow_sig import (
    async_step_sig_plug as sig_plug_handler,
)
from custom_components.tuesly.config_flow_telink import (
    async_step_telink_bridge as telink_bridge_handler,
)
from custom_components.tuesly.config_flow_validators import (
    _validate_mac,
    _validate_mesh_credential,
    _validate_vendor_id,
)
from custom_components.tuesly.const import (
    CONF_APP_KEY,
    CONF_BRIDGE_HOST,
    CONF_BRIDGE_PORT,
    CONF_DEV_KEY,
    CONF_DEVICE_TYPE,
    CONF_IV_INDEX,
    CONF_MAC_ADDRESS,
    CONF_MESH_ADDRESS,
    CONF_MESH_NAME,
    CONF_MESH_PASSWORD,
    CONF_NET_KEY,
    CONF_UNICAST_OUR,
    CONF_UNICAST_TARGET,
    CONF_VENDOR_ID,
    DEFAULT_MESH_ADDRESS,
    DEFAULT_VENDOR_ID,
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_PLUG,
    DEVICE_TYPE_SIG_BRIDGE_PLUG,
    DEVICE_TYPE_SIG_PLUG,
    DEVICE_TYPE_TELINK_BRIDGE_LIGHT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Allowlist of ValueError message strings that are valid HA translation keys.
# validate_and_connect raises ValueError("<key>") — any unrecognised key would
# expose raw exception text in the UI (CR-019).  Add new keys here as needed.
_KNOWN_BLE_ERROR_KEYS: frozenset[str] = frozenset(
    {
        "device_not_found",
        "ble_adapter_busy",
        "cannot_connect_ble",
        "unknown_device_type",
        "device_type_mismatch",
        "timeout_validation",
        "pairing_failed",
        "verify_failed",
    }
)


class TueslyConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Tuesly."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TueslyOptionsFlow:
        """Return the options flow handler."""
        return TueslyOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Initialize config flow state for a new Tuesly entry."""
        super().__init__()
        self._discovery_info: dict[str, Any] | None = None

    def _finalize_entry(
        self,
        mac: str,
        device_type: str,
        title: str | None = None,
        **extra_data: Any,
    ) -> FlowResult:
        """Create config entry after all validation passed.

        PLAT-740 QC BRIST 1: SINGLE entry point for async_create_entry.
        ALL code paths must call this method to create entries.

        Args:
            mac: Device MAC address.
            device_type: Validated device type.
            title: Entry title (auto-generated if None).
            **extra_data: Additional config data (mesh_name, keys, etc.).
                Accepts both snake_case kwargs and CONF_* constants.

        Returns:
            FlowResult from async_create_entry.
        """
        short_mac = mac[-8:]
        if title is None:
            type_label = {
                DEVICE_TYPE_LIGHT: "LED Light",
                DEVICE_TYPE_PLUG: "Smart Plug",
                DEVICE_TYPE_SIG_PLUG: "Smart Plug",
                DEVICE_TYPE_SIG_BRIDGE_PLUG: "Smart Plug",
                DEVICE_TYPE_TELINK_BRIDGE_LIGHT: "LED Light",
            }.get(device_type, "Smart Device")
            title = f"{type_label} {short_mac}"

        # Map snake_case kwargs to CONF_* constants
        key_map = {
            "mesh_name": CONF_MESH_NAME,
            "mesh_password": CONF_MESH_PASSWORD,
            "vendor_id": CONF_VENDOR_ID,
            "mesh_address": CONF_MESH_ADDRESS,
            "unicast_target": CONF_UNICAST_TARGET,
            "unicast_our": CONF_UNICAST_OUR,
            "iv_index": CONF_IV_INDEX,
            "net_key": CONF_NET_KEY,
            "dev_key": CONF_DEV_KEY,
            "app_key": CONF_APP_KEY,
            "bridge_host": CONF_BRIDGE_HOST,
            "bridge_port": CONF_BRIDGE_PORT,
        }
        data = {CONF_MAC_ADDRESS: mac, CONF_DEVICE_TYPE: device_type}
        for key, value in extra_data.items():
            conf_key = key_map.get(key, key)
            data[conf_key] = value

        _LOGGER.info(
            "Creating config entry: %s (type=%s, data keys=%s)",
            title,
            device_type,
            list(data.keys()),
        )
        return self.async_create_entry(title=title, data=data)

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        """Delegate bluetooth discovery to BLE handler."""
        return await ble_bluetooth_handler(self, discovery_info)

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Delegate discovery confirmation to BLE handler."""
        return await async_step_confirm_impl(self, user_input)

    async def async_step_sig_plug(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Delegate SIG Mesh plug provisioning to SIG handler."""
        return await sig_plug_handler(self, user_input)

    async def async_step_sig_bridge(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Delegate SIG bridge config to SIG handler."""
        return await sig_bridge_handler(self, user_input)

    async def async_step_telink_bridge(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delegate Telink bridge config to options handler."""
        return await telink_bridge_handler(self, user_input)

    async def async_step_bridge_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delegate bridge config to options handler."""
        return await bridge_config_handler(self, user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Delegate reconfigure to options handler."""
        return await reconfigure_handler(self, user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Delegate reauth to options handler."""
        return await reauth_handler(self, entry_data)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Delegate reauth_confirm to options handler."""
        return await reauth_confirm_handler(self, user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        from custom_components.tuesly.config_flow_setup import async_step_user
        return await async_step_user(self, user_input)

    async def async_step_sig_setup(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        from custom_components.tuesly.config_flow_setup import async_step_sig_setup
        return await async_step_sig_setup(self, user_input)
