# 0.2.17 — independently configure power-off memory and DND

Physical feedback after 0.2.16: white temperature survived mains cycling,
but a light switched Off in HA still started On. A combined DP33/DP34 echo
was therefore insufficient evidence that both settings took effect.

The isolated ESP32 probe subsequently sent DP34 alone:

- WRITE `c9 d0 07 01 22 01 01`
- DATA acknowledgement `01 22 01 01`
- Separate READ `cc d0 07 01 01 22`
- DATA readback `01 22 01 01`
- Generic OnOff Set Off then returned OnOff Status `00`.

0.2.17 queries, writes, and independently reads each DP separately. DP33
retains its documented version and custom fields. DP34 uses a short standalone
message, independent of the segmented RAW memory message. The code only marks
native power-on behavior confirmed after both independent readbacks match.

If a DP query times out, first prove the application bearer with an ordinary
OnOff read before initializing that setting. Each request is bounded at three
seconds, within the existing optional-preference budget; failure leaves normal
controls available and the preference unconfirmed. No reconnect command
replays an On/Off state after startup. No provisioning credentials change.

The user confirmed one normal mains cycle after the separate DP34 command:
"Stayed off, no flash". This verifies native Off retention on the target driver
for that cycle; temperature retention was separately confirmed earlier. The
new automatic 0.2.17 path is staged and still requires activation and its own
acceptance check. This is not fleet-wide or long-duration validation.

Temperature handling and the status-authority fix remain unchanged: Lightness
cannot override explicit Generic OnOff state. No HA restart is performed by
the deployment helper.

Sources:

- [Tuya DP33 structure and DP34 semantics](https://developer.tuya.com/en/docs/iot/product-function-definition?id=K9s9rhj576ypf)
- [Tuya compact vendor wire protocol](https://developer.tuya.com/en/docs/iot-device-dev/tuya-sigmesh-device-vendor-model-access-standard?id=K9pikwhoo3gux)
