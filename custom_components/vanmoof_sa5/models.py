"""Data models for the VanMoof SA5 integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class VanMoofBike:
    """VanMoof bike metadata plus per-bike credentials."""

    unique_id: str
    name: str
    frame_number: str
    bike_api_id: str
    ble_profile: str
    model: str
    frame_serial: str | None = None
    main_ecu_serial: str | None = None
    owner_name: str | None = None
    certificate: str | None = None
    certificate_expiry: int | None = None
    private_key: str | None = None
    public_key: str | None = None
    ble_address: str | None = None

    @property
    def display_model(self) -> str:
        """Return a friendly model label."""
        return self.model or self.ble_profile


@dataclass(slots=True)
class BikeState:
    """Runtime state fetched from the bike over BLE."""

    available: bool
    in_range: bool
    battery_level: int | None = None
    module_battery: int | None = None
    # True = locked, False = unlocked or unlocking
    locked: bool | None = None
    lock_state: str | None = None
    bike_state: str | None = None
    distance_km: float | None = None
    speed_kmh: float | None = None
    calories: float | None = None
    power_level: str | None = None
    light_mode: str | None = None
    speed_limit: str | None = None
    region: str | None = None
    bell_sound: str | None = None
    alarm_enabled: bool | None = None
    brake_light: bool | None = None
    indicator_light: bool | None = None
    riding_display: str | None = None
    animation_theme: str | None = None
    firmware_version: str | None = None
    update_available: str | None = None
    find_my_version: str | None = None
    find_my_state: dict[str, bool] | None = None
    connection_state: str = "disconnected"
    last_seen: datetime | None = None
    firmware_info: str | None = None
    # Last connection error (None after a successful poll).
    errors: str | None = None
    # Error map reported by the bike (topic 255) and the number of active errors.
    bike_errors: dict[str, Any] | None = None
    error_count: int | None = None
    raw_topics: dict[int, Any] = field(default_factory=dict)

    # Settings the bike only reports on connect. They are carried over from
    # the previous state so entities keep their last known value
    # while the bike is out of range or a topic is missing from one poll.
    SETTINGS_FIELDS = (
        "power_level",
        "light_mode",
        "speed_limit",
        "region",
        "bell_sound",
        "alarm_enabled",
        "brake_light",
        "indicator_light",
        "riding_display",
        "animation_theme",
        "firmware_version",
    )
    # Live values that are only carried over when the bike is unreachable.
    LIVE_FIELDS = (
        "locked",
        "lock_state",
        "bike_state",
        "distance_km",
        "last_seen",
        "bike_errors",
        "error_count",
        "find_my_version",
    )

    def carry_over(self, previous: BikeState | None) -> None:
        """Fill missing fields from ``previous``."""
        if previous is None:
            return
        names = self.SETTINGS_FIELDS
        if not self.available:
            names = names + self.LIVE_FIELDS
        for name in names:
            if getattr(self, name) is None:
                setattr(self, name, getattr(previous, name))
