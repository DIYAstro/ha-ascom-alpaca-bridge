"""Cover platform for Alpaca Bridge."""
from homeassistant.components.cover import CoverEntity, CoverDeviceClass, CoverEntityFeature

from .const import DOMAIN
from .base import AlpacaEntity

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the cover platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for device in coordinator.devices:
        dev_type = device["DeviceType"].lower()
        if dev_type == "dome" or dev_type == "covercalibrator":
            entities.append(AlpacaCover(coordinator, device))

    if entities:
        async_add_entities(entities)

class AlpacaCover(AlpacaEntity, CoverEntity):
    """Cover representation."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name}"
        self._attr_unique_id = f"{super().unique_id}_cover"
        self._attr_device_class = CoverDeviceClass.AWNING
        self._attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        
        # Provide stop feature if dome
        if self.dev_type.lower() == "dome":
             self._attr_supported_features |= CoverEntityFeature.STOP

    def _get_status(self):
        """Get the cover/shutter status value."""
        data = self.coordinator.data.get(self.dev_key, {})
        if self.dev_type.lower() == "covercalibrator":
            # ASCOM CoverStatus: 0=NotPresent, 1=Closed, 2=Moving, 3=Open, 4=Unknown, 5=Error
            return data.get("coverstate")
        else:
            # ASCOM ShutterState: 0=Open, 1=Closed, 2=Opening, 3=Closing, 4=Error
            return data.get("shutterstatus")

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        status = self._get_status()
        if status is None:
            return None
        if self.dev_type.lower() == "covercalibrator":
            return status == 1  # Closed
        else:
            return status == 1  # Closed

    @property
    def is_opening(self):
        """Return if the cover is opening."""
        status = self._get_status()
        if self.dev_type.lower() == "covercalibrator":
            return status == 2  # Moving (could be opening)
        else:
            return status == 2  # Opening

    @property
    def is_closing(self):
        """Return if the cover is closing."""
        status = self._get_status()
        if self.dev_type.lower() == "covercalibrator":
            return False  # CoverCalibrator only reports "Moving", not direction
        else:
            return status == 3  # Closing

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        cmd = "opencover" if self.dev_type.lower() == "covercalibrator" else "openshutter"
        
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, cmd
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        cmd = "closecover" if self.dev_type.lower() == "covercalibrator" else "closeshutter"
        
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, cmd
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        if self.dev_type.lower() == "dome":
             success = await self.coordinator.send_command(
                 self.dev_type, self.dev_num, "abortslew"
             )
             if success:
                 await self.coordinator.async_refresh()
        elif self.dev_type.lower() == "covercalibrator":
             success = await self.coordinator.send_command(
                 self.dev_type, self.dev_num, "haltcover"
             )
             if success:
                 await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        data = self.coordinator.data.get(self.dev_key, {})
        if self.dev_type.lower() == "covercalibrator":
            return super().available and "coverstate" in data
        return super().available and "shutterstatus" in data
