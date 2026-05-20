@echo off
setlocal enabledelayedexpansion
title Road Ledger - Debug Share

echo ================================================
echo   Road Ledger -- LAN Share Setup
echo ================================================
echo.

:: --- Detect LAN IP ---
set MY_IP=
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /i "IPv4"') do (
    set "ip=%%i"
    set "ip=!ip: =!"
    if not "!ip!"=="127.0.0.1" if "!MY_IP!"=="" set "MY_IP=!ip!"
)
if "%MY_IP%"=="" (
    echo [!!] No IPv4 found. Run ipconfig manually.
    pause
    exit /b 1
)
echo [OK] LAN IP: %MY_IP%
echo.

:: --- Firewall: Flask port 5000 ---
echo [1/2] Open port 5000 for Flask ...
netsh advfirewall firewall delete rule name="RoadLedgerFlask" >nul 2>&1
netsh advfirewall firewall add rule name="RoadLedgerFlask" dir=in action=allow protocol=tcp localport=5000 >nul
if errorlevel 1 (
    echo [!!] Failed. Run as Administrator then retry.
    pause
    exit /b 1
)
echo [OK] Port 5000 done.

:: --- MySQL port ---
echo.
choice /c YN /n /m "Open port 3306 for MySQL? [Y/N]: "
if errorlevel 2 goto skip_mysql
if errorlevel 1 goto do_mysql
goto skip_mysql

:do_mysql
echo [2/2] Open port 3306 for MySQL ...
netsh advfirewall firewall delete rule name="RoadLedgerMySQL" >nul 2>&1
netsh advfirewall firewall add rule name="RoadLedgerMySQL" dir=in action=allow protocol=tcp localport=3306 >nul
if errorlevel 1 (
    echo [!!] MySQL firewall failed.
) else (
    echo [OK] Port 3306 done.
    echo.
    echo WARNING: MySQL root has no password!
    echo Run these SQL commands in MySQL client:
    echo   CREATE USER 'ledger'@'%%' IDENTIFIED BY 'your_password';
    echo   GRANT ALL PRIVILEGES ON road_ledger.* TO 'ledger'@'%%';
    echo   FLUSH PRIVILEGES;
)
goto show_info

:skip_mysql
echo [SKIP] Web access only (no MySQL).

:: --- Summary ---
:show_info
echo.
echo ================================================
echo   Share this to your colleague:
echo ================================================
echo.
echo   http://%MY_IP%:5000
echo.
echo ================================================
echo.
echo Starting Flask server ...
echo.

cd /d "%~dp0server"
start "Flask" cmd /k "python app.py"
if errorlevel 1 (
    echo [!!] Failed to start Flask. Check Python installation.
    pause
    exit /b 1
)
echo [OK] Flask started in a new window.
echo.
echo Share URL: http://%MY_IP%:5000
echo Colleague just needs to open that in a browser.
echo.
echo To close: run close_debug.bat and close the Flask window.
echo.
pause
