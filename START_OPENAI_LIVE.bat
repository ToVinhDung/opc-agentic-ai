@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0START_OPENAI_LIVE.ps1"
if errorlevel 1 pause
endlocal
