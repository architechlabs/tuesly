# Tuesly 0.2.10

Bleak 3 rejects high-level writes to CCCD (UUID 2902), including writes of zero
during provisioning cleanup. Those writes could raise ValueError after mesh
keys were delivered and before the fresh proxy/model configuration handoff.

Notification enabling now uses start_notify. The active ESPHome backend already
writes the CCCD itself; its REMOTE_CACHING capability remains advertised even
with device-side service caching disabled. Native backends own notification
cleanup through stop_notify. ESPHome's backend descriptor API clears its peer
CCCD before local unsubscribe, without calling Bleak's forbidden facade API.
The single backend compatibility boundary is isolated in sig_notify.py.

The HA-managed fresh reset listener from 0.2.9 is retained. The gateway stays
enabled during pairing, and callbacks are cleaned up on timeout/cancellation.

107 software tests pass, including tests using the real Bleak facade guard and
simulated HA/ESPHome/native backends. Firmware 1.1.5 configurations validate;
physical commissioning, restart recovery and a sustained soak remain required.

Versions 0.2.8 and 0.2.9 are superseded; install 0.2.10. Test results from those
versions used simulated descriptor APIs and did not prove Bleak compatibility.

Primary sources:
- https://bleak.readthedocs.io/en/latest/api/client.html#bleak.BleakClient.write_gatt_descriptor
- https://github.com/Bluetooth-Devices/bleak-esphome/blob/main/bleak_esphome/backend/client.py
- https://github.com/esphome/esphome/blob/2026.9.0/esphome/components/bluetooth_proxy/bluetooth_proxy.h
