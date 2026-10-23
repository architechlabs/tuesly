# Tuesly 0.2.9

Superseded by 0.2.10, which corrects the inherited high-level CCCD writes for Bleak 3.

Replacement commissioning waits for a fresh provisioning advertisement through
Home Assistant's existing active Bluetooth callback. It does not require disabling
the gateway or transferring its Bluetooth subscription to a diagnostic client.
An operator readiness event is emitted after registration; stale discovery is
ignored, and the callback is removed on success, timeout or cancellation.

Explicit notification CCCD setup from 0.2.8 is retained for pairing and control.
104 software tests passed; the final freshness-clock adjustment also passed the
three discovery tests. Hardware commissioning and recovery are still pending.

Firmware 1.1.5 adds recovery after the final API client disconnects, a diagnostic
Bluetooth recovery button, a 30-second scan cycle, and a five-minute API disconnect
reboot. Both configurations validate. These mechanisms are recovery safeguards;
they are not evidence that a complete installation has passed its soak test.
