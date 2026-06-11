@echo off
setlocal
cd /d "%~dp0.."

echo ========================================
echo DXM Agent Console - Desktop Mode
echo ========================================
echo.

echo [1/3] Building frontend...
call npm --prefix app\frontend run build
if errorlevel 1 (
  echo Frontend build failed.
  exit /b %errorlevel%
)

if not exist app\desktop\node_modules (
  echo [2/3] Installing desktop dependencies...
  call npm --prefix app\desktop install
  if errorlevel 1 (
    echo Desktop dependency install failed.
    exit /b %errorlevel%
  )
) else (
  echo [2/3] Desktop dependencies OK
)

echo [3/3] Starting Electron Agent Console...
call npm --prefix app\desktop run dev

