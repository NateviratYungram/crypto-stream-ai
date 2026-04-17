@echo off
cd /d "%~dp0"
setlocal
echo ==================================================
echo   CryptoStream AI - Institutional Dashboard
echo ==================================================
echo.

REM ── Kill any stale processes on required ports ───────────────
echo [0/2] Clearing ports 8000 and 8888...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " 2^>nul') do (
    if not "%%a"=="0" (
        taskkill /F /PID %%a >nul 2>&1
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8888 " 2^>nul') do (
    if not "%%a"=="0" (
        taskkill /F /PID %%a >nul 2>&1
    )
)
timeout /t 1 /nobreak > nul
echo     Ports cleared.
echo.

if not exist "frontend\dist\index.html" (
    echo [!] Warning: Frontend build not found.
    echo [!] Running 'npm run build' in /frontend...
    cd frontend && npm run build && cd ..
)

echo [1/2] Launching MCP Bridge (Port 8000)...
start "MCP SERVER" /B python -m uvicorn mcp_server.main:app --host 127.0.0.1 --port 8000
timeout /t 3 /nobreak > nul

echo [2/2] Launching Chat Logic (Port 8888)...
echo [!] Dashboard available at: http://localhost:8888
python chat_server.py
pause
