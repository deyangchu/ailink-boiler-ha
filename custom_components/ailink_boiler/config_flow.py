"""配置流程：只需粘贴访问令牌，其余信息自动发现。

配置步骤：
1. 用户粘贴 access_token（可选填手机号与轮询间隔）
2. 从 JWT 解析出 userId
3. 调用 family/getFamilyList 得到 familyId
4. 调用 appDevice/getHomepageV2 得到设备清单
5. 只保留 productType=24 的壁挂炉；多台时进入选择步骤
6. 调用 device/queryDeviceInfo 补齐型号，创建配置项

令牌过期时（getLastToken 拒绝续期），配置流程会提示重新抓包。
"""

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
    token_expires_at,
    token_username,
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


def _base_schema(token_default: str = "") -> vol.Schema:
    """首次配置表单：只要求访问令牌。"""
    return vol.Schema(
        {
            vol.Required(CONF_ACCESS_TOKEN, default=token_default): str,
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

    VERSION = 2

    def __init__(self) -> None:
        self._user_id = ""
        self._family_id = ""
        self._mobile = ""
        self._scan_interval = DEFAULT_SCAN_INTERVAL
        self._candidates: list[dict[str, Any]] = []
        self._token = ""

    async def _async_discover(
        self, token: str
    ) -> list[dict[str, Any]]:
        """凭令牌自动发现账号下的壁挂炉，返回候选设备列表。"""
        user_id = token_username(token)
        if not user_id:
            raise AilinkAuthError("无法从令牌中解析出用户 ID")

        session = async_get_clientsession(self.hass)
        api = AilinkApi(
            session=session,
            user_id=user_id,
            family_id="",
            device_id="",
            access_token=token,
            mobile=self._mobile,
        )
        # 先用令牌换一个可用的
        if token_expires_at(token) <= 0:
            raise AilinkAuthError("令牌格式不正确")
        await api.async_refresh_token()

        families = await api.async_get_families()
        if not families:
            raise AilinkError("账号下没有找到家庭")

        candidates: list[dict[str, Any]] = []
        for family in families:
            family_id = str(family.get("familyId") or "")
            if not family_id:
                continue
            devices = await api.async_get_home_devices(family_id)
            for device in devices:
                category = str(
                    device.get("deviceCategory")
                    or device.get("productMajorClassCode")
                    or ""
                )
                if category != BOILER_PRODUCT_TYPE:
                    continue
                device_id = str(device.get("deviceId") or "")
                if not device_id:
                    continue
                candidates.append(
                    {
                        CONF_DEVICE_ID: device_id,
                        CONF_FAMILY_ID: family_id,
                        "name": str(device.get("productName") or "壁挂炉"),
                        "online": str(device.get("devState")) != "0",
                    }
                )
        return candidates

    async def _async_finish(
        self, candidate: dict[str, Any], token: str
    ) -> FlowResult:
        """补齐型号并创建配置项。"""
        session = async_get_clientsession(self.hass)
        api = AilinkApi(
            session=session,
            user_id=self._user_id,
            family_id=candidate[CONF_FAMILY_ID],
            device_id=candidate[CONF_DEVICE_ID],
            access_token=token,
            mobile=self._mobile,
        )
        info = await api.async_get_device_info()

        await self.async_set_unique_id(candidate[CONF_DEVICE_ID])
        self._abort_if_unique_id_configured()

        data = {
            CONF_USER_ID: self._user_id,
            CONF_FAMILY_ID: candidate[CONF_FAMILY_ID],
            CONF_DEVICE_ID: candidate[CONF_DEVICE_ID],
            CONF_ACCESS_TOKEN: api.access_token,
            CONF_DEVICE_MODEL: str(info.get("productModel") or ""),
            CONF_MOBILE: self._mobile,
            CONF_SCAN_INTERVAL: self._scan_interval,
        }
        return self.async_create_entry(
            title=str(info.get("deviceName") or candidate.get("name") or "AI-LiNK 壁挂炉"),
            data=data,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """第一步：粘贴令牌，自动发现设备。"""
        errors: dict[str, str] = {}

        if user_input is not None:
            token = str(user_input[CONF_ACCESS_TOKEN]).strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            self._mobile = str(user_input.get(CONF_MOBILE) or "").strip()
            self._scan_interval = int(
                user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
            self._user_id = token_username(token)
            self._token = token

            try:
                candidates = await self._async_discover(token)
            except AilinkAuthError:
                errors["base"] = "invalid_auth"
            except AilinkConnectionError:
                errors["base"] = "cannot_connect"
            except AilinkError as err:
                _LOGGER.warning("自动发现失败: %s", err)
                errors["base"] = "no_device"
            else:
                if not candidates:
                    errors["base"] = "unsupported_device"
                elif len(candidates) == 1:
                    try:
                        return await self._async_finish(candidates[0], token)
                    except AilinkAuthError:
                        errors["base"] = "invalid_auth"
                    except AilinkConnectionError:
                        errors["base"] = "cannot_connect"
                    except AilinkError as err:
                        _LOGGER.warning("读取设备详情失败: %s", err)
                        errors["base"] = "unknown"
                else:
                    self._candidates = candidates
                    return await self.async_step_select()

        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(),
            errors=errors,
        )

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """账号下有多台壁挂炉时，让用户选一台。"""
        errors: dict[str, str] = {}
        options = {
            item[CONF_DEVICE_ID]: (
                f"{item['name']}（{item[CONF_DEVICE_ID]}"
                + ("" if item["online"] else "，离线")
                + "）"
            )
            for item in self._candidates
        }

        if user_input is not None:
            chosen = user_input[CONF_DEVICE_ID]
            for item in self._candidates:
                if item[CONF_DEVICE_ID] == chosen:
                    try:
                        return await self._async_finish(item, self._token)
                    except AilinkAuthError:
                        errors["base"] = "invalid_auth"
                    except AilinkConnectionError:
                        errors["base"] = "cannot_connect"
                    except AilinkError as err:
                        _LOGGER.warning("创建配置失败: %s", err)
                        errors["base"] = "unknown"
                    break

        return self.async_show_form(
            step_id="select",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(options)}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """令牌彻底失效时，引导用户更新令牌。"""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """输入新的访问令牌。"""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None and entry is not None:
            token = str(user_input[CONF_ACCESS_TOKEN]).strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            session = async_get_clientsession(self.hass)
            api = AilinkApi(
                session=session,
                user_id=entry.data[CONF_USER_ID],
                family_id=entry.data[CONF_FAMILY_ID],
                device_id=entry.data[CONF_DEVICE_ID],
                access_token=token,
                mobile=entry.data.get(CONF_MOBILE, ""),
                device_model=entry.data.get(CONF_DEVICE_MODEL, ""),
            )
            try:
                await api.async_refresh_token()
                await api.async_get_device_info()
            except AilinkAuthError:
                errors["base"] = "invalid_auth"
            except AilinkConnectionError:
                errors["base"] = "cannot_connect"
            except AilinkError as err:
                _LOGGER.warning("重新认证失败: %s", err)
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_ACCESS_TOKEN: api.access_token},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_ACCESS_TOKEN): str}),
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
            if new_token.lower().startswith("bearer "):
                new_token = new_token[7:].strip()
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
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_ACCESS_TOKEN: api.access_token,
                        CONF_DEVICE_MODEL: str(
                            info.get("productModel")
                            or entry.data.get(CONF_DEVICE_MODEL, "")
                        ),
                    },
                )
                return self.async_create_entry(
                    title="",
                    data={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]},
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
