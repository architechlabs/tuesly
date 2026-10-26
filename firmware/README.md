# Tuesly proxy firmware

This image is the ESP32 Bluetooth radio for Tuesly. It scans, connects, and
forwards GATT. Tuesly owns mesh keys and light commands. No driver MAC, mesh
key, or site Wi-Fi password is compiled in.

The live board that is already installed can keep running its current image.
Flash this build only onto a board you mean to use as a Tuesly proxy.

## What it does

- Active GATT proxy, 3 connection slots
- Services are not cached, so a driver can move between provisioning and proxy
- Wi-Fi power save off, 16 KB TCP send buffer, API queue 32
- Setup AP on first boot; Wi-Fi is saved on the board
- Encrypted API and OTA
- One restart if Home Assistant connects and never finishes entity setup
- A **Recover Bluetooth Gateway** button

It does not list individual lights. Those show up in Tuesly after discovery.

## Build

From `tuesly/firmware`, with the existing ESPHome environment:

```powershell
copy secrets.example.yaml secrets.yaml
# put this board's setup password and API key in secrets.yaml

..\..\mopeka\firmware-esp32\.venv\Scripts\esphome.exe compile tuesly-proxy.yaml
..\..\mopeka\firmware-esp32\.venv\Scripts\esphome.exe upload tuesly-proxy.yaml --device COM_PORT
```

Delete `secrets.yaml` when the build is finished. Do not commit it.
