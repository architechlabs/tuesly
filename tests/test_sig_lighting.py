"""Wire vectors and malformed/multi-element cases for SIG CCT light support."""
import unittest
from test_transport import COMPONENT
from tuesly_mesh.sig_lighting import (
    lightness_get, temperature_get, lightness_set, temperature_set,
    parse_lightness_status, parse_temperature_status,
    parse_element_models, discover_lighting_models,
)
from tuesly_mesh.exceptions import MalformedPacketError


class LightingCodecTests(unittest.TestCase):
    def test_standard_access_wire_vectors(self):
        self.assertEqual(lightness_get().hex(), "824b")
        self.assertEqual(temperature_get().hex(), "8261")
        self.assertEqual(lightness_set(32768, 7).hex(), "824c008007")
        self.assertEqual(lightness_set(65535, 255, acknowledged=False).hex(), "824dffffff")
        self.assertEqual(temperature_set(3000, 7, delta_uv=-2).hex(), "8264b80bfeff07")
        self.assertEqual(temperature_set(20000, 0, acknowledged=False).hex(), "8265204e000000")

    def test_wire_fields_cannot_wrap_or_accept_boolean_levels(self):
        for level in (-1, 65536, True):
            with self.assertRaises(ValueError):
                lightness_set(level, 0)
        for temperature in (799, 20001):
            with self.assertRaises(ValueError):
                temperature_set(temperature, 0)
        with self.assertRaises(ValueError):
            temperature_set(3000, 256)

    def test_present_and_target_are_not_confused(self):
        state = parse_lightness_status(bytes.fromhex("0010ffff01"))
        self.assertEqual(state.present, 4096)
        self.assertEqual(state.target, 65535)
        self.assertEqual(state.remaining_encoded, 1)
        self.assertIsNone(parse_lightness_status(b"\x00\x00").target)

    def test_signed_delta_uv_and_optional_temperature_target(self):
        state = parse_temperature_status(bytes.fromhex("b80bfeff6419000001"))
        self.assertEqual(state.present_kelvin, 3000)
        self.assertEqual(state.present_delta_uv, -2)
        self.assertEqual(state.target_kelvin, 6500)
        self.assertIsNone(parse_temperature_status(bytes.fromhex("b80b0000")).target_kelvin)

    def test_truncated_statuses_are_rejected(self):
        for params in (b"", b"\x00", b"\x00"*3, b"\x00"*6):
            with self.assertRaises(MalformedPacketError):
                parse_lightness_status(params)
        for params in (b"", b"\x00"*5, b"\x00"*8):
            with self.assertRaises(MalformedPacketError):
                parse_temperature_status(params)

    def test_models_on_secondary_elements_keep_correct_addresses(self):
        # Synthetic Composition Page 0 element bytes, not a capture from H12X2.
        raw = bytes.fromhex("0000020100000010d0070400" "000001000013" "000001000613")
        elements = parse_element_models(raw, 0x0100)
        models = discover_lighting_models(elements)
        self.assertEqual(models.onoff, (0x0100,))
        self.assertEqual(models.lightness, (0x0101,))
        self.assertEqual(models.temperature, (0x0102,))
        self.assertEqual(elements[0].vendor_models, ((0x07D0, 0x0004),))
        self.assertTrue(models.supports_cct)

    def test_vendor_only_node_is_not_claimed_to_support_cct(self):
        elements = parse_element_models(bytes.fromhex("00000001d0070400"), 0x0100)
        self.assertFalse(discover_lighting_models(elements).supports_cct)

    def test_truncated_composition_and_address_overflow_are_rejected(self):
        for raw in (b"", b"\x00"*3, bytes.fromhex("000002000010")):
            with self.assertRaises(MalformedPacketError):
                parse_element_models(raw, 1)
        with self.assertRaises(MalformedPacketError):
            parse_element_models(bytes.fromhex("00000000" "00000000"), 0x7FFF)


if __name__ == "__main__":
    unittest.main()
