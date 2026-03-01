"""Config flow for Alpaca Bridge."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, CONF_HOST, CONF_PORT, CONF_DEVICES, MGMT_BASE, LOGGER,
    DEFAULT_SCAN_INTERVAL, MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL,
    CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE, MIN_MAX_SENSOR_AGE, MAX_MAX_SENSOR_AGE,
)
from .discovery import async_discover_alpaca_servers

CONF_SCAN_INTERVAL = "scan_interval"

class AlpacaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alpaca Bridge."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return AlpacaOptionsFlow()

    def __init__(self):
        """Initialize."""
        self.discovered_servers = []
        self._host = None
        self._port = None
        self._server_name = None
        self._available_devices = []

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if user_input.get(CONF_HOST) == "Manual":
                return await self.async_step_manual()
            else:
                # User selected a discovered server
                for server in self.discovered_servers:
                    if f"{server['host']}:{server['port']}" == user_input.get(CONF_HOST):
                        result = await self._async_validate_and_fetch_devices(server['host'], server['port'])
                        if result:
                            return result
                        errors["base"] = "cannot_connect"
                        break
                
        # Discover servers
        self.discovered_servers = await async_discover_alpaca_servers()
        
        # If no servers discovered, move to manual entry immediately
        if not self.discovered_servers:
            return await self.async_step_manual()

        # Build list for dropdown
        hosts = [f"{s['host']}:{s['port']}" for s in self.discovered_servers]
        hosts.append("Manual")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=hosts[0]): vol.In(hosts)
            }),
            errors=errors,
        )

    async def async_step_manual(self, user_input=None):
        """Handle manual entry."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            
            result = await self._async_validate_and_fetch_devices(host, port)
            if result:
                return result
            
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=11111): int,
            }),
            errors=errors,
        )

    async def async_step_select_devices(self, user_input=None):
        """Handle device selection."""
        if user_input is not None:
            selected_keys = user_input.get("devices", [])
            
            selected_devices = []
            for dev in self._available_devices:
                key = f"{dev['DeviceType']}_{dev['DeviceNumber']}"
                if key in selected_keys:
                    selected_devices.append(dev)
            
            if not selected_devices:
                return self.async_show_form(
                    step_id="select_devices",
                    data_schema=self._build_device_schema(),
                    errors={"base": "no_devices_selected"},
                )

            return self.async_create_entry(
                title=self._server_name,
                data={
                    CONF_HOST: self._host,
                    CONF_PORT: self._port,
                    CONF_DEVICES: selected_devices
                }
            )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=self._build_device_schema(),
        )

    def _build_device_schema(self):
        """Build a schema with checkboxes for device selection."""
        device_map = {}
        for dev in self._available_devices:
            key = f"{dev['DeviceType']}_{dev['DeviceNumber']}"
            label = f"{dev['DeviceType']} #{dev['DeviceNumber']}: {dev.get('DeviceName', 'Unknown')}"
            device_map[key] = label
        
        return vol.Schema({
            vol.Required("devices", default=list(device_map.keys())): cv.multi_select(device_map)
        })

    async def _async_validate_and_fetch_devices(self, host: str, port: int):
        """Validate connection, fetch devices, and proceed to selection step."""
        session = async_get_clientsession(self.hass)
        
        # 1. Validate description endpoint
        desc_url = f"http://{host}:{port}/{MGMT_BASE}/description"
        server_name = "Alpaca Server"
        LOGGER.debug("Validating Alpaca server at %s", desc_url)
        try:
            async with session.get(desc_url, timeout=5) as response:
                if response.status != 200:
                    LOGGER.error("Alpaca server returned status %s for %s", response.status, desc_url)
                    return None
                res = await response.json()
                value = res.get("Value", {})
                if "ServerName" not in value:
                    LOGGER.error("Alpaca server response missing 'ServerName': %s", res)
                    return None
                server_name = value["ServerName"]
        except Exception as err:
            LOGGER.error("Failed to connect to Alpaca server at %s: %s", desc_url, err)
            return None

        # Make sure it's not already configured
        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        # 2. Get active devices
        devices_url = f"http://{host}:{port}/{MGMT_BASE}/configureddevices"
        devices = []
        LOGGER.debug("Fetching configured devices from %s", devices_url)
        try:
            async with session.get(devices_url, timeout=5) as response:
                if response.status == 200:
                    res = await response.json()
                    values = res.get("Value", [])
                    for dev in values:
                        dev["ServerName"] = server_name
                        devices.append(dev)
                    LOGGER.debug("Found %s Alpaca devices", len(devices))
                else:
                    LOGGER.error("Alpaca server returned status %s for %s", response.status, devices_url)
                    return None
        except Exception as err:
            LOGGER.error("Failed fetching configured devices from %s: %s", devices_url, err)
            return None

        # Store data for the selection step
        self._host = host
        self._port = port
        self._server_name = server_name
        self._available_devices = devices
        
        # Go to device selection step
        return await self.async_step_select_devices()


class AlpacaOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Alpaca Bridge."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_max_age = self.config_entry.options.get(
            CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE
        )

        from homeassistant.helpers.selector import (
            NumberSelector, NumberSelectorConfig, NumberSelectorMode
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current_interval,
                ): NumberSelector(NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                )),
                vol.Required(
                    CONF_MAX_SENSOR_AGE,
                    default=current_max_age,
                ): NumberSelector(NumberSelectorConfig(
                    min=MIN_MAX_SENSOR_AGE,
                    max=MAX_MAX_SENSOR_AGE,
                    step=10,
                    mode=NumberSelectorMode.BOX,
                )),
            }),
        )
