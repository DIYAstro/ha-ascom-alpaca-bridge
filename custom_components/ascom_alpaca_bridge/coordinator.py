"""DataUpdateCoordinator for Alpaca Bridge."""
import asyncio
import time
from datetime import timedelta
from typing import Any, Dict

import aiohttp
import async_timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, API_BASE, LOGGER, CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE


class AlpacaDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Alpaca data from the server."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, devices: list, scan_interval: int = DEFAULT_SCAN_INTERVAL, max_sensor_age: int = DEFAULT_MAX_SENSOR_AGE) -> None:
        """Initialize."""
        self.host = host
        self.port = port
        self.devices = devices
        self.base_url = f"http://{host}:{port}/{API_BASE}"
        self._client_transaction_id = 1
        self.max_sensor_age = max_sensor_age
        
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    def get_client_transaction_id(self) -> int:
        """Get and increment the ClientTransactionID, resetting before reaching the 32-bit unsigned limit."""
        self._client_transaction_id += 1
        if self._client_transaction_id > 2000000000:
            self._client_transaction_id = 1
        return self._client_transaction_id

    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        """Update data via HTTP."""
        try:
            session = async_get_clientsession(self.hass)
            data = {}
            
            async with async_timeout.timeout(30):
                # Fetch data for each device sequentially or concurrently
                # To avoid overwhelming the device, we do it in a reasonably controlled way
                tasks = []
                for device in self.devices:
                    dev_type = device["DeviceType"].lower()
                    dev_num = device["DeviceNumber"]
                    dev_key = f"{dev_type}_{dev_num}"
                    
                    # Preserve unapplied target values for up to 30 seconds
                    old_device_data = self.data.get(dev_key, {}) if self.data else {}
                    data[dev_key] = {}
                    
                    for k, v in old_device_data.items():
                        if k.startswith("target_") and not k.endswith("_timestamp"):
                            target_ts = old_device_data.get(f"{k}_timestamp", 0)
                            if time.time() - target_ts < 30:
                                data[dev_key][k] = v
                                data[dev_key][f"{k}_timestamp"] = target_ts
                    
                    tasks.append(self._fetch_common_meta(session, data, dev_key, dev_type, dev_num))
                    
                    if dev_type == "observingconditions":
                        props = ["cloudcover", "dewpoint", "humidity", "pressure", 
                                 "temperature", "windspeed", "starfwhm", 
                                 "skybrightness", "skytemperature", "winddirection",
                                 "skyquality", "rainrate", "windgust"]
                        for p in props:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                            # Fetch age via timesincelastupdate?SensorName=<prop>
                            age_prop = f"timesincelastupdate?SensorName={p}"
                            tasks.append(self._fetch_age_task(session, data, dev_key, dev_type, dev_num, p, age_prop))
                    elif dev_type == "safetymonitor":
                        tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "issafe"))
                    elif dev_type == "switch":
                        tasks.append(self._fetch_switch_task(session, data, dev_key, dev_num))
                    elif dev_type == "dome":
                        # Fetch static capabilities
                        tasks.append(self._fetch_dome_capabilities(session, data, dev_key, dev_num))
                        
                        # Fetch dynamic properties
                        for p in ["shutterstatus", "altitude", "azimuth", "athome", "atpark", "slaved", "slewing"]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                    elif dev_type == "covercalibrator":
                        tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "coverstate"))
                        tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "calibratorstate"))
                        tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "brightness"))
                        tasks.append(self._fetch_covercal_meta(session, data, dev_key, dev_num))
                    elif dev_type == "telescope":
                        # Fetch static capabilities once
                        tasks.append(self._fetch_telescope_capabilities(session, data, dev_key, dev_num))
                        
                        # Position & coordinates
                        for p in [
                            "rightascension", "declination", "altitude", "azimuth", "siderealtime",
                            "sitelatitude", "sitelongitude", "siteelevation", "focallength",
                            "aperturediameter", "aperturearea", "equatorialsystem", "alignmentmode"
                        ]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                        
                        # Status & tracking
                        for p in [
                            "tracking", "trackingrate", "atpark", "athome", "slewing",
                            "sideofpier", "doesrefraction", "ispulseguiding", "slewsettletime", "utcdate"
                        ]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                            
                        for p in [
                            "declinationrate", "rightascensionrate", "guideratedeclination", "guideraterightascension"
                        ]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                    elif dev_type == "rotator":
                        # Fetch static capability CanReverse once
                        tasks.append(self._fetch_rotator_capabilities(session, data, dev_key, dev_num))
                        
                        # Fetch dynamic properties
                        for p in ["position", "targetposition", "stepsize", "ismoving", "reverse", "mechanicalposition"]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                    elif dev_type == "filterwheel":
                        tasks.append(self._fetch_filterwheel_meta(session, data, dev_key, dev_num))
                        tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "position"))
                    elif dev_type == "focuser":
                        tasks.append(self._fetch_focuser_capabilities(session, data, dev_key, dev_num))
                        for p in ["position", "temperature", "ismoving", "tempcomp", "stepsize"]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                    elif dev_type == "camera":
                        # Fetch static capabilities once
                        tasks.append(self._fetch_camera_capabilities(session, data, dev_key, dev_num))
                        
                        # Fetch dynamic properties
                        for p in [
                            "camerastate", "ccdtemperature", "coolerpower", "percentcompleted", 
                            "electronsperadu", "fullwellcapacity", "maxadu", "pixelsizex", "pixelsizey",
                            "imageready", "ispulseguiding", "cooleron", "fastreadout", "sensorname", "sensortype",
                            "gain", "offset", "binx", "biny", "readoutmode", "numx", "numy", "startx", "starty",
                            "heatsinktemperature", "setccdtemperature",
                            "maxbinx", "maxbiny", "gainmax", "gainmin", "offsetmax", "offsetmin", "exposuremax", "exposuremin"
                        ]:
                            tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                
                if tasks:
                    await asyncio.gather(*tasks)
                    
                    # Debug: log CoverCalibrator state after fetch
                    if dev_type == "covercalibrator":
                        cc_data = data.get(dev_key, {})
                        LOGGER.debug(
                            "CoverCalibrator %s state: calibratorstate=%s, brightness=%s, coverstate=%s, maxbrightness=%s",
                            dev_key, cc_data.get("calibratorstate"), cc_data.get("brightness"),
                            cc_data.get("coverstate"), cc_data.get("maxbrightness")
                        )

            return data
        except aiohttp.ClientConnectorError as err:
            raise UpdateFailed(f"Connection failed: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _fetch_prop_task(self, session, data, dev_key, dev_type, dev_num, prop):
        """Helper to fetch a single property and assign it to the data dict."""
        val = await self.fetch_property(session, dev_type, dev_num, prop)
        if val is not None:
            data[dev_key][prop] = val

    async def _fetch_age_task(self, session, data, dev_key, dev_type, dev_num, prop_name, age_prop):
        """Fetch timesincelastupdate for a given sensor property and store as age_<prop>."""
        val = await self.fetch_property(session, dev_type, dev_num, age_prop)
        if val is not None:
            data[dev_key][f"age_{prop_name}"] = float(val)

    async def _fetch_common_meta(self, session, data, dev_key, dev_type, dev_num):
        """Fetch and cache common properties like driverversion."""
        if not hasattr(self, "_common_meta"):
            self._common_meta = {}
            
        if dev_key not in self._common_meta:
            meta = {}
            version = await self.fetch_property(session, dev_type, dev_num, "driverversion")
            info = await self.fetch_property(session, dev_type, dev_num, "driverinfo")
            meta["driverversion"] = version if version else "Unknown"
            meta["driverinfo"] = info if info else "Unknown"
            self._common_meta[dev_key] = meta
            
        data[dev_key]["driverversion"] = self._common_meta[dev_key]["driverversion"]
        data[dev_key]["driverinfo"] = self._common_meta[dev_key]["driverinfo"]

    async def _fetch_covercal_meta(self, session, data, dev_key, dev_num):
        """Fetch and cache CoverCalibrator maxbrightness."""
        if not hasattr(self, "_covercal_meta"):
            self._covercal_meta = {}
        if dev_key not in self._covercal_meta:
            maxbright = await self.fetch_property(session, "covercalibrator", dev_num, "maxbrightness")
            if maxbright is not None:
                LOGGER.debug("CoverCalibrator %s maxbrightness: %s", dev_key, maxbright)
                self._covercal_meta[dev_key] = int(maxbright)
            else:
                LOGGER.warning("Could not fetch maxbrightness for CoverCalibrator %s, defaulting to 255", dev_key)
                self._covercal_meta[dev_key] = 255
        # Always write into the data dict so switch.py and number.py can access it
        data[dev_key]["maxbrightness"] = self._covercal_meta[dev_key]

    async def _fetch_dome_capabilities(self, session, data, dev_key, dev_num):
        """Fetch and cache dome capabilities."""
        if not hasattr(self, "_dome_capabilities"):
            self._dome_capabilities = {}
            
        if dev_key not in self._dome_capabilities:
            caps = {}
            cap_props = [
                "canfindhome", "canpark", "cansetaltitude", "cansetazimuth",
                "cansetpark", "cansetshutter", "canslave", "cansyncazimuth"
            ]
            
            tasks = [self.fetch_property(session, "dome", dev_num, p) for p in cap_props]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for prop, val in zip(cap_props, results):
                if isinstance(val, Exception) or val is None:
                    caps[prop] = False
                else:
                    caps[prop] = bool(val)
            
            LOGGER.debug("Dome %s capabilities cached: %s", dev_key, caps)
            self._dome_capabilities[dev_key] = caps
            
        data[dev_key]["capabilities"] = self._dome_capabilities[dev_key]
                
    async def _fetch_telescope_capabilities(self, session, data, dev_key, dev_num):
        """Fetch and cache telescope Can* capabilities."""
        if not hasattr(self, "_telescope_capabilities"):
            self._telescope_capabilities = {}
            
        if dev_key not in self._telescope_capabilities:
            caps = {}
            cap_props = [
                "canpark", "canfindhome", "canslewasync", "canslewaltazasync",
                "cansettracking", "canpulseguide", "cansetguiderates",
                "cansetdeclinationrate", "cansetrightascensionrate", "cansync", "cansyncaltaz",
                "cansetpierside"
            ]
            
            # Fetch all capabilities in parallel
            tasks = [self.fetch_property(session, "telescope", dev_num, p) for p in cap_props]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for prop, val in zip(cap_props, results):
                if isinstance(val, Exception) or val is None:
                    caps[prop] = False
                else:
                    caps[prop] = bool(val)
            
            LOGGER.debug("Telescope %s capabilities cached: %s", dev_key, caps)
            self._telescope_capabilities[dev_key] = caps
            
        data[dev_key]["capabilities"] = self._telescope_capabilities[dev_key]

    async def _fetch_rotator_capabilities(self, session, data, dev_key, dev_num):
        """Fetch and cache rotator CanReverse capability."""
        if not hasattr(self, "_rotator_capabilities"):
            self._rotator_capabilities = {}
            
        if dev_key not in self._rotator_capabilities:
            caps = {}
            val = await self.fetch_property(session, "rotator", dev_num, "canreverse")
            caps["canreverse"] = bool(val) if val is not None else False
            self._rotator_capabilities[dev_key] = caps
            
        data[dev_key]["capabilities"] = self._rotator_capabilities[dev_key]

    async def _fetch_focuser_capabilities(self, session, data, dev_key, dev_num):
        """Fetch and cache focuser capabilities."""
        if not hasattr(self, "_focuser_capabilities"):
            self._focuser_capabilities = {}
            
        if dev_key not in self._focuser_capabilities:
            caps = {}
            cap_props = ["absolute", "tempcompavailable", "maxstep", "maxincrement"]
            
            tasks = [self.fetch_property(session, "focuser", dev_num, p) for p in cap_props]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for prop, val in zip(cap_props, results):
                if isinstance(val, Exception) or val is None:
                    caps[prop] = None if prop in ("maxstep", "maxincrement") else False
                else:
                    caps[prop] = int(val) if prop in ("maxstep", "maxincrement") else bool(val)
            
            LOGGER.debug("Focuser %s capabilities cached: %s", dev_key, caps)
            self._focuser_capabilities[dev_key] = caps
            
        data[dev_key]["capabilities"] = self._focuser_capabilities[dev_key]
        if self._focuser_capabilities[dev_key].get("maxstep") is not None:
            data[dev_key]["maxstep"] = self._focuser_capabilities[dev_key]["maxstep"]
        if self._focuser_capabilities[dev_key].get("maxincrement") is not None:
            data[dev_key]["maxincrement"] = self._focuser_capabilities[dev_key]["maxincrement"]

    async def _fetch_camera_capabilities(self, session, data, dev_key, dev_num):
        """Fetch and cache camera capabilities."""
        if not hasattr(self, "_camera_capabilities"):
            self._camera_capabilities = {}
            
        if dev_key not in self._camera_capabilities:
            caps = {}
            cap_props = [
                "canabortexposure", "canasymmetricbin", "canfastreadout", 
                "cangetcoolerpower", "cansetccdtemperature", "canstopexposure",
                "canpulseguide"
            ]
            
            tasks = [self.fetch_property(session, "camera", dev_num, p) for p in cap_props]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for prop, val in zip(cap_props, results):
                if isinstance(val, Exception) or val is None:
                    caps[prop] = False
                else:
                    caps[prop] = bool(val)
                    
            # Fetch readoutmodes array
            readoutmodes_val = await self.fetch_property(session, "camera", dev_num, "readoutmodes")
            if readoutmodes_val is not None and isinstance(readoutmodes_val, list):
                caps["readoutmodes"] = readoutmodes_val
            else:
                caps["readoutmodes"] = []
            
            LOGGER.debug("Camera %s capabilities cached: %s", dev_key, caps)
            self._camera_capabilities[dev_key] = caps
            
        data[dev_key]["capabilities"] = self._camera_capabilities[dev_key]

    async def _fetch_filterwheel_meta(self, session, data, dev_key, dev_num):
        """Fetch and cache filterwheel Names and FocusOffsets."""
        if not hasattr(self, "_filterwheel_meta"):
            self._filterwheel_meta = {}
            
        if dev_key not in self._filterwheel_meta:
            meta = {}
            names = await self.fetch_property(session, "filterwheel", dev_num, "names")
            offsets = await self.fetch_property(session, "filterwheel", dev_num, "focusoffsets")
            
            meta["names"] = names if names is not None else []
            meta["focusoffsets"] = offsets if offsets is not None else []
            self._filterwheel_meta[dev_key] = meta
            
        data[dev_key]["names"] = self._filterwheel_meta[dev_key]["names"]
        data[dev_key]["focusoffsets"] = self._filterwheel_meta[dev_key]["focusoffsets"]

    async def _fetch_switch_task(self, session, data, dev_key, dev_num):
        """Helper to fetch switch states."""
        # First we need maxswitch if we don't have it
        maxswitch = await self.fetch_property(session, "switch", dev_num, "maxswitch")
        if maxswitch is not None:
            data[dev_key]["maxswitch"] = maxswitch
            
            # Ensure our metadata cache exists
            if not hasattr(self, "_switch_meta"):
                self._switch_meta = {}
                
            for i in range(maxswitch):
                val = await self.fetch_property(session, "switch", dev_num, f"getswitch?Id={i}")
                if val is not None:
                    data[dev_key][f"switch_{i}"] = val
                    
                val2 = await self.fetch_property(session, "switch", dev_num, f"getswitchvalue?Id={i}")
                if val2 is not None:
                    data[dev_key][f"switchvalue_{i}"] = val2
                    
                meta_key = f"{dev_key}_{i}"
                if meta_key not in self._switch_meta:
                    canwrite = await self.fetch_property(session, "switch", dev_num, f"canwrite?Id={i}")
                    name = await self.fetch_property(session, "switch", dev_num, f"getswitchname?Id={i}")
                    
                    min_val = await self.fetch_property(session, "switch", dev_num, f"minswitchvalue?Id={i}")
                    max_val = await self.fetch_property(session, "switch", dev_num, f"maxswitchvalue?Id={i}")
                    step_val = await self.fetch_property(session, "switch", dev_num, f"switchstep?Id={i}")
                    
                    min_val = min_val if min_val is not None else 0.0
                    max_val = max_val if max_val is not None else 1.0
                    step_val = step_val if step_val is not None else 1.0
                    
                    is_analog = (max_val - min_val > 1.0) or (step_val != 1.0 and step_val > 0.0)
                    
                    self._switch_meta[meta_key] = {
                        "canwrite": canwrite if canwrite is not None else True,
                        "name": name if name is not None else f"Switch {i}",
                        "min": min_val,
                        "max": max_val,
                        "step": step_val,
                        "is_analog": is_analog
                    }
                    
                meta = self._switch_meta[meta_key]
                data[dev_key][f"canwrite_{i}"] = meta["canwrite"]
                data[dev_key][f"name_{i}"] = meta["name"]
                data[dev_key][f"min_{i}"] = meta["min"]
                data[dev_key][f"max_{i}"] = meta["max"]
                data[dev_key][f"step_{i}"] = meta["step"]
                data[dev_key][f"is_analog_{i}"] = meta["is_analog"]


    async def fetch_property(self, session, dev_type, dev_num, prop) -> Any:
        """Fetch a specific property from the Alpaca API."""
        tid = self.get_client_transaction_id()
        
        # Determine if we need to append ?ClientTransactionID= or &ClientTransactionID=
        sep = "&" if "?" in prop else "?"
        url = f"{self.base_url}/{dev_type.lower()}/{dev_num}/{prop}{sep}ClientID=1&ClientTransactionID={tid}"
        
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    res = await response.json()
                    # ErrorNumber 0 means success.
                    # Some devices return ErrorNumber 1024 (Not Implemented) for optional properties.
                    if res.get("ErrorNumber") == 0:
                        return res.get("Value")
                elif response.status == 400:
                    LOGGER.warning(
                        "HTTP 400 for %s – check device type/number spelling in config (URL: %s)",
                        prop, url
                    )
                elif response.status == 404:
                    LOGGER.warning("HTTP 404 for %s – device not found (URL: %s)", prop, url)
                else:
                    LOGGER.debug("HTTP %s for %s (URL: %s)", response.status, prop, url)
                return None
        except Exception as err:
            LOGGER.debug("Request failed for %s: %s", url, err)
            return None

    async def send_command(self, dev_type: str, dev_num: int, command: str, data: dict = None) -> Any:
        """Send a PUT command to the Alpaca API."""
        session = async_get_clientsession(self.hass)
        tid = self.get_client_transaction_id()
        url = f"{self.base_url}/{dev_type.lower()}/{dev_num}/{command}"
        
        payload = {
            "ClientID": "1",
            "ClientTransactionID": str(tid)
        }
        if data:
            payload.update(data)
            
        try:
            async with session.put(url, data=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    res = await response.json()
                    err_num = res.get("ErrorNumber")
                    if err_num == 0:
                        # Schedule a fast follow-up poll to catch quick state changes (Smart Polling)
                        self.hass.async_create_task(self._smart_poll())
                        return True
                    elif err_num == 1024 or err_num == 1025: # NotImplemented or InvalidValue
                        LOGGER.debug("Alpaca command %s failed (Not Implemented / Invalid): %s", command, res.get("ErrorMessage"))
                        return False
                    else:
                        LOGGER.error("Alpaca error (Code %s): %s", err_num, res.get("ErrorMessage"))
                        return False
                else:
                    LOGGER.error("HTTP error %s from %s", response.status, url)
                    return False
        except Exception as err:
            LOGGER.error("Request failed for %s: %s", url, err)
            return False

    async def _smart_poll(self) -> None:
        """Intelligently poll a few times after a command to catch state changes quickly.
        This provides a 'snappy' UI response without hammering the API constantly.
        """
        for _ in range(3):
            await asyncio.sleep(1.5)
            await self.async_refresh()
