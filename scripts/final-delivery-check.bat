@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0final-delivery-check.ps1" %*
exit /b %ERRORLEVEL%
