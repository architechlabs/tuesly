import asyncio,copy,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
ADDON=Path(__file__).resolve().parents[1]/'addons/tuesly_recovery'
sys.path[:0]=[str(ADDON),str(ADDON/'lib')]
from policy import unprovisioned_uuid,radio_evidence,permitted,remember_startup,observe_live_event
import service

UUID='dc23528160bb5112626c627474626779'
MAC='DC:23:52:81:60:BB'
DEVICE={'address':MAC,'uuid':UUID}

class PolicyTests(unittest.TestCase):
    def test_live_startup_is_retained_when_vendor_packet_replaces_it(self):
        payload=b'\x2b\x00'+bytes.fromhex(UUID)+b'\x00\x00'
        event={'address':MAC,'time':1000,'raw':(bytes([len(payload)])+payload).hex(),'source':'native'}
        pending={};proxies={}
        self.assertTrue(observe_live_event(event,[DEVICE],pending,proxies,now=1001,monotonic=50))
        event.update(raw='020106',time=1002)
        self.assertFalse(observe_live_event(event,[DEVICE],pending,proxies,now=1002,monotonic=51))
        self.assertEqual(pending[MAC]['expires'],170)
        self.assertEqual(proxies,{})

    def test_live_packet_rejects_cached_and_merged_provisioning_data(self):
        payload=b'\x2b\x00'+bytes.fromhex(UUID)+b'\x00\x00'
        event={'address':MAC,'time':1000,'raw':(bytes([len(payload)])+payload).hex()}
        self.assertFalse(observe_live_event(event,[DEVICE],{}, {},now=1011))
        event.update(raw='020106',service_data={'00001827':UUID})
        self.assertFalse(observe_live_event(event,[DEVICE],{}, {},now=1001))

    def test_resume_requires_real_connectable_proxy_service_packet(self):
        event={'address':MAC,'time':1000,'raw':'0c16281800'+'11'*8,'connectable':True}
        pending={};proxies={}
        self.assertTrue(observe_live_event(event,[DEVICE],pending,proxies,now=1001,monotonic=50))
        self.assertEqual(proxies[MAC],50)
        self.assertEqual(pending,{})
        event['connectable']=False
        self.assertFalse(observe_live_event(event,[DEVICE],{}, {},now=1001))

    def test_startup_survives_ha_state_delay_but_expires(self):
        payload=b'\x2b\x00'+bytes.fromhex(UUID)+b'\x00\x00'
        scanner={'monotonic_time':102,'discovered_device_timestamps':{MAC:101},
                 'raw_advertisement_data':{MAC:{'repr':repr(bytes([len(payload)])+payload)}}}
        pending={}
        self.assertTrue(remember_startup(pending,scanner,DEVICE,now=1000))
        scanner['raw_advertisement_data'][MAC]={'repr':repr(b'\x02\x01\x06')}
        scanner['monotonic_time']=170
        self.assertTrue(remember_startup(pending,scanner,DEVICE,now=1068))
        self.assertFalse(remember_startup(pending,scanner,DEVICE,now=1121))
        self.assertNotIn(MAC,pending)

    def test_accepts_complete_fresh_pb_gatt_service_data(self):
        payload=b'\x16\x27\x18'+bytes.fromhex(UUID)+b'\x00\x00'
        raw=bytes([len(payload)])+payload
        scanner={'monotonic_time':102,'discovered_device_timestamps':{MAC:101},
                 'raw_advertisement_data':{MAC:{'repr':repr(raw)}}}
        self.assertEqual(radio_evidence(scanner,DEVICE),101)
        scanner['monotonic_time']=112
        self.assertIsNone(radio_evidence(scanner,DEVICE))

    def test_real_unprovisioned_beacon_accepted_vendor_frame_rejected(self):
        payload=b'\x2b\x00'+bytes.fromhex(UUID)+b'\x00\x00'
        self.assertEqual(unprovisioned_uuid(bytes([len(payload)])+payload),UUID)
        vendor=b'\x03\x40'+bytes.fromhex(MAC.replace(':',''))+b'blbttbgy'
        self.assertIsNone(unprovisioned_uuid(bytes([len(vendor)])+vendor))

    def test_bogus_merged_uuid_and_wrong_device_do_not_trigger(self):
        scanner={'monotonic_time':5,'service_uuids':['00001827'],
                 'discovered_device_timestamps':{MAC:5},'raw_advertisement_data':{}}
        self.assertIsNone(radio_evidence(scanner,DEVICE))
        payload=b'\x2b\x00'+bytes.fromhex('11'*16)+b'\x00\x00'
        scanner['raw_advertisement_data'][MAC]={'repr':repr(bytes([len(payload)])+payload)}
        self.assertIsNone(radio_evidence(scanner,DEVICE))

    def test_malformed_packets_fail_closed(self):
        for raw in (b'',b'\xff\x16\x27\x18',b'\x03\x16\x27\x18'):
            self.assertIsNone(unprovisioned_uuid(raw))

    def test_retry_and_daily_limits(self):
        self.assertTrue(permitted({},10000))
        self.assertFalse(permitted({'retry_after':10001},10000))
        self.assertTrue(permitted({'attempts':[9990,9980,9970]},10000))
        self.assertTrue(permitted({'attempts':[5000]*12},10000))
        self.assertTrue(permitted({'attempts':[0]*12},100000))
        record={'retry_after':10300,'last_failure':{'at':10000}}
        self.assertFalse(permitted(record,10016))
        self.assertTrue(permitted(record,10016,startup=True))
        self.assertFalse(permitted(record,10005,startup=True))

class DurabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_without_reset_evidence_preserves_identity(self):
        await self.run_recovery_path(service.MeshConnectionError('link closed'),expect_success=False)

    async def test_timeout_without_reset_evidence_preserves_identity(self):
        await self.run_recovery_path(TimeoutError(),expect_success=False)

    async def test_saved_configuration_resumes_without_recommissioning(self):
        await self.run_recovery_path(None)

    async def test_confirmed_unprovisioned_event_uses_exact_direct_sequence(self):
        await self.run_recovery_path(None,confirmed=True)

    async def test_ha_can_finish_configuration_after_completed_exchange(self):
        await self.run_recovery_path(None,confirmed=True,binding_error=TimeoutError())

    async def run_recovery_path(self,filter_error,confirmed=False,binding_error=None,expect_success=True):
        from unittest.mock import AsyncMock,MagicMock
        mesh={'data':{'net_key':'11'*16,'app_key':'22'*16,'iv_index':0,'address_next':257,'sequence_high':10000,
             'nodes':{MAC:{'address':2,'elements':6,'dev_key':'33'*16,'status':'ready'}}}}
        options={'ha_url':'http://example','ha_token':'private','provider_entry':'proxy','proxy_ip':'192.0.2.1','proxy_key':'private'}
        enrolled={**DEVICE,'entry_id':'light','entity_id':'light.test'}
        api=MagicMock();api.connect=AsyncMock();api.device_info=AsyncMock()
        api.device_capabilities_compat=AsyncMock(return_value=types.SimpleNamespace(bluetooth_proxy=types.SimpleNamespace(feature_flags=0)))
        api.bluetooth_device_connect=AsyncMock(return_value=lambda:None)
        api.bluetooth_gatt_get_services=AsyncMock(return_value=types.SimpleNamespace(services=[]))
        api.bluetooth_device_disconnect=AsyncMock();api.disconnect=AsyncMock()
        api.bluetooth_gatt_read_descriptor=AsyncMock(return_value=b'\x00\x00')
        first=types.SimpleNamespace(connect=AsyncMock(),configure_filter=AsyncMock(side_effect=filter_error),disconnect=AsyncMock())
        second=types.SimpleNamespace(connect=AsyncMock(),configure_filter=AsyncMock(),disconnect=AsyncMock())
        provisioner=types.SimpleNamespace(_finish_provisioning_bearer=AsyncMock(),configuration_deadline=asyncio.get_running_loop().time()+30,stage='complete')
        provisioner._prov_data_out=types.SimpleNamespace(descriptors=[types.SimpleNamespace(uuid='00002902-0000-1000-8000-00805f9b34fb',handle=21)])
        async def exchange(adapter):
            await provisioner.journal_callback(bytes.fromhex('44'*16),6)
            return types.SimpleNamespace(num_elements=6)
        provisioner._run_exchange=AsyncMock(side_effect=exchange)
        def configurator(mac,journal,device):
            async def configure(**kwargs):
                if binding_error:raise binding_error
                await journal.update(mac,status='ready',binding_revision=3,proxy_enabled=True)
            return types.SimpleNamespace(_configure=configure,_read=AsyncMock(),stage='binding model')
        with tempfile.TemporaryDirectory() as directory,patch.object(service,'DATA',Path(directory)),patch.object(service,'MESH_FILE',Path(directory)/'mesh.json'):
            service.MESH_FILE.write_text(json.dumps(mesh))
            recovery=service.Recovery(options)
            recovery.ha=types.SimpleNamespace(ws=AsyncMock(return_value=[{'entry_id':'proxy','disabled_by':None},{'entry_id':'light','disabled_by':None}]),
                disable=AsyncMock(),rest=AsyncMock(return_value={'state':'on'}))
            with patch.object(service,'APIClient',return_value=api),patch.object(service,'ManagedMeshDevice',side_effect=[second] if confirmed else [first,second]),patch.object(service,'SIGMeshProvisioner',return_value=provisioner),patch.object(service,'NodeConfigurator',side_effect=configurator):
                await recovery.recover(enrolled,unprovisioned_confirmed=confirmed)
            api.subscribe_states.assert_called_once()
            if confirmed:
                first.configure_filter.assert_not_awaited()
                api.connect.assert_awaited_once()
            if confirmed:provisioner._run_exchange.assert_awaited_once()
            else:
                provisioner._run_exchange.assert_not_awaited()
                self.assertFalse((service.DATA/'commissioning.json').exists())
            status=json.loads((service.DATA/'status.json').read_text())
            self.assertEqual(status['phase'],'recovered' if expect_success else 'recovery_failed')
            if expect_success:
                self.assertEqual(status['configuration_finished_by'],'ha' if binding_error else 'app')
                self.assertEqual(recovery.records[MAC]['consecutive_failures'],0)
            self.assertFalse((service.DATA/'transaction.json').exists())
            self.assertEqual(recovery.ha.disable.await_args_list[-2].args,('proxy',None))
            self.assertEqual(recovery.ha.disable.await_args_list[-1].args,('light',None))

    async def test_original_flags_restore_after_service_restart(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(service,'DATA',Path(directory)):
            service.save(service.DATA/'transaction.json',{'provider':'proxy','target':'light','original':{'proxy':None,'light':None}})
            recovery=service.Recovery({'ha_url':'http://example','ha_token':'private'})
            calls=[]
            async def disable(entry,value):calls.append((entry,value))
            recovery.ha=types.SimpleNamespace(disable=disable)
            await recovery.restore()
            self.assertEqual(calls,[('proxy',None),('light',None)])
            self.assertFalse((service.DATA/'transaction.json').exists())

    async def test_protocol_sender_sequences_skip_unused_lease_after_restart(self):
        state={'net_key':'11'*16,'app_key':'22'*16,'iv_index':0,'address_next':257,'sequence_high':10000,
               'nodes':{MAC:{'address':2,'elements':6,'dev_key':'33'*16}}}
        with tempfile.TemporaryDirectory() as directory,patch.object(service,'DATA',Path(directory)):
            first=await service.MeshJournal(service.Store(state)).load()
            self.assertEqual(await first.allocate_sequences(),0)
            second=await service.MeshJournal(service.Store(state)).load()
            self.assertEqual(await second.allocate_sequences(),256)
            self.assertEqual(state['sequence_high'],10000)

    async def test_new_identity_does_not_inherit_old_replay_window(self):
        state={'net_key':'11'*16,'app_key':'22'*16,'iv_index':0,'sequence_high':0,
               'nodes':{MAC:{'address':2,'elements':6,'dev_key':'33'*16}}}
        with tempfile.TemporaryDirectory() as directory,patch.object(service,'DATA',Path(directory)):
            old=copy.deepcopy(state);old['nodes'][MAC]['received']={'2':[99,1]}
            service.save(service.DATA/'protocol.json',old)
            state['nodes'][MAC].update(address=257,dev_key='44'*16)
            current=await service.Store(state).async_load()
            self.assertNotIn('received',current['nodes'][MAC])

if __name__=='__main__':unittest.main()
