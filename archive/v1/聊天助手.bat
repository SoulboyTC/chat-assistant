@echo off
cd /d "%~dp0"
start "" powershell -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0assistant.ps1"
