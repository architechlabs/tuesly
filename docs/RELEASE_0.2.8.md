# Tuesly 0.2.8

Superseded by 0.2.10. The high-level CCCD writes described below are incompatible
with Bleak 3; these historical simulated tests did not detect that guard.

Fresh provisioning and mesh proxy connections explicitly enable notifications on
the standard service's CCCD after registering their callback. This follows the
ESPHome Bluetooth connection API contract and avoids dependence on a backend
automatically writing the descriptor. Duplicate vendor UUIDs remain excluded.
Descriptor failures release the connection rather than leaving a stuck slot.

Software validation: 101 tests passed. This is a recovery candidate; gateway
restart, HA reload, physical control and a site soak must pass before deployment
is considered accepted. Firmware remains 1.1.4 in this release.

Live recovery tools use Home Assistant public APIs and do not open USB serial.
Existing mesh keys are resumed; a restart is not a reason to reset/reprovision a
driver. Historical private operator exports must not overwrite newer HA keys.
