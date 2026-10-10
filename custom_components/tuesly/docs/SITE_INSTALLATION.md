# Tuesly site installation and acceptance

Validation candidate: integration **0.2.7**, ESP32 firmware **1.1.4**.
Complete the acceptance checks before handing over a site.

## 1. Prepare and connect the proxy

Give every proxy stable power, good Wi-Fi and a DHCP reservation. Allow HA to
reach TCP 6053 across the site's subnets. Measure coverage with fixtures installed;
avoid putting the ESP32 in electrical enclosures or against network equipment.

Use `mopeka/firmware-esp32/device-tuesly-site.yaml`. It has no fixture MAC and adds
a MAC suffix to its node name. Generate a unique `api_encryption_key` and
`wifi_fallback_password` in the board's local `secrets.yaml`. Do not reuse customer
credentials across sites. The bench board uses the separate dedicated profile.

From the firmware folder with the virtual environment activated:

```powershell
python -m esphome config device-tuesly-site.yaml
python -m esphome compile device-tuesly-site.yaml
python -m esphome upload device-tuesly-site.yaml --device COM8
```

Use the actual board serial port. First boot exposes the protected setup AP;
enter site Wi-Fi through the captive portal. Credentials persist in NVS.

In **HA → Settings → Devices & services → Add integration → ESPHome**, enter the
proxy IP and API encryption key. Confirm it is connected and diagnostics update.
In the ESPHome entry's options, select **Active** Bluetooth scanning for setup.
Active scanning and active GATT connections are separate settings. Ping alone
does not prove GATT works. Do not enter its IP into an HTTP bridge on port 8099.

## 2. Install or update Tuesly

1. Make a full HA backup and retain the currently installed component/package.
2. Extract `dist/tuesly-0.2.7.zip`.
3. Copy its `custom_components/tuesly` folder to `/config/custom_components/tuesly`.
4. Restart HA once, refresh the browser and confirm the integration version.
5. Confirm the ESPHome proxy remains connected.

Updates preserve mesh storage. Do not edit HA internal files manually. Roll back
component code if needed; do not replace the journal with older sequence state.

## 3. Commission fixtures

Commission one fixture at a time. Record its Bluetooth address, room/fixture name,
HA entity and acceptance result. Kelvin labels are not required.

1. Open **Add integration → Tuesly**, enter the Bluetooth address and select
   **Detect protocol** before performing the physical reset.
2. Intentionally remove the light from its previous app mesh, if applicable.
3. Use the manufacturer's reset procedure and verify it is blinking.
4. Submit immediately and proceed to the SIG commissioning screen.
5. Confirm the physical reset and submit while the pairing window is open.
6. Keep power steady throughout provisioning and application/model binding.
7. Verify physical on/off and dimming from the HA light entity.
8. Test tunable white with **White temperature** at 0%, 50% and 100%.
9. Name the device, assign an area and add its controls to a dashboard.

Close phone Bluetooth apps and competing controllers during commissioning.
Tuesly cannot use an existing Smart Life mesh from a MAC address alone. Replacing
pairing intentionally transfers mesh ownership; Smart Life control then stops.
The setup reads actual models and does not invent tunable-white capability.

## 4. Everyday use

Use the light for on/off and brightness. **White temperature** means 0% warm and
100% cool; changing it alone preserves on/off. A valid driver-reported Kelvin
range also enables HA's normal color-temperature control. The percentage scale
does not claim an optically measured Kelvin range.

Automations use `light.turn_on`, `light.turn_off` and `number.set_value` with the
site's actual entities. Slider bursts coalesce to the newest setting. Confirmed
state comes from replies; a failed command does not create a false success.
Start with small batches and measure scene latency. Mesh group commands and
synchronized 100-light scenes are not implemented.

## 5. Recovery

Confirm the proxy is connected under ESPHome. Check its signal/uptime/API response,
driver power/range, and any phone holding the BLE link. Let retries run and download
Tuesly diagnostics for the failing stage.

Open **Tuesly → light entry ⋮ → Reconfigure**:

- Leave both boxes unchecked to retry model configuration using saved keys.
- Only after intentionally factory-resetting this driver, check both replacement
  boxes and submit while it is blinking. Old credentials are archived, a new mesh
  address is reserved, and the HA device/entity is retained.

Do not reset for a generic timeout or reset a whole site at once. If provisioning
fails after credentials were saved, retain the backup/logs and resume configuration.
Do not discard uncertain credentials or silently provision repeatedly.

Tuesly retries one interrupted provisioning exchange only before any network
data has been attempted. After possible delivery, it retains the credentials
and resumes configuration. Do not open/close USB serial monitors, run a second
raw proxy client, or reload the proxy while commissioning or validating control.
Serial control signals can restart some development boards; another raw client
can take over the proxy's Bluetooth subscription.

If direct BLE reception of a saved fixture is unavailable, Tuesly can try one
reachable saved node in the same mesh. It authenticates that proxy and keeps
the destination fixture's own device key. This depends on real mesh relaying;
it does not make a powered-off fixture controllable.

## 6. Acceptance and handover

Record versions, timestamps, durations and physical results. These are required
checks, not claims that the current bench has passed them:

| Check | Required result |
|---|---|
| Commissioning | Confirmed application/model bindings |
| Controls | Physical on/off, dimming and warm/cool match HA |
| Driver normal power cycle | Same entity recovers automatically |
| Proxy unplug/replug | API/control recover without resetting lights |
| HA restart | Saved keys reused; accepted fixtures recover |
| Network interruption | Availability reflects outage; control recovers |
| Slider bursts | Latest value wins; no growing retry backlog |
| Multiple fixtures | Distinct addresses/entities; correct individual control |
| Installed coverage | Every fixture tested in its final position |
| Soak | At least 24 hours without unexplained loss of control |

For a large site, validate a pilot batch and expand in measured stages. Three
GATT slots mean simultaneous connections, not a three-light inventory limit.
Same-network nodes can share a connected bearer. Actual relaying, RF coverage
and 100 physical nodes remain unvalidated here.

Deliver the inventory, packages/versions, redacted acceptance report, private
site credentials and HA backup. Keep keys out of shared reports.

## Lifecycle limits

Automatic IV Update/key refresh are not implemented. Sequence exhaustion fails
closed. Do not restore an older journal onto an active mesh or run cloned state
in a second HA controller: nonce reuse/replay rollback is unsupported. Fleet
longevity and restoration onto a running mesh require further validation.

## References

- [ESPHome proxy](https://esphome.io/components/bluetooth_proxy/)
- [ESPHome TCP send buffer](https://esphome.io/components/network/)
- [Tuya pairing/configuration deadline](https://developer.tuya.com/en/docs/iot-device-dev/bluetooth_software_map_mesh_provision?id=Kd5wkuunhsjtq)
- [Tuya lighting mappings](https://developer.tuya.com/en/docs/iot-device-dev/bluetooth_software_map_mesh_data_control?id=Kd5wq9xmg0u3i)
