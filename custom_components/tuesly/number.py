"""Uniform warm-to-cool control without per-fixture Kelvin calibration."""
from homeassistant.components.number import NumberEntity,NumberMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity

async def async_setup_entry(hass,entry,async_add_entities):
    if entry.data.get('device_type')!='sig_light':
        return
    coordinator=entry.runtime_data
    if coordinator.models.temperature:
        async_add_entities([WhiteTemperature(coordinator,entry)])

class WhiteTemperature(CoordinatorEntity,NumberEntity):
    _attr_name='White temperature'
    _attr_has_entity_name=True
    _attr_icon='mdi:thermometer-lines'
    _attr_native_min_value=0
    _attr_native_max_value=100
    _attr_native_step=1
    _attr_native_unit_of_measurement='%'
    _attr_mode=NumberMode.SLIDER

    def __init__(self,coordinator,entry):
        super().__init__(coordinator)
        self._attr_unique_id=f'{entry.unique_id}_white_temperature'
        self._attr_device_info={'identifiers':{('tuesly',entry.unique_id)}}

    @property
    def native_value(self):
        return self.coordinator.data.get('temperature_percent')

    @property
    def extra_state_attributes(self):
        return {'warm_endpoint':0,'cool_endpoint':100}

    async def async_set_native_value(self,value):
        await self.coordinator.command(temperature_percent=value)
