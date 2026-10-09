"""Standard SIG white-light messages and Composition Page 0 model discovery.

Original Architech Labs implementation. Message facts follow Bluetooth Mesh
models; no driver model or colour-temperature range is inferred from a label.
This module does not commission devices, store keys, or transmit packets.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from tuesly_mesh.exceptions import MalformedPacketError

GENERIC_ONOFF_SERVER = 0x1000
LIGHT_LIGHTNESS_SERVER = 0x1300
LIGHT_CTL_SERVER = 0x1303
LIGHT_CTL_TEMPERATURE_SERVER = 0x1306


def _integer(value: int, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside its protocol range")
    return value


def lightness_get() -> bytes:
    return bytes.fromhex("824b")


def temperature_get() -> bytes:
    return bytes.fromhex("8261")


def lightness_set(lightness: int, tid: int, *, acknowledged: bool = True) -> bytes:
    level = _integer(lightness, 0, 65535, "Lightness")
    transaction = _integer(tid, 0, 255, "Transaction ID")
    return bytes.fromhex("824c" if acknowledged else "824d") + struct.pack("<HB", level, transaction)


def temperature_set(kelvin: int, tid: int, *, delta_uv: int = 0, acknowledged: bool = True) -> bytes:
    temperature = _integer(kelvin, 800, 20000, "Temperature")
    transaction = _integer(tid, 0, 255, "Transaction ID")
    delta = _integer(delta_uv, -32768, 32767, "Delta UV")
    return bytes.fromhex("8264" if acknowledged else "8265") + struct.pack("<HhB", temperature, delta, transaction)


@dataclass(frozen=True)
class LightnessStatus:
    present: int
    target: int | None = None
    remaining_encoded: int | None = None


@dataclass(frozen=True)
class TemperatureStatus:
    present_kelvin: int
    present_delta_uv: int
    target_kelvin: int | None = None
    target_delta_uv: int | None = None
    remaining_encoded: int | None = None


def parse_lightness_status(params: bytes) -> LightnessStatus:
    if len(params) == 2:
        return LightnessStatus(struct.unpack("<H", params)[0])
    if len(params) == 5:
        return LightnessStatus(*struct.unpack("<HHB", params))
    raise MalformedPacketError("Lightness Status has an invalid length")


def parse_temperature_status(params: bytes) -> TemperatureStatus:
    if len(params) == 4:
        return TemperatureStatus(*struct.unpack("<Hh", params))
    if len(params) == 9:
        return TemperatureStatus(*struct.unpack("<HhHhB", params))
    raise MalformedPacketError("CTL Temperature Status has an invalid length")


@dataclass(frozen=True)
class MeshElement:
    address: int
    location: int
    sig_models: tuple[int, ...]
    # Vendor model identifiers are (company_id, model_id), not SIG model IDs.
    vendor_models: tuple[tuple[int, int], ...]


def parse_element_models(raw_elements: bytes, primary_address: int) -> tuple[MeshElement, ...]:
    address = _integer(primary_address, 1, 0x7FFF, "Primary address")
    result = []
    offset = 0
    while offset < len(raw_elements):
        if len(raw_elements) - offset < 4:
            raise MalformedPacketError("Composition element header is truncated")
        location, sig_count, vendor_count = struct.unpack_from("<HBB", raw_elements, offset)
        offset += 4
        required = sig_count * 2 + vendor_count * 4
        if len(raw_elements) - offset < required:
            raise MalformedPacketError("Composition model list is truncated")
        if address > 0x7FFF:
            raise MalformedPacketError("Composition element addresses exceed the unicast range")
        sig_models = tuple(struct.unpack_from("<H", raw_elements, offset + i*2)[0] for i in range(sig_count))
        offset += sig_count * 2
        vendor_models = tuple(struct.unpack_from("<HH", raw_elements, offset + i*4) for i in range(vendor_count))
        offset += vendor_count * 4
        result.append(MeshElement(address, location, sig_models, vendor_models))
        address += 1
    if not result:
        raise MalformedPacketError("Composition Data contains no elements")
    return tuple(result)


@dataclass(frozen=True)
class LightingModelAddresses:
    onoff: tuple[int, ...]
    lightness: tuple[int, ...]
    temperature: tuple[int, ...]
    ctl: tuple[int, ...] = ()

    @property
    def supports_cct(self) -> bool:
        return bool(self.onoff and self.lightness and self.temperature and self.ctl)


def discover_lighting_models(elements: tuple[MeshElement, ...]) -> LightingModelAddresses:
    def addresses(model):
        return tuple(element.address for element in elements if model in element.sig_models)
    return LightingModelAddresses(addresses(GENERIC_ONOFF_SERVER),
                                  addresses(LIGHT_LIGHTNESS_SERVER),
                                  addresses(LIGHT_CTL_TEMPERATURE_SERVER),
                                  addresses(LIGHT_CTL_SERVER))


def select_lighting_channel(elements: tuple[MeshElement, ...]) -> LightingModelAddresses:
    """Select a unique brightness-bearing channel, excluding OnOff-only auxiliaries.

    The measured Tuya H12X2 has its complete lighting servers on one element
    and five extra OnOff-only elements. Require structural evidence rather than
    selecting the first address from unrelated switch elements.
    """
    models = discover_lighting_models(elements)
    if len(models.lightness) == 1 and models.lightness[0] in models.onoff:
        return LightingModelAddresses((models.lightness[0],), models.lightness,
                                      models.temperature, models.ctl)
    return models
