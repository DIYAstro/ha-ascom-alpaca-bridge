"""Binary sensor platform for Alpaca Bridge."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

from .const import DOMAIN
from .base import AlpacaEntity

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the binary sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for device in coordinator.devices:
        if device["DeviceType"].lower() == "safetymonitor":
            entities.append(AlpacaSafetyMonitor(coordinator, device))
        elif device["DeviceType"].lower() == "switch":
            dev_key = f"switch_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            maxswitch = data.get("maxswitch", 0)
            for i in range(maxswitch):
                # If it cannot write AND it is not analog, it's a read-only boolean
                if not data.get(f"canwrite_{i}", True) and not data.get(f"is_analog_{i}", False):
                    entities.append(AlpacaSwitchBinarySensor(coordinator, device, i))

        elif device["DeviceType"].lower() == "telescope":
            dev_key = f"telescope_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            telescope_status = {
                "atpark": {"name": "Parked", "icon": "mdi:parking"},
                "athome": {"name": "At Home", "icon": "mdi:home"},
                "slewing": {"name": "Slewing", "icon": "mdi:rotate-orbit"},
                # doesrefraction is handled by switch.py (R/W) — no need for a separate binary_sensor
            }
            for prop, config in telescope_status.items():
                if prop in data:
                    entities.append(AlpacaTelescopeBinarySensor(coordinator, device, prop, config))
                    
            caps = data.get("capabilities", {})
            if "ispulseguiding" in data:
                entities.append(AlpacaTelescopeBinarySensor(coordinator, device, "ispulseguiding", {"name": "Pulse Guiding", "icon": "mdi:crosshairs"}))

        elif device["DeviceType"].lower() == "rotator":
            dev_key = f"rotator_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            if "ismoving" in data:
                entities.append(AlpacaRotatorBinarySensor(coordinator, device, "ismoving", {"name": "Is Moving", "icon": "mdi:cursor-move"}))

        elif device["DeviceType"].lower() == "camera":
            dev_key = f"camera_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            if "imageready" in data:
                entities.append(AlpacaCameraBinarySensor(coordinator, device, "imageready", {"name": "Image Ready", "icon": "mdi:camera-burst"}))
            if "ispulseguiding" in data:
                entities.append(AlpacaCameraBinarySensor(coordinator, device, "ispulseguiding", {"name": "Pulse Guiding", "icon": "mdi:crosshairs-gps"}))

        elif device["DeviceType"].lower() == "focuser":
            dev_key = f"focuser_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            if "ismoving" in data:
                entities.append(AlpacaFocuserBinarySensor(coordinator, device, "ismoving", {"name": "Moving", "icon": "mdi:motion-play"}))

        elif device["DeviceType"].lower() == "dome":
            dev_key = f"dome_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            dome_status = {
                "athome": {"name": "At Home", "icon": "mdi:home"},
                "atpark": {"name": "Parked", "icon": "mdi:parking"},
            }
            for prop, config in dome_status.items():
                if prop in data:
                    entities.append(AlpacaDomeBinarySensor(coordinator, device, prop, config))
                    
            if "slewing" in data:
                entities.append(AlpacaDomeMovingBinarySensor(coordinator, device, "slewing", {"name": "Moving", "icon": "mdi:motion-play"}))

    if entities:
        async_add_entities(entities)


class AlpacaSafetyMonitor(AlpacaEntity, BinarySensorEntity):
    """Safety Monitor Binary Sensor."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Safety"
        self._attr_unique_id = f"{super().unique_id}_issafe"
        self._attr_device_class = BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self):
        """Return true if safety issue detected."""
        # HA Device Class SAFETY: On means unsafe, Off means safe.
        # ASCOM isSafe: True means safe, False means unsafe.
        data = self.coordinator.data.get(self.dev_key, {})
        is_safe = data.get("issafe")
        
        if is_safe is None:
            return None
        return not is_safe

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "issafe" in self.coordinator.data.get(self.dev_key, {})


class AlpacaSwitchBinarySensor(AlpacaEntity, BinarySensorEntity):
    """Switch Binary Sensor for read-only boolean switch metrics."""

    def __init__(self, coordinator, device, switch_id):
        """Initialize."""
        super().__init__(coordinator, device)
        self.switch_id = switch_id
        
        name = self.coordinator.data.get(self.dev_key, {}).get(f"name_{switch_id}", f"Switch {switch_id}")
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{switch_id}_binary"

    @property
    def is_on(self):
        """Return true if switch is on."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(f"switch_{self.switch_id}")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and f"switch_{self.switch_id}" in self.coordinator.data.get(self.dev_key, {})


class AlpacaTelescopeBinarySensor(AlpacaEntity, BinarySensorEntity):
    """Binary sensor for telescope status (AtPark, AtHome, Slewing)."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]

    @property
    def is_on(self):
        """Return true if the status flag is true."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(self.prop)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaCameraBinarySensor(AlpacaEntity, BinarySensorEntity):
    """Binary sensor for camera status (ImageReady, IsPulseGuiding)."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]

    @property
    def is_on(self) -> bool:
        """Return true if the status flag is true."""
        return bool(self.coordinator.data.get(self.dev_key, {}).get(self.prop))

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.coordinator.data.get(self.dev_key, {}).get(self.prop) is not None

class AlpacaRotatorBinarySensor(AlpacaEntity, BinarySensorEntity):
    """Binary sensor for rotator status (IsMoving)."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]
        self._attr_device_class = BinarySensorDeviceClass.MOVING

    @property
    def is_on(self):
        """Return true if moving."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(self.prop)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaFocuserBinarySensor(AlpacaEntity, BinarySensorEntity):
    """Binary sensor for focuser status (IsMoving)."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]
        self._attr_device_class = BinarySensorDeviceClass.MOVING

    @property
    def is_on(self):
        """Return true if moving."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(self.prop)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaDomeBinarySensor(AlpacaEntity, BinarySensorEntity):
    """Binary sensor for dome status (AtPark, AtHome)."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]

    @property
    def is_on(self):
        """Return true if the status flag is true."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(self.prop)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaDomeMovingBinarySensor(AlpacaDomeBinarySensor):
    """Binary sensor for dome moving status (Slewing)."""
    
    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device, prop, config)
        self._attr_device_class = BinarySensorDeviceClass.MOVING
