@echo off
setlocal enabledelayedexpansion
title Road Ledger - Close Share

echo ================================================
echo   Close LAN Share
echo ================================================
echo.

echo [1/2] Removing firewall rule: Flask port 5000 ...
netsh advfirewall firewall delete rule name="RoadLedgerFlask" >nul 2>&1
if errorlevel 1 (echo [..] Already removed) else (echo [OK] Removed)

echo [2/2] Removing firewall rule: MySQL port 3306 ...
netsh advfirewall firewall delete rule name="RoadLedgerMySQL" >nul 2>&1
if errorlevel 1 (echo [..] Already removed) else (echo [OK] Removed)

echo.
echo ================================================
echo   Done. External access to this machine
echo   via ports 5000 and 3306 is now blocked.
echo ================================================
echo.
pause
