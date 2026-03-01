"""Constants for the AscomAlpacaBridge integration."""
from datetime import timedelta
import logging

LOGGER = logging.getLogger(__package__)

DOMAIN = "ascom_alpaca_bridge"

# Alpaca API configuration
DISCOVERY_PORT = 32227
DEFAULT_PORT = 11111

UPDATE_INTERVAL = timedelta(seconds=10)
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 120

CONF_MAX_SENSOR_AGE = "max_sensor_age"
DEFAULT_MAX_SENSOR_AGE = 600
MIN_MAX_SENSOR_AGE = 30
MAX_MAX_SENSOR_AGE = 86400

# Platforms supported by the bridge
PLATFORMS = [
    "sensor",        # ObservingConditions + Telescope position
    "binary_sensor", # SafetyMonitor + Telescope status
    "switch",        # Switch (Boolean) + CoverCalibrator Power + Telescope Tracking
    "number",        # Switch (Analog/Slider) + CoverCalibrator Brightness + Telescope GoTo targets
    "cover",         # Cover/Dome
    "button",        # Telescope actions (Park, Unpark, Slew, etc.)
    "select",        # Telescope Tracking Rate
    "camera",        # Camera ImageBytes stream
]

# ASCOM Standard Paths
API_BASE = "api/v1"
MGMT_BASE = "management/v1"

# Configuration Keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICES = "devices"

# Services
SERVICE_SLEW_TO_COORDINATES = "slew_to_coordinates"
SERVICE_SLEW_TO_ALT_AZ = "slew_to_alt_az"
SERVICE_ROTATOR_MOVE = "rotator_move"
SERVICE_ROTATOR_SYNC = "rotator_sync"
SERVICE_FOCUSER_MOVE = "focuser_move"
SERVICE_DOME_SLEW_AZ = "dome_slew_az"
SERVICE_DOME_SLEW_ALT = "dome_slew_alt"
SERVICE_DOME_SYNC_AZ = "dome_sync_az"
SERVICE_CAMERA_START_EXPOSURE = "camera_start_exposure"
SERVICE_CAMERA_PULSEGUIDE = "camera_pulseguide"
SERVICE_CAMERA_SET_ROI = "camera_set_roi"
SERVICE_TELESCOPE_PULSEGUIDE = "telescope_pulseguide"
