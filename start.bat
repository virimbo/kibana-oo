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

:: Check if .env exists
if not exist .env (
    echo [SETUP] First time? Creating .env file...
    copy .env.example .env
    echo.
    echo ============================================
    echo  IMPORTANT: Edit the .env file first!
    echo ============================================
    echo.
    echo Open the .env file in this folder and fill in:
    echo   - ELASTICSEARCH_USER  = your Kibana username
    echo   - ELASTICSEARCH_PASSWORD = your Kibana password
    echo.
    echo After editing .env, run this script again.
    echo.
    start notepad .env
    pause
    exit /b 0
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
echo ============================================
echo.
echo Press any key to open in browser...
pause >nul
start http://localhost:3000
