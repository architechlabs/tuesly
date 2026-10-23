"""Wait for a fresh pairing advertisement through HA's existing proxy subscriber."""
import asyncio
import time
from homeassistant.components import bluetooth

PROVISIONING_UUID='00001827-0000-1000-8000-00805f9b34fb'

def is_tuya_mesh_advertisement(info, address):
    """Recognize the measured Tuya AD03 frame without assuming its GATT mode.

    This driver puts 0x40, its six-byte MAC, and product bytes in an AD03
    field. BLE parsers expose it as bogus 16-bit service UUIDs, not 1827.
    Only accept that exact address signature; provisioning still discovers
    service 1827 and requires a completed PB-GATT exchange.
    """
    try:
        mac=bytes.fromhex(address.replace(':',''))
        if len(mac)!=6:return False
        words=[]
        for uuid in info.service_uuids:
            if len(uuid)==36 and uuid.startswith('0000') and uuid[8:].lower()=='-0000-1000-8000-00805f9b34fb':
                words.append(int(uuid[4:8],16).to_bytes(2,'little'))
        signature=b'\x40'+mac
        return signature in b''.join(words)
    except (ValueError,AttributeError,TypeError):
        return False

async def wait_for_pairing(hass,mac,entry_id,*,timeout=90):
    future=asyncio.get_running_loop().create_future()
    # HA scanner timestamps can use its one-second coarse monotonic clock.
    started=time.monotonic()-1.0
    def heard(info,change):
        if getattr(info,'time',started)<started:
            return
        # AD03 identifies Tuya reachability, not provisioning readiness. It must
        # not start an exchange while the operator is still about to reset.
        if PROVISIONING_UUID in info.service_uuids and not future.done():
            future.set_result(info)
    cancel=bluetooth.async_register_callback(hass,heard,{'address':mac,'connectable':True},bluetooth.BluetoothScanningMode.ACTIVE)
    try:
        # An operator can arm before the physical reset. No second API client
        # replaces HA's Bluetooth subscription and no stale discovery is used.
        hass.bus.async_fire('tuesly_pairing_armed',{'entry_id':entry_id})
        return await asyncio.wait_for(future,timeout)
    finally:
        cancel()
