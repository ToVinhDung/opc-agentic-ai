@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_OFFLINE_DEMO.ps1"
if errorlevel 1 pause
endlocal
