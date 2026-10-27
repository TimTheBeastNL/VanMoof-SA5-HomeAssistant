"""VanMoof SA5 BLE protocol helpers.

Topic ids, value encodings and enum mappings were taken from the official
VanMoof Android app (v26.5.1, class ``ElectrifiedS5A5`` profile).

Wire format of one application message (before fragmentation)::

    [payload type: 1 byte] [topic: 2 bytes big endian] [CBOR value]

Payload type 1 is used both for notifications from the bike and for writes
to the bike. Writing a topic uses the *write topic* which is usually the
read topic + 1 (e.g. read 106 = light mode, write 107 = set light mode).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import IntEnum

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .cbor import decode_cbor, encode_cbor


class PayloadType(IntEnum):
    """VanMoof payload types."""

    TOPIC_CBOR = 1
    SUBSCRIBE = 2
    AUTH_CERT = 3
    AUTH_CHALLENGE = 4
    AUTH_DETAILS = 5
    MTU_UPDATE = 6
    PARAM_UPDATE = 7


class Topic(IntEnum):
    """Topics the bike publishes (read side)."""

    BIKE_STATE = 1
    MODULE_BATTERY = 16
    BATTERY_LEVEL = 24
    ESHIFTER_HEARTBEAT = 53
    CALORIES = 73
    SPEED = 80
    REGION = 97
    SHIFTING_POINTS = 104
    POWER_LEVEL = 101
    LIGHT_MODE = 106
    LIGHT_SENSOR = 108
    ALARM_MODE = 110
    ANIMATION_THEME = 112
    BELL_SOUND = 114
    BACKUP_CODE = 116
    BRAKE_LIGHT = 123
    INDICATOR_LIGHT = 125
    RIDING_DISPLAY = 121
    LIGHT_SENSOR_INFO = 129
    LOCK_STATE = 161
    UNLOCK_REJECTED = 163
    DISTANCE = 165
    FW_INFO = 192
    FIND_MY = 225
    ERRORS = 255
    FIRMWARE_VERSION = 20481
    UPDATE_AVAILABLE = 20496
    SUBSCRIBE_CONTROL = 0xE001
    UNSUBSCRIBE_CONTROL = 0xE002


class WriteTopic(IntEnum):
    """Topics the bike accepts writes on."""

    REGION = 98
    SHIFTING_POINTS = 105
    POWER_LEVEL = 103
    LIGHT_MODE = 107
    ALARM_MODE = 111
    ANIMATION_THEME = 113
    BELL_SOUND = 115
    BACKUP_CODE = 117
    RIDING_DISPLAY = 122
    BRAKE_LIGHT = 124
    INDICATOR_LIGHT = 126
    UNLOCK = 160
    TOUCH_UNLOCK = 164


TOPIC_NAMES: dict[int, str] = {
    Topic.BIKE_STATE: "bike_state",
    Topic.MODULE_BATTERY: "module_battery",
    Topic.BATTERY_LEVEL: "battery_level",
    Topic.ESHIFTER_HEARTBEAT: "eshifter_heartbeat",
    Topic.CALORIES: "calories",
    Topic.SPEED: "speed",
    Topic.REGION: "region",
    Topic.SHIFTING_POINTS: "shifting_points",
    Topic.POWER_LEVEL: "power_level",
    Topic.LIGHT_MODE: "light_mode",
    Topic.LIGHT_SENSOR: "light_sensor",
    Topic.ALARM_MODE: "alarm_mode",
    Topic.ANIMATION_THEME: "animation_theme",
    Topic.BELL_SOUND: "bell_sound",
    Topic.BACKUP_CODE: "backup_code",
    Topic.BRAKE_LIGHT: "brake_light",
    Topic.INDICATOR_LIGHT: "indicator_light",
    Topic.RIDING_DISPLAY: "riding_display",
    Topic.LIGHT_SENSOR_INFO: "light_sensor_info",
    Topic.LOCK_STATE: "lock_state",
    Topic.UNLOCK_REJECTED: "unlock_rejected",
    Topic.DISTANCE: "distance",
    Topic.FW_INFO: "find_my_version",
    Topic.FIND_MY: "find_my",
    Topic.ERRORS: "errors",
    Topic.FIRMWARE_VERSION: "firmware_version",
    Topic.UPDATE_AVAILABLE: "update_available",
}

# Same subscription list the official app sends after authentication.
# The backup code topic (116) is deliberately left out: it is a secret that
# Home Assistant has no use for.
ALL_TOPICS: list[int] = [
    Topic.BIKE_STATE,
    Topic.BATTERY_LEVEL,
    Topic.CALORIES,
    Topic.SPEED,
    Topic.REGION,
    Topic.SHIFTING_POINTS,
    Topic.POWER_LEVEL,
    Topic.LIGHT_MODE,
    Topic.ALARM_MODE,
    Topic.BELL_SOUND,
    Topic.RIDING_DISPLAY,
    Topic.BRAKE_LIGHT,
    Topic.INDICATOR_LIGHT,
    Topic.ANIMATION_THEME,
    Topic.LOCK_STATE,
    Topic.UNLOCK_REJECTED,
    Topic.DISTANCE,
    Topic.FW_INFO,
    Topic.FIND_MY,
    Topic.ERRORS,
    Topic.FIRMWARE_VERSION,
    Topic.UPDATE_AVAILABLE,
    Topic.MODULE_BATTERY,
]


# ---------------------------------------------------------------------------
# Value mappings (raw CBOR value <-> friendly string)
# ---------------------------------------------------------------------------

BIKE_STATES: dict[int, str] = {0: "off", 1: "shipping", 2: "standby", 3: "on"}

LOCK_STATES: dict[int, str] = {1: "locked", 2: "unlocking", 3: "unlocked"}

POWER_LEVEL_OPTIONS: dict[int, str] = {0: "off", 1: "1", 2: "2", 3: "3", 4: "4"}

# App: 1 = ALWAYS_ON, 2 = OFF, 3 = AUTO
LIGHT_MODES: dict[int, str] = {1: "on", 2: "off", 3: "auto"}

BELL_SOUNDS: dict[int, str] = {
    0: "ding_dong",
    1: "party_horn",
    2: "ping",
    3: "vanmoof",
    4: "ship_horn",
}

# App: 0 = EU, 1 = US, 2 = JAPAN, 3 = OFFROAD
REGIONS: dict[int, str] = {0: "eu", 1: "us", 2: "japan", 3: "offroad"}
# Speed limit label per region, shown by the app for S5/A5
REGION_SPEED_LIMITS: dict[str, str] = {
    "eu": "25 km/h",
    "us": "32 km/h",
    "japan": "24 km/h",
    "offroad": "unrestricted",
}

RIDING_DISPLAY_MODES: dict[int, str] = {0: "speed", 1: "motor_power"}
ANIMATION_THEMES: dict[int, str] = {0: "default", 1: "pride"}

# Touch unlock "distance" -> RSSI threshold in dBm (values the app uses for S5/A5)
TOUCH_UNLOCK_RSSI: dict[str, int] = {
    "closest": -70,
    "close": -75,
    "average": -80,
    "far": -85,
    "furthest": -90,
}


def invert(mapping: dict[int, str]) -> dict[str, int]:
    """Return the reverse mapping."""
    return {value: key for key, value in mapping.items()}


# ---------------------------------------------------------------------------
# Decoded message containers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TopicMessage:
    """Decoded topic message."""

    topic: int
    topic_name: str
    value: object | None


@dataclass(slots=True)
class AuthMessage:
    """Decoded auth message."""

    authenticated: bool
    encrypted: bool


@dataclass(slots=True)
class ChallengeMessage:
    """Decoded challenge message."""

    nonce: bytes


@dataclass(slots=True)
class ParamMessage:
    """Decoded param message."""

    data: object | None


S5Message = TopicMessage | AuthMessage | ChallengeMessage | ParamMessage


@dataclass(frozen=True, slots=True)
class BleWrite:
    """One write to a bike topic."""

    topic: int
    value: object
    label: str = ""

    def to_payload(self) -> bytes:
        """Return the unfragmented application payload."""
        return build_write_message(self.topic, self.value)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_write_message(topic: int, value: object) -> bytes:
    """Build a topic write: payload type 1 + topic (BE) + CBOR value."""
    return (
        bytes([PayloadType.TOPIC_CBOR])
        + int(topic).to_bytes(2, "big")
        + encode_cbor(value)
    )


def write_power_level(level: int) -> BleWrite:
    """Set the assist level 0 (off) .. 4."""
    if level not in POWER_LEVEL_OPTIONS:
        raise ValueError(f"Invalid power level: {level}")
    return BleWrite(WriteTopic.POWER_LEVEL, level, "power_level")


def write_light_mode(mode: str) -> BleWrite:
    """Set the light mode: on, off or auto."""
    reverse = invert(LIGHT_MODES)
    if mode not in reverse:
        raise ValueError(f"Invalid light mode: {mode}")
    return BleWrite(WriteTopic.LIGHT_MODE, reverse[mode], "light_mode")


def write_bell_sound(sound: str) -> BleWrite:
    """Select the bell sound."""
    reverse = invert(BELL_SOUNDS)
    if sound not in reverse:
        raise ValueError(f"Invalid bell sound: {sound}")
    return BleWrite(WriteTopic.BELL_SOUND, reverse[sound], "bell_sound")


def write_alarm_mode(enabled: bool) -> BleWrite:
    """Enable or disable the alarm."""
    return BleWrite(WriteTopic.ALARM_MODE, bool(enabled), "alarm_mode")


def write_brake_light(enabled: bool) -> BleWrite:
    """Enable or disable the brake light mode."""
    return BleWrite(WriteTopic.BRAKE_LIGHT, bool(enabled), "brake_light")


def write_indicator_light(enabled: bool) -> BleWrite:
    """Enable or disable the indicator light mode."""
    return BleWrite(WriteTopic.INDICATOR_LIGHT, bool(enabled), "indicator_light")


def write_riding_display(mode: str) -> BleWrite:
    """Select what the top tube display shows while riding."""
    reverse = invert(RIDING_DISPLAY_MODES)
    if mode not in reverse:
        raise ValueError(f"Invalid riding display mode: {mode}")
    return BleWrite(WriteTopic.RIDING_DISPLAY, reverse[mode], "riding_display")


def write_animation_theme(theme: str) -> BleWrite:
    """Select the start-up animation theme."""
    reverse = invert(ANIMATION_THEMES)
    if theme not in reverse:
        raise ValueError(f"Invalid animation theme: {theme}")
    return BleWrite(WriteTopic.ANIMATION_THEME, reverse[theme], "animation_theme")


def write_touch_unlock(enabled: bool, distance: str = "average") -> BleWrite:
    """Configure proximity (touch) unlock.

    The app serialises ``TouchUnlockData(rssi, enabled)`` as a CBOR map.
    """
    if distance not in TOUCH_UNLOCK_RSSI:
        raise ValueError(f"Invalid touch unlock distance: {distance}")
    return BleWrite(
        WriteTopic.TOUCH_UNLOCK,
        {"rssi": TOUCH_UNLOCK_RSSI[distance], "enabled": bool(enabled)},
        "touch_unlock",
    )


def build_fragments(payload: bytes, mtu: int = 244) -> list[bytes]:
    """Split a payload into BLE fragments."""
    chunk_size = mtu - 3
    fragments: list[bytes] = []
    offset = 0
    index = 0

    while offset < len(payload):
        chunk = payload[offset : offset + chunk_size]
        remaining = len(payload) - 1 if index == 0 else len(payload) - (chunk_size * index)
        header = bytes(
            [
                (0x80 if index == 0 else 0x00) | 1,
                (remaining >> 8) & 0xFF,
                remaining & 0xFF,
            ]
        )
        fragments.append(header + chunk)
        offset += chunk_size
        index += 1

    return fragments


def build_certificate_message(certificate_b64: str) -> bytes:
    """Build the AUTH_CERT message."""
    return bytes([PayloadType.AUTH_CERT]) + base64.b64decode(certificate_b64)


def sign_challenge(challenge: bytes, private_key_b64: str) -> bytes:
    """Sign a challenge with the VanMoof Ed25519 key."""
    private_bytes = base64.b64decode(private_key_b64)
    if len(private_bytes) >= 32:
        private_bytes = private_bytes[:32]
    private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    signature = private_key.sign(challenge)
    return bytes([PayloadType.AUTH_CHALLENGE]) + signature


def build_subscribe_message(topics: list[int]) -> bytes:
    """Build the topic subscription message."""
    control_topic = Topic.SUBSCRIBE_CONTROL.to_bytes(2, "big")
    topic_bytes = b"".join(int(topic).to_bytes(2, "big") for topic in topics)
    return bytes([PayloadType.SUBSCRIBE]) + control_topic + topic_bytes


def parse_message(data: bytes) -> S5Message | None:
    """Parse a reassembled payload."""
    if not data:
        return None

    payload_type = data[0]
    rest = data[1:]

    if payload_type == PayloadType.AUTH_DETAILS:
        info, _ = decode_cbor(rest)
        if isinstance(info, dict):
            return AuthMessage(
                authenticated=bool(info.get("auth", False)),
                encrypted=bool(info.get("enc", False)),
            )
        return AuthMessage(authenticated=False, encrypted=False)

    if payload_type == PayloadType.AUTH_CHALLENGE:
        return ChallengeMessage(nonce=rest)

    if payload_type == PayloadType.PARAM_UPDATE:
        decoded, _ = decode_cbor(rest)
        return ParamMessage(data=decoded)

    if payload_type == PayloadType.TOPIC_CBOR:
        if len(rest) < 2:
            return None
        topic = int.from_bytes(rest[:2], "big")
        value: object | None = None
        if len(rest) > 2:
            value, _ = decode_cbor(rest, 2)
        return TopicMessage(
            topic=topic,
            topic_name=TOPIC_NAMES.get(topic, f"topic_{topic}"),
            value=value,
        )

    return None


class FragmentReassembler:
    """Reassemble VanMoof BLE fragments."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._total_len = 0

    def feed(self, data: bytes) -> S5Message | None:
        """Feed one fragment and return a full message if complete."""
        is_first = bool(data[0] & 0x80)
        total_len = int.from_bytes(data[1:3], "big")
        payload = data[3:]

        if is_first:
            self._buffer = bytearray(payload)
            self._total_len = total_len
        else:
            self._buffer.extend(payload)

        if len(self._buffer) >= self._total_len + 1:
            message = bytes(self._buffer[: self._total_len + 1])
            self._buffer = bytearray()
            return parse_message(message)

        return None


# ---------------------------------------------------------------------------
# Value decoders
# ---------------------------------------------------------------------------


def decode_packed_version(value: object | None) -> str | None:
    """Decode a packed u32 version into ``major.minor.build``.

    App: bytes [b3, b2, b1, b0] -> ``b3 . b2 . (b1<<8 | b0)``. Used for the
    Find My module versions on topic 192 (``{"fw": u32, "findMy": u32}``).
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    major = (value >> 24) & 0xFF
    minor = (value >> 16) & 0xFF
    build = value & 0xFFFF
    return f"{major}.{minor}.{build}"
