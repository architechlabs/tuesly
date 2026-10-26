"""Recognize Tuya standard-light UUIDs without inspecting fixture labels."""
PROVISIONING_UUID = "00001827-0000-1000-8000-00805f9b34fb"


def _mac_bytes(address: str):
    try:
        mac = bytes.fromhex(address.replace(":", "").replace("-", ""))
    except ValueError:
        return None
    return mac if len(mac) == 6 else None


def provisioning_payload(address: str, service_data) -> bytes:
    """Return Mesh Provisioning service data, whatever key Home Assistant used."""
    if not isinstance(service_data, dict):
        return b""
    mac = _mac_bytes(address)
    chosen = b""
    for key, value in service_data.items():
        if isinstance(value, bytearray):
            value = bytes(value)
        if not isinstance(value, bytes) or not value:
            continue
        key_text = str(key).lower().replace("-", "")
        keyed = "1827" in key_text or key_text == PROVISIONING_UUID.replace("-", "")
        owned = mac is not None and len(value) >= 6 and value[:6] == mac
        if keyed or owned:
            if len(value) >= 18 or not chosen:
                chosen = value
            if len(value) >= 18 and keyed:
                return value
    return chosen


def light_profile(address: str, provisioning_data: bytes):
    if len(provisioning_data) < 18:
        return None
    mac = _mac_bytes(address)
    uuid = provisioning_data[:16]
    if mac is None or uuid[:6] != mac:
        return None
    category = int.from_bytes(uuid[6:8], "big")
    kind = category & 15
    if category & 0x3000 != 0x1000 or category & 0x00F0 != 0x10 or kind not in (1, 2, 3, 4, 5):
        return None
    return {
        "product_type": kind,
        "tunable_white": kind in (2, 5),
        "product_id": uuid[8:16].decode("ascii", errors="replace"),
    }


def pairing_light(address: str, name: str, service_uuids, service_data):
    """A reset driver that can be added the same way as the existing lights.

    A readable UUID that is not a standard light is refused. A provisioning
    advertisement whose UUID has not arrived yet is still offered; model
    binding rejects a node that has no light server. No keys are sent here.
    """
    label = (name or "").lower()
    if label.startswith("tymesh") or label.startswith("s17"):
        return None
    payload = provisioning_payload(address, service_data)
    profile = light_profile(address, payload) if payload else None
    if profile:
        return {"profile": profile}
    mac = _mac_bytes(address)
    if payload and mac and len(payload) >= 18 and payload[:6] == mac:
        return None
    uuids = [str(item).lower() for item in (service_uuids or [])]
    pairing = PROVISIONING_UUID in uuids or label.startswith("out_of_mesh")
    if pairing:
        return {"profile": None}
    return None
