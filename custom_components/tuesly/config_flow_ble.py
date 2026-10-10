"""BLE discovery and validation for Tuesly config flow.

Handles:
- Bluetooth discovery (async_step_bluetooth)
- Device validation and pairing (_validate_and_connect)
- Discovery confirmation (async_step_confirm)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from custom_components.tuesly.config_flow_telink import perform_telink_pairing
from custom_components.tuesly.const import (
    DEVICE_TYPE_LIGHT,
    DEVICE_TYPE_PLUG,
    DEVICE_TYPE_SIG_PLUG,
    SIG_MESH_PROV_UUID,
    SIG_MESH_PROXY_UUID,
)

_LOGGER = logging.getLogger(__name__)


def classify_mesh_services(service_uuids: list[str], requested_type: str | None = None) -> str:
    """Prefer SIG services over vendor UUIDs that a SIG node may also expose."""
    services = {value.lower() for value in service_uuids}
    if SIG_MESH_PROV_UUID in services or SIG_MESH_PROXY_UUID in services:
        return DEVICE_TYPE_SIG_PLUG
    if any(value.startswith("00010203-0405-0607-0809-0a0b0c0d") for value in services):
        if requested_type == DEVICE_TYPE_SIG_PLUG:
            raise ValueError("device_type_mismatch")
        return DEVICE_TYPE_PLUG if requested_type == DEVICE_TYPE_PLUG else DEVICE_TYPE_LIGHT
    raise ValueError("unknown_device_type")


def _rssi_to_signal_quality(rssi: int | None) -> str:
    """Convert RSSI dBm value to a human-readable signal quality label.

    Args:
        rssi: Signal strength in dBm (negative integer) or None if unknown.

    Returns:
        Human-readable label: Excellent, Good, Fair, Weak, or Unknown.
    """
    if rssi is None:
        return "Unknown"
    if rssi >= -65:
        return "Excellent"
    if rssi >= -75:
        return "Good"
    if rssi >= -85:
        return "Fair"
    return "Weak"


async def validate_and_connect(
    hass: Any,
    mac: str,
    device_type: str | None = None,
    mesh_name: str = "out_of_mesh",
    mesh_password: str = "123456",
) -> tuple[str, dict[str, Any]]:
    """Connect to device, detect type if needed, and verify basic communication.

    This method implements the Shelly-pattern: validate BEFORE creating config entry.

    Steps:
    1. BLE connect to device
    2. GATT service discovery to auto-detect device type (if not provided)
    3. Telink: PAIR_REQUEST → PAIR_SUCCESS (mesh login handshake)
    4. Send test command (status query) and verify RESPONSE with hex logging
    5. Return device_type + any discovered credentials/config

    PLAT-740 QC Round 3: Full implementation with pairing + verify + response check.
    Timeout: 30 seconds total for entire flow (connect + pair + verify).

    Args:
        hass: Home Assistant instance.
        mac: BLE MAC address.
        device_type: Known device type, or None to auto-detect.
        mesh_name: Telink mesh network name (for Telink devices).
        mesh_password: Telink mesh password (for Telink devices).

    Returns:
        Tuple of (detected_device_type, extra_data_dict).
        extra_data_dict may contain keys like net_key, dev_key, app_key for SIG devices.

    Raises:
        ValueError: With translatable error key if connection/pairing/verify fails.
        asyncio.TimeoutError: If total flow exceeds 30 seconds.
    """
    from homeassistant.components import bluetooth as ha_bluetooth

    _LOGGER.info("Validating device %s (type=%s)", mac, device_type or "auto-detect")

    # PLAT-740 AC6: 30s total timeout for entire flow
    async def _validate_inner() -> tuple[str, dict[str, Any]]:
        # Step 1: Check device is advertising
        ble_device = ha_bluetooth.async_ble_device_from_address(hass, mac.upper(), connectable=True)
        if ble_device is None:
            _LOGGER.warning("Device %s not found in HA bluetooth registry", mac)
            raise ValueError("device_not_found")

        # An advertised SIG service is enough to choose its setup path. Never
        # send Telink login packets just because the user selected "LED Light".
        info = ha_bluetooth.async_last_service_info(hass, mac.upper(), connectable=True)
        advertised = {value.lower() for value in info.service_uuids} if info else set()
        if SIG_MESH_PROV_UUID in advertised or SIG_MESH_PROXY_UUID in advertised:
            return DEVICE_TYPE_SIG_PLUG, {
                "sig_proxy_advertised": SIG_MESH_PROXY_UUID in advertised,
                "sig_provisioning_advertised": SIG_MESH_PROV_UUID in advertised,
            }

        # Step 2: Connect via Bleak
        from bleak_retry_connector import (
            BleakClientWithServiceCache,
            close_stale_connections_by_address,
            establish_connection,
        )

        await close_stale_connections_by_address(mac.upper())

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                f"Validating {mac}",
                max_attempts=1,
                use_services_cache=False,
                ble_device_callback=lambda: ha_bluetooth.async_ble_device_from_address(
                    hass,mac.upper(),connectable=True) or ble_device,
            )
        except Exception as exc:
            # PLAT-737: Detect BLE adapter busy (0x0a) errors
            exc_str = str(exc).lower()
            if "busy" in exc_str or "0x0a" in exc_str or "in progress" in exc_str:
                from custom_components.tuesly.repairs import (
                    async_create_issue_ble_adapter_busy,
                )

                _LOGGER.error(
                    "BLE adapter busy for %s — another integration is monopolizing the adapter. "
                    "User needs ESPHome Bluetooth Proxy or a second BLE adapter.",
                    mac,
                )
                # Create repair issue to guide user
                await async_create_issue_ble_adapter_busy(hass, f"Device {mac[-8:]}")
                raise ValueError("ble_adapter_busy") from exc
            _LOGGER.warning("BLE connect failed for %s: %s", mac, exc, exc_info=True)
            raise ValueError("cannot_connect_ble") from exc

        try:
            # Step 3: GATT service discovery (always needed — for auto-detection
            # and/or SIG Mesh verification). Fresh services are required because
            # the same MAC can transition between provisioning and proxy mode.
            service_uuids = [str(s.uuid).lower() for s in client.services]
            _LOGGER.debug("Discovered services for %s: %s", mac, service_uuids)

            # Classify the services even when a device category was selected.
            # The paired driver exposes SIG services AND vendor UUIDs.
            detected_type = classify_mesh_services(service_uuids, device_type)

            # Step 4: Pairing/provisioning (device-type specific)
            extra_data: dict[str, Any] = {}

            if detected_type == DEVICE_TYPE_SIG_PLUG:
                extra_data = {
                    "sig_proxy_advertised": SIG_MESH_PROXY_UUID in advertised,
                    "sig_provisioning_advertised": SIG_MESH_PROV_UUID in advertised,
                }
                # SIG setup is routed separately; classification never provisions.
                # Verify the device actually exposes a SIG Mesh service first.
                if (
                    SIG_MESH_PROV_UUID not in service_uuids
                    and SIG_MESH_PROXY_UUID not in service_uuids
                ):
                    _LOGGER.warning("%s claims to be SIG plug but lacks SIG Mesh services", mac)
                    raise ValueError("device_type_mismatch")
                # Mesh ownership and lighting support are checked by the setup router.

            elif detected_type in (DEVICE_TYPE_LIGHT, DEVICE_TYPE_PLUG):
                # PLAT-740: Telink pairing — delegated to config_flow_telink
                extra_data = await perform_telink_pairing(
                    client, mac, mesh_name, mesh_password, detected_type
                )

            else:
                # Unknown device type
                raise ValueError("unknown_device_type")

            _LOGGER.info("Device %s validated successfully (type=%s)", mac, detected_type)
            return detected_type, extra_data

        finally:
            await client.disconnect()

    # PLAT-740 AC6: Wrap entire flow in 30s timeout
    try:
        return await asyncio.wait_for(_validate_inner(), timeout=30.0)
    except TimeoutError:
        _LOGGER.warning("Validation timed out for %s after 30s", mac)
        raise ValueError("timeout_validation") from None
