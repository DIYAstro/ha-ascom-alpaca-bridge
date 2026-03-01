# Deployment script for AscomAlpacaBridge to Home Assistant
# Usage: .\deploy.ps1

$HA_IP = ""
$HA_USER = "root"

$secretsFile = Join-Path $PSScriptRoot "deployconf.secrets"
if (Test-Path $secretsFile) {
    Get-Content $secretsFile | ForEach-Object {
        if ($_ -match "^\s*([^#=]+)\s*=\s*(.*)\s*$") {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            if ($key -eq "HA_IP") { $HA_IP = $value }
            if ($key -eq "HA_USER") { $HA_USER = $value }
            if ($key -eq "HA_URL" -and $HA_IP -match "^\s*$") {
                # Fallback: Extract IP/Hostname from HA_URL
                if ($value -match "://([^:/]+)") {
                    $HA_IP = $matches[1]
                }
            }
        }
    }
}

if ($HA_IP -match "^\s*$") {
    Write-Host "Error: Could not determine HA_IP. Please add HA_IP or HA_URL to your .secrets file." -ForegroundColor Red
    exit 1
}

$REMOTE_PATH = "/config/custom_components/"
$LOCAL_FOLDER = "custom_components/ascom_alpaca_bridge"

Write-Host "Starting deployment to Home Assistant ($HA_IP)..." -ForegroundColor Cyan

# Use scp to copy the folder
# -r for recursive, -O for legacy protocol, -c to fix MAC errors
scp -r -O -c aes256-gcm@openssh.com $LOCAL_FOLDER "${HA_USER}@${HA_IP}:${REMOTE_PATH}"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Successfully uploaded ascom_alpaca_bridge to Home Assistant." -ForegroundColor Green
    Write-Host "Restarting Home Assistant Core..." -ForegroundColor Cyan
    ssh -c aes256-gcm@openssh.com "${HA_USER}@${HA_IP}" "ha core restart"
    
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "1. Wait a moment for HA to come back online."
    Write-Host "2. Go to Settings -> Devices & Services -> Add Integration -> AscomAlpacaBridge."
} else {
    Write-Host "Deployment failed. Please check your SSH connection and credentials." -ForegroundColor Red
}
