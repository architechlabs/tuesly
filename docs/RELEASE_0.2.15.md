# 0.2.15 — power-state authority and Tuya power-off memory

Fix: Lightness status no longer changes OnOff. Some drivers report a last
nonzero brightness while switched off; merging that value as `on=True` caused
UI oscillation against explicit OnOff replies.

The live driver's composition has Tuya vendor lighting models but does not
advertise Generic Power OnOff. 0.2.14 therefore never configured its restore
setting. Add the Tuya-documented vendor DP 33 path (mode 1: previous state),
using compressed DP encoding, acknowledged writes and an independent readback.
Raw DP custom-state bytes are preserved. Support is shown as unconfirmed until
the device actually responds; temporary failure is retried at most once per
minute. No startup on/off commands are sent to simulate persistence.

Power-on Off remains available for standard Generic OnPowerUp devices; the
Tuya DP33 path exposes Restore previous and device defaults only. It does not
guess a custom-state or DND payload to implement forced Off.

Driver-level readback and a physical mains cycle remain necessary before
certifying persistent state or flash-free startup. No claim is made that a
syntax check verifies hardware behavior. HA Core restart is required to load
changed Python code; do not restart HA without current authorization.

References:

- https://developer.tuya.com/en/docs/iot-device-dev/bluetooth-sigmesh-lighting-sdkdemo-instructions?id=Ka5e0524ewo4n
- https://developer.tuya.com/en/docs/iot-device-dev/tuya-sigmesh-device-vendor-model-access-standard?id=K9pikwhoo3gux
