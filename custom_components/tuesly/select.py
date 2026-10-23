"""Driver-native startup behavior; no delayed HA state replay."""
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

async def async_setup_entry(hass,entry,async_add_entities):
    if entry.data.get('device_type')=='sig_light' and entry.runtime_data.power_up_supported:
        async_add_entities([PowerOnBehavior(entry.runtime_data,entry)])

class PowerOnBehavior(CoordinatorEntity,SelectEntity):
    _attr_name='Power-on behavior'
    _attr_has_entity_name=True
    _attr_entity_category=EntityCategory.CONFIG
    _attr_icon='mdi:power-settings'
    _attr_options=['Restore previous','Off','On (device defaults)']
    _values={'Restore previous':'restore','Off':'off','On (device defaults)':'on'}

    def __init__(self,coordinator,entry):
        super().__init__(coordinator)
        self._attr_unique_id=f'{entry.unique_id}_power_on_behavior'
        self._attr_device_info={'identifiers':{('tuesly',entry.unique_id)}}

    @property
    def current_option(self):
        value=self.coordinator.journal.state['nodes'][self.coordinator.mac].get('power_up_behavior','restore')
        return next(label for label,stored in self._values.items() if stored==value)

    async def async_select_option(self,option):
        await self.coordinator.set_power_up_behavior(self._values[option])
