"""Base entity for Tuesly devices.

All entity platforms (light, switch, sensor) inherit from TueslyEntity
which extends CoordinatorEntity for automatic state update handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from custom_components.tuesly.coordinator import TueslyCoordinator


class TueslyEntity(CoordinatorEntity["TueslyCoordinator"]):
    """Base entity for Tuesly devices.

    Provides automatic state update handling via CoordinatorEntity.
    Subclasses get async_write_ha_state() called whenever the coordinator
    dispatches async_set_updated_data().
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TueslyCoordinator,
        entry_id: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize the base entity.

        Args:
            coordinator: Coordinator managing the BLE mesh device state.
            entry_id: Config entry ID used to scope the unique entity ID.
            device_info: Device registry info for grouping entities under a device.
        """
        super().__init__(coordinator)
        self._entry_id = entry_id
        if device_info is not None:
            self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        """Return True if the device is available."""
        return self.coordinator.state.available
