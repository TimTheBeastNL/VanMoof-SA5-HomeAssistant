"""Constants for the VanMoof SA5 integration."""

from __future__ import annotations

DOMAIN = "vanmoof_sa5"

PLATFORMS = ["sensor", "binary_sensor", "button", "update"]

DEFAULT_SCAN_SECONDS = 8.0
DEFAULT_POLL_INTERVAL = 300
CERT_RENEWAL_WINDOW_SECONDS = 24 * 60 * 60

CONF_AUTH_TOKEN = "auth_token"
CONF_APP_TOKEN = "app_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_BIKES = "bikes"
CONF_POLL_INTERVAL = "poll_interval"

API_KEY = "fcb38d47-f14b-30cf-843b-26283f6a5819"
API_BASE_URL = "https://api.vanmoof-api.com/v8"
BIKE_API_BASE_URL = "https://bikeapi.production.vanmoof.cloud"
VEHICLE_REGISTRY_BASE_URL = "https://vehicleregistry.production.vanmoof.cloud"

SUPPORTED_BLE_PROFILES = {
    "ELECTRIFIED_2022": "SA5",
    "ELECTRIFIED_2023_TRACK_1": "SA5",
    "ELECTRIFIED_2025": "S6",
}

SERVICE_UUID = "e3d80000-3416-4a54-b011-68d41fdcbfcf"
APP_CHAR_UUID = "e3d80001-3416-4a54-b011-68d41fdcbfcf"
WRITE_CHAR_UUID = "e3d80002-3416-4a54-b011-68d41fdcbfcf"
SERVICE_UUID_NODASH = SERVICE_UUID.replace("-", "")
APP_CHAR_UUID_NODASH = APP_CHAR_UUID.replace("-", "")
WRITE_CHAR_UUID_NODASH = WRITE_CHAR_UUID.replace("-", "")
