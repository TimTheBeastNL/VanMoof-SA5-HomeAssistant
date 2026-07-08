"""Shared entity helpers for VanMoof SA5."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VanMoofCoordinatorData, VanMoofDataUpdateCoordinator
from .models import BikeState, VanMoofBike


class VanMoofEntity(CoordinatorEntity[VanMoofDataUpdateCoordinator]):
    """Base entity bound to one bike."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VanMoofDataUpdateCoordinator, bike_id: str) -> None:
        super().__init__(coordinator)
        self._bike_id = bike_id

    @property
    def bike(self) -> VanMoofBike:
        return self.coordinator.data.bikes[self._bike_id]

    @property
    def bike_state(self) -> BikeState:
        return self.coordinator.data.states.get(
            self._bike_id,
            BikeState(available=False, in_range=False),
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.bike.unique_id)},
            name=self.bike.name,
            manufacturer="VanMoof",
            model=self.bike.display_model,
            serial_number=self.bike.frame_number,
            sw_version=self.bike_state.firmware_info,
        )
