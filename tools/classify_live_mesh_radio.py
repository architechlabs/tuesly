"""Classify raw target packets only while HA's proxy subscription is paused."""
import asyncio,json,yaml
from aioesphomeapi import APIClient
from aioesphomeapi.model import BluetoothScannerMode
from ha_recovery import ROOT,PROVIDER,ws
async def main():
 entries=await ws({'type':'config_entries/get'})
 if next(e['disabled_by'] for e in entries if e['entry_id']==PROVIDER) is None:
  print('SKIPPED: HA owns the proxy subscription');return
 config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
 api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-raw-packet-classification')
 counts={'packets':0,'pb_gatt':0,'pb_adv_unprovisioned':0,'pb_adv_transactions':0,'mesh_proxy':0,'tuya_ad03':0}
 cancel=None
 try:
  await asyncio.wait_for(api.connect(login=True),12)
  def heard(message):
   for adv in message.advertisements:
    if adv.address!=int('DC23528160BB',16):continue
    counts['packets']+=1;counts['last_rssi']=adv.rssi;counts['address_type']=adv.address_type
    raw=bytes(adv.data);offset=0
    while offset<len(raw):
     size=raw[offset]
     if not size or offset+size>=len(raw):break
     kind=raw[offset+1];payload=raw[offset+2:offset+size+1]
     if kind==0x16 and payload[:2]==b'\x27\x18' and len(payload)>=20:counts['pb_gatt']+=1
     if kind==0x16 and payload[:2]==b'\x28\x18':counts['mesh_proxy']+=1
     if kind==0x2b and payload[:1]==b'\x00' and len(payload)>=19:counts['pb_adv_unprovisioned']+=1
     if kind==0x29:counts['pb_adv_transactions']+=1
     if kind==0x03 and payload.startswith(bytes.fromhex('40dc23528160bb')):counts['tuya_ad03']+=1
     offset+=size+1
  cancel=api.subscribe_bluetooth_le_raw_advertisements(heard)
  api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
  await asyncio.sleep(12)
 except Exception as exc:counts['failure_type']=type(exc).__name__
 finally:
  if cancel:cancel()
  await api.disconnect(force=True)
  (ROOT/'reports/live-mesh-radio-classification.json').write_text(json.dumps(counts,indent=2))
  print(json.dumps(counts,indent=2))
asyncio.run(main())
