@echo off
rem Copies bots 2 and 3 paper keys from .env.rotation and .env.crypto into GitHub secrets (never shown).
cd /d "%~dp0"
where gh >nul 2>nul || winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
where gh >nul 2>nul || set "PATH=%PATH%;C:\Program Files\GitHub CLI"
.venv\Scripts\python.exe set_cloud_keys.py
pause
