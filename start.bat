@echo off
echo ============================================
echo   KIBANA-OO - AI Log Assistant
echo ============================================
echo.

:: Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running!
    echo Please open Docker Desktop and wait until it's ready.
    echo Then run this script again.
    pause
    exit /b 1
)

:: Create .env from example if it doesn't exist
if not exist .env (
    echo [SETUP] Creating config file...
    copy .env.example .env >nul
)

echo [1/3] Starting services...
docker compose up --build -d

echo.
echo [2/3] Waiting for Ollama to be ready...
timeout /t 10 /nobreak >nul

echo.
echo [3/3] Downloading LLAMA model (first time takes a few minutes)...
docker exec kibana-oo-ollama ollama pull llama3.1:8b

echo.
echo ============================================
echo   KIBANA-OO is ready!
echo   Open your browser: http://localhost:3000
echo   Log in with your Kibana username/password
echo ============================================
echo.
echo Press any key to open in browser...
pause >nul
start http://localhost:3000
