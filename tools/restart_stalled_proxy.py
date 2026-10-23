"""Bench restart via the verified firmware button key, without a BLE subscription."""
import asyncio,json,time,re
import yaml
from aioesphomeapi import APIClient
from aioesphomeapi.api_pb2 import LogLevel
from ha_recovery import ROOT

async def probe(key=None):
    config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
    api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-verified-restart')
    row={'elapsed':round(time.monotonic()-START,1)}
    try:
        await asyncio.wait_for(api.connect(login=True),5)
        info=await asyncio.wait_for(api.device_info(),4)
        row['version']=info.project_version
        if key is not None:
            if info.project_version!='1.1.8':raise RuntimeError('Firmware differs from inspected button key')
            api.button_command(key)
            await asyncio.sleep(1)
            row['restart_sent']=True
        else:
            ents,_=await asyncio.wait_for(api.list_entities_services(),5)
            row['entities']=len(ents)
    except Exception as exc:row['error']=type(exc).__name__
    finally:await api.disconnect(force=True)
    print(json.dumps(row),flush=True)
    return row

async def main():
    generated=(ROOT.parent/'mopeka/firmware-esp32/.esphome/build/tuya-ble-proxy-01/src/main.cpp').read_text()
    matches=re.findall(r'App.register_button\([^,]+, "Restart Gateway", (\d+),',generated)
    if len(matches)!=1:raise RuntimeError('Restart key cannot be verified')
    results=[await probe(int(matches[0]))]
    for _ in range(6):
        await asyncio.sleep(5)
        results.append(await probe())
        if results[-1].get('entities'):break
    (ROOT/'reports/stalled-proxy-restart.json').write_text(json.dumps(results,indent=2))

START=time.monotonic()
if __name__=='__main__':asyncio.run(main())
