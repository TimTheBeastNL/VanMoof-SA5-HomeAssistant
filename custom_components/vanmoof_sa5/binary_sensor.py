"""Binary sensors for VanMoof SA5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VanMoofDataUpdateCoordinator
from .entity import VanMoofEntity


@dataclass(frozen=True, kw_only=True)
class VanMoofBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Any], Any]


BINARY_SENSORS: tuple[VanMoofBinarySensorDescription, ...] = (
    VanMoofBinarySensorDescription(
        key="locked",
        translation_key="locked",
        value_fn=lambda state: state.locked,
    ),
    VanMoofBinarySensorDescription(
        key="in_range",
        translation_key="in_range",
        device_class=BinarySensorDeviceClass.PRESENCE,
        value_fn=lambda state: state.in_range,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VanMoofDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[VanMoofBinarySensor] = []
    for bike_id in coordinator.data.bikes:
        entities.extend(
            VanMoofBinarySensor(coordinator, bike_id, description)
            for description in BINARY_SENSORS
        )
    async_add_entities(entities)


class VanMoofBinarySensor(VanMoofEntity, BinarySensorEntity):
    """VanMoof binary sensor."""

    entity_description: VanMoofBinarySensorDescription

    def __init__(
        self,
        coordinator: VanMoofDataUpdateCoordinator,
        bike_id: str,
        description: VanMoofBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, bike_id)
        self.entity_description = description
        self._attr_unique_id = f"{bike_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.bike_state)

    @property
    def available(self) -> bool:
        return self.bike_state.available or self.entity_description.key == "in_range"
