"""Arm pairing inside HA; its existing ESPHome subscription stays online."""
import asyncio,json,sys,runpy,time
import websockets
from ha_recovery import rest,ws,session,refresh_session,TARGET,PROVIDER,ROOT,PRIVATE
from reset_pattern import ResetPattern
VERSION=json.loads((ROOT/'custom_components/tuesly/manifest.json').read_text())['version']
CONTROL_REPORT=ROOT/'reports'/f'ha-controls-{VERSION}.json'

async def main():
    refresh_session();report={'stage':'preparing','paired':False}
    operation=None;native_original=None;native_changed=False;competitors={};provider_original=None;provider_changed=False
    native='01JKB1JJXYFTSZR1M5XAK7XSR8'
    try:
        if '--quiet-competitors' in sys.argv:
            entries=await ws({'type':'config_entries/get'})
            competing_ids={'01M4AZ160HZRX3N2AT8QKWEWG8','01M4G0VZNTVVFHR46EYDNB2RQ4'}
            for entry in entries:
                if entry['entry_id'] in competing_ids:
                    competitors[entry['entry_id']]=entry['disabled_by']
                    await ws({'type':'config_entries/disable','entry_id':entry['entry_id'],'disabled_by':'user'})
            report['switchbot_comparison_paused']=len(competitors)
        if '--esp-only' in sys.argv:
            entries=await ws({'type':'config_entries/get'})
            native_original=next(e['disabled_by'] for e in entries if e['entry_id']==native)
            await ws({'type':'config_entries/disable','entry_id':native,'disabled_by':'user'})
            native_changed=True
            report['pi_bluetooth_disabled_for_test']=True
        await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':'user'})
        if '--native-only' in sys.argv:
            entries=await ws({'type':'config_entries/get'})
            provider_original=next(e['disabled_by'] for e in entries if e['entry_id']==PROVIDER)
            await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':'user'})
            provider_changed=True;report['native_only']=True
        else:
            await ws({'type':'config_entries/disable','entry_id':PROVIDER,'disabled_by':None})
        if '--esp-only' in sys.argv:
            # Entry enabled / socket open is not a registered, scanning proxy.
            # Never ask for a physical reset while HA lacks the ESP32 scanner.
            deadline=time.monotonic()+150
            printed=False
            while time.monotonic()<deadline:
                diagnostics=await asyncio.to_thread(rest,'/api/diagnostics/config_entry/'+native,timeout=8)
                scanners=diagnostics.get('data',{}).get('manager',{}).get('scanners',[])
                if any(str(s.get('source','')).upper()=='44:1D:64:F6:B5:FE'
                       and s.get('scanning') and s.get('connectable') for s in scanners):
                    report['esp32_scanner_verified']=True
                    break
                if not printed:
                    print('WAITING_FOR_ESP32_SCANNER: do not reset the LED yet',flush=True)
                    printed=True
                await asyncio.sleep(3)
            else:
                raise TimeoutError('ESP32 scanner was not registered and scanning')
        flow=await asyncio.to_thread(rest,'/api/config/config_entries/flow',{'handler':'tuesly','entry_id':TARGET})
        if flow.get('step_id')!='sig_repair':raise RuntimeError('Unexpected repair flow')
        s=session()
        async with websockets.connect(s['base'].replace('http:','ws:')+'/api/websocket',max_size=16*1024*1024) as connection:
            await connection.recv()
            await connection.send(json.dumps({'type':'auth','access_token':s['access_token']}))
            if json.loads(await connection.recv())['type']!='auth_ok':raise RuntimeError('HA authentication failed')
            await connection.send(json.dumps({'id':1,'type':'subscribe_events','event_type':'tuesly_pairing_armed'}))
            acknowledgement=json.loads(await connection.recv())
            if not acknowledgement.get('success'):raise RuntimeError('Cannot observe pairing readiness')
            if '--observe-reset' in sys.argv:
                pattern=None;last_phase=None;deadline=time.monotonic()+600
                print('RESET_MONITOR_READY: waiting for OFF 10s, ON 4s, OFF 4s, ON 4s, OFF 4s, then final ON',flush=True)
                while time.monotonic()<deadline:
                    diagnostics=await asyncio.to_thread(rest,'/api/diagnostics/config_entry/'+native,timeout=8)
                    manager=diagnostics.get('data',{}).get('manager',{})
                    source='2C:CF:67:57:ED:65' if '--native-only' in sys.argv else '44:1D:64:F6:B5:FE'
                    scanner=next((s for s in manager.get('scanners',[]) if str(s.get('source','')).upper()==source and s.get('scanning')),None)
                    if scanner is None:raise RuntimeError('Selected scanner stopped during reset capture')
                    now=scanner['monotonic_time']
                    if pattern is None:pattern=ResetPattern(now)
                    # Remote timestamps advance on received radio packets; HA's
                    # merged history can remain unchanged while a lamp is ON.
                    if '--native-only' in sys.argv:
                        raise RuntimeError('Native diagnostics do not expose per-packet timestamps; use the direct native listener')
                    seen=scanner.get('discovered_device_timestamps',{}).get('DC:23:52:81:60:BB')
                    complete=pattern.observe(now,seen)
                    if pattern.phase!=last_phase:
                        print('RESET_MONITOR_PHASE:',pattern.phase,flush=True);last_phase=pattern.phase
                    if complete:
                        report['reset_sequence_observed']=True
                        break
                    await asyncio.sleep(.5)
                else:raise TimeoutError('Complete reset pattern was not observed')
            # Extend the operator wait without restarting HA. Only rearm when
            # discovery found no device; never repeat a provisioning exchange
            # after it has begun or failed.
            for attempt in range(4):
                operation=asyncio.create_task(asyncio.to_thread(rest,'/api/config/config_entries/flow/'+flow['flow_id'],{'recommission':True,'reset_confirmed':True},timeout=240))
                async with asyncio.timeout(30):
                    while True:
                        message=json.loads(await connection.recv())
                        if message.get('event',{}).get('data',{}).get('entry_id')==TARGET:
                            report['stage']='armed_inside_home_assistant'
                            print('ARMED INSIDE HA: reset advertisement starts commissioning immediately; no chat reply needed',flush=True)
                            break
                result=await operation
                if result.get('errors',{}).get('base')!='device_not_found':
                    break
            report['flow_result']={key:result.get(key) for key in ('type','reason','step_id','errors')}
            report['paired']=result.get('reason')=='reconfigure_successful'
            report['stage']='flow_complete'
        if report['paired'] and '--controls' in sys.argv:
            await ws({'type':'config_entries/disable','entry_id':TARGET,'disabled_by':None})
            await asyncio.to_thread(runpy.run_path,str(ROOT/'tools/validate_ha_controls.py'))
            controls=json.loads(CONTROL_REPORT.read_text())
            report['controls_passed']=controls.get('passed',False)
            print('CONTROL READBACKS PASSED:',report['controls_passed'],
                  'Pi Bluetooth disabled:',bool(report.get('pi_bluetooth_disabled_for_test')),flush=True)
            if report['controls_passed'] and '--confirmed-power-cycle' in sys.argv:
                marker=PRIVATE/'driver-cycle-confirmation.json'
                marker.write_text(json.dumps({'armed_at':time.time(),'confirmed':False}))
                print('ARMED_FOR_CONFIRMED_POWER_CYCLE: only driver OFF 10 seconds then ON; operator confirmation required',flush=True)
                deadline=time.monotonic()+600
                while time.monotonic()<deadline:
                    if json.loads(marker.read_text()).get('confirmed'):
                        report['physical_cycle_confirmed_at']=time.time()
                        break
                    await asyncio.sleep(1)
                else:
                    raise TimeoutError('Physical power cycle was not confirmed')
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    await asyncio.to_thread(rest,'/api/services/homeassistant/update_entity',{'entity_id':'light.tuesly_light_81_60_bb'})
                    current=await asyncio.to_thread(rest,'/api/states/light.tuesly_light_81_60_bb')
                    if current['state'] in ('on','off'):
                        await asyncio.to_thread(runpy.run_path,str(ROOT/'tools/validate_ha_controls.py'))
                        report['confirmed_cycle_controls_passed']=json.loads(CONTROL_REPORT.read_text()).get('passed',False)
                        break
                    await asyncio.sleep(3)
                else:
                    report['confirmed_cycle_controls_passed']=False
            if report['controls_passed'] and '--power-cycle' in sys.argv:
                print('ARMED_FOR_NORMAL_POWER_CYCLE: only driver OFF 10 seconds then ON',flush=True)
                deadline=time.monotonic()+150;offline=False;checks=[]
                while time.monotonic()<deadline:
                    await asyncio.to_thread(rest,'/api/services/homeassistant/update_entity',{'entity_id':'light.tuesly_light_81_60_bb'})
                    current=await asyncio.to_thread(rest,'/api/states/light.tuesly_light_81_60_bb')
                    row={'time':time.time(),'state':current['state']};checks.append(row)
                    if current['state']=='unavailable':offline=True
                    elif offline and current['state'] in ('on','off'):
                        await asyncio.to_thread(runpy.run_path,str(ROOT/'tools/validate_ha_controls.py'))
                        report['power_cycle_recovered']=json.loads(CONTROL_REPORT.read_text()).get('passed',False)
                        break
                    await asyncio.sleep(2)
                report['power_cycle_states']=checks
    except Exception as exc:
        report['failure_type']=type(exc).__name__
        if operation:
            try:
                result=await operation
                report['flow_result']={key:result.get(key) for key in ('type','reason','step_id','errors')}
            except Exception as second:report['operation_error']=type(second).__name__
    finally:
        for entry in (PROVIDER,TARGET):
            try:await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':provider_original if entry==PROVIDER and provider_changed else None})
            except Exception as exc:report['restore_error']=type(exc).__name__
        if native_changed:
            try:await ws({'type':'config_entries/disable','entry_id':native,'disabled_by':native_original})
            except Exception as exc:report['native_restore_error']=type(exc).__name__
        for entry,disabled_by in competitors.items():
            try:await ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':disabled_by})
            except Exception as exc:report['competitor_restore_error']=type(exc).__name__
        (ROOT/'reports/ha-native-pairing.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':asyncio.run(main())
