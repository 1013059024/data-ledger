@echo off
setlocal enabledelayedexpansion
title Road Ledger

:: ==============================================
::   Road Ledger — One-click launcher
::   Starts MySQL + Flask + optional LAN firewall
:: ==============================================

echo ================================================
echo   Road Ledger -- One-Click Launcher
echo ================================================
echo.

:: ── 1. MySQL ────────────────────────────────────
echo [1/3] Checking MySQL ...
set MYSQLD=C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe
set MYSQL=C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe
set DATADIR=%~dp0mysql-data

:: Check if MySQL is already running
netstat -an 2>nul | findstr ":3306 " >nul 2>&1
if not errorlevel 1 (
    echo   [OK] MySQL is already running.
) else (
    if not exist "%MYSQLD%" (
        echo   [!!] MySQL not found at %MYSQLD%
        echo   Please install MySQL 8.4 first.
        pause
        exit /b 1
    )
    :: Initialize if first run
    if not exist "%DATADIR%\mysql" (
        echo   [..] Initializing MySQL data directory (root empty password) ...
        "%MYSQLD%" --initialize-insecure --datadir="%DATADIR%" --console
        if errorlevel 1 (
            echo   [!!] MySQL initialization failed.
            pause
            exit /b 1
        )
        echo   [OK] Data directory initialized.
    )
    echo   [..] Starting MySQL server ...
    start "MySQL" /MIN "%MYSQLD%" --datadir="%DATADIR%" --port=3306 --console
    :: Wait for MySQL to start
    for /l %%i in (1,1,20) do (
        timeout /t 1 /nobreak >nul
        netstat -an 2>nul | findstr ":3306 " >nul 2>&1
        if not errorlevel 1 goto mysql_ready
    )
    echo   [!!] MySQL failed to start within 20 seconds.
    pause
    exit /b 1
    :mysql_ready
    echo   [OK] MySQL is ready.
)

:: ── 2. Database ─────────────────────────────────
echo [2/3] Ensuring database ...
"%MYSQL%" -u root -e "CREATE DATABASE IF NOT EXISTS road_ledger CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" 2>nul
if errorlevel 1 (
    echo   [!!] Failed to create database.
    pause
    exit /b 1
) else (
    echo   [OK] Database road_ledger ready.
)

:: ── 3. Flask ────────────────────────────────────
echo [3/3] Starting Flask ...
cd /d "%~dp0server"
start "Flask" /MIN cmd /c "python app.py"
if errorlevel 1 (
    echo   [!!] Failed to start Flask.
    pause
    exit /b 1
)
echo   [OK] Flask started.

:: ── Optional: LAN Firewall ──────────────────────
echo.
choice /c YN /n /m "Open port 5000 for LAN access? [Y/N]: "
if errorlevel 2 goto done
netsh advfirewall firewall delete rule name="RoadLedgerFlask" >nul 2>&1
netsh advfirewall firewall add rule name="RoadLedgerFlask" dir=in action=allow protocol=tcp localport=5000 >nul
if errorlevel 1 (
    echo [!!] Firewall failed. Run as Administrator?
) else (
    :: Detect LAN IP
    set MY_IP=
    for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /i "IPv4"') do (
        set "ip=%%i"
        set "ip=!ip: =!"
        if not "!ip!"=="127.0.0.1" if "!MY_IP!"=="" set "MY_IP=!ip!"
    )
    if not "!MY_IP!"=="" echo [OK] LAN: http://!MY_IP!:5000
)

:done
echo.
echo ================================================
echo   ALL SYSTEMS READY!
echo   Local:  http://127.0.0.1:5000
echo ================================================
echo.
echo Close: run close_debug.bat + close the Flask/MySQL windows
echo.
pause