@echo off
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo.
echo ==========================================
echo   SIA -- Windows Setup
echo ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Download from https://python.org
    echo         Make sure to check "Add Python to PATH" during install.
    pause & exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER%

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Download from https://nodejs.org
    pause & exit /b 1
)
for /f %%v in ('node --version') do set NODEVER=%%v
echo [OK] Node %NODEVER%

:: Check pip
pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip not found. Reinstall Python with pip included.
    pause & exit /b 1
)

:: Virtual environment
if not exist ".venv" (
    echo [..] Creating Python virtual environment...
    python -m venv .venv
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

:: Activate and install Python deps
echo [..] Installing Python dependencies...
call .venv\Scripts\activate.bat
pip install -q --upgrade pip
pip install -q python-dotenv
pip install -q -r requirements.txt
echo [OK] Python dependencies installed

:: Frontend deps
echo [..] Installing frontend dependencies...
cd frontend
call npm install --silent
cd ..
echo [OK] Frontend dependencies installed

:: .env
if not exist ".env" (
    copy .env.example .env >nul
    echo.
    echo [!] Created .env file. Please edit it and add your Anthropic API key:
    echo     notepad .env
    echo.
) else (
    echo [OK] .env already exists
)

:: SSL certs
if not exist "cert.pem" (
    echo [..] Generating SSL certificates...
    openssl req -x509 -newkey rsa:2048 ^
        -keyout key.pem -out cert.pem ^
        -days 365 -nodes ^
        -subj "/CN=localhost" 2>nul
    if errorlevel 1 (
        echo [WARN] openssl not found. Generating self-signed cert via PowerShell...
        powershell -NoProfile -Command ^
            "$cert = New-SelfSignedCertificate -DnsName 'localhost' -CertStoreLocation 'cert:\LocalMachine\My' -NotAfter (Get-Date).AddDays(365); $pwd = ConvertTo-SecureString -String 'sia123' -Force -AsPlainText; Export-PfxCertificate -Cert $cert -FilePath 'sia.pfx' -Password $pwd; Write-Host 'PFX created as sia.pfx'"
        echo [WARN] SSL via PFX. Server will run HTTP on port 8340.
    ) else (
        echo [OK] SSL certificates generated
    )
) else (
    echo [OK] SSL certificates already exist
)

:: Data dir
if not exist "data\ambient" mkdir data\ambient

echo.
echo ==========================================
echo   Setup complete!
echo.
echo   Next steps:
echo.
echo   1. Add your Anthropic API key to .env:
echo      notepad .env
echo.
echo   2. Start the backend (Command Prompt 1):
echo      start_backend.bat
echo.
echo   3. Start the frontend (Command Prompt 2):
echo      start_frontend.bat
echo.
echo   4. Open Chrome and go to:
echo      http://localhost:5173
echo.
echo   5. Click the page and speak!
echo.
echo   Note: ElevenLabs is optional.
echo   Without it, SIA uses Windows built-in
echo   speech synthesis automatically.
echo ==========================================
echo.
pause
