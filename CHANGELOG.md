# Changelog

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
