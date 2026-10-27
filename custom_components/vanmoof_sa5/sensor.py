"""Sensor entities for VanMoof SA5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VanMoofDataUpdateCoordinator
from .entity import VanMoofEntity


@dataclass(frozen=True, kw_only=True)
class VanMoofSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Any], Any]
    attributes_fn: Callable[[Any], dict[str, Any]] | None = None


SENSORS: tuple[VanMoofSensorDescription, ...] = (
    VanMoofSensorDescription(
        key="battery",
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.battery_level,
    ),
    VanMoofSensorDescription(
        key="module_battery",
        translation_key="module_battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.module_battery,
    ),
    VanMoofSensorDescription(
        key="distance",
        translation_key="distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda state: state.distance_km,
    ),
    VanMoofSensorDescription(
        key="lock_state",
        translation_key="lock_state",
        device_class=SensorDeviceClass.ENUM,
        options=["locked", "unlocking", "unlocked"],
        value_fn=lambda state: state.lock_state,
    ),
    VanMoofSensorDescription(
        key="bike_state",
        translation_key="bike_state",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "shipping", "standby", "on"],
        value_fn=lambda state: state.bike_state,
    ),
    VanMoofSensorDescription(
        key="region",
        translation_key="region",
        device_class=SensorDeviceClass.ENUM,
        options=["eu", "us", "japan", "offroad"],
        value_fn=lambda state: state.region,
    ),
    VanMoofSensorDescription(
        key="speed_limit",
        translation_key="speed_limit",
        value_fn=lambda state: state.speed_limit,
    ),
    VanMoofSensorDescription(
        key="power_level",
        translation_key="power_level",
        value_fn=lambda state: state.power_level,
    ),
    VanMoofSensorDescription(
        key="light_mode",
        translation_key="light_mode",
        value_fn=lambda state: state.light_mode,
    ),
    VanMoofSensorDescription(
        key="connection_state",
        translation_key="connection_state",
        value_fn=lambda state: state.connection_state,
    ),
    VanMoofSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.last_seen,
    ),
    VanMoofSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.firmware_version,
    ),
    VanMoofSensorDescription(
        key="find_my_version",
        translation_key="find_my_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.find_my_version,
    ),
    VanMoofSensorDescription(
        key="firmware_info",
        translation_key="firmware_info",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.firmware_info,
    ),
    VanMoofSensorDescription(
        key="errors",
        translation_key="errors",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.error_count,
        attributes_fn=lambda state: {
            "bike_errors": state.bike_errors,
            "connection_error": state.errors,
        },
    ),
)



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VanMoofDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for bike_id in coordinator.data.bikes:
        entities.extend(VanMoofSensor(coordinator, bike_id, description) for description in SENSORS)
    async_add_entities(entities)


class VanMoofSensor(VanMoofEntity, SensorEntity):
    """VanMoof sensor entity."""

    entity_description: VanMoofSensorDescription

    def __init__(
        self,
        coordinator: VanMoofDataUpdateCoordinator,
        bike_id: str,
        description: VanMoofSensorDescription,
    ) -> None:
        super().__init__(coordinator, bike_id)
        self.entity_description = description
        self._attr_unique_id = f"{bike_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.bike_state)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.bike_state)

    @property
    def available(self) -> bool:
        if self.entity_description.key in ("connection_state", "last_seen", "errors"):
            return True
        return self.bike_state.available

