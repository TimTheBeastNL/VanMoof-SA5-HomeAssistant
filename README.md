# VanMoof SA5 Home Assistant Integration

Home Assistant integration for the VanMoof S/A5 e-bike series. This custom integration exposes sensors, binary sensors and buttons for VanMoof S/A5 bikes so you can monitor bike state and interact with supported features from Home Assistant.

> **STATUS: BETA** — use at your own risk.

## Features

- Battery sensor
- Lock state, power level, light mode & speed limit
- Total distance
- BLE-based communication with automatic reconnection

## Install via HACS

1. In Home Assistant, open **HACS**
2. Go to **Integrations** → three-dot menu → **Custom repositories**
3. Add: `https://github.com/TimTheBeastNL/VanMoof-SA5-HomeAssistant`
4. Category: **Integration**
5. Install and restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration** → search "VanMoof SA5"

## Requirements

- Home Assistant with Bluetooth support
- VanMoof S5 or A5 bike
- Recommended: ESP32-S3 as Bluetooth proxy near the bike for stable signal

## Special thanks

- [j-o-a-c-h-i](https://github.com/j-o-a-c-h-i)
- [Victor Lagerfors](https://github.com/victorlagerfors/vanmoof-s5-homey)
