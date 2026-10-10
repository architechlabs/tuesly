# Tuesly 0.2.7 validation and reconnect plan

## What the earlier captures establish

| Observation | What it establishes |
|---|---|
| User confirmed physical on/off, brightness and warm/cool changes | The driver supports the tested lighting commands |
| PB-GATT, descriptor readback, fresh Proxy connection and bindings in 7.83 s | A complete operator commissioning/configuration exchange worked |
| HA later handed over a new identity; authenticated Filter Status reported primary 4592 | A later HA-owned network membership was confirmed; the old operator export is stale |
| Driver/proxy outages, setup timeouts and failed restart monitor | End-to-end recovery was not accepted |
| Provisioning and proprietary advertisements during restart, later Proxy advertising | Advertising 1827 alone cannot diagnose erased storage |
| USB capture without an explicit reset coincided with a boot log and short gateway uptime | Serial diagnostics may have disrupted a test; avoid reopening the port during GATT work |

The successful filter response authenticates the network. It does not by itself
prove every application binding, the current device key, or power-cycle retention.
No driver hardware/storage fault has been established. No 100-fixture fleet or
24-hour soak has been accepted.

## Changes in 0.2.7

- A timeout or disconnect before Provisioning Data permits one fresh connection
  and ECDH retry. Lost acknowledgements after possible delivery never restart
  provisioning or discard the saved credentials.
- Provisioning waits wake on disconnect. A peer that already ended PB-GATT can
  proceed to the fresh Mesh Proxy connection.
- Both provisioning and mesh notification descriptors are cleared explicitly.
- Failed retries no longer retain the intentional-disconnect flag.
- Cancelled notification cleanup still disconnects and drops the local session.
- Failed discovery, disconnect cleanup and first entry refresh release radio
  ownership and active-scan registrations.
- HA-managed connection attempts are bounded without stacking two internal
  20-second attempts inside the controller's connection deadline. Device lookup
  is refreshed through the public retry-connector callback.
- An unreachable direct target can use one reachable saved same-network anchor.
  The proxy source and destination device key remain distinct and authenticated.
- Interrupted repair now explains that credentials may already be installed
  and directs the user to resume rather than reset.
- Old bench snapshots are blocked from destructive recovery/import after
  subsequent HA commissioning.

The regression tests use real P-256/CMAC/CCM, encrypted Proxy PDUs and segmented
GATT frames with simulated HA/radio boundaries. They cover failures and recovery,
not physical radio reliability.

## Reconnect the existing bench without resetting it

1. Put the ESP32 and driver back on stable power near each other. Keep the phone
   Bluetooth app closed during the acceptance run.
2. Make a full HA backup. Install `dist/tuesly-0.2.7.zip` into
   `/config/custom_components/tuesly`, then restart HA once.
3. Keep the existing ESP32 firmware and saved mesh Store. Confirm the actual
   proxy IP under ESPHome; do not assume an old DHCP address is still correct.
4. Confirm ESPHome is connected and Bluetooth scanning is Active. Keep USB
   monitoring and private raw proxy tools closed during the HA test.
5. Enable the existing Tuesly light entry if paused. Use **Reconfigure** with
   both boxes unchecked to resume application configuration with the live keys.
6. Confirm HA on/off and brightness, then test **White temperature** at 0%, 50%,
   100%. Confirm the actual light, not just the dashboard values.
7. With automatic HA recovery active, test one normal driver restart, one proxy
   restart and an HA restart. Do not insert a factory-reset sequence.
8. Record the failing stage if recovery fails. Preserve the journal. Do not
   import the old private bench export or repeat commissioning indiscriminately.
9. Complete the site guide's pilot and soak checks before expanding the fleet.

Factory recommissioning is for an intentionally reset device only. Prepare the
HA commissioning screen first, then reset and submit immediately. It must not
depend on sending a chat message before a listener begins.

## Primary research

- [Tuya pairing stages and configuration deadline](https://developer.tuya.com/en/docs/iot-device-dev/bluetooth_software_map_mesh_provision?id=Kd5wkuunhsjtq)
- [Tuya reset and network recovery](https://developer.tuya.com/en/docs/iot-device-dev/bluetooth_software_map_mesh_reset?id=Kd5wkznhwupfc)
- [HA public Bluetooth API, 2026.9.3](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/bluetooth/api.py)
- [HA Bluetooth backend routing](https://github.com/Bluetooth-Devices/habluetooth/blob/main/src/habluetooth/wrappers.py)
- [Retry connector connection/cache behavior](https://github.com/Bluetooth-Devices/bleak-retry-connector/blob/main/src/bleak_retry_connector/__init__.py)
- [ESPHome Bleak descriptor/notification behavior](https://github.com/Bluetooth-Devices/bleak-esphome/blob/main/src/bleak_esphome/backend/client.py)
- [pySerial control-line behavior](https://pyserial.readthedocs.io/en/latest/pyserial_api.html)

HA chooses an available connection backend; a direct SDK diagnostic does not
prove that HA chose the same path. The retry connector sets its own connection
timeout, so passing a constructor `timeout` does not replace a complete-session
deadline. ESPHome's local notification unregistration does not alone clear the
peer's CCCD. These behaviors informed the cleanup and retry changes above.
