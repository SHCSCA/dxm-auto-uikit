@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-mvp.ps1" %*
exit /b %ERRORLEVEL%
