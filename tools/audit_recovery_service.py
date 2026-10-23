"""Read-only live app health; output no configuration credentials."""
import json,shlex
from deploy_recovery_addon import ssh
from ha_recovery import ROOT
PROGRAM='''import json,asyncio
from pathlib import Path
from service import HA,MESH_FILE
from policy import radio_evidence
async def main():
 options=json.loads(Path('/data/options.json').read_text())
 ha=HA(options)
 diagnostics=await ha.rest('/api/diagnostics/config_entry/'+options['bluetooth_entry'])
 scanners=diagnostics['data']['manager']['scanners']
 source=options['proxy_source'].upper()
 scanner=next((s for s in scanners if s.get('source','').upper()==source),None)
 mesh=json.loads(MESH_FILE.read_text())['data']
 attempts_path=Path('/data/attempts.json')
 attempts=json.loads(attempts_path.read_text()) if attempts_path.exists() else {}
 protocol_path=Path('/data/protocol.json')
 protocol=json.loads(protocol_path.read_text()) if protocol_path.exists() else {'nodes':{}}
 states=[]
 for enrolled in options['enrolled']:
  light=await ha.rest('/api/states/'+enrolled['entity_id'])
  seen=scanner.get('discovered_device_timestamps',{}).get(enrolled['address']) if scanner else None
  states.append({'address':enrolled['address'],'entity_state':light['state'],'enrolled_in_mesh':enrolled['address'] in mesh['nodes'],
   'node':{key:mesh['nodes'].get(enrolled['address'],{}).get(key) for key in ('address','status','elements','binding_revision','proxy_enabled')},
   'app_node':{key:protocol['nodes'].get(enrolled['address'],{}).get(key) for key in ('address','status','elements','binding_revision','proxy_enabled')},
   'radio_evidence':radio_evidence(scanner,enrolled) if scanner else None,'attempt_record':attempts.get(enrolled['address'],{}),
   'advertisement_age':scanner['monotonic_time']-seen if seen else None,
   'raw':str(scanner.get('raw_advertisement_data',{}).get(enrolled['address']))[:240] if scanner else None})
 print(json.dumps({'enabled':options['enabled'],'enrolled_count':len(options['enrolled']),
  'proxy_scanning':bool(scanner and scanner.get('scanning')),'proxy_connectable':bool(scanner and scanner.get('connectable')),
  'proxy_seen_devices':len(scanner.get('discovered_device_timestamps',{})) if scanner else 0,
  'proxy_last_packet_age':scanner['monotonic_time']-max(scanner.get('discovered_device_timestamps',{}).values()) if scanner and scanner.get('discovered_device_timestamps') else None,
  'mesh_readable':True,'status':json.loads(Path('/data/status.json').read_text()),'devices':states}))
asyncio.run(main())
'''
remote=ssh()
try:
    _,out,err=remote.exec_command('sudo -n docker exec app_local_tuesly_recovery python -c '+shlex.quote(PROGRAM),timeout=60)
    raw=out.read()
    if out.channel.recv_exit_status():
        reason=err.read().decode().splitlines()[-1:]
        print('App health check failed:',reason)
        raise SystemExit(1)
    data=json.loads(raw)
    (ROOT/'reports/automatic-recovery-service.json').write_text(json.dumps(data,indent=2))
    print(json.dumps(data,indent=2))
finally:remote.close()
