"""VanMoof cloud API client and certificate management."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from dataclasses import asdict
from typing import Any

from aiohttp import ClientResponseError, ClientSession
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from homeassistant.core import HomeAssistant

from .cbor import decode_cbor
from .const import (
    API_BASE_URL,
    API_KEY,
    BIKE_API_BASE_URL,
    CERT_RENEWAL_WINDOW_SECONDS,
    CONF_APP_TOKEN,
    CONF_AUTH_TOKEN,
    CONF_BIKES,
    CONF_REFRESH_TOKEN,
    SUPPORTED_BLE_PROFILES,
    VEHICLE_REGISTRY_BASE_URL,
)
from .models import VanMoofBike

_LOGGER = logging.getLogger(__name__)


class VanMoofApiError(Exception):
    """Raised on VanMoof API failures."""


class VanMoofAuthError(VanMoofApiError):
    """Raised when VanMoof rejects credentials or tokens."""


class VanMoofNoSupportedBikesError(VanMoofApiError):
    """Raised when the account has no supported bikes."""


class VanMoofApiClient:
    """Async client for the VanMoof API."""

    def __init__(self, session: ClientSession, entry_data: dict[str, Any]) -> None:
        self._session = session
        self._email: str = entry_data["email"]
        self._password: str = entry_data["password"]
        self._auth_token: str | None = entry_data.get(CONF_AUTH_TOKEN)
        self._app_token: str | None = entry_data.get(CONF_APP_TOKEN)
        self._refresh_token: str | None = entry_data.get(CONF_REFRESH_TOKEN)
        self._customer_uuid: str | None = None
        self._bikes: dict[str, VanMoofBike] = {
            bike_payload["unique_id"]: VanMoofBike(**bike_payload)
            for bike_payload in entry_data.get(CONF_BIKES, [])
        }

    @property
    def bikes(self) -> dict[str, VanMoofBike]:
        """Return the configured bikes."""
        return self._bikes

    def export_entry_data(self) -> dict[str, Any]:
        """Return updated config entry data."""
        return {
            "email": self._email,
            "password": self._password,
            CONF_AUTH_TOKEN: self._auth_token,
            CONF_APP_TOKEN: self._app_token,
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_BIKES: [asdict(bike) for bike in self._bikes.values()],
        }

    async def async_initialize(self) -> dict[str, VanMoofBike]:
        """Authenticate, fetch bikes, and ensure certificates exist."""
        try:
            await self._async_resolve_tokens()
            bikes = await self._async_fetch_bikes()
            await self.async_ensure_certificates(bikes.values())
            self._bikes = bikes
            return self._bikes
        except VanMoofApiError as err:
            _LOGGER.warning(
                "VanMoof API error during initialization (%s), "
                "clearing tokens and retrying with fresh authentication",
                err,
            )
            self._auth_token = None
            self._app_token = None
            self._refresh_token = None

        # Retry once with fresh credentials
        await self._async_resolve_tokens()
        bikes = await self._async_fetch_bikes()
        await self.async_ensure_certificates(bikes.values())
        self._bikes = bikes
        return self._bikes

    async def async_ensure_certificates(
        self, bikes: list[VanMoofBike] | Any
    ) -> dict[str, VanMoofBike]:
        """Ensure every bike has a usable certificate and keypair."""
        await self._async_resolve_tokens()

        for bike in bikes:
            needs_certificate = not bike.certificate or not bike.private_key or not bike.public_key
            expiring = (
                bike.certificate_expiry is None
                or bike.certificate_expiry <= int(time.time()) + CERT_RENEWAL_WINDOW_SECONDS
            )
            if not needs_certificate and not expiring:
                continue

            if not bike.private_key or not bike.public_key:
                bike.private_key, bike.public_key = _generate_ed25519_keypair()

            certificate_payload = await self._async_create_certificate(
                bike.bike_api_id, bike.public_key
            )
            bike.certificate = certificate_payload["certificate"]
            bike.certificate_expiry = parse_certificate_expiry(bike.certificate)
            self._bikes[bike.unique_id] = bike

        return self._bikes

    async def _async_resolve_tokens(self) -> None:
        """Resolve tokens using cached app/auth/refresh tokens or credentials."""
        if self._app_token and not _is_jwt_expired(self._app_token):
            return

        if self._auth_token and not _is_jwt_expired(self._auth_token):
            self._app_token = await self._async_get_application_token(self._auth_token)
            return

        if self._refresh_token:
            try:
                self._auth_token = await self._async_refresh_auth_token(self._refresh_token)
                self._app_token = await self._async_get_application_token(self._auth_token)
                return
            except VanMoofApiError as err:
                _LOGGER.warning("VanMoof refresh token no longer valid: %s", err)
                _LOGGER.debug("Refresh token no longer valid", exc_info=True)

        self._auth_token, self._refresh_token = await self._async_authenticate(
            self._email, self._password
        )
        self._app_token = await self._async_get_application_token(self._auth_token)

    async def _async_authenticate(self, email: str, password: str) -> tuple[str, str]:
        basic = base64.b64encode(f"{email}:{password}".encode()).decode()
        response = await self._async_request(
            "post",
            f"{API_BASE_URL}/authenticate",
            headers={
                "Api-Key": API_KEY,
                "Authorization": f"Basic {basic}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            raw_data=b"",
        )
        try:
            return response["token"], response["refreshToken"]
        except KeyError as err:
            raise VanMoofApiError("VanMoof authentication response was incomplete") from err

    async def _async_refresh_auth_token(self, refresh_token: str) -> str:
        response = await self._async_request(
            "post",
            f"{API_BASE_URL}/token",
            headers={
                "Api-Key": API_KEY,
                "Content-Type": "application/json",
            },
            json_data={"refreshToken": refresh_token},
        )
        try:
            return response["token"]
        except KeyError as err:
            raise VanMoofApiError("VanMoof token refresh response was incomplete") from err

    async def _async_get_application_token(self, auth_token: str) -> str:
        response = await self._async_request(
            "get",
            f"{API_BASE_URL}/getApplicationToken",
            headers={
                "Api-Key": API_KEY,
                "Authorization": f"Bearer {auth_token}",
            },
        )
        try:
            return response["token"]
        except KeyError as err:
            raise VanMoofApiError("VanMoof app token response was incomplete") from err

    async def _async_fetch_bikes(self) -> dict[str, VanMoofBike]:
        customer_data = await self._async_request(
            "get",
            f"{API_BASE_URL}/getCustomerData?includeBikeDetails",
            headers={
                "Api-Key": API_KEY,
                "Authorization": f"Bearer {self._auth_token}",
            },
        )
        customer = customer_data.get("data", {})
        customer_uuid = customer.get("uuid")
        if not customer_uuid:
            raise VanMoofApiError("VanMoof customer UUID missing from response")
        self._customer_uuid = customer_uuid

        bike_payloads = customer.get("bikes", [])
        if not bike_payloads:
            bike_payloads = customer.get("bikeDetails", [])

        bikes = [self._bike_from_api_payload(bike_payload) for bike_payload in bike_payloads]

        try:
            shared_payload = await self._async_request(
                "get",
                f"{VEHICLE_REGISTRY_BASE_URL}/external/riders/{customer_uuid}/vehicles",
                headers={"Authorization": f"Bearer {self._app_token}"},
            )
        except VanMoofApiError as err:
            _LOGGER.warning("Could not fetch VanMoof shared vehicles: %s", err)
            _LOGGER.debug("Could not fetch shared vehicles", exc_info=True)
            shared_payload = {"vehicle_access": []}

        for vehicle in shared_payload.get("vehicle_access", []):
            bike = self._bike_from_shared_payload(vehicle)
            if bike.unique_id not in {known.unique_id for known in bikes}:
                bikes.append(bike)

        supported: dict[str, VanMoofBike] = {}
        for bike in bikes:
            if bike.ble_profile not in SUPPORTED_BLE_PROFILES:
                continue
            model = SUPPORTED_BLE_PROFILES[bike.ble_profile]
            bike.model = model
            existing = self._bikes.get(bike.unique_id)
            if existing:
                bike.certificate = existing.certificate
                bike.certificate_expiry = existing.certificate_expiry
                bike.private_key = existing.private_key
                bike.public_key = existing.public_key
                bike.ble_address = existing.ble_address
            supported[bike.unique_id] = bike

        if not supported:
            found_profiles = sorted(
                {
                    bike.ble_profile or "unknown"
                    for bike in bikes
                }
            )
            _LOGGER.warning(
                "No supported VanMoof bikes found for %s. Profiles returned: %s",
                self._email,
                ", ".join(found_profiles) if found_profiles else "none",
            )
            raise VanMoofNoSupportedBikesError(
                "No supported SA5/A5/S6 bikes found in this account"
                f" (profiles returned: {', '.join(found_profiles) if found_profiles else 'none'})"
            )

        return supported

    def _bike_from_api_payload(self, payload: dict[str, Any]) -> VanMoofBike:
        frame_number = payload["frameNumber"]
        certificate_bike_id = str(payload.get("bikeId") or frame_number)
        return VanMoofBike(
            unique_id=frame_number,
            name=payload.get("name") or frame_number,
            frame_number=frame_number,
            bike_api_id=certificate_bike_id,
            ble_profile=payload.get("bleProfile", ""),
            model="",
            frame_serial=payload.get("frameSerial"),
            main_ecu_serial=payload.get("mainEcuSerial"),
            owner_name=payload.get("ownerName"),
        )

    def _bike_from_shared_payload(self, payload: dict[str, Any]) -> VanMoofBike:
        frame_number = payload["vehicle_id"]
        owner_name = payload.get("owner_name")
        label = payload.get("name") or frame_number
        if owner_name:
            label = f"{label} (shared by {owner_name})"
        return VanMoofBike(
            unique_id=frame_number,
            name=label,
            frame_number=frame_number,
            bike_api_id=frame_number,
            ble_profile=payload.get("ble_profile", ""),
            model="",
            owner_name=owner_name,
            ble_address=payload.get("ble_id"),
        )

    async def _async_create_certificate(
        self, bike_api_id: str, public_key_b64: str
    ) -> dict[str, Any]:
        response = await self._async_request(
            "post",
            f"{BIKE_API_BASE_URL}/bikes/{bike_api_id}/create_certificate",
            headers={
                "Authorization": f"Bearer {self._app_token}",
                "Content-Type": "application/json",
            },
            json_data={"public_key": public_key_b64},
        )
        if "err" in response:
            raise VanMoofApiError(f"VanMoof certificate request failed: {response['err']}")
        if "certificate" not in response:
            raise VanMoofApiError("VanMoof did not return a certificate")
        return response

    async def _async_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        raw_data: bytes | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data,
                data=raw_data,
                timeout=30,
                allow_redirects=False,
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    if response.status in (401, 403):
                        raise VanMoofAuthError(
                            f"{method.upper()} {url} -> HTTP {response.status}: {text}"
                        )
                    raise VanMoofApiError(
                        f"{method.upper()} {url} -> HTTP {response.status}: {text}"
                    )
        except ClientResponseError as err:
            raise VanMoofApiError(f"{method.upper()} {url} -> {err}") from err
        except OSError as err:
            raise VanMoofApiError(
                f"{method.upper()} {url} -> Network error talking to VanMoof: {err}"
            ) from err

        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise VanMoofApiError(
                f"{method.upper()} {url} -> VanMoof returned invalid JSON: {text}"
            ) from err


async def async_bootstrap_client(
    hass: HomeAssistant, entry_data: dict[str, Any]
) -> VanMoofApiClient:
    """Create and initialize the VanMoof API client."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    client = VanMoofApiClient(async_get_clientsession(hass), entry_data)
    await client.async_initialize()
    return client


def _generate_ed25519_keypair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return (
        base64.b64encode(seed + public).decode(),
        base64.b64encode(public).decode(),
    )


def _is_jwt_expired(token: str | None) -> bool:
    if not token:
        return True

    try:
        parts = token.split(".")
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode()))
        return int(time.time()) >= int(decoded["exp"]) - 60
    except (IndexError, KeyError, ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return True


def parse_certificate_expiry(certificate_b64: str) -> int | None:
    """Extract the expiry from a VanMoof certificate."""
    try:
        certificate = base64.b64decode(certificate_b64)
    except (ValueError, binascii.Error):
        return None

    if len(certificate) < 65:
        return None

    payload, _ = decode_cbor(certificate[64:])
    if not isinstance(payload, dict):
        return None

    expiry = payload.get("e")
    return int(expiry) if isinstance(expiry, int) else None

