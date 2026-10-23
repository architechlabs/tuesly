"""Catch an explicitly authorized reset, then commission with HA's current Store."""
import asyncio,json,time
from pathlib import Path
import yaml
from aioesphomeapi import APIClient
from aioesphomeapi.model import BluetoothScannerMode
from ha_recovery import rest,ws,refresh_session,TARGET,PROVIDER,ROOT

async def main():
    refresh_session()
    report={'stage':'preparing','paired':False}
    api=None;cancel=None
    try:
        for entry in (TARGET,PROVIDER):
            report['stage']='pausing_'+('target' if entry==TARGET else 'proxy')
            print(report['stage'],flush=True)
            await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':'user'})
        report['stage']='opening_repair_flow'
        flow=await asyncio.to_thread(rest,'/api/config/config_entries/flow',{'handler':'tuesly','entry_id':TARGET})
        if flow.get('step_id')!='sig_repair':raise RuntimeError('Unexpected repair flow')
        config=yaml.safe_load((ROOT.parent/'mopeka/firmware-esp32/secrets.yaml').read_text())
        api=APIClient('192.168.20.181',6053,noise_psk=config['tuya_api_encryption_key'],client_info='tuesly-reset-handoff')
        report['stage']='connecting_proxy_api'
        stopped=asyncio.Event()
        async def on_stop(expected):
            if not expected:stopped.set()
        await asyncio.wait_for(api.connect(login=True,on_stop=on_stop),12)
        report['stage']='reading_device_info'
        await asyncio.wait_for(api.device_info(),8)
        seen=asyncio.Event();target=int('DC23528160BB',16)
        def heard(message):
            for adv in message.advertisements:
                if adv.address!=target:continue
                raw=bytes(adv.data)
                if b'\x27\x18' in raw:
                    report['reset_rssi']=adv.rssi
                    seen.set()
        cancel=api.subscribe_bluetooth_le_raw_advertisements(heard)
        api.bluetooth_scanner_set_mode(BluetoothScannerMode.PASSIVE)
        await asyncio.sleep(1)
        api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
        report['stage']='armed'
        print('ARMED: pairing advertisement will trigger HA commissioning automatically',flush=True)
        deadline=time.monotonic()+300
        while not seen.is_set():
            seen_task=asyncio.create_task(seen.wait())
            stop_task=asyncio.create_task(stopped.wait())
            done,pending=await asyncio.wait((seen_task,stop_task),timeout=max(0,deadline-time.monotonic()),return_when=asyncio.FIRST_COMPLETED)
            for task in pending:task.cancel()
            await asyncio.gather(*pending,return_exceptions=True)
            if not done:raise TimeoutError('No reset advertisement within deadline')
            if seen.is_set():break
            print('Proxy link dropped; rearming automatically',flush=True)
            if cancel:cancel();cancel=None
            await api.disconnect(force=True)
            while time.monotonic()<deadline:
                try:
                    stopped.clear()
                    await asyncio.wait_for(api.connect(login=True,on_stop=on_stop),12)
                    await asyncio.wait_for(api.device_info(),8)
                    cancel=api.subscribe_bluetooth_le_raw_advertisements(heard)
                    api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
                    print('Listener rearmed after proxy reconnection',flush=True)
                    break
                except Exception:
                    await api.disconnect(force=True)
                    await asyncio.sleep(1)
            else:raise TimeoutError('Proxy did not reconnect')
        print('Pairing advertisement caught; handing transport to HA',flush=True)
        cancel();cancel=None
        await api.disconnect(force=True);api=None
        await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':None})
        await asyncio.sleep(4)
        report['stage']='commissioning'
        result=await asyncio.to_thread(rest,'/api/config/config_entries/flow/'+flow['flow_id'],
            {'recommission':True,'reset_confirmed':True},timeout=150)
        report['flow_result']={k:result.get(k) for k in ('type','reason','step_id','errors')}
        report['paired']=result.get('reason')=='reconfigure_successful'
        print(json.dumps(report),flush=True)
    except Exception as exc:
        report['failure_type']=type(exc).__name__
    finally:
        if cancel:cancel()
        if api:await api.disconnect(force=True)
        for entry in (PROVIDER,TARGET):
            try:await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':None})
            except Exception as exc:report['restore_error']=type(exc).__name__
        (ROOT/'reports/automatic-ha-pairing.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':asyncio.run(main())
