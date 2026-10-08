"""Standard white-light entity, with state confirmed by mesh replies."""
from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class SIGLight(CoordinatorEntity, LightEntity):
    _attr_name = None
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f'{entry.unique_id}_sig_light'
        self._attr_device_info = dict(identifiers={('tuesly', entry.unique_id)},
                                     name=entry.title, manufacturer='Tuya', model='SIG Mesh white light')
        mode = ColorMode.COLOR_TEMP if coordinator.models.temperature else (
            ColorMode.BRIGHTNESS if coordinator.models.lightness else ColorMode.ONOFF)
        self._attr_supported_color_modes = {mode}
        self._attr_color_mode = mode
        if coordinator.minimum_kelvin is not None:
            self._attr_min_color_temp_kelvin = coordinator.minimum_kelvin
            self._attr_max_color_temp_kelvin = coordinator.maximum_kelvin

    @property
    def is_on(self):
        return self.coordinator.data.get('on')

    @property
    def brightness(self):
        return self.coordinator.data.get('brightness')

    @property
    def color_temp_kelvin(self):
        return self.coordinator.data.get('kelvin')

    async def async_turn_on(self, **kwargs):
        await self.coordinator.command(on=True, brightness=kwargs.get('brightness'),
                                       kelvin=kwargs.get('color_temp_kelvin'))

    async def async_turn_off(self, **kwargs):
        await self.coordinator.command(on=False)
