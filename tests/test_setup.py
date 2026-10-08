"""Regressions for the actual SIG-driver/Telink/HTTP setup mismatch."""
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_transport import load_ha_module

MAC = "DC:23:52:81:60:BB"
PROXY = "00001828-0000-1000-8000-00805f9b34fb"
PROVISIONING = "00001827-0000-1000-8000-00805f9b34fb"
VENDOR = "00010203-0405-0607-0809-0a0b0c0d1912"


class SetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup = load_ha_module("custom_components.tuesly.config_flow_setup", "config_flow_setup.py")
        self.ble = sys.modules["custom_components.tuesly.config_flow_ble"]

    def flow(self, advanced=False):
        flow = MagicMock()
        flow.show_advanced_options = advanced
        flow.hass.config_entries.async_entries.return_value = []
        flow.async_set_unique_id = AsyncMock()
        flow.async_step_telink_bridge = AsyncMock(return_value={"step_id": "telink_bridge"})
        flow.async_step_sig_bridge = AsyncMock(return_value={"step_id": "sig_bridge"})
        flow.async_show_form.side_effect = lambda **kwargs: {"type": "form", **kwargs}
        flow.async_abort.side_effect = lambda **kwargs: {"type": "abort", **kwargs}
        flow._finalize_entry.side_effect = lambda **kwargs: {"type": "create_entry", **kwargs}
        async def sig_setup(user_input=None):
            return await self.setup.async_step_sig_setup(flow, user_input)
        flow.async_step_sig_setup = AsyncMock(side_effect=sig_setup)
        return flow

    def test_sig_services_take_priority_over_vendor_service_and_light_choice(self):
        self.assertEqual(self.ble.classify_mesh_services([VENDOR, PROVISIONING, PROXY], "light"), "sig_plug")

    def test_unrecognized_services_are_not_assumed_telink(self):
        with self.assertRaisesRegex(ValueError, "unknown_device_type"):
            self.ble.classify_mesh_services(["0000180f-0000-1000-8000-00805f9b34fb"], "light")

    async def test_sig_advertisement_never_sends_telink_login(self):
        bluetooth = types.ModuleType("homeassistant.components.bluetooth")
        bluetooth.async_ble_device_from_address = MagicMock(return_value=MagicMock())
        bluetooth.async_last_service_info = MagicMock(return_value=types.SimpleNamespace(service_uuids=[PROXY]))
        components = types.ModuleType("homeassistant.components")
        components.bluetooth = bluetooth
        ha = types.ModuleType("homeassistant")
        ha.components = components
        with patch.dict(sys.modules, {"homeassistant": ha, "homeassistant.components": components,
                                      "homeassistant.components.bluetooth": bluetooth}), \
             patch.object(self.ble, "perform_telink_pairing", new=AsyncMock()) as login, \
             patch("bleak_retry_connector.establish_connection", new=AsyncMock()) as connect:
            detected, details = await self.ble.validate_and_connect(MagicMock(), MAC, "light")
        self.assertEqual(detected, "sig_plug")
        self.assertTrue(details["sig_proxy_advertised"])
        login.assert_not_awaited()
        connect.assert_not_awaited()

    async def test_led_selection_routes_paired_sig_to_explicit_key_blocker(self):
        flow = self.flow()
        with patch.object(self.setup, "validate_and_connect", new=AsyncMock(
            return_value=("sig_plug", {"sig_proxy_advertised": True}))):
            result = await self.setup.async_step_user(flow, {"mac_address": MAC, "device_type": "light"})
        self.assertEqual(result["reason"], "sig_mesh_keys_required")
        flow._finalize_entry.assert_not_called()
        flow.async_step_telink_bridge.assert_not_awaited()

    async def test_blank_telink_fields_restore_defaults(self):
        flow = self.flow()
        with patch.object(self.setup, "validate_and_connect", new=AsyncMock(return_value=("light", {}))) as validate:
            result = await self.setup.async_step_user(flow, {
                "mac_address": MAC, "device_type": "light", "mesh_name": "", "mesh_password": "",
            })
        self.assertEqual(validate.await_args.args[3:], ("out_of_mesh", "123456"))
        self.assertEqual(result["mesh_name"], "out_of_mesh")

    async def test_default_form_detects_protocol_and_hides_http_bridge(self):
        result = await self.setup.async_step_user(self.flow())
        fields = result["data_schema"].schema
        device_key = next(key for key in fields if key.schema == "device_type")
        self.assertEqual(device_key.default(), "auto")
        self.assertNotIn("telink_bridge_light", fields[device_key].container)

    async def test_advanced_bridge_labels_name_http_daemon(self):
        result = await self.setup.async_step_user(self.flow(advanced=True))
        fields = result["data_schema"].schema
        device_key = next(key for key in fields if key.schema == "device_type")
        self.assertIn("HTTP bridge daemon", fields[device_key].container["telink_bridge_light"])

    async def test_unverified_sig_setup_does_not_provision(self):
        flow = self.flow()
        flow._discovery_info = {"address": MAC}
        result = await self.setup.async_step_sig_setup(flow)
        self.assertEqual(result["reason"], "sig_mesh_setup_unavailable")
        flow._finalize_entry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
