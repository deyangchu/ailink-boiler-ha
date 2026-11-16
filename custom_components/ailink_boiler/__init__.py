"""AI-LiNK 壁挂炉集成入口。"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AilinkApi
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_DEVICE_MODEL,
    CONF_FAMILY_ID,
    CONF_MOBILE,
    CONF_USER_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import AilinkCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """创建 API 与协调器，并转发到各平台。"""
    session = async_get_clientsession(hass)
    api = AilinkApi(
        session=session,
        user_id=entry.data[CONF_USER_ID],
        family_id=entry.data[CONF_FAMILY_ID],
        device_id=entry.data[CONF_DEVICE_ID],
        access_token=entry.data[CONF_ACCESS_TOKEN],
        mobile=entry.data.get(CONF_MOBILE, ""),
        device_model=entry.data.get(CONF_DEVICE_MODEL, ""),
    )
    coordinator = AilinkCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载平台并清理协调器。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """只在选项变化时重载，避免令牌续期写回数据时触发无谓重载。"""
    coordinator: AilinkCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None and dict(entry.options) == coordinator.applied_options:
        return
    await hass.config_entries.async_reload(entry.entry_id)
