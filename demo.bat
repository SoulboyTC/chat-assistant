@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PYEXE=C://Users//666//.workbuddy-ai//binaries//python//versions//3.13.12//python.exe
if not exist "%PYEXE%" set PYEXE=python

echo.
echo ============================================
echo   Judge demo - no WeChat needed
echo   Type a message, press Enter, see the card
echo   Type q to quit
echo ============================================
echo.

"%PYEXE%" -X utf8 bot.py --demo

echo.
echo Done. Press any key to close.
pause >nul
