"""Camera platform for Alpaca Bridge."""
import struct
import io
import logging

import aiohttp
from PIL import Image

from homeassistant.components.camera import Camera
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .base import AlpacaEntity

LOGGER = logging.getLogger(__package__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the camera platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in coordinator.devices:
        if device["DeviceType"].lower() == "camera":
            entities.append(AlpacaCamera(coordinator, device))
    if entities:
        async_add_entities(entities)

class AlpacaCamera(AlpacaEntity, Camera):
    """Representation of an ASCOM Alpaca Camera."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        Camera.__init__(self)
        self._attr_name = f"Alpaca Camera {self.dev_num}"
        self._attr_unique_id = f"{super().unique_id}_camera"
        self._attr_is_streaming = False
        
        # Caching logic
        self._last_image_data = None
        self._last_image_ready = False

    @property
    def brand(self) -> str | None:
        """Return the camera brand."""
        return self.coordinator.data.get(self.dev_key, {}).get("sensorname")

    @property
    def model(self) -> str | None:
        """Return the camera model."""
        return self.coordinator.data.get(self.dev_key, {}).get("sensorname") or "ASCOM Camera"

    @property
    def available(self) -> bool:
        """Return False if the camera is not available. Wait until image is ready."""
        if not super().available:
            return False
            
        # Optional: could check if imageready is true, but HA allows viewing cameras anytime.
        # We will let async_camera_image decide whether to return an image or fallback.
        return True

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """Return bytes of camera image."""
        # Check if exposing. If currently exposing, downloading the image might fail or return the old one.
        camerastate = self.coordinator.data.get(self.dev_key, {}).get("camerastate")
        imageready = self.coordinator.data.get(self.dev_key, {}).get("imageready")
        
        # camerastate: 0=Idle, 1=Waiting, 2=Exposing, 3=Reading, 4=Download, 5=Error
        if camerastate in (1, 2, 3, 5) and not imageready:
            LOGGER.debug("Camera %s is busy (state %s) and no image is ready.", self.name, camerastate)
            return self._last_image_data
            
        # If image is not ready and we have a cached image, return it
        if not imageready and self._last_image_data is not None:
            return self._last_image_data
            
        # Avoid re-fetching the same image repeatedly. We only fetch if imageready recently turned True.
        # But if we don't have an image at all, try to fetch it anyway (maybe HA restarted while image is ready).
        if imageready and self._last_image_ready and self._last_image_data is not None:
             return self._last_image_data
             
        self._last_image_ready = imageready
        
        url = f"http://{self.coordinator.host}:{self.coordinator.port}/api/v1/camera/{self.dev_num}/imagearray"
        headers = {
            "Accept": "application/imagebytes",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        tid = self.coordinator.get_client_transaction_id()
        
        max_retries = 3
        retry_delay = 0.5
        raw_data = None
        
        import asyncio
        for attempt in range(max_retries):
            try:
                get_url = f"{url}?ClientID=1&ClientTransactionID={tid}"
                session = async_get_clientsession(self.coordinator.hass)
                # Adding a specific timeout for the image download to prevent locking up
                async with session.get(get_url, headers=headers, timeout=15) as response:
                    if response.status != 200:
                        LOGGER.debug("Camera %s image fetch failed with status %s", self.name, response.status)
                        return None
                        
                    raw_data = await response.read()
                    
                    if len(raw_data) < 44:
                        LOGGER.debug("Camera %s returned invalid ImageBytes (too short).", self.name)
                        return None
                        
                    break # Success, exit retry loop
                    
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                if attempt < max_retries - 1:
                    LOGGER.debug("Camera %s image fetch failed (%s), retrying in %s seconds...", self.name, err, retry_delay)
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    tid = self.coordinator.get_client_transaction_id() # get new ID for retry
                else:
                    LOGGER.warning("Camera %s image fetch failed after %s attempts: %s", self.name, max_retries, err)
                    return None
            except Exception as err:
                LOGGER.error("Camera %s unexpected error during image fetch: %s", self.name, err)
                return None

        if not raw_data:
            return None
            
        # Parse the 44-byte Little-Endian ArrayMetadataV1
        # Format: 11x uint32
        header_format = "<11I"
        header_tuple = struct.unpack_from(header_format, raw_data, 0)
        
        metadata_version = header_tuple[0]
        error_number = header_tuple[1]
        data_start = header_tuple[4]
        image_element_type = header_tuple[5]
        dim1 = header_tuple[8]   # X (width)
        dim2 = header_tuple[9]   # Y (height)
        dim3 = header_tuple[10]  # Z (channels)
        
        if error_number != 0 or metadata_version != 1:
            LOGGER.debug("Camera %s returned Alpaca error %s or unknown header.", self.name, error_number)
            return None
            
        pixel_data = raw_data[data_start:]
        
        # Pillow decoding
        try:
            mode = "L"
            if dim3 == 3:
                # 3 channels (RGB)
                if image_element_type == 1: # Int16 usually mapping to 2 in Alpaca, let's assume 1=Int16?
                    # Usually 8-bit RGB
                    mode = "RGB"
                    image = Image.frombytes(mode, (dim2, dim1), pixel_data).transpose(Image.TRANSPOSE)
                else:
                    # Assume 8-bit for RGB fallback
                    mode = "RGB"
                    image = Image.frombytes(mode, (dim2, dim1), pixel_data).transpose(Image.TRANSPOSE)
            else:
                # Mono
                # Determine element type (Alpaca standard: 1=Int16, 2=Int32, etc.. wait.. actually standard is:
                # 0=Unknown, 1=Int16, 2=Int32, 3=Double, 4=Single, 5=UInt64, 6=Byte, 7=Int64, 8=UInt16)
                # We will try to guess from len(pixel_data) / (dim1 * dim2)
                num_pixels = dim1 * dim2
                bytes_per_pixel = len(pixel_data) // num_pixels
                
                if bytes_per_pixel == 1:
                    mode = "L"
                    image = Image.frombytes(mode, (dim2, dim1), pixel_data).transpose(Image.TRANSPOSE)
                elif bytes_per_pixel == 2:
                    mode = "I;16" # 16-bit integer, standard little endian
                    image = Image.frombytes(mode, (dim2, dim1), pixel_data).transpose(Image.TRANSPOSE)
                    # Simple linear stretch: scale 16-bit to 8-bit.
                    image = image.point(lambda i: i * (1/256)).convert("L")
                elif bytes_per_pixel == 4:
                    mode = "I" # 32-bit integer
                    image = Image.frombytes(mode, (dim2, dim1), pixel_data).transpose(Image.TRANSPOSE)
                    # Assume data is primarily 16-bit scaled inside a 32-bit int, scale by 1/256
                    image = image.point(lambda i: i * (1/256)).convert("L")
                else:
                    LOGGER.debug("Unsupported precise bytes per pixel = %s", bytes_per_pixel)
                    return None

            # Render to JPEG for Home Assistant
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG', quality=85)
            self._last_image_data = img_byte_arr.getvalue()
            return self._last_image_data
            
        except Exception as e:
            LOGGER.debug("Failed to decode ImageBytes for camera %s: %s", self.name, e)
            return self._last_image_data
