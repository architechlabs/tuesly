"""Observe a normal driver restart without taking over HA's Bluetooth proxy."""
import asyncio
import json
import time
import serial
from ha_recovery import ROOT, TARGET, rest


async def main():
    report = {'stage':'waiting_for_driver_restart','events':[], 'recovered':False}
    connection = serial.Serial(port=None,baudrate=115200,timeout=0.2)
    connection.dtr = connection.rts = False
    connection.port = 'COM8'
    connection.open()
    started = time.monotonic()
    restart_seen = asyncio.Event()
    async def states():
        reloaded = False
        while True:
            if restart_seen.is_set() and not reloaded:
                reloaded = True
                report['stage']='reloading_after_fresh_advertisement'
                try:
                    await asyncio.to_thread(rest,'/api/config/config_entries/entry/'+TARGET+'/reload',{},timeout=70)
                except Exception as exc:
                    report['reload_result']=type(exc).__name__
            try:
                light = await asyncio.to_thread(rest,'/api/states/light.tuesly_light_81_60_bb',timeout=5)
                temperature = await asyncio.to_thread(rest,'/api/states/number.tuesly_light_81_60_bb_white_temperature',timeout=5)
                if restart_seen.is_set() and light['state'] in ('on','off') and temperature['state'] not in ('unknown','unavailable'):
                    report.update(stage='recovered',recovered=True,light_state=light['state'],
                        brightness=light['attributes'].get('brightness'),temperature_percent=temperature['state'],
                        elapsed_seconds=round(time.monotonic()-started,2))
                    print(json.dumps(report),flush=True)
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
    poll = asyncio.create_task(states())
    print('Automatic restart monitor armed. HA proxy and light entries remain enabled.',flush=True)
    pending = ''
    try:
        async with asyncio.timeout(600):
            while not poll.done():
                pending += (await asyncio.to_thread(connection.read,4096)).decode('utf-8',errors='replace')
                while '\n' in pending:
                    line,pending = pending.split('\n',1)
                    if 'Target DC:23:52:81:60:BB heard' in line:
                        restart_seen.set()
                        print('Driver advertisement caught; HA recovery starts automatically',flush=True)
                    if 'Target advertised service:' in line:
                        service = line.split('Target advertised service:',1)[1].strip()
                        report['events'].append({'service':service,'seconds':round(time.monotonic()-started,2)})
                        print('Driver service:',service,flush=True)
                await asyncio.sleep(0)
    except TimeoutError:
        report['stage']='recovery_deadline_exceeded'
    finally:
        poll.cancel()
        await asyncio.gather(poll,return_exceptions=True)
        connection.close()
        (ROOT/'reports/ha-power-cycle-recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    asyncio.run(main())
