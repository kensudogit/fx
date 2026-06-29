@echo off
echo === FX Tool Setup ===

echo.
echo [1/4] Starting databases...
docker compose up -d
timeout /t 5 /nobreak > nul

echo.
echo [2/4] Setting up Python backend...
cd backend
call install.bat
if errorlevel 1 exit /b 1
cd ..

if not exist .env copy .env.example .env

echo.
echo [3/4] Setting up frontend...
cd frontend
call npm install
cd ..

echo.
echo [4/4] Setup complete!
echo.
echo To start the application:
echo   Terminal 1: cd backend ^&^& .venv\Scripts\activate ^&^& python run.py
echo   Terminal 2: cd frontend ^&^& npm run dev
echo.
echo   Backend API: http://localhost:8000
echo   Frontend UI: http://localhost:3000
