"""Proxy routing regressions; uses real mesh library with simulated BLE clients."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "tuesly"
sys.path.insert(0, str(COMPONENT / "lib"))
# Import only the mesh modules under test, rather than unrelated HTTP daemons
# re-exported by the library's package initializer.
mesh_package = types.ModuleType("tuesly_mesh")
mesh_package.__path__ = [str(COMPONENT / "lib" / "tuesly_mesh")]
sys.modules["tuesly_mesh"] = mesh_package
from bleak.exc import BleakError
from tuesly_mesh.exceptions import MeshConnectionError
from tuesly_mesh.sig_mesh_device import SIGMeshDevice


def load_ha_module(name, filename):
    # HA runs on Linux. Only its constant/container modules are substituted
    # here; connection behavior under test is the actual upstream Python code.
    for parent in ("custom_components", "custom_components.tuesly"):
        if parent not in sys.modules:
            module = types.ModuleType(parent)
            module.__path__ = [str(COMPONENT)]
            sys.modules[parent] = module
    const_name = "custom_components.tuesly.const"
    if const_name not in sys.modules and name != const_name:
        ha_const = types.ModuleType("homeassistant.const")
        ha_const.Platform = types.SimpleNamespace(**{
            key: key.lower() for key in
            ("BINARY_SENSOR", "BUTTON", "LIGHT", "SENSOR", "SWITCH", "UPDATE")
        })
        sys.modules["homeassistant.const"] = ha_const
        load_ha_module(const_name, "const.py")
    spec = importlib.util.spec_from_file_location(name, COMPONENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ProxyConnectionTests(unittest.IsolatedAsyncioTestCase):
    def make_device(self, client):
        resolver = MagicMock(return_value=MagicMock(address="DC:23:52:81:60:BB"))
        connector = AsyncMock(return_value=client)
        device = SIGMeshDevice("DC:23:52:81:60:BB", 0xB0, 1, MagicMock(),
                               ble_device_callback=resolver,
                               ble_connect_callback=connector)
        device._load_keys = AsyncMock()
        device.request_composition_data = AsyncMock()
        device._bluetoothctl_remove = AsyncMock()
        return device, resolver, connector

    async def test_connect_uses_managed_proxy_client(self):
        client = MagicMock(is_connected=True)
        client.start_notify = AsyncMock()
        client.disconnect = AsyncMock()
        device, resolver, connector = self.make_device(client)
        with patch("tuesly_mesh.sig_mesh_device.BleakClient") as local_client, \
             patch("tuesly_mesh.sig_mesh_device.BleakScanner") as scanner:
            await device.connect(max_retries=1)
        local_client.assert_not_called()
        scanner.find_device_by_address.assert_not_called()
        connector.assert_awaited_once_with(
            resolver.return_value, disconnected_callback=device._on_ble_disconnect)
        client.start_notify.assert_awaited_once()
        self.assertTrue(device.is_connected)
        client.disconnect.assert_not_awaited()

    async def test_notify_failure_releases_slot_and_rejects_connection(self):
        client = MagicMock()
        client.start_notify = AsyncMock(side_effect=BleakError("notify failed"))
        client.disconnect = AsyncMock()
        device, _, _ = self.make_device(client)
        with patch("tuesly_mesh.sig_mesh_device.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(MeshConnectionError):
                await device.connect(max_retries=1)
        client.disconnect.assert_awaited_once()
        device._bluetoothctl_remove.assert_not_awaited()
        self.assertFalse(device.is_connected)

    async def test_duplicate_vendor_uuids_select_standard_proxy_service(self):
        client = MagicMock(is_connected=True)
        client.start_notify = AsyncMock()
        client.stop_notify = AsyncMock()
        client.disconnect = AsyncMock()
        incoming = MagicMock(handle=32)
        outgoing = MagicMock(handle=28)
        proxy_service = MagicMock()
        proxy_service.get_characteristic.side_effect = lambda uuid: (
            incoming if "2add" in uuid else outgoing)
        client.services.get_service.return_value = proxy_service
        device, _, _ = self.make_device(client)
        await device.connect(max_retries=1)
        client.services.get_service.assert_called_once_with("00001828-0000-1000-8000-00805f9b34fb")
        client.start_notify.assert_awaited_once_with(outgoing, device._on_notify)
        self.assertIs(device._proxy_data_in, incoming)
        await device.disconnect()
        client.stop_notify.assert_awaited_once_with(outgoing)

    async def test_missing_proxy_service_releases_slot(self):
        client = MagicMock()
        client.services.get_service.return_value = None
        client.disconnect = AsyncMock()
        device, _, _ = self.make_device(client)
        with patch("tuesly_mesh.sig_mesh_device.asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(MeshConnectionError):
                await device.connect(max_retries=1)
        client.disconnect.assert_awaited_once()

    async def test_cancelled_notify_releases_slot(self):
        client = MagicMock()
        client.start_notify = AsyncMock(side_effect=asyncio.CancelledError())
        client.disconnect = AsyncMock()
        device, _, _ = self.make_device(client)
        with self.assertRaises(asyncio.CancelledError):
            await device.connect(max_retries=1)
        client.disconnect.assert_awaited_once()

    async def test_factory_accepts_connection_callback(self):
        factory = load_ha_module("custom_components.tuesly.device_factory", "device_factory.py")
        connector = AsyncMock()
        device = factory.create_device("sig_plug", "DC:23:52:81:60:BB", {
            "net_key": "00" * 16, "dev_key": "11" * 16, "app_key": "22" * 16,
        }, ble_device_callback=MagicMock(), ble_connect_callback=connector)
        self.assertIsInstance(device, SIGMeshDevice)
        self.assertIs(device._ble_connect_callback, connector)

    async def test_cancelled_composition_request_releases_slot(self):
        client = MagicMock()
        client.start_notify = AsyncMock()
        client.disconnect = AsyncMock()
        device, _, _ = self.make_device(client)
        device.request_composition_data = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await device.connect(max_retries=1)
        client.disconnect.assert_awaited_once()
        self.assertFalse(device.is_connected)

    async def test_post_provision_configuration_keeps_proxy_callbacks(self):
        module = load_ha_module("custom_components.tuesly.config_flow_sig", "config_flow_sig.py")
        ha = types.ModuleType("homeassistant")
        components = types.ModuleType("homeassistant.components")
        bluetooth = types.ModuleType("homeassistant.components.bluetooth")
        bluetooth.async_ble_device_from_address = MagicMock(return_value=MagicMock())
        components.bluetooth = bluetooth
        ha.components = components
        provisioner = MagicMock()
        provisioner.provision = AsyncMock(return_value=types.SimpleNamespace(
            dev_key=b"\x11" * 16, num_elements=1))
        device = MagicMock()
        device.connect = AsyncMock()
        device.disconnect = AsyncMock()
        device.send_config_app_key_add = AsyncMock(return_value=True)
        device.send_config_model_app_bind = AsyncMock(return_value=True)
        with patch.dict(sys.modules, {"homeassistant": ha, "homeassistant.components": components,
                                     "homeassistant.components.bluetooth": bluetooth}), \
             patch("tuesly_mesh.sig_mesh_provisioner.SIGMeshProvisioner", return_value=provisioner) as create_prov, \
             patch("tuesly_mesh.sig_mesh_device.SIGMeshDevice", return_value=device) as create_device, \
             patch.object(module.asyncio, "sleep", new=AsyncMock()):
            keys = await module.run_provision(MagicMock(), "DC:23:52:81:60:BB")
        self.assertEqual(len(keys), 3)
        self.assertIs(create_prov.call_args.kwargs["ble_connect_callback"],
                      create_device.call_args.kwargs["ble_connect_callback"])
        self.assertIs(create_prov.call_args.kwargs["ble_device_callback"],
                      create_device.call_args.kwargs["ble_device_callback"])
        device.disconnect.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
