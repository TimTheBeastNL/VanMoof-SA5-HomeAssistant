"""BLE transport for VanMoof SA5/A5 bikes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any, TypeVar

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import (
    APP_CHAR_UUID,
    DEFAULT_SCAN_SECONDS,
    SERVICE_UUID,
    SERVICE_UUID_NODASH,
    WRITE_CHAR_UUID,
)
from .models import BikeState, VanMoofBike
from .protocol import (
    ALL_TOPICS,
    ANIMATION_THEMES,
    BELL_SOUNDS,
    BIKE_STATES,
    LIGHT_MODES,
    LOCK_STATES,
    POWER_LEVEL_OPTIONS,
    REGION_SPEED_LIMITS,
    REGIONS,
    RIDING_DISPLAY_MODES,
    AuthMessage,
    ChallengeMessage,
    FragmentReassembler,
    Topic,
    TopicMessage,
    build_certificate_message,
    build_fragments,
    build_subscribe_message,
    decode_packed_version,
    sign_challenge,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")

# Seconds of silence after which a burst of notifications counts as complete.
_QUIET_SECONDS = 1.5
# How long to wait for the very first notification after subscribing.
_FIRST_MESSAGE_SECONDS = 4.0
_MAX_COLLECT_SECONDS = 8.0


class VanMoofBleError(Exception):
    """Raised when BLE communication fails."""


class VanMoofBleConnectError(VanMoofBleError):
    """Raised when the bike is advertising but does not accept a connection."""


def _looks_like_vanmoof(name: str | None, service_uuids: Iterable[str] | None) -> bool:
    lowered = (name or "").lower()
    services = {service.lower() for service in service_uuids or []}
    return (
        "vanmoof" in lowered
        or lowered.startswith("xs4-")
        or SERVICE_UUID.lower() in services
        or SERVICE_UUID_NODASH.lower() in services
    )


class VanMoofBikeBleClient:
    """Connect to a single VanMoof bike over BLE.

    When ``hass`` is given, devices are discovered through Home Assistant's
    Bluetooth stack, which makes local adapters and ESPHome Bluetooth proxies
    work. Without ``hass`` a plain Bleak scan is used.
    """

    def __init__(self, bike: VanMoofBike, hass: HomeAssistant | None = None) -> None:
        self._bike = bike
        self._hass = hass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def async_fetch_state(self) -> tuple[BikeState, str | None]:
        """Connect, subscribe to all topics and return the current state."""
        topics, address = await self._async_run(self._async_read_topics)
        return self._build_state(topics), address

    async def async_execute_raw_command(self, command_hex: str) -> str | None:
        """Authenticate and send a raw, already framed payload (hex)."""

        async def action(
            client: BleakClient, write_uuid: str, queue: asyncio.Queue[Any]
        ) -> None:
            await client.write_gatt_char(write_uuid, bytes.fromhex(command_hex), response=False)
            await asyncio.sleep(0.5)

        _, address = await self._async_run(action)
        return address

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    async def _async_run(
        self,
        action: Callable[[BleakClient, str, asyncio.Queue[Any]], Awaitable[_T]],
    ) -> tuple[_T, str]:
        """Try every candidate advertisement until one authenticates."""
        candidates = await self._async_discover_candidates()
        if not candidates:
            raise VanMoofBleError("No nearby VanMoof BLE advertisements were found")

        last_error: Exception | None = None
        connect_failed = True
        for candidate in candidates:
            try:
                result = await self._async_with_connection(candidate, action)
                return result, candidate.address
            except Exception as err:  # noqa: BLE001
                last_error = err
                if not isinstance(err, VanMoofBleConnectError):
                    connect_failed = False
                _LOGGER.debug(
                    "Candidate %s did not work for bike %s",
                    candidate.address,
                    self._bike.frame_number,
                    exc_info=True,
                )

        if connect_failed:
            raise VanMoofBleConnectError(
                f"Bike {self._bike.frame_number} is advertising but did not accept a "
                "connection. Close the VanMoof app on your phone (the bike allows only "
                "one Bluetooth connection) or move the Bluetooth adapter or proxy "
                f"closer to the bike. Last error: {last_error}"
            )
        raise VanMoofBleError(
            f"Could not authenticate to bike {self._bike.frame_number}: {last_error}"
        )

    async def _async_with_connection(
        self,
        device: BLEDevice,
        action: Callable[[BleakClient, str, asyncio.Queue[Any]], Awaitable[_T]],
    ) -> _T:
        if not self._bike.certificate or not self._bike.private_key:
            raise VanMoofBleError("Missing certificate or private key for bike")

        queue: asyncio.Queue[Any] = asyncio.Queue()
        reassembler = FragmentReassembler()

        def notification_handler(_: object, payload: bytearray) -> None:
            message = reassembler.feed(bytes(payload))
            if message is not None:
                queue.put_nowait(message)

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                device.name or device.address,
                ble_device_callback=self._fresh_device_callback(device),
            )
        except (BleakError, asyncio.TimeoutError) as err:
            raise VanMoofBleConnectError(str(err)) from err
        try:
            write_uuid = await self._async_authenticate_connection(
                client, queue, notification_handler
            )
            return await action(client, write_uuid, queue)
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()

    def _fresh_device_callback(self, device: BLEDevice) -> Callable[[], BLEDevice]:
        """Return a callback that picks the best adapter or proxy on every retry."""

        def callback() -> BLEDevice:
            if self._hass is None:
                return device
            from homeassistant.components import bluetooth

            return (
                bluetooth.async_ble_device_from_address(
                    self._hass, device.address, connectable=True
                )
                or device
            )

        return callback

    async def _async_read_topics(
        self, client: BleakClient, write_uuid: str, queue: asyncio.Queue[Any]
    ) -> dict[int, Any]:
        await self._async_write_fragments(
            client, write_uuid, build_subscribe_message(ALL_TOPICS)
        )
        topics: dict[int, Any] = {}
        await self._async_collect_topics(queue, topics)
        if not {Topic.BATTERY_LEVEL, Topic.LOCK_STATE, Topic.BIKE_STATE} & topics.keys():
            raise VanMoofBleError("Bike connected but did not return the expected topics")
        return topics

    async def _async_discover_candidates(self) -> list[BLEDevice]:
        if self._hass is not None:
            return self._discover_via_home_assistant()

        discovered = await BleakScanner.discover(
            timeout=DEFAULT_SCAN_SECONDS,
            return_adv=True,
        )

        matched: list[BLEDevice] = []
        stored: BLEDevice | None = None
        for _, (device, advertisement) in discovered.items():
            name = advertisement.local_name or device.name
            if not _looks_like_vanmoof(name, advertisement.service_uuids):
                continue
            if self._bike.ble_address and device.address.lower() == self._bike.ble_address.lower():
                stored = device
            else:
                matched.append(device)

        if stored:
            return [stored, *matched]
        return matched

    def _discover_via_home_assistant(self) -> list[BLEDevice]:
        """Use Home Assistant's Bluetooth manager (local adapters + proxies)."""
        from homeassistant.components import bluetooth

        assert self._hass is not None
        stored: BLEDevice | None = None
        matched: list[BLEDevice] = []
        seen: set[str] = set()

        if self._bike.ble_address:
            stored = bluetooth.async_ble_device_from_address(
                self._hass, self._bike.ble_address, connectable=True
            )
            if stored is not None:
                seen.add(stored.address.lower())

        infos = list(bluetooth.async_discovered_service_info(self._hass, connectable=True))
        # Strongest signal first: it is most likely the bike next to us.
        for info in sorted(infos, key=lambda item: item.rssi, reverse=True):
            if info.address.lower() in seen:
                continue
            if _looks_like_vanmoof(info.name, info.service_uuids):
                matched.append(info.device)
                seen.add(info.address.lower())

        return [stored, *matched] if stored else matched

    # ------------------------------------------------------------------
    # Authentication and framing
    # ------------------------------------------------------------------

    async def _async_authenticate_connection(
        self,
        client: BleakClient,
        queue: asyncio.Queue[Any],
        notification_handler,
    ) -> str:
        await client.start_notify(APP_CHAR_UUID, notification_handler)
        write_uuid = await self._async_resolve_write_uuid(client)
        await asyncio.sleep(1.5)

        await self._async_write_fragments(
            client, write_uuid, build_certificate_message(self._bike.certificate)
        )
        challenge = await self._async_wait_for(queue, ChallengeMessage, timeout=6.0)

        await self._async_write_fragments(
            client, write_uuid, sign_challenge(challenge.nonce, self._bike.private_key)
        )
        auth = await self._async_wait_for(queue, AuthMessage, timeout=10.0)
        if not auth.authenticated:
            raise VanMoofBleError("Bike rejected the certificate for this advertisement")

        await asyncio.sleep(0.5)
        return write_uuid

    async def _async_resolve_write_uuid(self, client: BleakClient) -> str:
        with contextlib.suppress(Exception):
            services = client.services
            if not services or not list(services):
                services = await client.get_services()
            for service in services:
                for characteristic in service.characteristics:
                    if characteristic.uuid.lower() == WRITE_CHAR_UUID.lower():
                        return WRITE_CHAR_UUID
        return APP_CHAR_UUID

    async def _async_write_fragments(
        self, client: BleakClient, write_uuid: str, payload: bytes
    ) -> None:
        for fragment in build_fragments(payload):
            await client.write_gatt_char(write_uuid, fragment, response=False)

    async def _async_wait_for(
        self,
        queue: asyncio.Queue[Any],
        message_type: type[Any],
        *,
        timeout: float,
    ) -> Any:
        end = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise VanMoofBleError(f"Timed out waiting for {message_type.__name__}")
            try:
                message = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError as err:
                raise VanMoofBleError(
                    f"Timed out waiting for {message_type.__name__}"
                ) from err
            if isinstance(message, message_type):
                return message

    async def _async_collect_topics(
        self,
        queue: asyncio.Queue[Any],
        topics: dict[int, Any],
        *,
        max_duration: float = _MAX_COLLECT_SECONDS,
    ) -> None:
        """Collect topic notifications into ``topics`` until the bike goes quiet."""
        loop = asyncio.get_running_loop()
        end = loop.time() + max_duration
        got_any = False
        while True:
            remaining = end - loop.time()
            if remaining <= 0:
                return
            wait = min(remaining, _QUIET_SECONDS if got_any else _FIRST_MESSAGE_SECONDS)
            try:
                message = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                return
            if isinstance(message, TopicMessage):
                topics[message.topic] = message.value
                got_any = True

    # ------------------------------------------------------------------
    # State mapping
    # ------------------------------------------------------------------

    def _build_state(self, topics: dict[int, Any]) -> BikeState:
        lock_raw = _as_int(topics.get(Topic.LOCK_STATE))
        region = REGIONS.get(_as_int(topics.get(Topic.REGION)))
        fw_info = topics.get(Topic.FW_INFO)
        find_my = topics.get(Topic.FIND_MY)
        distance = _as_int(topics.get(Topic.DISTANCE))
        speed = _as_int(topics.get(Topic.SPEED))
        alarm = topics.get(Topic.ALARM_MODE)
        brake = topics.get(Topic.BRAKE_LIGHT)
        indicator = topics.get(Topic.INDICATOR_LIGHT)
        update = topics.get(Topic.UPDATE_AVAILABLE)
        firmware = topics.get(Topic.FIRMWARE_VERSION)
        calories = topics.get(Topic.CALORIES)
        raw_errors = topics.get(Topic.ERRORS)
        bike_errors = (
            {str(key): value for key, value in raw_errors.items()}
            if isinstance(raw_errors, dict)
            else {}
        )

        return BikeState(
            available=True,
            in_range=True,
            battery_level=_as_int(topics.get(Topic.BATTERY_LEVEL)),
            module_battery=_as_int(topics.get(Topic.MODULE_BATTERY)),
            lock_state=LOCK_STATES.get(lock_raw),
            locked=None if lock_raw not in LOCK_STATES else lock_raw == 1,
            bike_state=_map_bike_state(topics.get(Topic.BIKE_STATE)),
            # The raw value is in units of 10 m (raw / 100 = km).
            distance_km=None if distance is None else round(distance / 100.0, 1),
            speed_kmh=None if speed is None else round(speed / 100.0, 1),
            calories=float(calories) if isinstance(calories, int | float) else None,
            power_level=POWER_LEVEL_OPTIONS.get(_as_int(topics.get(Topic.POWER_LEVEL))),
            light_mode=LIGHT_MODES.get(_as_int(topics.get(Topic.LIGHT_MODE))),
            speed_limit=REGION_SPEED_LIMITS.get(region) if region else None,
            region=region,
            bell_sound=BELL_SOUNDS.get(_as_int(topics.get(Topic.BELL_SOUND))),
            alarm_enabled=alarm if isinstance(alarm, bool) else None,
            brake_light=brake if isinstance(brake, bool) else None,
            indicator_light=indicator if isinstance(indicator, bool) else None,
            riding_display=RIDING_DISPLAY_MODES.get(_as_int(topics.get(Topic.RIDING_DISPLAY))),
            animation_theme=ANIMATION_THEMES.get(_as_int(topics.get(Topic.ANIMATION_THEME))),
            firmware_version=firmware if isinstance(firmware, str) else None,
            update_available=update if isinstance(update, str) and update else None,
            find_my_version=_map_find_my_version(fw_info),
            find_my_state=_map_find_my_state(find_my),
            connection_state="connected",
            firmware_info=_stringify_value(fw_info),
            bike_errors=bike_errors,
            error_count=_count_errors(bike_errors),
            raw_topics=topics,
        )


def _as_int(value: object | None) -> int | None:
    """Return ``value`` as int unless it is missing or a bool."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _map_bike_state(value: object | None) -> str | None:
    raw = _as_int(value)
    if raw is None:
        return None
    # The app treats every value above 2 as "on".
    return BIKE_STATES.get(raw, "on")


def _map_find_my_version(value: object | None) -> str | None:
    if not isinstance(value, dict):
        return None
    # Firmware versions differ in the key spelling ("findMy" or "findmy").
    for key, item in value.items():
        if str(key).lower() == "findmy":
            return decode_packed_version(item)
    return None


def _count_errors(errors: dict[str, Any]) -> int:
    """Count active entries; zero, false and empty values mean no error."""
    return sum(1 for value in errors.values() if value not in (None, False, 0, "", [], {}))


def _map_find_my_state(value: object | None) -> dict[str, bool] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): bool(item) for key, item in value.items() if isinstance(item, bool)}


def _stringify_value(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)
