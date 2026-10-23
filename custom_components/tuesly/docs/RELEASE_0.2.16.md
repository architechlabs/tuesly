# 0.2.16 — correct the Tuya power policy

This corrects 0.2.15's DP33 raw schema. Tuya specifies a 12-byte value:
version (0), mode, then H/S/V/brightness/temperature as five two-byte fields.
The previous implementation incorrectly used byte 0 as mode. A write could
therefore change the version rather than enable memory. The new implementation
requires the documented version/length and preserves the version and all five
lighting fields while changing only byte 1.

Restore previous also enables DP34 (Do Not Disturb). Tuya documents this as
preserving app-switched-off behavior across a mains cycle. Explicit device
defaults disable DND. Both settings require acknowledged writes and independent
readback; no boot-time on/off replay is used. Replies can arrive in separate
DATA messages and are accumulated within the same bounded request.

Tuya vendor group replies are admitted temporarily only while a matching
enrolled source has a pending DATA request. Application-key decryption and
persisted replay checks remain enforced. Temporary destinations are removed
when the request finishes. Existing group publication settings are preserved.

Syntax/package checks do not certify driver persistence or flash-free startup.
Those require confirmed live readback followed by a physical mains cycle. This
release requires loading the updated Python modules; respect the user's
prohibition against initiating HA restarts without permission.

Sources:

- [DP33 version/mode layout and DP34 behavior](https://developer.tuya.com/en/docs/iot/product-function-definition?id=K9s9rhj576ypf)
- [Tuya Mesh vendor wire encoding](https://developer.tuya.com/en/docs/iot-device-dev/tuya-sigmesh-device-vendor-model-access-standard?id=K9pikwhoo3gux)
- [Tuya report-group routing](https://developer.tuya.com/en/docs/iot-device-dev/bluetooth_software_mesh?id=Kcy65o1aiv76y)
