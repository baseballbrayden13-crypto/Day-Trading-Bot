@echo off
rem Fleet maintenance (read-only): collects every bot's data, checks them, alerts the phone on problems.
rem Schedule daily at 8:30pm ET:  schtasks /Create /TN "Fleet maintenance (read-only)" /SC DAILY /ST 20:30 /TR "\"%~f0\""
cd /d "%~dp0"
.venv\Scripts\python.exe -W ignore -m bot.maintenance --collect --alert > fleet_data\last_run.txt 2>&1
