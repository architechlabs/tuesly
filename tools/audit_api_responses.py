"""Distinguish a stalled API batch from a dead connection, without BLE ownership."""
import asyncio,json,collections
import yaml
from aioesphomeapi import APIClient
from aioesphomeapi.client import LIST_ENTITIES_MSG_TYPES
from ha_recovery import ROOT

async def main():
    config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
    api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-api-audit')
    report={};counts=collections.Counter();task=None;cancel=None
    try:
        await asyncio.wait_for(api.connect(login=True),8)
        info=await asyncio.wait_for(api.device_info(),5);report['version']=info.project_version
        cancel=api._get_connection().add_message_callback(lambda msg:counts.update([type(msg).__name__]),LIST_ENTITIES_MSG_TYPES)
        task=asyncio.create_task(api.list_entities_services())
        await asyncio.sleep(4)
        # DeviceInfo is an immediate response; entity replies use batching.
        try:
            await asyncio.wait_for(api.device_info(),5)
            report['device_info_while_listing']=True
        except Exception as exc:report['device_info_while_listing']=type(exc).__name__
        try:
            entities,_=await asyncio.wait_for(task,8);report['entities']=len(entities)
        except Exception as exc:report['enumeration_error']=type(exc).__name__
    except Exception as exc:report['connection_error']=type(exc).__name__
    finally:
        report['entity_response_counts']=dict(counts)
        if cancel:cancel()
        if task and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
        await api.disconnect(force=True)
        (ROOT/'reports/api-response-audit-1.1.6.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':asyncio.run(main())
