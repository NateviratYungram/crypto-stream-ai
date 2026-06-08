# MT5 Live Trading Bridge

CryptoStream AI runs in Docker, while the `MetaTrader5` Python package must run on the Windows host where MetaTrader 5 is installed and logged in. The bridge lets Docker call the Windows MT5 runtime through HTTP.

## Setup

1. Install MetaTrader 5 on Windows and log in to your broker account.
2. Install Python 3.10+ on Windows.
3. Install the MT5 package:

```powershell
py -m pip install MetaTrader5
```

4. Confirm `.env` has matching bridge values:

```env
MT5_BRIDGE_URL=http://host.docker.internal:8765
MT5_BRIDGE_API_KEY=CHANGE_ME_LOCAL_MT5_BRIDGE_KEY
MT5_BRIDGE_HOST=0.0.0.0
MT5_BRIDGE_PORT=8765
MT5_BRIDGE_ENABLE_LIVE_TRADING=0
```

5. Start the bridge from the project root:

```powershell
.\scripts\start_mt5_bridge.ps1
```

6. Recreate the Docker API so it reloads `.env`:

```powershell
docker --context default compose up -d --force-recreate chat-server
```

7. Verify:

```powershell
Invoke-RestMethod http://localhost:8888/api/mt5/account
Invoke-RestMethod "http://localhost:8888/api/mt5/quote?symbol=GOLD"
Invoke-RestMethod http://localhost:8888/api/system/readiness
```

When Docker reaches the bridge via `host.docker.internal`, the bridge must bind to `0.0.0.0` on Windows. Binding only `127.0.0.1` can leave the MT5 API unreachable from the container even though it works locally in the browser.

## Enable Live Orders

Keep live orders disabled until account and quote checks pass.

```env
MT5_BRIDGE_ENABLE_LIVE_TRADING=1
```

Restart the bridge and recreate `chat-server` after changing this value.
