# Tuesly

Bluetooth Mesh for Home Assistant, by **Architech Labs**. Version **0.2.3**.

This development release adds an HA-owned SIG white-light controller using HA
Bluetooth and an active ESPHome proxy. Software checks pass; live HAOS installation
and control of the user's H12X2 driver remain to be validated.

## Install in HAOS

1. Back up HA. Extract `dist/tuesly-0.2.3.zip`.
2. Replace `/config/custom_components/tuesly` with the ZIP's
   `custom_components/tuesly` folder. Avoid an extra nested `custom_components` folder.
3. Restart Home Assistant, then refresh the browser.
4. Confirm **Settings → Devices & services → ESPHome → Tuya BLE Proxy 01**
   is connected. Its current firmware at `192.168.20.181` already supports this path.
5. Open **Settings → Devices & services → Add integration → Tuesly**.
   Enter `DC:23:52:81:60:BB`, leave **Detect protocol** selected, and submit.
6. Read **Commission SIG Mesh light**. This creates a new HA-owned mesh and
   requires intentionally replacing the driver's existing Tuya Smart pairing.
   Tuya Smart control will stop. Use the manufacturer's physical reset instructions;
   no reset sequence is inferred from the photograph. Only check the confirmation
   once the driver is reset and in pairing mode near the ESP32.
7. Submit. Provisioning can take up to 90 seconds plus reconnect. HA discovers
   and binds the actual models, then creates a light entity after confirmed replies.

Do not enter the ESP32 IP into an HTTP bridge dialog on port 8099. This controller
uses HA's ESPHome/Bluetooth transport. Disable competing integrations targeting
this driver while commissioning. No driver has been reset or commissioned by the
software work performed so far.

## Implemented SIG controller

- No-OOB PB-GATT provisioning using P-256 ECDH, CMAC confirmation and CCM data.
- Shared network/application keys and non-overlapping reserved node ranges.
- Device keys journaled before provisioning data is handed to the node.
- Pending configuration retained and resumed using saved credentials.
- Shared durable sequence leases: save before transmission, skip unused leases
  after restart, never wrap exhausted counters.
- Authenticated proxy filter configuration and MTU-aware Proxy SAR.
- Full SeqAuth for segmented replies, segment acknowledgements and persistent
  receive replay windows.
- Composition Page 0 discovery and application-key/model binding at actual
  OnOff (1000), Lightness (1300) and CTL Temperature (1306) and CTL Server (1303) element addresses. Temperature-range
  queries go to CTL Server; temperature control goes to Temperature Server.
- HA light controls with acknowledged responses, actual reported Kelvin limits,
  confirmed state, 30-second polling and connection cleanup after each session.
- Private mesh storage, no keys in config-entry data or diagnostics.

Existing Telink profiles remain available through explicitly named routes.
Existing Tuya-owned mesh key import is not implemented.

## Recovery and capacity

Keep `/config/.storage/tuesly.mesh` in HA backups and treat it as private. It
contains keys, addresses and sequence/replay state. Removing an integration entry
preserves these credentials. Re-add the same MAC to resume configuration without
provisioning again. Do not reset a Tuesly-commissioned node as a troubleshooting
shortcut: a reset node cannot authenticate with its old device key.

If HA says **Failed setup, will retry**, inspect **Settings → System → Logs**;
check driver power, receiver connection and range. Preserve storage and logs for
uncertain provisioning outcomes, including failure after journaling but before
network-data delivery. Do not overwrite its device key automatically.

Multiple drivers share a mesh and sequence allocator. Operations are serialized,
opening the GATT proxy on each target MAC and releasing it afterward. The ESP32
has three GATT slots; this does not mean three drivers must remain connected.
The initial supported topology requires each driver in receiver range. Unlimited
capacity, relay routing through another node, groups and multiple lighting
channels are not claimed. Multi-driver load and soak validation are still needed.

Automatic IV Update and key refresh are not implemented. Sequence exhaustion
fails closed and requires a proper IV Update implementation. Do not restore older
mesh storage onto an active mesh, or run two HA instances with identical controller
state: sequence/replay rollback is unsupported. Vendor-only lighting requires a
verified profile.

## Software validation and hardware acceptance

60 checks pass, including real cryptographic simulated provisioning and encrypted
proxy/configuration/light traffic, secondary-element binding, fragmented fast
replies, crash-safe sequence reservations, storage failures and replay rejection.
HA framework boundaries and hardware transport are simulated in these tests.

Before calling this production ready, validate on HAOS: commissioning this H12X2,
on/off, brightness, warm/cool control, HA restart, driver/receiver power cycles,
out-of-range recovery and sustained use with multiple drivers. Record the actual
Composition Data and Kelvin limits. No H12X2-specific firmware compatibility claim
is established by synthetic tests.

## Source layout

`custom_components/tuesly/mesh_store.py` owns storage;
`sig_commission.py` implements the wizard;
`sig_controller.py` implements configuration and commands;
`sig_light.py` exposes the HA entity;
`lib/tuesly_mesh/` provides the protocol and crypto;
`brand/` contains original local light/dark icons and logos.
`docs/devices/H12X2.md` records the label/Bluetooth evidence.

Development: install `requirements-dev.txt`, run
`python -m unittest discover -s tests -v`, then
`python tools/package_release.py`. HA 2026.3+ supports the local brand assets.

## Ownership and references

Architech Labs reserves rights in its original contributions and branding under
`LICENSE`. Required third-party MIT rights and attribution remain in
`THIRD_PARTY_NOTICES.md`; those inherited portions are not exclusive. Releases
are built from this standalone source tree and contain no firmware secrets.

- [Bluetooth Mesh Protocol](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/MshPRT_v1.1/out/en/index-en.html)
- [Tuya SIG lighting models](https://developer.tuya.com/en/docs/iot-device-dev/tuya-sigmesh-light-access-standard?id=K9pieafepp3q7)
- [HA Bluetooth API](https://developers.home-assistant.io/docs/core/bluetooth/api/)
