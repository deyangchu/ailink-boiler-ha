"""配置流程：在界面上填写账号参数并校验设备。"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    AilinkApi,
    AilinkAuthError,
    AilinkConnectionError,
    AilinkError,
)
from .const import (
    BOILER_PRODUCT_TYPE,
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_MODEL,
    CONF_FAMILY_ID,
    CONF_MOBILE,
    CONF_SCAN_INTERVAL,
    CONF_USER_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _user_schema() -> vol.Schema:
    """首次配置表单。"""
    return vol.Schema(
        {
            vol.Required(CONF_USER_ID): str,
            vol.Required(CONF_FAMILY_ID): str,
            vol.Required(CONF_DEVICE_ID): str,
            vol.Required(CONF_ACCESS_TOKEN): str,
            vol.Optional(CONF_MOBILE, default=""): str,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
            ): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
            ),
        }
    )


class AilinkBoilerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """AI-LiNK 壁挂炉的配置流程。"""

    VERSION = 1

    async def _async_validate(
        self, data: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        """用填写的参数实际调用一次接口，返回设备信息与可用令牌。"""
        session = async_get_clientsession(self.hass)
        api = AilinkApi(
            session=session,
            user_id=data[CONF_USER_ID],
            family_id=data[CONF_FAMILY_ID],
            device_id=data[CONF_DEVICE_ID],
            access_token=data[CONF_ACCESS_TOKEN],
            mobile=data.get(CONF_MOBILE, ""),
        )
        await api.async_refresh_token()
        info = await api.async_get_device_info()
        return info, api.access_token

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """处理首次配置。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info, token = await self._async_validate(user_input)
            except AilinkAuthError:
                errors["base"] = "invalid_auth"
            except AilinkConnectionError:
                errors["base"] = "cannot_connect"
            except AilinkError as err:
                _LOGGER.warning("配置校验失败: %s", err)
                errors["base"] = "unknown"
            else:
                if str(info.get("productType")) != BOILER_PRODUCT_TYPE:
                    errors["base"] = "unsupported_device"
                else:
                    device_id = str(user_input[CONF_DEVICE_ID])
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                    entry_data = {
                        **user_input,
                        CONF_DEVICE_ID: device_id,
                        CONF_ACCESS_TOKEN: token,
                        CONF_DEVICE_MODEL: str(info.get("productModel") or ""),
                    }
                    title = str(info.get("deviceName") or "AI-LiNK 壁挂炉")
                    return self.async_create_entry(title=title, data=entry_data)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """返回选项流程。"""
        return AilinkBoilerOptionsFlow()


class AilinkBoilerOptionsFlow(config_entries.OptionsFlow):
    """修改轮询间隔或更新令牌。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """处理选项表单。"""
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            new_token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            effective_token = new_token or entry.data[CONF_ACCESS_TOKEN]
            session = async_get_clientsession(self.hass)
            api = AilinkApi(
                session=session,
                user_id=entry.data[CONF_USER_ID],
                family_id=entry.data[CONF_FAMILY_ID],
                device_id=entry.data[CONF_DEVICE_ID],
                access_token=effective_token,
                mobile=entry.data.get(CONF_MOBILE, ""),
                device_model=entry.data.get(CONF_DEVICE_MODEL, ""),
            )
            try:
                await api.async_refresh_token()
                info = await api.async_get_device_info()
            except AilinkAuthError:
                errors["base"] = "invalid_auth"
            except AilinkConnectionError:
                errors["base"] = "cannot_connect"
            except AilinkError as err:
                _LOGGER.warning("选项校验失败: %s", err)
                errors["base"] = "unknown"
            else:
                if str(info.get("productType")) != BOILER_PRODUCT_TYPE:
                    errors["base"] = "unsupported_device"
                else:
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            CONF_ACCESS_TOKEN: api.access_token,
                            CONF_DEVICE_MODEL: str(
                                info.get("productModel") or entry.data.get(CONF_DEVICE_MODEL, "")
                            ),
                        },
                    )
                    return self.async_create_entry(
                        title="",
                        data={
                            CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                        },
                    )

        current_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_interval
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Optional(CONF_ACCESS_TOKEN, default=""): str,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
