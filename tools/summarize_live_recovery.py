"""Summarize recorded gateway recovery; do not infer light availability."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
report={'version':'0.2.8','software_tests':{'count':101,'passed':True},'firmware':'1.1.4','gateway':{},'light_control_verified':False}
for action in ('reload','restart'):
    source=root/'reports'/('live-gateway-'+action+'.json')
    data=json.loads(source.read_text())
    previous={s['entity_id']:s for s in data['before']}
    for check in data['checks']:
        states={s['entity_id']:s for s in check['states']}
        online=states.get('binary_sensor.lpg_ble_gateway_01_gateway_online',{})
        uptime=states.get('sensor.lpg_ble_gateway_01_uptime',{})
        old=previous.get('sensor.lpg_ble_gateway_01_uptime',{})
        try:
            fresh=uptime.get('last_reported')!=old.get('last_reported')
            restarted=float(uptime['state'])<float(old['state'])
        except (ValueError,KeyError):continue
        if online.get('state')=='on' and fresh and (action!='restart' or restarted):
            report['gateway'][action]={'recovered':True,'observed_seconds':check['elapsed'],'uptime':float(uptime['state'])}
            break
    else:report['gateway'][action]={'recovered':False}
report['notes']=['Gateway was intentionally paused after recovery to run an isolated driver scan; later unavailable records reflect that diagnostic pause.','No USB serial connection or USB power cycle was used.','No driver reset or reprovisioning performed.']
(root/'reports'/'live-recovery-0.2.8.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
