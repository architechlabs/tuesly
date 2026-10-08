# Tuesly

**Bluetooth Mesh for Home Assistant, by Architech Labs.**

Tuesly connects compatible Tuya/Telink Bluetooth Mesh devices through Home
Assistant's Bluetooth stack and active ESPHome proxies. It has its own Home
Assistant domain (`tuesly`), protocol library (`tuesly_mesh`), services, storage
namespace, setup screens, and bundled light/dark brand assets.

Version **0.1.1**. Home Assistant **2026.3 or later** is required for the bundled
local brand images. This is a development release; the branding and transport
changes do not establish complete SIG Mesh LED control or unlimited capacity.

## Install

1. Extract `dist/tuesly-0.1.1.zip` into your Home Assistant configuration directory.
   The resulting path must be `/config/custom_components/tuesly/manifest.json`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Tuesly**.
4. Register the active ESPHome receiver separately under the ESPHome integration.
   The gateway tested in this workspace is **Tuya BLE Proxy 01** at
   **192.168.20.181**, using its dedicated ESPHome API encryption key.

Tuesly's icon and logos live in `custom_components/tuesly/brand/`. Home Assistant
loads them locally; no external brand repository or CDN contribution is needed.
Refresh the browser after restarting if a placeholder is cached.

The GitHub repository URL and maintainer handles are not assumed. Hosted
documentation, issue tracker and codeowners can be supplied when an Architech
Labs repository is published. The local integration does not link to another
project's documentation, issues or update endpoint. `hacs.json` is prepared for
a future repository release; a ZIP alone is not a HACS custom repository.

## Device compatibility and commissioning

- **Telink lights/relays:** the bundled implementation supports its existing
  on/off and lighting commands for compatible device profiles.
- **SIG Mesh:** the bundled runtime has Generic OnOff commands, but new SIG
  setup now stops explicitly: existing-key import and verified lighting
  commissioning have not been implemented. It does not create a working SIG
  light by collecting a Bluetooth address alone. SIG LED
  brightness/temperature models still require implementation and verification
  against the device's Composition Data; selecting a Telink light does not add
  SIG lighting support.
- **Already paired devices:** mesh ownership and keys are required. Discovering
  the Proxy Service does not disclose its network/application/device keys.
  Commission a new mesh only when the device has intentionally been reset.
- **Capacity:** the tested Wi-Fi ESP32 has three concurrent GATT slots. Its
  target diagnostic address is not an allowlist. Larger installations need more
  receivers or a shared mesh controller implementation and verified relay support.

The tested driver **DC:23:52:81:60:BB** exposes standard SIG Mesh Proxy Service
`1828`, plus a vendor service with duplicate characteristic UUIDs. Tuesly keeps
the transport fixes that select characteristics inside `1828`, use HA-managed
connections during commissioning and runtime, and release failed connection
slots. Hardware transport was verified through the existing ESP32; no mesh
commands have been sent to this app-paired driver yet.

## Existing installations

The new `tuesly` domain creates a separate integration. Existing entries from a
previous integration are not silently renamed, and stored mesh keys are not
discarded or regenerated. Keep a Home Assistant backup and the existing mesh
keys before migrating device configuration. Disable the previous integration
while testing Tuesly to avoid competing connections to the same drivers.
Do not reset a working app-paired driver simply to change the integration name.

## Source layout

```text
tuesly/
  custom_components/tuesly/
    brand/                   local Home Assistant icons and logos
    lib/tuesly_mesh/          bundled protocol and transport implementation
    profiles/                device profile data
    translations/            setup and entity translations
    manifest.json            domain, version, requirements
  assets/                    SVG mark and light/dark preview
  tools/                     brand renderer and release packager
  tests/                     namespace, brand and transport regressions
  LICENSE
  THIRD_PARTY_NOTICES.md
  hacs.json
  project.json
```

For development, from the Tuesly project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/build_brand.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/package_release.py
```

The packager reads only this standalone source tree. It needs no external
repository checkout. The release contains the integration, its local brand
images and license notices; it does not contain ESP32 API keys, mesh credentials
or development environment files.

Validation on 2026-10-08: 25 namespace, branding, licensing, release, setup routing and simulated transport
checks passed; all Python source compiled; the complete standalone protocol
library imported and loaded its three bundled profiles. The logo was visually
reviewed in light and dark variants. Tuesly has not yet been installed in a live
Home Assistant instance; these checks do not replace HA setup or LED control tests.

## Setup diagnosis for the current SIG driver

The ESPHome proxy at **192.168.20.181** authenticates and reports active GATT;
the user also confirms it is connected in HA. It is not an HTTP bridge daemon
on port 8099. The driver **DC:23:52:81:60:BB** advertises SIG Mesh Proxy Service
1828 and is paired in Tuya Smart; the user has no export of its mesh keys.

In 0.1.0 the label "LED Light" selected Telink login and "via bridge" selected
the separate HTTP daemon route. Those paths do not control this SIG driver.
0.1.1 defaults to protocol detection, names the Telink/HTTP routes explicitly,
and prioritizes SIG services even when vendor UUIDs are also present. A known
SIG advertisement skips the Telink login entirely. Empty Telink credential
fields restore the documented defaults rather than sending empty credentials.

For this paired SIG driver the updated flow displays an explicit existing-key
and incomplete-controller blocker rather than hanging on the wrong handshake.
This fixes misleading setup routing; it does not claim to add LED control.
No factory reset, provisioning, key generation or driver command was performed.
The remaining work is mesh key access/commissioning, authenticated responses,
lighting model discovery, durable sequence management and verified LED controls.

## Attribution

Tuesly's product identity and new branding belong to Architech Labs. Modified
MIT-licensed implementation code retains its required copyright/permission
notice in `THIRD_PARTY_NOTICES.md`; rebranding does not remove that obligation.

## Licensing

Architech Labs-owned original contributions and artwork are reserved under the
rights notice in `LICENSE`; they are not offered under MIT. Permission to use,
modify or redistribute those portions must be granted separately in writing.
Third-party implementation code retains its original MIT terms and notices.

The current implementation contains substantial MIT-licensed code. This rights
notice does not turn that code into exclusively owned proprietary code or
prevent others from using the MIT portions independently. A version that does
not rely on those portions would require an independently implemented codebase
or appropriate alternative permissions from the relevant owners.

No customer licensing agreement has been drafted or published. Commercial
distribution terms should be reviewed before offering the product to customers.
