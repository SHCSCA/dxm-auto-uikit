import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DESKTOP_DIR = REPO_ROOT / "app" / "desktop"
DESKTOP_PACKAGE = DESKTOP_DIR / "package.json"
DESKTOP_PORTABLE_PATCH = DESKTOP_DIR / "scripts" / "patch-electron-builder-portable.cjs"
DESKTOP_MAIN = DESKTOP_DIR / "src" / "main.cjs"
DESKTOP_PRELOAD = DESKTOP_DIR / "src" / "preload.cjs"
DESKTOP_BUILDER = DESKTOP_DIR / "electron-builder.yml"
DESKTOP_PRUNE_RUNTIME = DESKTOP_DIR / "scripts" / "prune-packaged-runtime.cjs"
START_DESKTOP = REPO_ROOT / "scripts" / "start-desktop.bat"
VERIFY_DESKTOP_PACKAGE = REPO_ROOT / "scripts" / "verify-desktop-package.ps1"
FRONTEND_VITE_CONFIG = REPO_ROOT / "app" / "frontend" / "vite.config.ts"
README = REPO_ROOT / "README.md"
USER_GUIDE = REPO_ROOT / "docs" / "product" / "用户交付使用说明-20260526.md"
PORTABLE_QUICK_GUIDE = REPO_ROOT / "docs" / "product" / "免安装版快速使用说明-20260615.md"
APP_TSX = REPO_ROOT / "app" / "frontend" / "src" / "App.tsx"
SAFETY_STATUS_BAR = REPO_ROOT / "app" / "frontend" / "src" / "components" / "SafetyStatusBar.tsx"
WORKBENCH_MODULES_TSX = REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx"
TYPES_TS = REPO_ROOT / "app" / "frontend" / "src" / "types.ts"


def test_desktop_package_declares_electron_entrypoints_and_build_scripts():
    package = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))

    assert package["name"] == "dxm-agent-desktop"
    assert package["main"] == "src/main.cjs"
    assert package["scripts"]["dev"] == "electron ."
    assert "npm --prefix ../frontend run build" in package["scripts"]["build:frontend"]
    assert "electron-builder --dir --config electron-builder.yml" in package["scripts"]["build"]
    assert "electron-builder --win portable --config electron-builder.yml" in package["scripts"]["build:portable"]
    assert "electron-builder --config electron-builder.yml" in package["scripts"]["build:installer"]
    assert "electron" in package["devDependencies"]
    assert "electron-builder" in package["devDependencies"]


def test_desktop_build_patches_portable_launcher_exec_quoting():
    package = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
    patch_source = DESKTOP_PORTABLE_PATCH.read_text(encoding="utf-8")

    assert "patch:portable-template" in package["scripts"]
    assert "patch-electron-builder-portable.cjs" in package["scripts"]["patch:portable-template"]
    assert "npm run patch:portable-template" in package["scripts"]["build:portable"]
    assert "npm run patch:portable-template" in package["scripts"]["build:installer"]
    assert r'ExecWait "$INSTDIR\\${APP_EXECUTABLE_FILENAME} $R0" $0' in patch_source
    assert r'ExecWait `"$INSTDIR\\${APP_EXECUTABLE_FILENAME}" $R0` $0' in patch_source


def test_desktop_main_starts_backend_hidden_and_loads_frontend_with_api_base():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")

    assert "app.setName('DXM Agent Console')" in source
    assert "function resolveRepoRoot()" in source
    assert "process.resourcesPath" in source
    assert "app/backend/src/main.py" in source
    assert "findFreePort(8000" in source
    assert "app/backend/.venv/Scripts/python.exe" in source
    assert "if (app.isPackaged)" in source
    assert "Packaged backend Python is missing" in source
    assert "app.getPath('userData')" in source
    assert "src.main:app" in source
    assert "DXM_DATA_DIR" in source
    assert "DXM_RESOURCE_ROOT" in source
    assert "DXM_LAUNCHER_LOG_FILE" in source
    assert "DXM_BACKEND_PORT: String(port)" in source
    assert "DXM_BACKEND_URL: `http://127.0.0.1:${port}`" in source
    assert "DXM_DESKTOP=1" in source
    assert "PYTHONDONTWRITEBYTECODE" in source
    assert "windowsHide: true" in source
    assert "data/desktop-main.log" in source
    assert "app/frontend/dist/index.html" in source
    assert "apiBase=" in source
    assert "killBackendProcess()" in source
    assert "will-quit" in source
    assert "function getQaCapturePath()" in source
    assert "--qa-capture=" in source
    assert "--qa-visible-smoke=" in source
    assert "show: !qaCapturePath" in source
    assert "windowVisible: Boolean(mainWindow && mainWindow.isVisible())" in source
    assert "QA visible smoke written" in source
    assert "webContents.capturePage()" in source


def test_desktop_main_logs_packaged_probe_resource_status_before_backend_start():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    startup_section = source[source.index("async function createWindow"):source.index("ipcMain.handle")]

    assert "function logPackagedResourceStatus" in source
    assert "tools/probes/l2_readonly_probe_runner.py" in source
    assert "tools/probes/l2_readonly_probe.py" in source
    assert "config/l2_readonly_allowlist.json" in source
    assert "Packaged resource status:" in source
    assert "logPackagedResourceStatus(repoRoot)" in startup_section
    assert startup_section.index("logPackagedResourceStatus(repoRoot)") < startup_section.index("startBackend(repoRoot, port)")
    assert "QA capture written" in source


def test_desktop_backend_health_check_requires_ok_json_response():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    health_section = source[source.index("function waitForHealth"):source.index("function resolveFrontendPath")]

    assert "const chunks = []" in health_section
    assert "JSON.parse(raw)" in health_section
    assert "payload.status === 'ok'" in health_section
    assert "response.statusCode >= 200 && response.statusCode < 300" in health_section
    assert "response.statusCode < 500" not in health_section


def test_desktop_main_surfaces_startup_failures_in_visible_window():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    startup_error_section = source[
        source.index("function createStartupErrorWindow"):
        source.index("function findFreePort")
    ]

    assert "function createStartupErrorWindow(error)" in source
    assert "DXM Agent Console startup failed" in source
    assert "desktop-main.log" in source
    assert "loadURL(`data:text/html" in source
    assert "killBackendProcess()" in source
    assert "function userStartupErrorMessage" in source
    assert "appendDesktopLog(`Startup failure detail:" in startup_error_section
    assert "const message = userStartupErrorMessage(error)" in startup_error_section
    assert "error.stack || error.message" not in startup_error_section
    assert "处理步骤" in startup_error_section


def test_desktop_preload_exposes_readonly_runtime_metadata():
    source = DESKTOP_PRELOAD.read_text(encoding="utf-8")
    main_source = DESKTOP_MAIN.read_text(encoding="utf-8")

    assert "contextBridge" in source
    assert "dxmDesktop" in source
    assert "getRuntimeInfo" in source
    assert "ipcRenderer.invoke('desktop:get-runtime-info')" in source
    assert "loadDxmCredential" in source
    assert "saveDxmCredential" in source
    assert "clearDxmCredential" in source
    assert "safeStorage" in main_source
    assert "desktop:dxm-credential:load" in main_source
    assert "desktop:dxm-credential:save" in main_source
    assert "desktop:dxm-credential:clear" in main_source


def test_desktop_credential_smoke_verifies_safe_storage_without_destroying_user_secret():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    verify_source = VERIFY_DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert "function getQaUserDataDir()" in source
    assert "--qa-user-data-dir=" in source
    assert "app.setPath('userData', qaUserDataDir)" in source
    assert "function getQaCredentialSmokePath()" in source
    assert "--qa-credential-smoke=" in source
    assert "function runCredentialSmoke(outputPath)" in source
    assert "const previousCredential = fs.existsSync(credentialPath)" in source
    assert "saveDxmCredential({ username: '__qa_dxm_user__', password: '__qa_dxm_password__' })" in source
    assert "loaded.credential.username !== '__qa_dxm_user__'" in source
    assert "loaded.credential.password !== '__qa_dxm_password__'" in source
    assert "fs.writeFileSync(credentialPath, previousCredential, 'utf8')" in source
    assert "fs.rmSync(credentialPath, { force: true })" in source
    assert "Credential smoke written" in source

    assert "--qa-credential-smoke=$CredentialSmokePath" in verify_source
    assert "[string]$SmokeUserDataDir" in verify_source
    assert "dxm-agent-console-packaged-smoke-user-data" in verify_source
    assert "Get-DesktopSmokeLog -UserDataDir $SmokeUserDataDir" in verify_source
    assert "--qa-user-data-dir=$SmokeUserDataDir" in verify_source
    assert "Credential smoke passed" in verify_source


def test_desktop_builder_packages_windows_exe_without_console_windows():
    source = DESKTOP_BUILDER.read_text(encoding="utf-8")

    assert "appId: com.dxm.agent.console" in source
    assert "productName: DXM Agent Console" in source
    assert "target: portable" in source
    assert "target: nsis" in source
    assert "artifactName: DXM-Agent-Console-${version}.${ext}" in source
    assert "DXM-Agent-Console-Portable-${version}.${ext}" in source
    assert "executableName: DXM-Agent-Console" in source
    assert "app/frontend/dist/**" in source
    assert "app/backend/src/**" in source
    assert "../backend/.venv" in source
    assert "app/backend/.venv" in source
    assert "../../tools/probes" in source
    assert "tools/probes" in source
    assert "../../config" in source
    assert "to: config" in source


def test_desktop_builder_excludes_backend_dev_runtime_cache_from_delivery_bundle():
    source = DESKTOP_BUILDER.read_text(encoding="utf-8")
    prune_source = DESKTOP_PRUNE_RUNTIME.read_text(encoding="utf-8")

    assert "afterPack: scripts/prune-packaged-runtime.cjs" in source
    assert "!**/__pycache__/**" in source
    assert "!**/*.pyc" in source
    assert "!Lib/site-packages/pytest/**" in source
    assert "!Lib/site-packages/_pytest/**" in source
    assert "!Lib/site-packages/pip/**" in source
    assert "!Lib/site-packages/setuptools/**" in source
    assert "function prunePackagedRuntime" in prune_source
    assert "__pycache__" in prune_source
    assert ".pyc" in prune_source
    assert "site-packages" in prune_source
    assert "pytest" in prune_source
    assert "setuptools" in prune_source


def test_start_desktop_launcher_builds_frontend_then_runs_electron():
    source = START_DESKTOP.read_text(encoding="utf-8")

    assert "DXM Agent Console - Desktop Mode" in source
    assert "npm --prefix app\\frontend run build" in source
    assert "npm --prefix app\\desktop install" in source
    assert "npm --prefix app\\desktop run dev" in source


def test_verify_desktop_package_smoke_script_checks_packaged_exe_logs():
    source = VERIFY_DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert "DXM Agent Console packaged smoke" in source
    assert "trap {" in source
    assert "exit 1" in source[source.index("trap {"):source.index("$RepoRoot =")]
    assert "outputs\\desktop-build\\win-unpacked\\DXM-Agent-Console.exe" in source
    assert "DXM-Agent-Console-Portable-0.1.0.exe" in source
    assert "[switch]$CheckPortable" in source
    assert "desktop-main.log" in source
    assert "Loaded frontend" in source
    assert "Starting backend" in source
    assert "--qa-capture=$CapturePath" in source
    assert "QA capture was not created" in source
    assert "resources\\app\\backend\\.venv\\Scripts\\python.exe" in source
    assert "backend did not start with bundled Python" in source
    assert "tools\\probes\\l2_readonly_probe_runner.py" in source
    assert "config\\l2_readonly_allowlist.json" in source
    assert "Assert-PackagedBackendResourceStatus" in source
    assert "/api/runtime/status" in source
    assert "Packaged runtime backend port mismatch" in source
    assert "DXM_RESOURCE_ROOT" in source
    assert "l2_readonly_probe_runner" in source
    assert "l2_readonly_probe_script" in source
    assert "l2_readonly_probe_allowlist" in source
    assert "Packaged backend resource status passed" in source
    assert "Assert-PackagedRuntimeClean" in source
    assert "*.pyc" in source
    assert "__pycache__" in source
    assert "Packaged runtime generated Python bytecode cache" in source
    assert "taskkill" in source
    assert "PortableMinTempFreeMB" in source
    assert "Assert-PortableTempSpace" in source
    assert "Portable TEMP space OK" in source
    assert "Clean old %TEMP%" in source
    assert "portable extraction folders" in source
    assert "Portable smoke requires a longer first-launch wait" in source
    assert "$CheckPortable -and $WaitSeconds -lt 180" in source
    assert "$WaitSeconds = 180" in source
    assert "Portable QA capture was not created" in source
    assert "Get-DesktopSmokeLog -UserDataDir $PortableSmokeUserDataDir" in source
    assert "--qa-user-data-dir=$PortableSmokeUserDataDir" in source
    assert 'throw "Portable exe not found' in source
    assert "Portable smoke passed" in source
    assert "Portable smoke skipped. Current delivery target is the verified directory免安装版" in source


def test_user_docs_present_desktop_exe_as_primary_delivery_entry():
    readme = README.read_text(encoding="utf-8")
    user_guide = USER_GUIDE.read_text(encoding="utf-8")

    for source in (readme, user_guide):
        assert "DXM Agent Console 桌面版" in source
        assert "D:\\Desktop\\DXM-Agent-Console-免安装版\\DXM-Agent-Console-Portable-0.1.0.exe" in source
        assert "outputs\\desktop-build\\win-unpacked\\DXM-Agent-Console.exe" in source
        assert "outputs\\desktop-build\\DXM-Agent-Console-Portable-0.1.0.exe" in source
        assert "61B57C6EE39E6D2E6874CB7BB9F575D327EB274B87BC637E9CB6B19FC85E79FC" in source
        assert "portable 首次启动会解包 Electron 与 Python 运行时" in source
        assert "%TEMP%` 所在磁盘建议至少保留 1GB 可用空间" in source
        assert "scripts\\start-desktop.bat" in source
        assert "scripts\\verify-desktop-package.ps1" in source
        assert "AppData\\Roaming\\DXM Agent Console\\data\\desktop-main.log" in source


def test_portable_quick_guide_uses_verified_portable_entry():
    source = PORTABLE_QUICK_GUIDE.read_text(encoding="utf-8")

    assert "D:\\Desktop\\DXM-Agent-Console-免安装版\\DXM-Agent-Console-Portable-0.1.0.exe" in source
    assert "outputs\\desktop-build\\win-unpacked\\DXM-Agent-Console.exe" in source
    assert "使用目录版时必须保留整个文件夹和 `resources` 目录" in source
    assert "outputs\\desktop-build\\DXM-Agent-Console-Portable-0.1.0.exe" in source
    assert "61B57C6EE39E6D2E6874CB7BB9F575D327EB274B87BC637E9CB6B19FC85E79FC" in source
    assert "至少建议保留 1GB 可用空间" in source


def test_frontend_vite_build_uses_relative_base_for_electron_file_loading():
    source = FRONTEND_VITE_CONFIG.read_text(encoding="utf-8")

    assert "base: './'" in source


def test_app_shell_presents_agent_console_as_user_first_navigation():
    source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    index_html = (REPO_ROOT / "app" / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "DXM Agent Console" in index_html
    assert "type WorkbenchPrimaryArea" in source
    assert "const primaryAreas" in source
    assert "label: '执行'" in source
    assert "label: '准备'" in source
    assert "label: '复盘'" in source
    assert "label: '更多'" not in source
    assert "真实浏览器" in source
    assert "登录、只读检查、执行浏览器" in source
    assert "结果报告" in source
    assert "问题处理" in source
    assert "证据中心" in source
    assert "id: 'dashboard'" not in source[source.index("const primaryAreas"):source.index("const sectionLabels")]
    assert "{ id: 'evidence', label: '证据中心'" in source[source.index("const primaryAreas"):source.index("const sectionLabels")]
    assert "{ id: 'exceptions', label: '问题'" not in source[source.index("const primaryAreas"):source.index("const sectionLabels")]
    assert "{ id: 'agent_execution', label: '真实浏览器', short: '览', hint: '登录、只读检查、执行浏览器' }" in source
    assert "报告中心" not in source
    assert "异常池" not in source
    assert "nav-section" in source
    assert "nav-subitem" in source
    assert "Agent 控制台" not in source


def test_execution_console_focus_panel_keeps_primary_summary_small():
    source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx").read_text(encoding="utf-8")
    focus_section = source[source.index("function ConsoleFocusPanel"):source.index("function AgentBrowserFrame")]

    assert "console-focus-panel__status-strip" in focus_section
    assert "console-focus-panel__details" in focus_section
    primary_section = focus_section[
        focus_section.index("console-focus-panel__status-strip"):
        focus_section.index("<details className=\"console-focus-panel__details")
    ]
    assert primary_section.count("<span>") == 4
    assert "<strong>DXM 登录</strong>" in primary_section
    assert "<strong>真实只读检查</strong>" in primary_section
    assert "<strong>人工确认</strong>" in primary_section
    assert "<strong>执行浏览器</strong>" in primary_section
    assert "<summary>技术状态</summary>" in focus_section
    assert "<strong>任务</strong><b>" in focus_section
    assert "<strong>当前步骤</strong><b>" in focus_section
    assert "<strong>当前页面</strong><b>" in focus_section
    assert "<strong>日志</strong><b>" in focus_section


def test_execution_console_does_not_show_fake_browser_stage_by_default():
    source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "WorkbenchModules.tsx").read_text(encoding="utf-8")
    stage_section = source[source.index("function AgentStagePanel"):source.index("function ConsoleCompletedReviewPanel")]

    assert "agent-browser-drawer" in stage_section
    assert "<summary>浏览器状态与证据路径</summary>" in stage_section
    assert "外部真实浏览器窗口" in stage_section
    assert "控制台默认不内嵌浏览器画面" in stage_section
    assert "<AgentBrowserFrame" in stage_section


def test_frontend_surfaces_electron_desktop_runtime_metadata():
    app_source = APP_TSX.read_text(encoding="utf-8")
    safety_source = SAFETY_STATUS_BAR.read_text(encoding="utf-8")
    types_source = TYPES_TS.read_text(encoding="utf-8")

    assert "export type DesktopRuntimeInfo" in types_source
    assert "dxmDesktop?: {" in types_source
    assert "getRuntimeInfo: () => Promise<DesktopRuntimeInfo>" in types_source
    assert "const [desktopRuntime, setDesktopRuntime]" in app_source
    assert "window.dxmDesktop?.getRuntimeInfo" in app_source
    assert "desktopRuntime={desktopRuntime}" in app_source
    assert "desktopRuntime?: DesktopRuntimeInfo | null" in safety_source
    assert "DXM Agent Console 桌面模式" in safety_source
    assert "desktopRuntime.desktopLogPath" in safety_source
    assert "desktopRuntime.backendLogPath" in safety_source
    assert "桌面日志" in safety_source


def test_frontend_explains_runtime_ownership_for_desktop_exe_users():
    safety_source = SAFETY_STATUS_BAR.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = TYPES_TS.read_text(encoding="utf-8")

    assert "owner?: 'start_mvp' | 'desktop' | 'direct' | string" in types_source
    assert "managedByDesktop?: boolean" in types_source
    assert "runtimeOwnerLabel" in safety_source
    assert "启动来源" in safety_source
    assert "免安装版已接管" in safety_source
    assert "旧进程/直接启动" in safety_source
    assert "backendPortMismatch" in safety_source
    assert "桌面后端端口与接口端口不一致" in safety_source
    assert "DXM Agent Console 免安装版" in workbench_source
    assert "关闭并重新打开免安装版 exe" in workbench_source
    assert "请确认是通过 scripts/start-mvp.bat 启动" not in workbench_source
