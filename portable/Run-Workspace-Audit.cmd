@echo off
setlocal
set "SCRIPT=%~dp0Run-Workspace-Audit.ps1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
