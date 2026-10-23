"""Read ESPHome GATT slot occupancy without subscribing to BLE advertisements."""
import asyncio,json,yaml
from aioesphomeapi import APIClient
from ha_recovery import ROOT
async def main():
 config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
 api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-slot-inspection')
 cancel=None
 try:
  await asyncio.wait_for(api.connect(login=True),5)
  ready=asyncio.get_running_loop().create_future()
  def received(free,limit,allocated):
   if not ready.done():ready.set_result({'free':free,'limit':limit,'allocated_count':len(allocated),
    'target_allocated':int('DC23528160BB',16) in allocated})
  cancel=api.subscribe_bluetooth_connections_free(received)
  print(json.dumps(await asyncio.wait_for(ready,5)))
 finally:
  if cancel:cancel()
  await api.disconnect(force=True)
asyncio.run(main())
