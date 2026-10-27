"""End-to-end test of the BLE client against a simulated bike."""

from __future__ import annotations

import asyncio
import base64

import pytest

pytest.importorskip("bleak")
pytest.importorskip("bleak_retry_connector")

from custom_components.vanmoof_sa5 import ble as ble_module  # noqa: E402
from custom_components.vanmoof_sa5.api import _generate_ed25519_keypair  # noqa: E402
from custom_components.vanmoof_sa5.cbor import decode_cbor, encode_cbor  # noqa: E402
from custom_components.vanmoof_sa5.models import BikeState, VanMoofBike  # noqa: E402
from custom_components.vanmoof_sa5.protocol import (  # noqa: E402
    FragmentReassembler,
    PayloadType,
    Topic,
    build_fragments,
)


class FakeBike:
    """Tiny model of the bike side of the protocol."""

    def __init__(self) -> None:
        self.reassembler = FragmentReassembler()
        self.notify = None
        self.subscribed: list[int] = []
        self.state = {
            Topic.BATTERY_LEVEL: 87,
            Topic.LOCK_STATE: 1,
            Topic.BIKE_STATE: 2,
            Topic.DISTANCE: 12345,
            Topic.POWER_LEVEL: 2,
            Topic.LIGHT_MODE: 3,
            Topic.BELL_SOUND: 3,
            Topic.REGION: 0,
            Topic.ALARM_MODE: False,
            Topic.BRAKE_LIGHT: True,
            Topic.FIRMWARE_VERSION: "1.2.3",
            Topic.FW_INFO: {"fw": 1, "findmy": (1 << 24) | (4 << 16) | 77},
            Topic.FIND_MY: {"provisioned": True, "ready": True, "enabled": False,
                            "pairing": False, "paired": True},
        }
        self.writes: list[tuple[int, object]] = []

    def _send(self, payload: bytes) -> None:
        for fragment in build_fragments(payload):
            self.notify(None, bytearray(fragment))

    def _send_topic(self, topic: int) -> None:
        self._send(bytes([PayloadType.TOPIC_CBOR]) + int(topic).to_bytes(2, "big")
                   + encode_cbor(self.state[topic]))

    def on_write(self, data: bytes) -> None:
        # The client's fragments use the same framing, so reuse the reassembler
        # but look at the raw payload type.
        is_first = bool(data[0] & 0x80)
        total = int.from_bytes(data[1:3], "big")
        if is_first:
            self._buf = bytearray(data[3:])
            self._total = total
        else:
            self._buf.extend(data[3:])
        if len(self._buf) < self._total + 1:
            return
        message = bytes(self._buf[: self._total + 1])
        kind, body = message[0], message[1:]
        if kind == PayloadType.AUTH_CERT:
            self._send(bytes([PayloadType.AUTH_CHALLENGE]) + b"\x01" * 16)
        elif kind == PayloadType.AUTH_CHALLENGE:
            self._send(bytes([PayloadType.AUTH_DETAILS]) + encode_cbor({"auth": True, "enc": False}))
        elif kind == PayloadType.SUBSCRIBE:
            assert body[:2] == b"\xe0\x01"
            self.subscribed = [int.from_bytes(body[i:i + 2], "big") for i in range(2, len(body), 2)]
            for topic in self.subscribed:
                if topic in self.state:
                    self._send_topic(topic)
        elif kind == PayloadType.TOPIC_CBOR:
            topic = int.from_bytes(body[:2], "big")
            value, _ = decode_cbor(body, 2)
            self.writes.append((topic, value))
            if topic == 160:                      # unlock
                self.state[Topic.LOCK_STATE] = 3
                self._send_topic(Topic.LOCK_STATE)
            elif topic == 103:                    # assist level
                self.state[Topic.POWER_LEVEL] = value
                self._send_topic(Topic.POWER_LEVEL)
            elif topic == 115:                    # bell sound
                self.state[Topic.BELL_SOUND] = value
                self._send_topic(Topic.BELL_SOUND)


class FakeClient:
    bike: FakeBike

    def __init__(self, *args, **kwargs) -> None:
        self.services = []

    async def start_notify(self, _uuid, handler) -> None:
        FakeClient.bike.notify = handler

    async def write_gatt_char(self, _uuid, data, response=False) -> None:
        await asyncio.sleep(0)
        FakeClient.bike.on_write(bytes(data))

    async def disconnect(self) -> None:
        pass


@pytest.fixture
def bike_env(monkeypatch):
    fake = FakeBike()
    FakeClient.bike = fake

    async def fake_establish(client_class, device, name, *args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(ble_module, "establish_connection", fake_establish)
    monkeypatch.setattr(ble_module, "_QUIET_SECONDS", 0.05)
    monkeypatch.setattr(ble_module, "_FIRST_MESSAGE_SECONDS", 0.5)

    real_sleep = asyncio.sleep
    monkeypatch.setattr(ble_module.asyncio, "sleep", lambda d: real_sleep(0))

    private, public = _generate_ed25519_keypair()
    vanmoof = VanMoofBike(
        unique_id="SA5", name="Test", frame_number="SA5", bike_api_id="SA5",
        ble_profile="ELECTRIFIED_2022", model="SA5",
        certificate=base64.b64encode(b"cert" * 40).decode(), private_key=private, public_key=public,
    )
    client = ble_module.VanMoofBikeBleClient(vanmoof)

    async def one_device():
        class Dev:
            address = "AA:BB:CC:DD:EE:FF"
            name = "VanMoof"
        return [Dev()]

    monkeypatch.setattr(client, "_async_discover_candidates", one_device)
    return fake, client


def test_fetch_state_maps_all_topics(bike_env):
    fake, client = bike_env
    state, address = asyncio.run(client.async_fetch_state())
    assert address == "AA:BB:CC:DD:EE:FF"
    assert state.battery_level == 87
    assert state.locked is True and state.lock_state == "locked"
    assert state.bike_state == "standby"
    assert state.distance_km == 123.5
    assert state.power_level == "2" and state.light_mode == "auto"
    assert state.bell_sound == "vanmoof" and state.region == "eu"
    assert state.speed_limit == "25 km/h"
    assert state.alarm_enabled is False and state.brake_light is True
    assert state.firmware_version == "1.2.3"
    assert state.find_my_version == "1.4.77"
    assert state.find_my_state["paired"] is True
    assert 116 not in fake.subscribed


def test_silent_bike_is_reported_as_error(bike_env):
    fake, client = bike_env
    fake.on_write = lambda data: None  # bike never answers the certificate
    with pytest.raises(ble_module.VanMoofBleError):
        asyncio.run(client.async_fetch_state())


def test_state_carry_over_keeps_settings_when_offline():
    previous = BikeState(available=True, in_range=True, power_level="3", locked=True,
                         light_mode="auto", distance_km=10.0)
    offline = BikeState(available=False, in_range=False)
    offline.carry_over(previous)
    assert offline.power_level == "3" and offline.locked is True and offline.distance_km == 10.0
    online = BikeState(available=True, in_range=True)
    online.carry_over(previous)
    assert online.power_level == "3" and online.locked is None  # live values not carried

