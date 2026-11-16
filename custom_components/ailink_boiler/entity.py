"""实体基类：统一设备信息与唯一 ID。"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AilinkCoordinator


class AilinkEntity(CoordinatorEntity[AilinkCoordinator]):
    """所有实体共享的设备信息与命名规则。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AilinkCoordinator,
        key: str,
        name: str,
        icon: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_name = name
        if icon:
            self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            manufacturer="A.O. Smith",
            model=coordinator.device_model,
            name=coordinator.device_name,
        )
