@echo off
chcp 65001 >nul
cd /d "%~dp0"

set PYEXE=C:/Users/666/.workbuddy-ai/binaries/python/versions/3.13.12/python.exe
if not exist "%PYEXE%" set PYEXE=python

echo.
echo ============================================
echo   WeChat x Jev Bot
echo   1) Scan the QR code with WeChat
echo   2) Then send a message to the bot
echo   Press Ctrl+C to stop
echo ============================================
echo.

"%PYEXE%" -X utf8 bot.py

echo.
echo Bot stopped. Press any key to close.
pause >nul
