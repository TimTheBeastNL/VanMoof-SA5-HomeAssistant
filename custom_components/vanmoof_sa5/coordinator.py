"""Coordinator for the VanMoof SA5 integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import VanMoofApiClient, VanMoofApiError
from .ble import VanMoofBikeBleClient, VanMoofBleConnectError, VanMoofBleError
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)
from .models import BikeState, VanMoofBike

_LOGGER = logging.getLogger(__name__)


def _connection_state_for(err: VanMoofBleError) -> str:
    if isinstance(err, VanMoofBleConnectError):
        return "unreachable"
    if "No nearby VanMoof BLE advertisements were found" in str(err):
        return "out_of_range"
    return "error"


@dataclass(slots=True)
class VanMoofCoordinatorData:
    """Coordinator payload."""

    bikes: dict[str, VanMoofBike]
    states: dict[str, BikeState]


class VanMoofDataUpdateCoordinator(DataUpdateCoordinator[VanMoofCoordinatorData]):
    """Coordinator that refreshes bikes sequentially over BLE."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: VanMoofApiClient,
    ) -> None:
        self.entry = entry
        self.api = api
        self._ble_locks: dict[str, asyncio.Lock] = {}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    def _lock_for(self, bike_id: str) -> asyncio.Lock:
        return self._ble_locks.setdefault(bike_id, asyncio.Lock())

    async def _async_update_data(self) -> VanMoofCoordinatorData:
        try:
            await self.api.async_ensure_certificates(list(self.api.bikes.values()))
        except VanMoofApiError as err:
            if "401" in str(err) or "403" in str(err):
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err

        states: dict[str, BikeState] = {}
        for bike in self.api.bikes.values():
            previous_state = self.data.states.get(bike.unique_id) if self.data else None
            try:
                async with self._lock_for(bike.unique_id):
                    state, address = await VanMoofBikeBleClient(
                        bike, self.hass
                    ).async_fetch_state()
                if address and bike.ble_address != address:
                    bike.ble_address = address
                state.last_seen = dt_util.utcnow()
                state.carry_over(previous_state)
                states[bike.unique_id] = state
            except VanMoofBleError as err:
                state = BikeState(
                    available=False,
                    in_range=False,
                    connection_state=_connection_state_for(err),
                    errors=str(err),
                )
                state.carry_over(previous_state)
                states[bike.unique_id] = state

        self.hass.async_create_task(self._async_persist_entry())
        return VanMoofCoordinatorData(
            bikes=dict(self.api.bikes), states=states
        )

    async def _async_persist_entry(self) -> None:
        new_data = self.api.export_entry_data()
        if new_data != self.entry.data:
            self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    async def async_manual_refresh(self) -> None:
        """Run an immediate refresh."""
        await self.async_request_refresh()

