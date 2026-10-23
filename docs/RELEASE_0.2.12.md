# Tuesly 0.2.12 connection retry candidate

An initial ESP32 GATT connection error was observed on 2026-10-13 at
18:59:03, before provisioning data delivery. The initial connection was
outside the provisioner's retry block. It now gets one additional bounded
attempt for a wrapped transient Bluetooth/OS/timeout error. Nontransient
service/protocol/storage errors are not retried by this new path, and
possible network-data delivery still prevents repeating provisioning.

The HA-side listener starts pairing from a Bluetooth event; a chat reply
does not start pairing. The operator helper can rearm discovery after a
device-not-found timeout, but never repeats a failed provisioning exchange.

The connection helper no longer sleeps after its final failed attempt;
the outer retry retains a one-second connection-slot release delay.

The targeted provisioning suite passed 15 tests; the full suite passed 117.
Live commissioning and
normal power-cycle recovery must still pass before production acceptance.
Firmware 1.1.7 remains installed; this change requires no firmware rebuild.
