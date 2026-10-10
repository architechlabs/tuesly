# Tuesly

Bluetooth Mesh for Home Assistant, by **Architech Labs**. Version **0.2.7**.

Tuesly commissions supported Tuya SIG Mesh lights into an HA-owned mesh and
controls them through HA Bluetooth and active ESPHome proxies. The ESP32 provides
GATT transport; Tuesly owns the mesh protocol and keys. Add the ESP32 under
**ESPHome**, not as an HTTP bridge on port 8099.

See [the site guide](docs/SITE_INSTALLATION.md) for installation, commissioning,
controls, recovery, updates and acceptance. Extract `dist/tuesly-0.2.7.zip`, replace
`/config/custom_components/tuesly`, and restart HA after backing up.

## Controls and recovery

The light exposes on/off and brightness. Tunable white exposes **White temperature**:
**0% warm to 100% cool**, without per-fixture Kelvin labels. Drivers reporting valid
Kelvin limits also expose HA color temperature. Tuya's protocol scale does not
claim a fixture's physical Kelvin range.

**Reconfigure** retries model configuration using existing keys. After an
intentional physical reset, its explicit replacement option commissions again,
archives old credentials and preserves the HA entry/entity. A timeout alone is
not a reason to reset. Credentials are journaled before delivery and configuration
continues on a fresh Mesh Proxy connection within Tuya's deadline. The provisioning
notification descriptor is cleared before that handoff.

## Reliability changes

- Standard service-qualified GATT handles avoid duplicate vendor UUIDs.
- Authenticated proxy filter and model acknowledgements precede availability.
- Tuya vendor and advertised application models are bound explicitly.
- Shared persistent mesh bearer, per-node device keys and replay windows.
- Serialized radio work; user controls precede queued background polls.
- Slider bursts coalesce; pending controls and retries are bounded.
- Disconnects abort pending replies and permit reconnection.
- Pre-delivery provisioning interruptions retry once with fresh ECDH material;
  possible key delivery prevents automatic reprovisioning.
- Radio ownership and scan registrations are released on failed setup and cleanup.
- One reachable, saved node can provide a fallback bearer for another node in
  the same mesh. Actual relay coverage still needs installation testing.
- Verified temperature profiles are cached.
- HA Store API saves keys, addresses and sequence reservations.
- Diagnostics expose the failing stage without keys.

Firmware stays in `mopeka/firmware-esp32/`: `device-tuya-dedicated.yaml` is the
bench board; `device-tuesly-site.yaml` is reusable with no fixed driver MAC.
Firmware 1.1.4 uses a 16KB TCP send buffer, API queue 32, active scanning/GATT,
three slots and Wi-Fi power saving disabled.

## Validation status

Software tests use real cryptography against simulated nodes, with simulated HA
and radio boundaries. Earlier hardware tests confirmed on/off, dimming and
warm/cool commands, but subsequent power-cycle recovery failed. **0.2.7 is an
offline-tested validation candidate**, pending hardware acceptance. It has not
been deployed while the gateway and fixtures are away from the network.

See [the validation record](docs/OFFLINE_VALIDATION_0.2.7.md) for the observed
failures, research, fixes and reconnect procedure. Keep the live HA mesh Store:
the old private bench export predates later HA commissioning and is blocked
from being imported over the newer credentials.

A 100-light physical fleet, long soak, relay coverage and firmware diversity have
not been validated. Multiple lighting channels, RGB, mesh groups, automatic IV
Update and key refresh are not implemented. Sequence exhaustion fails closed.
Smart Life mesh keys are not automatically retrieved. The private operator import
service recovers completed commissioning only into the same HA-owned network.

Keep HA backups private. Never restore an older journal onto an active mesh or
clone it to a second running HA controller: sequence rollback is unsafe. Removing
a Tuesly entry preserves its journal for re-adding without silently replacing keys.

## Source layout

- `mesh_store.py`: journal and sequence leases.
- `sig_commission.py`: commissioning and recovery.
- `sig_controller.py`, `radio.py`: sessions and scheduling.
- `sig_light.py`, `number.py`: HA controls.
- `lib/tuesly_mesh/`: protocol, bearer and cryptography.
- `brand/`: local icons/logos; `docs/devices/H12X2.md`: measured device evidence.
- `tools/`: packaging/bench diagnostics; `tests/`: regressions; `reports/`: evidence.

Architech Labs-owned contributions have reserved rights. Third-party notices
remain in `LICENSE` and `THIRD_PARTY_NOTICES.md`.
