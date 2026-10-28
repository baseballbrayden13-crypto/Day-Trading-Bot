@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File install_helpers.ps1
pause
