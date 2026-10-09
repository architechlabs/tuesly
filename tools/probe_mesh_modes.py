"""Read GATT layout and issue Provisioning Invite only; never deliver mesh keys."""
import asyncio,json
import yaml
from aioesphomeapi import APIClient
from inspect_mesh import ROOT,GATTAdapter,MAC

async def main():
    secrets=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
    api=APIClient('192.168.20.181',6053,noise_psk=secrets['tuya_api_encryption_key'],client_info='tuesly-mode-inspection')
    address=int(MAC.replace(':',''),16)
    cancel=None
    result={'stage':'api'}
    try:
        await asyncio.wait_for(api.connect(login=True),12)
        info=await api.device_info();capabilities=await api.device_capabilities_compat(info)
        cancel=await api.bluetooth_device_connect(address,lambda *args:None,timeout=20,
            feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=0)
        await api.bluetooth_device_set_connection_params(address,24,40,0,800)
        services=await api.bluetooth_gatt_get_services(address)
        result['services']=[{'uuid':s.uuid,'characteristics':[{'uuid':c.uuid,'handle':c.handle,'properties':c.properties,'descriptors':[(d.uuid,d.handle) for d in c.descriptors]} for c in s.characteristics]} for s in services.services]
        adapter=GATTAdapter(api,address,services)
        provisioning=adapter.get_service('00001827-0000-1000-8000-00805f9b34fb')
        result['stage']='provisioning_invite'
        receive=asyncio.get_running_loop().create_future()
        def reply(handle,data):
            if not receive.done():receive.set_result(bytes(data).hex())
        output=provisioning.get_characteristic('00002adc-0000-1000-8000-00805f9b34fb')
        input=provisioning.get_characteristic('00002adb-0000-1000-8000-00805f9b34fb')
        await adapter.start_notify(output,reply)
        await adapter.write_gatt_char(input,b'\x03\x00\x00',response=False)
        result['invite_response']=await asyncio.wait_for(receive,10)
        await adapter.stop_notify(output)
        result['stage']='complete'
    except Exception as exc:
        result['failure_type']=type(exc).__name__
    finally:
        try:await api.bluetooth_device_disconnect(address,timeout=5)
        except Exception:pass
        if cancel:cancel()
        await api.disconnect(force=True)
    (ROOT/'reports/mesh-mode-probe.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
asyncio.run(main())
