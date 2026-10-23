"""Independent HAOS process: fresh radio proof -> bounded mesh recovery -> HA."""
from __future__ import annotations
import asyncio,contextlib,copy,json,logging,os,signal,time,types,urllib.request
from pathlib import Path
import websockets
from aioesphomeapi import APIClient
from aioesphomeapi.model import BluetoothScannerMode
from mesh_core import MeshJournal,ManagedMeshDevice,NodeConfigurator
from policy import remember_startup,permitted,observe_live_event
from tuesly_mesh.secrets import DictSecretsManager
from tuesly_mesh.sig_mesh_crypto import k3
from tuesly_mesh.sig_mesh_provisioner import SIGMeshProvisioner
from tuesly_mesh.exceptions import MeshConnectionError

LOG=logging.getLogger('tuesly.recovery')
DATA=Path('/data')
SOURCE=0x7FFE
MESH_FILE=Path('/homeassistant/.storage/tuesly.mesh')

def save(path,value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)
    if os.name!='nt':
        descriptor=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

class Store:
    def __init__(self,current):self.current=current;self.path=DATA/'protocol.json'
    async def async_load(self):
        state=copy.deepcopy(self.current)
        previous=json.loads(self.path.read_text()) if self.path.exists() else None
        state['sequence_high']=previous['sequence_high'] if previous and previous['net_key']==state['net_key'] else 0
        if previous and previous['net_key']==state['net_key']:
            for mac,node in state['nodes'].items():
                old=previous['nodes'].get(mac,{})
                if old.get('dev_key')==node.get('dev_key') and old.get('address')==node['address']:
                    node['received']=old.get('received',{})
        return state
    async def async_save(self,value):await asyncio.to_thread(save,self.path,value)

class HA:
    def __init__(self,options):self.base=options['ha_url'].rstrip('/');self.token=options['ha_token']
    def request(self,path,data=None):
        request=urllib.request.Request(self.base+path,data=None if data is None else json.dumps(data).encode(),
            headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=35) as response:return json.load(response)
    async def rest(self,path,data=None):return await asyncio.to_thread(self.request,path,data)
    async def ws(self,command):
        async with asyncio.timeout(80):
            async with websockets.connect(self.base.replace('http:','ws:').replace('https:','wss:')+'/api/websocket',max_size=8*1024*1024) as connection:
                await connection.recv()
                await connection.send(json.dumps({'type':'auth','access_token':self.token}))
                if json.loads(await connection.recv()).get('type')!='auth_ok':raise RuntimeError('HA administrator authentication failed')
                await connection.send(json.dumps({'id':1,**command}))
                while True:
                    message=json.loads(await connection.recv())
                    if message.get('id')==1:
                        if not message.get('success'):raise RuntimeError('HA operation failed')
                        return message['result']
    async def disable(self,entry,disabled):
        return await self.ws({'type':'config_entries/disable','entry_id':entry,'disabled_by':disabled})

class GATT:
    mtu_size=23
    def __init__(self,api,target,services):
        self.api,self.target,self.table=api,target,services.services
        self.is_connected=True;self.disconnected=None;self.services=self;self.notifications={}
    def __iter__(self):return iter(self.table)
    def get_service(self,uuid):
        for service in self.table:
            if service.uuid.lower()==uuid.lower():
                return types.SimpleNamespace(get_characteristic=lambda uuid,service=service:
                    next((c for c in service.characteristics if c.uuid.lower()==uuid.lower()),None))
    async def start_notify(self,characteristic,callback):
        self.notifications[characteristic.handle]=await self.api.bluetooth_gatt_start_notify(self.target,characteristic.handle,callback)
        descriptor=next(d for d in characteristic.descriptors if d.uuid.lower().startswith('00002902'))
        await self.api.bluetooth_gatt_write_descriptor(self.target,descriptor.handle,b'\x01\x00')
    async def stop_notify(self,characteristic):
        pair=self.notifications.pop(characteristic.handle,None)
        if pair:
            descriptor=next(d for d in characteristic.descriptors if d.uuid.lower().startswith('00002902'))
            if self.is_connected:await self.api.bluetooth_gatt_write_descriptor(self.target,descriptor.handle,b'\x00\x00')
            await pair[0]()
    async def write_gatt_char(self,characteristic,data,*,response=False):
        await self.api.bluetooth_gatt_write(self.target,characteristic.handle,data,response)
    async def write_gatt_descriptor(self,handle,data):await self.api.bluetooth_gatt_write_descriptor(self.target,handle,data)
    async def set_connection_params(self,minimum,maximum,latency,timeout):
        await self.api.bluetooth_device_set_connection_params(self.target,minimum,maximum,latency,timeout)
    async def disconnect(self):
        await self.api.bluetooth_device_disconnect(self.target,timeout=5);self.is_connected=False

class Recovery:
    def __init__(self,options):
        self.options=options;self.ha=HA(options);self.evidence={};self.proxy_evidence={};self.radio_changed=asyncio.Event()
        path=DATA/'attempts.json';self.records=json.loads(path.read_text()) if path.exists() else {}
    def status(self,phase,**details):
        save(DATA/'status.json',{'phase':phase,'updated_at':time.time(),**details})
        LOG.info('%s%s',phase,' '+details['address'] if 'address' in details else '')
    async def restore(self):
        path=DATA/'transaction.json'
        if not path.exists():return
        transaction=json.loads(path.read_text())
        # Resume Bluetooth forwarding before resuming the light controller.
        for entry in (transaction['provider'],transaction['target']):
            await self.ha.disable(entry,transaction['original'][entry])
        path.unlink()
    async def import_node(self,state,mac,node,ready=False):
        payload={'address':mac,'device_key':node['dev_key'],'network_id':k3(bytes.fromhex(state['net_key'])).hex(),
            'primary':node['address'],'elements':node['elements'],'sequence_high':state['sequence_high'],
            'bindings_verified':ready,'proxy_verified':ready and bool(node.get('proxy_enabled'))}
        if ready and node.get('temperature_profile'):payload['temperature_profile']=node['temperature_profile']
        await self.ha.rest('/api/services/tuesly/import_commissioning',payload)
    async def recover(self,enrolled,*,unprovisioned_confirmed=False):
        mac=enrolled['address'];provider=self.options['provider_entry'];target_entry=enrolled['entry_id']
        entries=await self.ha.ws({'type':'config_entries/get'})
        original={e['entry_id']:e['disabled_by'] for e in entries if e['entry_id'] in (provider,target_entry)}
        if len(original)!=2 or any(v is not None for v in original.values()):return
        record=self.records.setdefault(mac,{})
        if not permitted(record,startup=unprovisioned_confirmed):self.status('rate_limited',address=mac);return
        record['attempts']=[t for t in record.get('attempts',[]) if time.time()-t<86400]+[time.time()]
        record['retry_after']=time.time()+60;save(DATA/'attempts.json',self.records)
        save(DATA/'transaction.json',{'provider':provider,'target':target_entry,'original':original})
        api=None;adapter=None;cancel=None;cancel_ads=None;provisioner=None;configured=False
        credentials_delivered=False;operation_stage='transport';configurator=None
        try:
            self.status('pausing_controller',address=mac)
            await self.ha.disable(target_entry,'user');await self.ha.disable(provider,'user')
            # The user authorized this exact custom mesh Store file. Read only.
            state=json.loads(MESH_FILE.read_text())['data']
            if mac not in state['nodes']:raise RuntimeError('Device is not enrolled in HA mesh')
            if unprovisioned_confirmed and state['address_next']+254>=SOURCE:raise RuntimeError('Fresh unicast address capacity exhausted')
            node=state['nodes'][mac]
            api=APIClient(self.options['proxy_ip'],6053,noise_psk=self.options['proxy_key'],client_info='tuesly-automatic-recovery')
            operation_stage='connecting proxy API'
            await asyncio.wait_for(api.connect(login=True),12)
            # Firmware 1.1.8 checks for a live API state subscriber after HA
            # connects. We deliberately paused HA to own GATT: maintain that
            # subscription during the bounded maintenance session so its
            # watchdog cannot reboot the board in the middle of commissioning.
            api.subscribe_states(lambda state:None)
            operation_stage='reading proxy capabilities'
            info=await asyncio.wait_for(api.device_info(),8)
            capabilities=await asyncio.wait_for(api.device_capabilities_compat(info),8)
            target=int(mac.replace(':',''),16)
            cancel_ads=api.subscribe_bluetooth_le_raw_advertisements(lambda message:None)
            api.bluetooth_scanner_set_mode(BluetoothScannerMode.ACTIVE)
            def changed(connected,mtu,error):
                if not connected and adapter:
                    adapter.is_connected=False
                    if adapter.disconnected:adapter.disconnected(adapter)
            async def open_gatt():
                nonlocal adapter,cancel,operation_stage
                operation_stage='connecting driver GATT'
                self.status('connecting_gatt',address=mac)
                cancel=await api.bluetooth_device_connect(target,changed,timeout=15,feature_flags=capabilities.bluetooth_proxy.feature_flags,has_cache=False,address_type=0)
                operation_stage='discovering driver GATT services'
                self.status('discovering_gatt',address=mac)
                services=await asyncio.wait_for(api.bluetooth_gatt_get_services(target),10)
                adapter=GATT(api,target,services)
                return adapter
            await open_gatt()
            journal=await MeshJournal(Store(state)).load()
            def device_for(node):
                secrets=DictSecretsManager({'recovery-net-key/password':state['net_key'],'recovery-app-key/password':state['app_key'],
                    f'recovery-dev-key-{node["address"]:04x}/password':node['dev_key']})
                async def connected(device,disconnected_callback=None):adapter.disconnected=disconnected_callback;return adapter
                device=ManagedMeshDevice(mac,node['address'],SOURCE,secrets,op_item_prefix='recovery',iv_index=state['iv_index'],journal=journal,
                    ble_device_callback=lambda address:types.SimpleNamespace(address=address),ble_connect_callback=connected)
                device._node_primary=node['address'];return device
            # The automatic trigger already requires a fresh unprovisioned
            # UUID and an unavailable enrolled HA light. Follow the proven
            # manual PB-GATT sequence directly; an extra Proxy session first
            # was disturbing the driver's provisioning notification setup.
            if unprovisioned_confirmed:
                self.status('commissioning',address=mac)
                operation_stage='commissioning'
                address=state['address_next']
                async def connected(device,**kwargs):return adapter
                provisioner=SIGMeshProvisioner(bytes.fromhex(state['net_key']),bytes.fromhex(state['app_key']),address,
                    iv_index=state['iv_index'],ble_device_callback=lambda address:types.SimpleNamespace(address=address),ble_connect_callback=connected)
                async def persist(key,elements):
                    new={'address':address,'dev_key':key.hex(),'elements':elements,'status':'configuration_pending'}
                    receipt={'data':copy.deepcopy(state)};receipt['data']['nodes'][mac]=new;receipt['data']['address_next']=address+255
                    save(DATA/'commissioning.json',receipt)
                    await self.import_node(state,mac,new)
                    state['nodes'][mac]=new
                provisioner.journal_callback=persist
                completion=await asyncio.wait_for(provisioner._run_exchange(adapter),75)
                credentials_delivered=True
                await provisioner._finish_provisioning_bearer(adapter)
                # Match the working operator sequence, including its remote
                # descriptor read barrier before switching GATT services.
                descriptor=next(d for d in provisioner._prov_data_out.descriptors
                    if d.uuid.lower()=='00002902-0000-1000-8000-00805f9b34fb')
                if bytes(await api.bluetooth_gatt_read_descriptor(target,descriptor.handle,timeout=5))!=b'\x00\x00':
                    raise RuntimeError('Provisioning notification cleanup was not confirmed')
                await adapter.disconnect()
                if cancel:cancel();cancel=None
                await open_gatt()
            else:
                self.status('resuming_saved_configuration',address=mac)
                operation_stage='authenticating saved pairing'
            self.status('binding_models',address=mac)
            operation_stage='binding_models'
            # Refresh the independently reserved sender journal for the new node.
            journal=await MeshJournal(Store(state)).load()
            device=device_for(state['nodes'][mac]);await device.connect(max_retries=1);await device.configure_filter()
            configurator=NodeConfigurator(mac,journal,device)
            deadline=provisioner.configuration_deadline if provisioner else asyncio.get_running_loop().time()+75
            async with asyncio.timeout_at(deadline):
                await configurator._configure(bindings_only=True)
            await configurator._configure()
            await configurator._read()
            await self.import_node(state,mac,journal.state['nodes'][mac],ready=True)
            configured=True
            self.status('restoring_ha_control',address=mac)
            record['consecutive_failures']=0
            record['retry_after']=time.time()+10
        except Exception as exc:
            # Exceptions may contain transport values; only their type is public.
            record['consecutive_failures']=record.get('consecutive_failures',0)+1
            record['retry_after']=time.time()+min(300,15*2**min(record['consecutive_failures'],5))
            stage=getattr(provisioner,'stage',operation_stage) if operation_stage=='commissioning' else operation_stage
            if configurator:stage=configurator.stage
            record['last_failure']={'failure_type':type(exc).__name__,'stage':stage,'at':time.time()}
            if error:=getattr(exc,'error',None):
                record['last_failure']['gatt']={name:getattr(error,name,None) for name in ('handle','error')}
            self.status('recovery_failed',address=mac,**record['last_failure'])
            LOG.warning('Recovery stopped: %s at %s',record['last_failure']['failure_type'],record['last_failure']['stage'])
        finally:
            if api:
                try:
                    if adapter and adapter.is_connected:await asyncio.wait_for(adapter.disconnect(),6)
                except Exception:pass
                if cancel:cancel()
                if cancel_ads:cancel_ads()
                await api.disconnect(force=True)
            save(DATA/'attempts.json',self.records)
            await asyncio.shield(self.restore())
        if not configured and not credentials_delivered:return
        if not configured:self.status('verifying_ha_configuration',address=mac)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            try:
                light=await self.ha.rest('/api/states/'+enrolled['entity_id'])
                if light['state'] in ('on','off'):
                    record['consecutive_failures']=0;record['retry_after']=time.time()+10
                    save(DATA/'attempts.json',self.records)
                    self.status('recovered',address=mac,configuration_finished_by='app' if configured else 'ha');return
            except Exception:pass
            await asyncio.sleep(3)
        self.status('ha_control_unavailable',address=mac,last_failure=record.get('last_failure'))
    async def watch_advertisements(self):
        while True:
            try:
                url=self.ha.base.replace('http:','ws:').replace('https:','wss:')+'/api/websocket'
                async with websockets.connect(url,max_size=8*1024*1024) as stream:
                    await stream.recv()
                    await stream.send(json.dumps({'type':'auth','access_token':self.ha.token}))
                    if json.loads(await stream.recv()).get('type')!='auth_ok':raise RuntimeError('HA authentication failed')
                    await stream.send(json.dumps({'id':1,'type':'bluetooth/subscribe_advertisements'}))
                    async for encoded in stream:
                        message=json.loads(encoded)
                        if message.get('type')=='result':
                            if not message.get('success'):raise RuntimeError('Bluetooth subscription refused')
                            LOG.info('Live HA advertisement subscription ready')
                        for event in message.get('event',{}).get('add',[]):
                            # The HA manager may forward the best scanner's
                            # packet. All scanners are HA-managed; GATT below
                            # still uses only the explicitly configured ESP32.
                            if observe_live_event(event,self.options['enrolled'],self.evidence,self.proxy_evidence):
                                self.radio_changed.set()
            except Exception as exc:
                LOG.warning('Advertisement stream retry: %s',type(exc).__name__)
                await asyncio.sleep(3)

    async def run(self):
        listener=asyncio.create_task(self.watch_advertisements())
        try:await self.monitor()
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):await listener

    async def monitor(self):
        await self.restore()
        self.status('watching')
        while True:
            try:
                if not self.options['enabled']:
                    await asyncio.sleep(5);continue
                diagnostics=await self.ha.rest('/api/diagnostics/config_entry/'+self.options['bluetooth_entry'])
                scanners=diagnostics['data']['manager']['scanners']
                scanner=next((s for s in scanners if s.get('source','').upper()==self.options['proxy_source'].upper()),None)
                if scanner is None:
                    await asyncio.sleep(3);continue
                entries=await self.ha.ws({'type':'config_entries/get'})
                enabled={e['entry_id'] for e in entries if e['disabled_by'] is None}
                enrolled_entities={device['entity_id'] for device in self.options['enrolled']}
                states={state['entity_id']:state for state in await self.ha.rest('/api/states')
                        if state['entity_id'] in enrolled_entities}
                nodes=json.loads(MESH_FILE.read_text())['data']['nodes']
                for enrolled in self.options['enrolled']:
                    mac=enrolled['address'];entry=enrolled['entry_id']
                    if entry not in enabled or self.options['provider_entry'] not in enabled:continue
                    # Capture the short startup window even while HA is still
                    # displaying its last successful state. Never replace a
                    # working identity solely because a packet was seen.
                    startup=remember_startup(self.evidence,scanner,enrolled)
                    light=states.get(enrolled['entity_id'])
                    pending=(nodes.get(mac,{}).get('status')=='configuration_pending'
                             and time.monotonic()-self.proxy_evidence.get(mac,float('-inf'))<=30)
                    if light is None or light['state']!='unavailable' or not (startup or pending):continue
                    if permitted(self.records.get(mac,{}),startup=startup):
                        self.evidence.pop(mac,None)
                        async with asyncio.timeout(240):await self.recover(enrolled,unprovisioned_confirmed=startup)
                status_path=DATA/'status.json'
                status=json.loads(status_path.read_text())
                status.update(last_monitor_at=time.time(),proxy_scanning=True)
                save(status_path,status)
            except Exception as exc:
                LOG.warning('Monitor retry: %s',type(exc).__name__)
                # Recover original HA entry flags if a transport timeout escaped.
                try:await self.restore()
                except Exception:LOG.warning('HA restoration pending; retrying')
            try:await asyncio.wait_for(self.radio_changed.wait(),2)
            except TimeoutError:pass
            self.radio_changed.clear()

async def run_service(options):
    recovery=Recovery(options)
    task=asyncio.create_task(recovery.run())
    stop=asyncio.Event()
    loop=asyncio.get_running_loop()
    for signum in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(signum,stop.set)
    stopped=asyncio.create_task(stop.wait())
    done,_=await asyncio.wait((task,stopped),return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        stopped.cancel();await task
    else:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):await task
        await recovery.restore()
        recovery.status('stopped')

def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.WARNING)
    LOG.setLevel(logging.INFO)
    options=json.loads((DATA/'options.json').read_text())
    for device in options['enrolled']:
        device['address']=device['address'].upper()
        if len(bytes.fromhex(device['uuid']))!=16 or not device['uuid'].lower().startswith(device['address'].replace(':','').lower()):
            raise RuntimeError('Enrollment UUID does not match the device address')
    asyncio.run(run_service(options))
if __name__=='__main__':main()
