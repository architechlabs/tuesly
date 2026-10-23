"""Wake a failed HA entry when its device becomes reachable again."""
import time
from homeassistant.components import bluetooth


def ensure_recovery_listener(hass, entry):
    """Keep one discovery listener across setup failures, without changing keys."""
    listeners = hass.data.setdefault('tuesly_mesh_recovery', {})
    if entry.entry_id in listeners:
        return
    last_reload = -float('inf')
    active = True
    cancel_stop = None

    def cancel_listener():
        nonlocal active
        if not active:
            return
        active = False
        cancel_scan()
        if cancel_stop is not None:
            cancel_stop()

    def stop_listener(event):
        nonlocal cancel_stop
        # listen_once has already removed its bus listener.
        cancel_stop = None
        if cancel := listeners.pop(entry.entry_id, None):
            cancel()

    def heard(info, change):
        nonlocal last_reload
        if not active or getattr(hass,'is_stopping',False):
            return
        current = hass.config_entries.async_get_entry(entry.entry_id)
        if current is None:
            if cancel := listeners.pop(entry.entry_id, None):
                cancel()
            return
        if current.disabled_by is not None or current.state.value != 'setup_retry':
            return
        now = time.monotonic()
        if getattr(info, 'time', 0) < now - 5 or now - last_reload < 15:
            return
        # HA cancels its exponential setup retry before scheduling the reload.
        # Never commission or reserve addresses in this recovery path.
        last_reload = now
        hass.config_entries.async_schedule_reload(entry.entry_id)

    cancel_scan = bluetooth.async_register_callback(
        hass, heard, {'address': entry.data['mac_address'], 'connectable': True},
        bluetooth.BluetoothScanningMode.ACTIVE)
    listeners[entry.entry_id] = cancel_listener
    cancel_stop = hass.bus.async_listen_once('homeassistant_stop',stop_listener)
