@echo off

:: Resolve project root from this script's own location (portable, no hardcoded path)
set ROOT=%~dp0
if "%ROOT:~-1%"=="\" set ROOT=%ROOT:~0,-1%

:: ---- Install frontend deps if node_modules is missing ----
if not exist "%ROOT%\frontend\node_modules" (
    echo [INFO] frontend\node_modules not found, running npm install...
    pushd "%ROOT%\frontend"
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed. Make sure Node.js is installed.
        popd
        pause
        exit /b 1
    )
    popd
    echo [INFO] npm install done.
    echo.
)

:: ---- Start backend (FastAPI + uvicorn hot-reload) ----
echo [INFO] Starting backend on http://127.0.0.1:18088 ...
start "VibeResearch Backend" cmd /k "cd /d %ROOT%\backend && python -m uvicorn main:app --reload --port 18088"

:: Wait for backend to initialize (DB migration takes ~2-3 s)
timeout /t 3 /nobreak >nul

:: ---- Start frontend Vite dev server (proxies /api to backend) ----
echo [INFO] Starting frontend on http://localhost:5173 ...
start "VibeResearch Frontend" cmd /k "cd /d %ROOT%\frontend && npm run dev"

echo.
echo =========================================
echo  Backend  : http://127.0.0.1:18088
echo  Frontend : http://localhost:5173
echo =========================================
echo  Frontend code edits  -^> browser HMR auto-reload
echo  Backend  code edits  -^> uvicorn   auto-reload
echo =========================================
echo.
pause
