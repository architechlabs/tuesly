"""Read ESP32 logs without subscribing to Bluetooth or opening USB."""
import asyncio,json
import yaml
from aioesphomeapi import APIClient
from ha_recovery import ROOT

async def main():
    config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
    api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-log-evidence')
    report={'stage':'connect','logs':[]}
    try:
        await asyncio.wait_for(api.connect(login=True),12)
        report['stage']='device_info'
        info=await asyncio.wait_for(api.device_info(),8)
        report['firmware']=info.esphome_version
        def logged(message):
            line=message.message.decode(errors='replace')
            if any(key in line.lower() for key in ('password','encryption','ssid','bssid','secret')):return
            if any(key in line.lower() for key in ('bluetooth','ble_tracker','scan','connection','target','wifi','warn','error','rst:','uptime')):
                report['logs'].append(line);print(line,flush=True)
        api.subscribe_logs(logged,log_level=3,dump_config=True)
        report['stage']='collecting_logs'
        await asyncio.sleep(25)
        report['stage']='complete'
    except Exception as exc:report['failure_type']=type(exc).__name__
    finally:
        await api.disconnect(force=True)
        (ROOT/'reports/api-stall-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='logs'}),flush=True)

if __name__=='__main__':asyncio.run(main())
