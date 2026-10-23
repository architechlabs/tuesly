import types,unittest
from unittest.mock import MagicMock,patch
from test_mesh_controller import controller_modules
from test_transport import load_ha_module

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        controller_modules()
        self.module=load_ha_module('custom_components.tuesly.sig_recovery','sig_recovery.py')
        self.entry=types.SimpleNamespace(entry_id='entry',data={'mac_address':'MAC'},
            disabled_by=None,state=types.SimpleNamespace(value='setup_retry'))
        self.hass=types.SimpleNamespace(data={},is_stopping=False,bus=types.SimpleNamespace(async_listen_once=MagicMock()),config_entries=types.SimpleNamespace(
            async_get_entry=MagicMock(return_value=self.entry),async_schedule_reload=MagicMock()))
        self.callbacks=[];self.cancel=MagicMock()
        def register(hass,callback,*args):self.callbacks.append(callback);return self.cancel
        self.registration=patch.object(self.module.bluetooth,'async_register_callback',side_effect=register)
        self.registration.start();self.addCleanup(self.registration.stop)

    def test_fresh_discovery_wakes_retry_once_and_throttles_advertisement_burst(self):
        self.module.ensure_recovery_listener(self.hass,self.entry)
        self.module.ensure_recovery_listener(self.hass,self.entry)
        self.assertEqual(len(self.callbacks),1)
        with patch.object(self.module.time,'monotonic',return_value=100):
            self.callbacks[0](types.SimpleNamespace(time=0),None)
            self.hass.config_entries.async_schedule_reload.assert_not_called()
            for _ in range(10):self.callbacks[0](types.SimpleNamespace(time=100),None)
        self.hass.config_entries.async_schedule_reload.assert_called_once_with('entry')

    def test_disabled_loaded_and_setup_in_progress_entries_are_not_reloaded(self):
        self.module.ensure_recovery_listener(self.hass,self.entry)
        for state in ('loaded','setup_in_progress','not_loaded'):
            self.entry.state.value=state
            self.callbacks[0](types.SimpleNamespace(time=100),None)
        self.entry.state.value='setup_retry';self.entry.disabled_by='user'
        self.callbacks[0](types.SimpleNamespace(time=100),None)
        self.hass.config_entries.async_schedule_reload.assert_not_called()

    def test_removed_entry_unregisters_listener(self):
        self.module.ensure_recovery_listener(self.hass,self.entry)
        self.hass.config_entries.async_get_entry.return_value=None
        self.callbacks[0](types.SimpleNamespace(time=100),None)
        self.cancel.assert_called_once()
        self.assertEqual(self.hass.data['tuesly_mesh_recovery'],{})

    def test_shutdown_does_not_schedule_reloads_and_removes_scanner(self):
        self.module.ensure_recovery_listener(self.hass,self.entry)
        self.hass.is_stopping=True
        with patch.object(self.module.time,'monotonic',return_value=100):
            self.callbacks[0](types.SimpleNamespace(time=100),None)
        self.hass.config_entries.async_schedule_reload.assert_not_called()
        callback=self.hass.bus.async_listen_once.call_args.args[1]
        callback(None)
        self.cancel.assert_called_once()
        self.assertEqual(self.hass.data['tuesly_mesh_recovery'],{})
