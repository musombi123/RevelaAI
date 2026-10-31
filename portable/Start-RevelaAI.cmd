@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-RevelaAI.ps1"
exit /b %ERRORLEVEL%
