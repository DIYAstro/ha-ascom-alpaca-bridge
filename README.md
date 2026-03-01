# ASCOM Alpaca Bridge for Home Assistant

Home Assistant integration for monitoring and basic control of astronomical equipment via the ASCOM Alpaca protocol.

![Alpaca Bridge Logo](custom_components/ascom_alpaca_bridge/brand/icon@2x.png)


> [!IMPORTANT]
> This integration is primarily designed for **observatory monitoring**. While device control (Telescope, Camera, etc.) is implemented, these features should be considered **experimental**.
> 
> **Disclaimer:** This software is provided **"as-is"**. It has only been tested using **ASCOM Simulators**. Use it with real hardware at your own risk.

## Core Functions

- **Monitoring:** Read status and telemetry from Telescope, Camera, Dome, Focuser, Rotator, Cover, ObservingConditions, and SafetyMonitor.
- **Camera Handling (Experimental):**
    - Uses Alpaca `ImageBytes` for data transfer.
    - Automatic 16-bit to 8-bit image stretching for dashboard previews.
    - **Caching:** Requests new images only when `ImageReady` is True.
    - **Retries:** Exponential backoff for `ImageBytes` HTTP requests.
- **Dynamic Updates:**
    - Real-time updates for numeric limits (Gain, Offset, Exposure).
    - Dynamic option lists for Filter Wheels and Readout Modes.
- **Custom Services (Experimental):**
    - `camera_set_roi`: Set StartX, StartY, NumX, and NumY.
    - `camera_start_exposure`: Trigger frames with manual duration.
    - `pulseguide`: Service-based guiding support.
- **Reliability:** Automatic `ClientTransactionID` reset at 2,000,000,000.

## Installation

### Via HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Go to **HACS** -> **Integrations**.
3. Click the three dots in the top right corner and select **Custom repositories**.
4. Paste the URL of this GitHub repository.
5. Select **Integration** as the category and click **Add**.
6. Find "ASCOM Alpaca Bridge" in the list and click **Download**.
7. Restart Home Assistant.

### Manual Installation
1. Copy the `custom_components/ascom_alpaca_bridge` folder to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. In Home Assistant: **Settings** -> **Devices & Services**.
2. **Add Integration** -> **ASCOM Alpaca Bridge**.
3. Enter the IP and Port (default: 11111) of the Alpaca server.

## Development Deployment

For developers looking to quickly deploy changes to their Home Assistant instance, a `deploy.ps1` script is included. 

**Setup:**
1. Rename or copy the provided `deployconf` file to `deployconf.secrets`.
2. Edit `deployconf.secrets` to include your Home Assistant URL and token:
```env
HA_URL=http://<YOUR_HA_IP>:8123
HA_TOKEN=your_long_lived_token
HA_USER=root  # Optional: defaults to 'root' if not specified
```
> [!TIP]
> `deploy.ps1` intelligently extracts the bare IP address from `HA_URL` for SSH/SCP. Alternatively, you can specify `HA_IP` directly in the secrets file.


**Running the Deployment:**
```powershell
.\deploy.ps1
```

## Testing & Diagnostics

A robust diagnostic script is included in `tests/stresstest.py` to verify connectivity and measure real-world UI latency between Home Assistant and the Alpaca devices.

**Setup:**
The diagnostic tool uses the same `deployconf.secrets` file as the deployment script. Ensure your Long-Lived Access Token is configured correctly:
```env
HA_URL=http://<YOUR_HA_IP>:8123
HA_TOKEN=your_long_lived_token
```


**Running the Test:**
```powershell
# List all connected entities
python .\tests\stresstest.py --mode audit

# Monitor live state changes across the integration
python .\tests\stresstest.py --mode monitor

# Actively test round-trip latency by vigorously toggling all Switches, Sliders (Numbers), and Dropdowns (Selects)
python .\tests\stresstest.py --mode stress
```

---
*Note: This integration is intended for status monitoring and simple remote checks. For active imaging, EAA, or complex sequencing, professional software like N.I.N.A., SGP, or KStars is required.*
