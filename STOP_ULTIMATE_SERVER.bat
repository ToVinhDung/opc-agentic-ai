@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0STOP_ULTIMATE_SERVER.ps1"
if errorlevel 1 pause
endlocal
