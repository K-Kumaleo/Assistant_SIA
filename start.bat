@echo off
:: Always run from the folder where this .bat file lives
cd /d "%~dp0"

echo.
echo ==========================================
echo   SIA is starting...
echo ==========================================
echo.

:: Start backend in a new window (pinned to this folder)
start "SIA Backend" cmd /k "cd /d "%~dp0" && call .venv\Scripts\activate.bat && python server.py"

:: Wait 2 seconds then start frontend
timeout /t 2 /nobreak >nul

:: Start frontend in a new window (pinned to frontend subfolder)
start "SIA Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

:: Wait for frontend to spin up, then open Chrome
timeout /t 5 /nobreak >nul
start chrome http://localhost:5173

echo.
echo Keep both command windows open while using SIA.
echo Open Chrome at: http://localhost:5173
echo.
