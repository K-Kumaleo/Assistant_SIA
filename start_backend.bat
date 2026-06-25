@echo off
cd /d "%~dp0"
echo Starting SIA Backend...
call .venv\Scripts\activate.bat
python server.py
pause
