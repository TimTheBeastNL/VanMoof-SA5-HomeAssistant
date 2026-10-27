# VanMoof S5 / A5 BLE protocol notes

Derived from the VanMoof Android app 26.5.1 (profile `ElectrifiedS5A5`, `ELECTRIFIED_2022` /
`ELECTRIFIED_2023_TRACK_1`). The S6 (`ELECTRIFIED_2025`) uses a different GATT service
(`df286100-...`) and is **not** covered by this document or this integration.

## GATT

| | UUID |
|---|---|
| Service | `e3d80000-3416-4a54-b011-68d41fdcbfcf` |
| App characteristic (notify + write) | `e3d80001-3416-4a54-b011-68d41fdcbfcf` |

## Framing

Every application message is split into fragments:

```
byte 0   0x81 for the first fragment, 0x01 for the following ones
byte 1-2 remaining length (first fragment: total length - 1)
byte 3.. payload chunk (MTU - 3 bytes)
```

Application message: `[payload type][body]`

| Type | Name | Body |
|---|---|---|
| 1 | topic | `topic (u16 BE) + CBOR value` (both directions; writes use the write topic) |
| 2 | subscribe | `0xE001 + list of u16 topics` (`0xE002` unsubscribes) |
| 3 | auth certificate | certificate from `bikeapi .../create_certificate` |
| 4 | auth challenge | bike sends nonce, client answers with Ed25519 signature |
| 5 | auth details | CBOR `{auth: bool, enc: bool}` |

## Read topics

| Topic | Meaning | Value |
|---|---|---|
| 1 | bike (power) state | 0 off, 1 shipping, 2 standby, 3+ on |
| 16 | module battery | % |
| 24 | battery level | % |
| 73 | calories | float |
| 80 | speed | raw / 100 km/h |
| 97 | region | 0 EU (25 km/h), 1 US (32), 2 Japan (24), 3 offroad |
| 101 | assist level | 0 (off) .. 4 |
| 104 | shifting points | 4 x int16 (speed x 100) |
| 106 | light mode | 1 always on, 2 off, 3 auto |
| 110 | alarm | bool |
| 112 | start-up animation theme | 0 default, 1 pride |
| 114 | bell sound | 0 ding dong, 1 party horn, 2 ping, 3 VanMoof, 4 ship horn |
| 116 | backup code | 3 digits (secret, never subscribed by this integration) |
| 121 | riding display | 0 speed, 1 motor power |
| 123 | brake light mode | bool |
| 125 | indicator light mode | bool |
| 161 | **lock state** | 1 locked, 2 unlocking, 3 unlocked |
| 165 | total distance | raw / 100 km (units of 10 m) |
| 192 | Find My versions | map `{fw: u32, findMy: u32}`, packed `major.minor.build` |
| 225 | Find My state | map `{provisioned, ready, enabled, pairing, paired}` |
| 255 | error map | map |
| 20481 | firmware version | string |
| 20496 | firmware update available | string |

## Write topics

| Topic | Action | Value |
|---|---|---|
| 160 | unlock | `1` (not exposed) |
| 103 | assist level | 0 .. 4 |
| 107 | light mode | 1 on, 2 off, 3 auto |
| 111 | alarm | bool |
| 113 | animation theme | 0 / 1 |
| 115 | bell sound | 0 ding dong, 1 party horn, 2 ping, 3 VanMoof, 4 ship horn |
| 122 | riding display | 0 / 1 |
| 124 | brake light mode | bool |
| 126 | indicator light mode | bool |
| 164 | touch unlock | map `{"rssi": int, "enabled": bool}` |
| 98 | region | 0 EU, 1 US, 2 Japan, 3 offroad (not exposed: changes the legal speed limit) |
| 105 | shifting points | 4 x int16 (not exposed) |
| 117 | backup code | 3 x int16 (not exposed) |
| 8208 | firmware update blocks | not implemented on purpose |

### Touch unlock distances

The app stores a distance name and converts it to an RSSI threshold. For S5/A5:
closest -70, close -75, average -80, far -85, furthest -90 dBm. The bike has no
read topic for this setting, so Home Assistant remembers it.

## Cloud endpoints used by the app

| Service | Base URL | Used for |
|---|---|---|
| account API | `https://api.vanmoof-api.com/v8` | `authenticate`, `token`, `getApplicationToken`, `getCustomerData?includeBikeDetails` |
| bike API | `https://bikeapi.production.vanmoof.cloud` | `POST bikes/{frame}/create_certificate`, `GET bikes/{id}`, `remote-command/locate`, `remote-command/track`, `secure-message/*` |
| vehicle registry | `https://vehicleregistry.production.vanmoof.cloud` | shared bikes, invitations |
| tenjin (rides) | `https://tenjin.vanmoof.com/api/v1` | `rides/{riderId}/{vehicleId}/weekly`, `ride/{riderId}/{vehicleId}?id=`, `riders/{riderId}/preferences` |
