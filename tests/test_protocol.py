"""Protocol tests. Expected bytes were derived from the decompiled VanMoof app."""

from __future__ import annotations

import pytest

from custom_components.vanmoof_sa5 import cbor
from custom_components.vanmoof_sa5.protocol import (
    ALL_TOPICS,
    BELL_SOUNDS,
    LIGHT_MODES,
    FragmentReassembler,
    TopicMessage,
    build_fragments,
    build_subscribe_message,
    decode_packed_version,
    parse_message,
    write_alarm_mode,
    write_bell_sound,
    write_brake_light,
    write_indicator_light,
    write_light_mode,
    write_power_level,
    write_riding_display,
    write_touch_unlock,
)


def test_cbor_negative_and_map_roundtrip():
    value = {"rssi": -80, "enabled": True}
    encoded = cbor.encode_cbor(value)
    # a2 | 64 "rssi" | 38 4f (-80) | 67 "enabled" | f5
    assert encoded == bytes.fromhex("a2") + b"\x64rssi" + bytes.fromhex("384f") + b"\x67enabled" + b"\xf5"
    assert cbor.decode_cbor(encoded)[0] == value


@pytest.mark.parametrize("number", [-1, -24, -25, -90, -300, 0, 23, 24, 255, 256, 70000])
def test_cbor_int_roundtrip(number):
    assert cbor.decode_cbor(cbor.encode_cbor(number))[0] == number


def test_simple_writes_match_app():
    assert write_power_level(3).to_payload() == bytes.fromhex("01" "0067" "03")
    assert write_light_mode("auto").to_payload() == bytes.fromhex("01" "006b" "03")
    assert write_light_mode("on").to_payload() == bytes.fromhex("01" "006b" "01")
    assert write_light_mode("off").to_payload() == bytes.fromhex("01" "006b" "02")
    assert write_alarm_mode(True).to_payload() == bytes.fromhex("01" "006f" "f5")
    assert write_brake_light(False).to_payload() == bytes.fromhex("01" "007c" "f4")
    assert write_indicator_light(True).to_payload() == bytes.fromhex("01" "007e" "f5")
    assert write_riding_display("motor_power").to_payload() == bytes.fromhex("01" "007a" "01")


def test_bell_sound_write_matches_app_mapping():
    # App write mapping: VANMOOF=3, DING_DONG=0, PARTY_HORN=1, SHIP_HORN=4, PING=2
    expected = {"vanmoof": 3, "ding_dong": 0, "party_horn": 1, "ship_horn": 4, "ping": 2}
    for name, raw in expected.items():
        assert write_bell_sound(name).to_payload() == bytes([1, 0, 115, raw])
    assert set(BELL_SOUNDS.values()) == set(expected)


def test_touch_unlock_payload():
    payload = write_touch_unlock(True, "average").to_payload()
    assert payload[:3] == bytes.fromhex("0100a4")
    assert cbor.decode_cbor(payload, 3)[0] == {"rssi": -80, "enabled": True}


def test_invalid_values_rejected():
    with pytest.raises(ValueError):
        write_power_level(5)
    with pytest.raises(ValueError):
        write_light_mode("halo")
    with pytest.raises(ValueError):
        write_touch_unlock(True, "nowhere")


def test_light_mode_mapping_roundtrip():
    assert LIGHT_MODES == {1: "on", 2: "off", 3: "auto"}


def test_subscribe_message_layout():
    message = build_subscribe_message([1, 161])
    assert message == bytes.fromhex("02" "e001" "0001" "00a1")
    assert 161 in ALL_TOPICS and 116 not in ALL_TOPICS  # backup code is never subscribed


def test_fragmentation_roundtrip():
    payload = write_touch_unlock(True, "far").to_payload()
    reassembler = FragmentReassembler()
    result = None
    for fragment in build_fragments(payload, mtu=10):
        result = reassembler.feed(fragment)
    assert isinstance(result, TopicMessage)
    assert result.topic == 164
    assert result.value == {"rssi": -85, "enabled": True}


def test_parse_lock_state_notification():
    message = parse_message(bytes.fromhex("0100a1" "03"))
    assert isinstance(message, TopicMessage)
    assert (message.topic, message.value) == (161, 3)


def test_packed_version():
    assert decode_packed_version((1 << 24) | (12 << 16) | 1234) == "1.12.1234"
    assert decode_packed_version("x") is None
