@echo off
setlocal

set ROOT=%~dp0
if "%ROOT:~-1%"=="\" set ROOT=%ROOT:~0,-1%

:: ---- Stop backend (18088) ----
echo [INFO] Stopping backend on port 18088...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":18088 " ^| findstr "LISTENING"') do (
    echo [INFO]   Killing PID %%p
    taskkill /PID %%p /F >nul 2>&1
)

:: ---- Stop frontend (5173) ----
echo [INFO] Stopping frontend on port 5173...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    echo [INFO]   Killing PID %%p
    taskkill /PID %%p /F >nul 2>&1
)

timeout /t 1 /nobreak >nul

:: ---- Start backend ----
echo [INFO] Starting backend on http://127.0.0.1:18088 ...
start "VibeResearch Backend" cmd /k "cd /d %ROOT%\backend && python -m uvicorn main:app --reload --port 18088"

:: Wait for backend to initialize before starting frontend
timeout /t 3 /nobreak >nul

:: ---- Start frontend ----
echo [INFO] Starting frontend on http://localhost:5173 ...
start "VibeResearch Frontend" cmd /k "cd /d %ROOT%\frontend && npm run dev"

echo.
echo =========================================
echo  Backend  : http://127.0.0.1:18088
echo  Frontend : http://localhost:5173
echo =========================================
echo.
endlocal
