"""设备状态传感器。"""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import is_device_online
from .const import DEVICE_STALE_SECONDS, DOMAIN
from .coordinator import AilinkCoordinator
from .entity import AilinkEntity

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="waterOutTEMP",
        name="出水温度",
        icon="mdi:thermometer-water",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="waterInTEMP",
        name="进水温度",
        icon="mdi:thermometer-low",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="waterTEMP",
        name="生活热水设定温度",
        icon="mdi:water-thermometer",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="warmTemp",
        name="采暖设定温度",
        icon="mdi:radiator",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="waterFlow",
        name="水流量",
        icon="mdi:water-flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="currentOutputPower",
        name="当前功率",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """注册所有传感器。"""
    coordinator: AilinkCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AilinkStatusSensor(coordinator, description) for description in SENSORS
    )


class AilinkStatusSensor(AilinkEntity, SensorEntity):
    """把设备上报的数值字段映射成 HA 传感器。"""

    def __init__(
        self,
        coordinator: AilinkCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(
            coordinator,
            description.key,
            description.name or description.key,
            description.icon,
        )
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class

    @property
    def available(self) -> bool:
        """设备离线时传感器不可用，避免展示上一次缓存的读数。"""
        if not super().available:
            return False
        return is_device_online(self.coordinator.data or {}, DEVICE_STALE_SECONDS)

    @property
    def native_value(self) -> float | None:
        """读取当前字段并转成数值，缺失或非法时返回 None。"""
        raw = (self.coordinator.data or {}).get(self.entity_description.key)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return round(value, 1)
