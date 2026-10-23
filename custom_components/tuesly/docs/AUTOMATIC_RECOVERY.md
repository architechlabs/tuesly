# Automatic recovery service

**Implemented on the bench HAOS Pi: app 0.1.11.** Integration
0.2.13 and ESP32 firmware 1.1.8 remain in place. HA Core was not restarted.

The service watches continuously and invokes the working manual ESP32 sequence
for the explicitly enrolled driver. Fresh, exact unprovisioned UUID evidence and
an unavailable enrolled HA light trigger the direct PB-GATT sequence. It persists
new credentials through HA before delivery, binds the
models, and restores the existing HA entity. Chat replies and laptop uptime are
not triggers or runtime dependencies.

Live health verified: enabled, Start on boot, Watchdog, readable mesh journal,
valid HA API access, and an actively scanning/connectable ESP32. Seventeen recovery
regression tests passed; sixteen real-cryptography provisioning simulation tests
passed previously. On 2026-10-15 the running app automatically recovered the
unavailable driver, commissioned and bound it through the ESP32, and restored the
normal HA light and temperature entities. The successful attempt took about 66
seconds; earlier transport attempts failed and retried. HA on/off, brightness
128/220 and temperature 0/50/100 readbacks passed afterward. The user's next
ordinary OFF-for-ten-seconds → ON cycle also recovered without a manual pairing
command or entry reload. That attempt hit the app's model-binding deadline; HA
finished configuration using the already imported credentials. All control
readbacks passed again. App 0.1.7 recognizes that HA handoff as recovery and
retains an exact startup event for up to 120 seconds while HA detects failure.
The next clean physical restart caught the startup packet and completed
provisioning, but model binding and HA configuration did not finish. App 0.1.8
adds automatic resumption of a journaled `configuration_pending` node using its
existing keys; this path never replaces credentials on authentication failure.
The resumed attempt exposed a gateway watchdog conflict: firmware 1.1.8 can reboot
90 seconds after an HA connection if HA is intentionally paused by the app.
App 0.1.9 subscribes to ESPHome entity states during its maintenance connection,
keeping that watchdog's API readiness condition true without a firmware rebuild.
App 0.1.10 also verifies that the peer's provisioning notification descriptor is
zero before reconnecting, matching the operator's successful read barrier.
Fresh unprovisioned evidence may retry after fifteen seconds instead of waiting
out a cooldown caused by an earlier missing startup window.
App 0.1.11 receives HA's live `bluetooth/subscribe_advertisements` websocket stream.
It retains each exact fresh raw startup packet even when a later vendor packet
overwrites the diagnostics snapshot. A read-only live contract check accepted the
subscription and received 105 events (104 with raw packets) in ten seconds.
The app still performs GATT exclusively through its configured ESP32. HA's manager
may supply the discovery packet through a different HA-managed scanner.

After the user's next normal cycle, HA completed configuration using primary
8927 without another credential import or replacement. The journal now records
`ready`, binding revision 3 and enabled GATT Proxy. Normal HA on/off, brightness
128/220 and white 0/50/100 readbacks passed. ESP32 reported the target's allocated
GATT slot while native BlueZ reported the target disconnected. Recovery was slow;
it does not establish an acceptable site recovery deadline. A clean restart from
this fully configured state is being checked separately.
With app 0.1.11 unchanged, a subsequent observed unavailable-to-online transition
recovered itself in approximately 43 seconds. All HA control readbacks passed
again, with the ESP32 target slot allocated and native BlueZ disconnected. No
new commissioning, manual reload or reset was performed for that return. The
operator subsequently confirmed performing the requested normal power cycle and
that Tuesly still worked. A final check confirmed the same primary 8927, ready
bindings and enabled GATT Proxy, with gateway and light online. This is one clean
physical restart pass on the final build. Repeated recovery and site-scale
reliability remain unaccepted.

User page: **Settings → Apps → Tuesly Automatic Recovery → Log**.
Source and configuration: `addons/tuesly_recovery/`.
Detailed flow and limits: `addons/tuesly_recovery/DOCS.md`.
Health evidence: `reports/automatic-recovery-service.json`.

This is bounded replacement commissioning for lost pairing. It does not repair
the driver's flash persistence. The installed HA allocator consumes 255 fresh
addresses per replacement. Failures back off for 30–300 seconds; successful
recoveries do not consume an hourly/daily attempt quota. Exhaustion checks prevent
address reuse, so repeated replacement is finite. A 100-light fleet with repeated
pairing loss remains unaccepted.
Reserve the proxy's IP in the router or update the app's proxy address if it changes.
Stop this app before manual raw ESP32 diagnostics, then restart it afterward.
