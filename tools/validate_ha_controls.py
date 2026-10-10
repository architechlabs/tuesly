"""Authorized bench acceptance through normal HA services; restore starting state."""
import json
import time
from ha_recovery import ROOT, rest

LIGHT = 'light.tuesly_light_81_60_bb'
TEMPERATURE = 'number.tuesly_light_81_60_bb_white_temperature'
report = {'version':'0.2.6','checks':[]}

def check(domain,service,values):
    started = time.monotonic()
    rest('/api/services/'+domain+'/'+service, values)
    light, temperature = rest('/api/states/'+LIGHT),rest('/api/states/'+TEMPERATURE)
    record = {'service':domain+'.'+service,'requested':values,
              'seconds':round(time.monotonic()-started,2),'onoff':light['state'],
              'brightness':light['attributes'].get('brightness'),
              'temperature_percent':temperature['state'],'last_reported':light['last_reported']}
    if domain == 'light' and light['state'] != ('off' if service=='turn_off' else 'on'):
        raise RuntimeError('Light state did not confirm requested on/off')
    if 'brightness' in values and abs(light['attributes'].get('brightness',-999)-values['brightness'])>1:
        raise RuntimeError('Brightness readback mismatch')
    if domain == 'number' and abs(float(temperature['state'])-values['value'])>1:
        raise RuntimeError('Warm/cool readback mismatch')
    report['checks'].append(record)
    print(json.dumps(record),flush=True)

original_light, original_temperature = rest('/api/states/'+LIGHT),rest('/api/states/'+TEMPERATURE)
if original_light['state'] not in ('on','off') or original_temperature['state'] in ('unavailable','unknown'):
    raise RuntimeError('Both controls must be available before acceptance')
try:
    check('light','turn_off',{'entity_id':LIGHT})
    check('light','turn_on',{'entity_id':LIGHT,'brightness':128})
    check('light','turn_on',{'entity_id':LIGHT,'brightness':220})
    for value in (0,50,100):
        check('number','set_value',{'entity_id':TEMPERATURE,'value':value})
    report['passed']=True
except Exception as exc:
    report.update(passed=False,failure_type=type(exc).__name__)
finally:
    try:
        check('number','set_value',{'entity_id':TEMPERATURE,'value':float(original_temperature['state'])})
        data={'entity_id':LIGHT}
        if original_light['attributes'].get('brightness') is not None:
            data['brightness']=original_light['attributes']['brightness']
        check('light','turn_on',data)
        if original_light['state']=='off':
            check('light','turn_off',{'entity_id':LIGHT})
        report['starting_state_restored']=True
    except Exception as exc:
        report.update(starting_state_restored=False,restore_failure_type=type(exc).__name__)
    (ROOT/'reports/ha-controls-0.2.6.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report.get('passed'), 'starting_state_restored':report.get('starting_state_restored')}))
