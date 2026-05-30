@echo off
chcp 65001 >nul
python "%~dp0start.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Start failed. Check:
    echo   - Python 3 installed
    echo   - MySQL 8.4 at C:\Program Files\MySQL\MySQL Server 8.4\
    echo   - pip install flask pymysql openpyxl xlrd
    pause
)
