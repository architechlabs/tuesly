"""Read firmware/API health without replacing HA's Bluetooth subscription."""
import asyncio,json,time
import yaml
from aioesphomeapi import APIClient
from ha_recovery import ROOT

async def main():
    config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
    api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-read-only-api-check')
    report={'stage':'connect'};started=time.monotonic()
    try:
        await asyncio.wait_for(api.connect(login=True),12)
        report['stage']='device_info'
        info=await asyncio.wait_for(api.device_info(),8)
        report.update(esphome=info.esphome_version,project_version=getattr(info,'project_version',None))
        report['stage']='entity_enumeration'
        entities,services=await asyncio.wait_for(api.list_entities_services(),16)
        report.update(stage='passed',entity_count=len(entities),
            recovery_button=any(getattr(e,'name','')=='Recover Bluetooth Gateway' for e in entities),seconds=round(time.monotonic()-started,2))
    except Exception as exc:report['failure_type']=type(exc).__name__
    finally:
        await api.disconnect(force=True)
        (ROOT/'reports/proxy-api-live.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':asyncio.run(main())
