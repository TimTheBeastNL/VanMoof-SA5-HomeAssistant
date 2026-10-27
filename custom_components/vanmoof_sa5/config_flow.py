"""Config flow for the VanMoof SA5 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    VanMoofApiClient,
    VanMoofApiError,
    VanMoofAuthError,
    VanMoofNoSupportedBikesError,
)
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=60, max=3600)
        ),
    }
)


class VanMoofConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for VanMoof SA5."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        error_detail = ""

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()
            try:
                client = VanMoofApiClient(
                    async_get_clientsession(self.hass),
                    {
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await client.async_initialize()
            except VanMoofAuthError as err:
                _LOGGER.warning("VanMoof config flow auth failed: %s", err)
                _LOGGER.debug("VanMoof config flow auth failed", exc_info=True)
                errors["base"] = "invalid_auth"
                error_detail = str(err)
            except VanMoofNoSupportedBikesError as err:
                _LOGGER.warning("VanMoof config flow found no supported bikes: %s", err)
                _LOGGER.debug("VanMoof config flow found no supported bikes", exc_info=True)
                errors["base"] = "no_supported_bikes"
                error_detail = str(err)
            except VanMoofApiError as err:
                _LOGGER.error("VanMoof config flow failed: %s", err)
                _LOGGER.debug("VanMoof config flow failed", exc_info=True)
                errors["base"] = "cannot_connect"
                error_detail = str(err)
            else:
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data=client.export_entry_data(),
                    options={CONF_POLL_INTERVAL: user_input[CONF_POLL_INTERVAL]},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
            description_placeholders={
                "error_detail": error_detail or "None",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return VanMoofOptionsFlow(config_entry)


class VanMoofOptionsFlow(config_entries.OptionsFlow):
    """Handle VanMoof SA5 options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # Kept under a private name: ``config_entry`` is a read-only property
        # on newer Home Assistant versions and missing on older ones.
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        options = self._entry.options
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=int(options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                }
            ),
        )
