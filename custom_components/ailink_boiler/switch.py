"""热水循环开关实体。"""

from __future__ import annotations

import logging
import time

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .api import AilinkError, is_cruise_running
from .const import DOMAIN
from .coordinator import AilinkCoordinator
from .entity import AilinkEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """注册热水循环开关。"""
    coordinator: AilinkCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AilinkCruiseSwitch(coordinator)])


class AilinkCruiseSwitch(AilinkEntity, SwitchEntity):
    """控制壁挂炉热水循环的开关。

    指令下发后设备上报有延迟，先按目标状态显示，并在 8 秒和 20 秒后各刷新一次。
    """

    def __init__(self, coordinator: AilinkCoordinator) -> None:
        super().__init__(coordinator, "cruise", "热水循环", "mdi:water-sync")
        self._optimistic_value: bool | None = None
        self._optimistic_until = 0.0

    @property
    def is_on(self) -> bool:
        """优先返回短时间内的乐观状态，之后以设备上报为准。"""
        if (
            self._optimistic_value is not None
            and time.monotonic() < self._optimistic_until
        ):
            return self._optimistic_value
        return is_cruise_running(self.coordinator.data or {})

    async def async_turn_on(self, **kwargs) -> None:
        """开启热水循环。"""
        await self._async_set_cruise(True)

    async def async_turn_off(self, **kwargs) -> None:
        """关闭热水循环。"""
        await self._async_set_cruise(False)

    async def _async_set_cruise(self, enabled: bool) -> None:
        """下发指令并安排两次延迟刷新。"""
        try:
            await self.coordinator.api.async_set_cruise(enabled)
        except AilinkError as err:
            raise HomeAssistantError(f"热水循环指令失败: {err}") from err

        self._optimistic_value = enabled
        self._optimistic_until = time.monotonic() + 20
        self.async_write_ha_state()
        async_call_later(self.hass, 8, self._async_delayed_refresh)
        async_call_later(self.hass, 20, self._async_delayed_refresh)

    async def _async_delayed_refresh(self, _now) -> None:
        """延迟刷新，让设备上报追上下发状态。"""
        await self.coordinator.async_request_refresh()
