# Changelog

## 0.2.3 — 2026-10-09

- Correct CTL temperature-range requests to use the CTL Server (1303) element, separate from Temperature Server (1306).
- Bind CTL Server and migrate already-ready nodes without regenerating their keys.
- Use mandatory-MTU Proxy SAR fragments without reading a backend default MTU.
- Request fresh discovery from HA AUTO scanners and register active-scan interest for the node. Explicit Passive selections remain user-controlled.
- Remove deprecated advanced-options property calls from setup/discovery.
- 60 software regressions pass; hardware control still requires HA-side validation.

## 0.2.2 — 2026-10-08

- Expose authored setup validation messages and the exact operation stage in HA retry errors.
- Record non-secret Composition model identifiers for hardware diagnosis.
- Distinguish normal session cleanup from unexpected Bluetooth disconnections.
- Retain all timeout fixes from 0.2.1.
- Root cause of the hardware ValueError remains unconfirmed until live detailed errors are available.

## 0.2.1 — 2026-10-08

- Bound whole mesh sessions to 50 seconds and connection establishment to 35 seconds, including managed-connector retries.
- Convert reachability timeouts to retryable HA setup failures and release connections on cancellation.
- Report the failed provisioning stage without exposing keys.
- Added timeout cleanup and shared-radio deadline regressions.
- Live HA evidence: the ESPHome proxy was unavailable; only hci0 was registered. The board itself authenticated at 192.168.20.181 and reported active GATT. HA receiver reconnection remains required.

## 0.2.0 — 2026-10-08

- Added explicit SIG lighting commissioning through HA Bluetooth/ESPHome.
- Journal mesh credentials before provisioning data is delivered; retain partially configured nodes.
- Share network keys, non-overlapping node ranges and durable sequence leases across drivers.
- Configure the GATT proxy filter with authenticated status and handle Proxy SAR.
- Discover and bind actual OnOff, Lightness and CTL Temperature model elements.
- Added HA light entity with acknowledged controls, queried Kelvin limits, polling and connection cleanup.
- Fixed PB-GATT reply loss during fragmented sends and full segmented SeqAuth reconstruction.
- Added persisted replay windows and source/parameter validation for configuration replies.
- 52 software checks pass, including a real cryptographic simulated provisioning exchange and encrypted controller/light traffic. Hardware commissioning/control and HAOS installation remain to be validated.

## Controller preparation

- Identified the photographed H12X2 driver family and recorded label/Bluetooth
  evidence separately from unverified model and Kelvin-range assumptions.
- Implemented standard SIG Light Lightness and CTL Temperature command/status
  codecs and bounded Composition element/model parsing, including secondary
  element addresses and vendor/SIG model separation.
- Added wire vectors, signed-value, truncation, unsupported-model and address
  range tests; 33 checks pass. These helpers do not yet enable SIG commissioning
  or an HA light entity. The paired driver's keys and controls remain untouched.

## 0.1.1 — 2026-10-08

- Default manual setup to protocol detection through HA Bluetooth/ESPHome.
- Prefer SIG Mesh services over vendor services and never send Telink login
  just because an app-paired SIG driver was entered as "LED Light".
- Name Telink and HTTP daemon routes explicitly; hide HTTP bridge choices
  outside advanced mode and explain why an ESP32 proxy IP is not an HTTP bridge.
- Restore defaults when Telink credential fields are submitted empty.
- Stop SIG setup with an explicit mesh-key/incomplete-controller reason instead
  of attempting provisioning or creating an unverified working light entry.
- Route discovery confirmations through the same SIG guard.
- Added setup routing regressions; 25 software checks passed. Existing SIG LED
  control remains unimplemented and no driver commands or reset were performed.

## 0.1.0 — 2026-10-08

- Reserved rights for Architech Labs-owned contributions and artwork instead of
  granting MIT permissions for them; retained the required third-party MIT terms.
- Introduced Tuesly by Architech Labs with domain `tuesly` and bundled library
  `tuesly_mesh`; namespaced services, registry and sequence storage separately.
- Added an original mesh T mark, SVG source, wordmark, and eight local HA brand
  images for light/dark mode and standard/high resolution.
- Updated setup text to explain active proxies, protocol selection and existing
  mesh ownership. Removed timeout advice that automatically recommends resets.
- Removed unrelated owner, support and repository links from the manifest.
- Preserved managed SIG proxy connections, connection cleanup, and characteristic
  selection within standard Mesh Proxy Service for duplicate vendor UUIDs.
- Bundled device profiles at the library's runtime lookup location.
- Created an independent release packager and namespace/brand regression checks.
- Retained required third-party MIT notices in the distributed package.
