"""Firmware update entity for VanMoof SA5.

Shows the installed firmware and whether the bike reports a newer one.
Installing is not supported on purpose: flashing the bike over Bluetooth can
brick it if the transfer breaks, so updates are done with the VanMoof app.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VanMoofDataUpdateCoordinator
from .entity import VanMoofEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VanMoofDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VanMoofFirmwareUpdate(coordinator, bike_id) for bike_id in coordinator.data.bikes
    )


class VanMoofFirmwareUpdate(VanMoofEntity, UpdateEntity):
    """Firmware of the bike (read only)."""

    _attr_translation_key = "firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VanMoofDataUpdateCoordinator, bike_id: str) -> None:
        super().__init__(coordinator, bike_id)
        self._attr_unique_id = f"{bike_id}_firmware_update"

    @property
    def available(self) -> bool:
        return self.installed_version is not None

    @property
    def installed_version(self) -> str | None:
        return self.bike_state.firmware_version

    @property
    def latest_version(self) -> str | None:
        # The bike only publishes topic 20496 when it knows of a newer version.
        return self.bike_state.update_available or self.installed_version

    @property
    def release_summary(self) -> str | None:
        if self.latest_version != self.installed_version:
            return "Install the update with the VanMoof app."
        return None
