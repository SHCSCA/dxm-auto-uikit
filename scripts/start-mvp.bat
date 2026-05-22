@echo off
chcp 936 > nul
setlocal EnableExtensions

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "BACKEND_DIR=%ROOT%\app\backend"
set "FRONTEND_DIR=%ROOT%\app\frontend"
set "DATA_DIR=%ROOT%\data"
set "LAUNCHER_LOG=%DATA_DIR%\start-mvp.log"
set "BACKEND_LOG=%DATA_DIR%\backend.log"
set "FRONTEND_LOG=%DATA_DIR%\frontend.log"
set "NPM_INSTALL_LOG=%DATA_DIR%\npm-install.log"
set "BACKEND_RUNNER=%DATA_DIR%\run-backend.cmd"
set "FRONTEND_RUNNER=%DATA_DIR%\run-frontend.cmd"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

if /I "%~1"=="--help" goto help
if /I "%~1"=="/?" goto help

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

echo [%date% %time%] ==============================================
echo [%date% %time%] ==============================================>>"%LAUNCHER_LOG%"
echo [%date% %time%] 店小秘自动刊登助手 MVP 启动器
echo [%date% %time%] 店小秘自动刊登助手 MVP 启动器>>"%LAUNCHER_LOG%"
echo [%date% %time%] 项目目录：%ROOT%
echo [%date% %time%] 项目目录：%ROOT%>>"%LAUNCHER_LOG%"
echo [%date% %time%] 服务窗口：后端和前端会分别打开普通 CMD 窗口，关闭窗口即停止对应服务。
echo [%date% %time%] 服务窗口：后端和前端会分别打开普通 CMD 窗口，关闭窗口即停止对应服务。>>"%LAUNCHER_LOG%"
echo [%date% %time%] 启动日志：%LAUNCHER_LOG%
echo [%date% %time%] 启动日志：%LAUNCHER_LOG%>>"%LAUNCHER_LOG%"
echo [%date% %time%] 后端日志：%BACKEND_LOG%
echo [%date% %time%] 后端日志：%BACKEND_LOG%>>"%LAUNCHER_LOG%"
echo [%date% %time%] 前端日志：%FRONTEND_LOG%
echo [%date% %time%] 前端日志：%FRONTEND_LOG%>>"%LAUNCHER_LOG%"
echo [%date% %time%] ==============================================
echo [%date% %time%] ==============================================>>"%LAUNCHER_LOG%"

if not exist "%BACKEND_DIR%" goto missing_backend
echo [%date% %time%] 后端目录检查通过：%BACKEND_DIR%
echo [%date% %time%] 后端目录检查通过：%BACKEND_DIR%>>"%LAUNCHER_LOG%"

if not exist "%FRONTEND_DIR%" goto missing_frontend
echo [%date% %time%] 前端目录检查通过：%FRONTEND_DIR%
echo [%date% %time%] 前端目录检查通过：%FRONTEND_DIR%>>"%LAUNCHER_LOG%"

set "PYTHON_EXE=%BACKEND_DIR%\.venv\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto python_ready
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE goto missing_python

:python_ready
echo [%date% %time%] Python：%PYTHON_EXE%
echo [%date% %time%] Python：%PYTHON_EXE%>>"%LAUNCHER_LOG%"

where npm >nul 2>nul
if errorlevel 1 goto missing_npm
echo [%date% %time%] npm 检查通过。
echo [%date% %time%] npm 检查通过。>>"%LAUNCHER_LOG%"

where curl >nul 2>nul
if errorlevel 1 goto missing_curl
echo [%date% %time%] curl 检查通过。
echo [%date% %time%] curl 检查通过。>>"%LAUNCHER_LOG%"

"%PYTHON_EXE%" -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 goto missing_pydeps
echo [%date% %time%] 后端依赖检查通过。
echo [%date% %time%] 后端依赖检查通过。>>"%LAUNCHER_LOG%"

set "VITE_CMD=%FRONTEND_DIR%\node_modules\.bin\vite.cmd"
if exist "%VITE_CMD%" goto frontend_deps_ready
echo [%date% %time%] 未检测到前端 node_modules，开始执行 npm install。
echo [%date% %time%] 未检测到前端 node_modules，开始执行 npm install。>>"%LAUNCHER_LOG%"
pushd "%FRONTEND_DIR%" >nul
call npm install >>"%NPM_INSTALL_LOG%" 2>&1
set "NPM_INSTALL_EXIT=%errorlevel%"
popd >nul
if not "%NPM_INSTALL_EXIT%"=="0" goto npm_install_failed

:frontend_deps_ready
echo [%date% %time%] 前端依赖检查通过。
echo [%date% %time%] 前端依赖检查通过。>>"%LAUNCHER_LOG%"

if /I "%~1"=="--check" goto check_done
if /I "%~1"=="/check" goto check_done

netstat -ano -p tcp | findstr /R /C:":%BACKEND_PORT% .*LISTENING" >"%TEMP%\dxm-backend-port.txt"
if not errorlevel 1 goto backend_port_busy

netstat -ano -p tcp | findstr /R /C:":%FRONTEND_PORT% .*LISTENING" >"%TEMP%\dxm-frontend-port.txt"
if not errorlevel 1 goto frontend_port_busy

echo [%date% %time%] 清空本次后端/前端运行日志。`r`necho [%date% %time%] 后端日志初始化。>"%BACKEND_LOG%"`r`necho [%date% %time%] 前端日志初始化。>"%FRONTEND_LOG%"`r`necho [%date% %time%] 写入后端服务脚本：%BACKEND_RUNNER%
echo [%date% %time%] 清空本次后端/前端运行日志。`r`necho [%date% %time%] 后端日志初始化。>"%BACKEND_LOG%"`r`necho [%date% %time%] 前端日志初始化。>"%FRONTEND_LOG%"`r`necho [%date% %time%] 写入后端服务脚本：%BACKEND_RUNNER%>>"%LAUNCHER_LOG%"
>"%BACKEND_RUNNER%" echo @echo off
>>"%BACKEND_RUNNER%" echo chcp 65001 ^>nul
>>"%BACKEND_RUNNER%" echo title DXM 后端服务 - 关闭窗口即停止
>>"%BACKEND_RUNNER%" echo cd /d "%BACKEND_DIR%"
>>"%BACKEND_RUNNER%" echo set DXM_LOGIN_HEADED=1
>>"%BACKEND_RUNNER%" echo echo 后端服务启动中，关闭此窗口即可停止服务。
>>"%BACKEND_RUNNER%" echo echo 日志文件：%BACKEND_LOG%
>>"%BACKEND_RUNNER%" echo echo [%%date%% %%time%%] 后端进程启动，监听 http://127.0.0.1:%BACKEND_PORT% ^>^>"%BACKEND_LOG%"
>>"%BACKEND_RUNNER%" echo "%PYTHON_EXE%" -m uvicorn src.main:app --host 127.0.0.1 --port %BACKEND_PORT% ^>^>"%BACKEND_LOG%" 2^>^&1
>>"%BACKEND_RUNNER%" echo echo [%%date%% %%time%%] 后端进程退出，退出码 %%errorlevel%% ^>^>"%BACKEND_LOG%"
>>"%BACKEND_RUNNER%" echo echo 后端服务已退出。可以关闭此窗口。

echo [%date% %time%] 写入前端服务脚本：%FRONTEND_RUNNER%
echo [%date% %time%] 写入前端服务脚本：%FRONTEND_RUNNER%>>"%LAUNCHER_LOG%"
>"%FRONTEND_RUNNER%" echo @echo off
>>"%FRONTEND_RUNNER%" echo chcp 65001 ^>nul
>>"%FRONTEND_RUNNER%" echo title DXM 前端服务 - 关闭窗口即停止
>>"%FRONTEND_RUNNER%" echo cd /d "%FRONTEND_DIR%"
>>"%FRONTEND_RUNNER%" echo echo 前端服务启动中，关闭此窗口即可停止服务。
>>"%FRONTEND_RUNNER%" echo echo 日志文件：%FRONTEND_LOG%
>>"%FRONTEND_RUNNER%" echo echo [%%date%% %%time%%] 前端进程启动，监听 http://127.0.0.1:%FRONTEND_PORT% ^>^>"%FRONTEND_LOG%"
>>"%FRONTEND_RUNNER%" echo call "%VITE_CMD%" --host 0.0.0.0 --port %FRONTEND_PORT% ^>^>"%FRONTEND_LOG%" 2^>^&1
>>"%FRONTEND_RUNNER%" echo echo [%%date%% %%time%%] 前端进程退出，退出码 %%errorlevel%% ^>^>"%FRONTEND_LOG%"
>>"%FRONTEND_RUNNER%" echo echo 前端服务已退出。可以关闭此窗口。

echo [%date% %time%] 打开后端 CMD 服务窗口。
echo [%date% %time%] 打开后端 CMD 服务窗口。>>"%LAUNCHER_LOG%"
start "DXM 后端服务 - 关闭窗口即停止" cmd.exe /k ""%BACKEND_RUNNER%""

echo [%date% %time%] 打开前端 CMD 服务窗口。
echo [%date% %time%] 打开前端 CMD 服务窗口。>>"%LAUNCHER_LOG%"
start "DXM 前端服务 - 关闭窗口即停止" cmd.exe /k ""%FRONTEND_RUNNER%""

echo [%date% %time%] 等待服务响应。
echo [%date% %time%] 等待服务响应。>>"%LAUNCHER_LOG%"
timeout /t 8 /nobreak >nul

curl -fsS --max-time 2 "http://127.0.0.1:%BACKEND_PORT%/health" >nul 2>nul
if errorlevel 1 (
  echo [%date% %time%] 提示：后端暂未响应，请查看：%BACKEND_LOG%
  echo [%date% %time%] 提示：后端暂未响应，请查看：%BACKEND_LOG%>>"%LAUNCHER_LOG%"
) else (
  echo [%date% %time%] 后端已响应：http://127.0.0.1:%BACKEND_PORT%/health
  echo [%date% %time%] 后端已响应：http://127.0.0.1:%BACKEND_PORT%/health>>"%LAUNCHER_LOG%"
)

curl -fsS --max-time 2 "http://127.0.0.1:%FRONTEND_PORT%" >nul 2>nul
if errorlevel 1 (
  echo [%date% %time%] 提示：前端暂未响应，请查看：%FRONTEND_LOG%
  echo [%date% %time%] 提示：前端暂未响应，请查看：%FRONTEND_LOG%>>"%LAUNCHER_LOG%"
) else (
  echo [%date% %time%] 前端已响应：http://127.0.0.1:%FRONTEND_PORT%
  echo [%date% %time%] 前端已响应：http://127.0.0.1:%FRONTEND_PORT%>>"%LAUNCHER_LOG%"
)

echo [%date% %time%] 前端控制台：http://127.0.0.1:%FRONTEND_PORT%
echo [%date% %time%] 前端控制台：http://127.0.0.1:%FRONTEND_PORT%>>"%LAUNCHER_LOG%"
echo [%date% %time%] 停止方式：关闭两个 DXM 服务 CMD 窗口。
echo [%date% %time%] 停止方式：关闭两个 DXM 服务 CMD 窗口。>>"%LAUNCHER_LOG%"
start "" "http://127.0.0.1:%FRONTEND_PORT%"
goto success

:check_done
echo [%date% %time%] 检查模式完成：环境满足启动条件，本次不启动服务。
echo [%date% %time%] 检查模式完成：环境满足启动条件，本次不启动服务。>>"%LAUNCHER_LOG%"
goto success

:backend_port_busy
echo [%date% %time%] 错误：后端端口 %BACKEND_PORT% 已被占用。请关闭占用端口的服务后重试。
echo [%date% %time%] 错误：后端端口 %BACKEND_PORT% 已被占用。请关闭占用端口的服务后重试。>>"%LAUNCHER_LOG%"
type "%TEMP%\dxm-backend-port.txt"
type "%TEMP%\dxm-backend-port.txt">>"%LAUNCHER_LOG%"
goto failed

:frontend_port_busy
echo [%date% %time%] 错误：前端端口 %FRONTEND_PORT% 已被占用。请关闭占用端口的服务后重试，避免打开错误页面。
echo [%date% %time%] 错误：前端端口 %FRONTEND_PORT% 已被占用。请关闭占用端口的服务后重试，避免打开错误页面。>>"%LAUNCHER_LOG%"
type "%TEMP%\dxm-frontend-port.txt"
type "%TEMP%\dxm-frontend-port.txt">>"%LAUNCHER_LOG%"
goto failed

:missing_backend
echo 错误：后端目录不存在：%BACKEND_DIR%
goto failed

:missing_frontend
echo 错误：前端目录不存在：%FRONTEND_DIR%
goto failed

:missing_python
echo 错误：未找到 Python。请先安装 Python 3.11+，或创建 app\backend\.venv。
goto failed

:missing_npm
echo 错误：未找到 npm。请先安装 Node.js。
goto failed

:missing_curl
echo 错误：未找到 curl。请检查 Windows 环境。
goto failed

:missing_pydeps
echo 错误：后端 Python 依赖缺失。请执行：
echo   "%PYTHON_EXE%" -m pip install -e .
goto failed

:npm_install_failed
echo 错误：npm install 失败，请查看：%NPM_INSTALL_LOG%
goto failed

:help
echo.
echo 用法：
echo   scripts\start-mvp.bat          启动后端和前端，并打开前端页面
echo   scripts\start-mvp.bat --check  只检查环境，不启动服务
echo.
echo 日志位置：
echo   data\start-mvp.log
echo   data\backend.log
echo   data\frontend.log
echo   data\npm-install.log
echo.
echo 停止方式：
echo   关闭“DXM 后端服务”和“DXM 前端服务”两个 CMD 窗口即可。
echo.
exit /b 0

:success
echo [%date% %time%] 完成。
echo [%date% %time%] 完成。>>"%LAUNCHER_LOG%"
exit /b 0

:failed
echo [%date% %time%] 启动器已停止。
echo [%date% %time%] 启动器已停止。>>"%LAUNCHER_LOG%"
exit /b 1
