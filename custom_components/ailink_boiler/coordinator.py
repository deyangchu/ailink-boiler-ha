"""数据协调器：负责轮询设备状态与令牌续期。"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AilinkApi, AilinkAuthError, AilinkError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_MODEL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AilinkCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """按配置的间隔拉取设备状态，并在令牌变化时写回配置项。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: AilinkApi) -> None:
        interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=int(interval)),
        )
        self.entry = entry
        self.api = api
        self.device_id = entry.data["device_id"]
        self.device_model = entry.data.get(CONF_DEVICE_MODEL, "")
        self.device_name = entry.title
        # 记录本次加载时的选项，用于区分“选项变化”和“仅令牌写回”
        self.applied_options = dict(entry.options)

    def _persist_token(self) -> None:
        """令牌变化时写回配置项，重启后无需重新填写。"""
        current = self.entry.data.get(CONF_ACCESS_TOKEN)
        if self.api.access_token and self.api.access_token != current:
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={**self.entry.data, CONF_ACCESS_TOKEN: self.api.access_token},
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """拉取一次设备状态，认证失败时强制续期后重试一次。"""
        try:
            await self.api.async_ensure_token()
            self._persist_token()
            return await self.api.async_get_output_data()
        except AilinkAuthError as err:
            _LOGGER.debug("令牌失效，尝试强制续期: %s", err)
            try:
                await self.api.async_refresh_token()
                self._persist_token()
                return await self.api.async_get_output_data()
            except AilinkError as retry_err:
                raise UpdateFailed(str(retry_err)) from retry_err
        except AilinkError as err:
            raise UpdateFailed(str(err)) from err
