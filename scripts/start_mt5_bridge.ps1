param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return
    }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim().Trim('"').Trim("'")
            if ($name) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
}

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $Python = $cmd.Source
    } else {
        $cmd = Get-Command py -ErrorAction SilentlyContinue
        if ($cmd) {
            $Python = $cmd.Source
        }
    }
}

if (-not $Python) {
    Write-Error "Python was not found. Install Python 3.10+ on Windows, then run: pip install MetaTrader5"
}

Import-DotEnv -Path (Join-Path $ProjectRoot ".env")
$env:PYTHONPATH = $ProjectRoot

if (
    $env:MT5_BRIDGE_URL -match "host\.docker\.internal" -and
    ([string]::IsNullOrWhiteSpace($env:MT5_BRIDGE_HOST) -or $env:MT5_BRIDGE_HOST -in @("127.0.0.1", "localhost"))
) {
    $env:MT5_BRIDGE_HOST = "0.0.0.0"
    Write-Host "MT5_BRIDGE_HOST adjusted to 0.0.0.0 so Docker can reach the Windows host bridge."
}

Write-Host "Starting CryptoStream MT5 Bridge..."
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Python: $Python"
Write-Host "Bridge bind host: $($env:MT5_BRIDGE_HOST)"
Write-Host "Bridge URL should be: http://127.0.0.1:$($env:MT5_BRIDGE_PORT -as [string])"
Write-Host "Install missing package if needed: pip install MetaTrader5"

& $Python -m intelligence.mt5_bridge_server
