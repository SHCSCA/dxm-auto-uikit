@echo off
setlocal
if /I "%~1"=="--help" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0final-delivery-check.ps1" -Help
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="/?" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0final-delivery-check.ps1" -Help
  exit /b %ERRORLEVEL%
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0final-delivery-check.ps1" %*
exit /b %ERRORLEVEL%
