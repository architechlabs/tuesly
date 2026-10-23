# Tuesly Automatic Recovery

Runs on the HAOS Pi independently of the laptop and HA Core's Python process.
The ESP32 remains the BLE transport; this app performs mesh commissioning.
Starting or updating this app does not restart Home Assistant.

## Configuration

Under Settings → Apps → Tuesly Automatic Recovery → Configuration:

- Set the HA URL and a dedicated administrator token. Tokens are private options.
- Set the ESPHome proxy IP, API encryption key, provider entry ID and Bluetooth source.
- Select a Bluetooth diagnostics entry on this HA instance.
- Enroll each intended device with its MAC, measured provisioning UUID, existing
  Tuesly entry ID and light entity ID. New nearby devices are not enrolled automatically.
- Enable recovery, Start on boot and Watchdog.

The installed bench enrollment is DC:23:52:81:60:BB on proxy 192.168.20.181.
View progress under this app's Log tab. `/data/status.json` records its current phase.

## Automatic flow

1. Subscribe to HA's live `bluetooth/subscribe_advertisements` websocket API;
   no second ESPHome BLE subscriber takes over the scanner. Automatically
   reconnect this stream if it drops. Diagnostics are a fallback/health snapshot.
2. Require the enrolled light to be unavailable and one complete raw unprovisioned
   packet with its exact UUID, received within ten seconds. Cached UUIDs and Tuya
   vendor frames do not qualify.
   Capture this event even while HA displays its previous successful state; keep
   it for at most 120 seconds to cover HA's polling and bounded session timeout.
   Consume it on an attempt. An available light is never replaced solely on this evidence.
3. Serialize recovery, pause the target and proxy entry, then own the ESP32 GATT
   transport temporarily. Other devices using this proxy can briefly lose reception.
4. For that confirmed unprovisioned event, follow the working direct PB-GATT
   commissioning sequence without an extra proxy authentication session first.
5. Provision a fresh identity. Save new credentials
   privately and through HA's existing admin service before sending network data.
   Verify the peer's provisioning notification descriptor is disabled before
   reconnecting to the Mesh Proxy service.
6. Bind the same models as the working manual sequence, read real state, save the
   verified configuration through HA, and restore both original entry flags.
7. Confirm normal HA entity availability. Future commands use the existing HA entities.
   If provisioning completed but the app's binding deadline expired, restore HA
   with the journaled credentials and allow its normal controller to finish setup.
   Only an available normal HA entity counts as recovery.
8. If the enrolled journal still records `configuration_pending` and the light
   remains unavailable, retry configuration through the ESP32 with the existing
   keys and address after a fresh connectable Mesh Proxy service packet. Failed
   saved-key authentication never causes replacement without unprovisioned proof.
   Mesh beacons alone do not trigger repeated gateway interruptions.

Crash recovery restores paused entries using a durable transaction record. The
protocol sender uses a separate address and durable sequence leases; it does not
reuse HA's sender counters. Keep app backups private and never run cloned copies.
During radio ownership the app also subscribes to ESPHome states. This maintains
the firmware 1.1.8 readiness watchdog while the usual HA subscriber is intentionally
paused, preventing a watchdog reboot halfway through a maintenance transaction.

## Limits

This is a bounded recovery workaround for pairing loss, not a driver flash fix.
Detection includes HA's time to mark the light unavailable; instant recovery is
not promised. Device UUID/MAC matching is not cryptographic identity authentication
for a reset No-OOB device.

The current integration reserves 255 fresh unicast addresses per replacement.
This app never reuses an old address, never changes the whole site's network key,
and stops before capacity is exhausted. Failed attempts use an exponential
30–300 second cooldown; a successful recovery resets that backoff. Successful
power cycles do not consume an hourly or daily attempt quota. Transport failures
retain their stage and error type for diagnosis. Recovery can take longer when
the gateway is unavailable or HA has not yet marked the light unavailable.
Fresh unprovisioned proof can admit a new attempt fifteen seconds after the last
failure, so a later physical restart does not wait out an old five-minute cooldown.
A 100-light site with repeated pairing loss is not accepted with this allocator.

The app reads only the specifically authorized custom mesh journal file from the
read-only HA configuration mount. It never writes HA's internal storage files.
HA remains the authority for imported device identities. The dedicated token has
an expiry and must be replaced before then. Disable `enabled` to stop automatic
commissioning; stop the app before running manual raw ESP32 diagnostics.
