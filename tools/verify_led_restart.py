"""Observe one confirmed physical restart and validate normal HA controls."""
import asyncio,json,runpy,time
from ha_recovery import ROOT,PRIVATE,rest,ws,refresh_session
NATIVE='01JKB1JJXYFTSZR1M5XAK7XSR8'
async def main():
    refresh_session();entries=await ws({'type':'config_entries/get'})
    original=next(e['disabled_by'] for e in entries if e['entry_id']==NATIVE)
    report={'esp32_only':True,'passed':False,'checks':[]}
    try:
        await ws({'type':'config_entries/disable','entry_id':NATIVE,'disabled_by':'user'})
        marker=PRIVATE/'driver-cycle-confirmation.json'
        marker.write_text(json.dumps({'armed_at':time.time(),'confirmed':False}))
        print('ARMED_FOR_LED_RESTART: Pi adapter paused; ESP32 remains online',flush=True)
        deadline=time.monotonic()+600
        while time.monotonic()<deadline and not json.loads(marker.read_text()).get('confirmed'):
            await asyncio.sleep(1)
        if not json.loads(marker.read_text()).get('confirmed'):raise TimeoutError('Operator cycle confirmation missing')
        report['physical_cycle_confirmed_at']=time.time()
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            try:
                await asyncio.to_thread(rest,'/api/services/homeassistant/update_entity',{'entity_id':'light.tuesly_light_81_60_bb'},timeout=35)
                light=await asyncio.to_thread(rest,'/api/states/light.tuesly_light_81_60_bb')
                gateway=await asyncio.to_thread(rest,'/api/states/binary_sensor.lpg_ble_gateway_01_gateway_online')
                row={'time':time.time(),'light':light['state'],'gateway':gateway['state']}
                report['checks'].append(row);print(json.dumps(row),flush=True)
                if light['state'] in ('on','off') and gateway['state']=='on':
                    await asyncio.to_thread(runpy.run_path,str(ROOT/'tools/validate_ha_controls.py'))
                    version=json.loads((ROOT/'custom_components/tuesly/manifest.json').read_text())['version']
                    report['passed']=json.loads((ROOT/'reports'/f'ha-controls-{version}.json').read_text())['passed']
                    break
            except Exception as exc:
                report['checks'].append({'failure_type':type(exc).__name__})
            await asyncio.sleep(3)
    finally:
        await ws({'type':'config_entries/disable','entry_id':NATIVE,'disabled_by':original})
        (ROOT/'reports/confirmed-led-restart.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'restart_controls_passed':report['passed'],'pi_adapter_restored':True}),flush=True)
asyncio.run(main())
