# Tuesly 0.2.11 / gateway 1.1.6 recovery candidate

## Changes

- Repair cancels HA's setup retry, waits for the config entry setup lock, and
  unloads before arming commissioning. The lock excludes competing reloads
  until provisioning/configuration completes. Keys remain saved on cancellation
  and incomplete configuration.
- A fresh advertisement wakes an entry in setup retry using HA's normal reload
  API, with a 15-second throttle. Disabled entries and active setup are left
  alone. This path never provisions, resets a node, or replaces credentials.
- Diagnostics recognize the measured Tuya AD03 address signature as reachability,
  not provisioning readiness. Pairing still requires 1827 and a verified PB-GATT
  exchange. A prepared operator flow now waits for physical reset confirmation
  before submitting; it cannot start from an old advertisement before that reset.
- Gateway recovery uses a complete board restart instead of BLE disable/enable.
  API client disconnection no longer cycles the BLE stack. The normal five-minute
  API loss reboot timeout remains.

## Evidence before changes

Gateway 1.1.5 answered DeviceInfo but failed entity enumeration while HA reported
it offline. A normal encrypted-API Restart Gateway command restored enumeration
of all 15 entities in 17.3 seconds, followed by HA gateway-online state.
HA's normal repair also raised OperationNotAllowed when the entry was in
SETUP_IN_PROGRESS. The manual helper avoids that by stopping setup before pairing.
Native hci0 was the selected bearer in the observed successful commissioning;
this does not prove ESP32-mediated controls.

The pairing listener can immediately commission an existing fresh provisioning
advertisement. Do not instruct a second physical reset after commissioning starts.
Provisioning success and model-binding acknowledgements are not a substitute for
controls and restart acceptance. This release remains a validation candidate
until live recovery tests pass. A 100-light installation is not yet validated.

## Software and gateway checks

114 software tests passed, including stopping recovery callbacks during HA
shutdown. Gateway 1.1.6 compiled and installed successfully via
encrypted OTA. DeviceInfo and all 15 entities responded in 0.97 seconds. HA
gateway reload and the new recovery button passed the bench monitor, including
15 seconds online after recovery. These were gateway checks without a working
light bearer; active-GATT recovery and driver pairing persistence remain separate
acceptance requirements.

## Longer live checks

Entity enumeration later stalled again on 1.1.6, and a USB hardware reset restored
it. Thus the successful short reload/recovery tests do not establish gateway
stability. The installed API and BLE sources matched their official release.
Two SwitchBot entries were observed attempting connections on the shared proxy;
pausing them was a comparison, not proof that they caused the gateway fault.

With those entries paused, commissioning at primary 0x17EA and on/off, brightness
128/220, warm/cool 0/50/100 readbacks passed using native Pi hci0. A later outage
was followed by successful controls with the same identity, but the light became
unavailable again. This is not accepted power-cycle recovery or an ESP32-only
control result. A native identity probe subsequently failed during service
discovery before authentication, so it did not establish whether keys changed.

Disconnect cleanup now allows the proxy's full five-second disconnect timeout,
with a twelve-second coordinator cleanup bound covering notification teardown.
The release remains a validation candidate, not a production-ready handover.

Gateway 1.1.7 explicitly tests an 80 ms idle scan window in a 320 ms interval,
with a 30 ms connection scan window, to investigate shared-radio API stalls.
This is a controlled configuration change, not an established root-cause fix.

1.1.7 compiled, flashed over COM8, and passed flash hash verification. API checks
listed all 15 entities in 0.86 and 0.87 seconds. HA gateway reload and recovery
passed the short monitor. The final 0.2.11 controller source was deployed and HA
restarted. These results do not establish long-term or 100-device stability.
