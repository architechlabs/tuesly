"""Keep the previous credential-bearing bench image privately for rollback."""
import hashlib,shutil
from ha_recovery import ROOT,PRIVATE
source=ROOT.parent/'mopeka/firmware-esp32/.esphome/build/tuya-ble-proxy-01/build/firmware.factory.bin'
destination=PRIVATE/'firmware-before-1.1.5.factory.bin'
if not destination.exists():shutil.copy2(source,destination)
print('Previous firmware retained privately; SHA256:',hashlib.sha256(destination.read_bytes()).hexdigest())
