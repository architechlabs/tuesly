# Tuesly 0.2.13 PB-GATT framing candidate

The successful native Pi path negotiated MTU 23. The ESP32 path negotiated
MTU 247 and reached Capabilities/PublicKey but timed out at Confirmation
on 2026-10-13. PB-GATT transmission now uses fragments fitting MTU 23 on
both paths, while retaining the negotiated connection MTU. This tests the
observed transport difference without changing authentication or keys.
The shared Mesh Proxy transport already uses the same conservative framing.

A real cryptographic in-process provisioning exchange at negotiated MTU
247 passed with every write limited to 20 bytes. The targeted suite passed
16 tests. This is a compatibility hypothesis until live ESP32 provisioning,
controls, gateway restart, and LED power-cycle recovery all pass.

Gateway firmware 1.1.8 is installed. It restarts the ESP32 if a Home Assistant
connection fails to subscribe to entity states within the existing 90-second
readiness deadline. The incomplete-setup recovery check passed, including fresh
enumeration of all 15 entities. This check does not establish GATT reliability
when HA's entity subscription is healthy.

On 2026-10-14 the gateway was online, scanning actively, with three free slots;
the driver was absent from both current Pi and ESP32 scans. Runtime setup still
failed at connecting to the GATT proxy. The operator reset monitor now reads
remote scanner packet timestamps rather than merged HA history. A direct native
Pi listener is available for an isolated commissioning attempt and persists
credentials through HA's existing import service before delivering network data.

The subsequent exclusive ESP32 attempt completed provisioning, reconnected the
Mesh Proxy bearer in 3.47 seconds, and completed bindings in 7.44 seconds. The
verified configuration was imported through HA's existing admin service.
Normal HA on/off, brightness 128/220 and warm/cool 0/50/100 checks then passed;
HA's connection log confirmed ESP32 source 44:1D:64:F6:B5:FE. The latest node
primary address is 7907; the obsolete identity at 6122 is retained only as history.

The user's subsequent normal LED restart failed: ESP32 GATT connections
succeeded, but authenticated filtering using the saved network key timed out.
A fresh ESP32 radio capture contained four PB-GATT unprovisioned advertisements
and one unprovisioned PB-ADV beacon, with no Mesh Proxy advertisement. Thus
reloading HA did not recover the previous pairing. This does not distinguish a
missing device-specific commissioning step from a driver persistence fault.

An explicit operator recovery without another physical reset provisioned node
8162 and completed bindings in 7.13 seconds. The documented optional Tuya
publication setup command received no acknowledgement and is not an accepted
fix. HA entity availability returned. See
`reports/led-restart-failure-2026-10-14.json` for the bounded evidence.

No further HA restarts are authorized. LED restart recovery failed acceptance;
this release is not production accepted.

After that operator recovery, both ESPHome entry reload and Recover Bluetooth
Gateway passed. Normal HA on/off, brightness and relative white-temperature
control passed after each action. The recovery button briefly made the gateway
unavailable, then it reconnected automatically without unplugging its power.
`reports/gateway-recovery-live.json` records those checks. This verifies gateway
recovery with the LED powered continuously, not LED pairing retention.
