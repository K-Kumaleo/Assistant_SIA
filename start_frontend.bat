@echo off
cd /d "%~dp0frontend"
echo Starting SIA Frontend...
call npm run dev
pause
