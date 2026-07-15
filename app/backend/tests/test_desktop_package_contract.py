import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DESKTOP_DIR = REPO_ROOT / "app" / "desktop"
DESKTOP_PACKAGE = DESKTOP_DIR / "package.json"
DESKTOP_PORTABLE_PATCH = DESKTOP_DIR / "scripts" / "patch-electron-builder-portable.cjs"
DESKTOP_BUILD_MANIFEST = DESKTOP_DIR / "scripts" / "generate-build-manifest.cjs"
DESKTOP_RUNTIME_IDENTITY = DESKTOP_DIR / "src" / "runtime-identity.cjs"
DESKTOP_RUNTIME_IDENTITY_TEST = DESKTOP_DIR / "test" / "runtime-identity.test.cjs"
DESKTOP_LAUNCH_POLICY = DESKTOP_DIR / "src" / "launch-policy.cjs"
DESKTOP_LAUNCH_POLICY_TEST = DESKTOP_DIR / "test" / "launch-policy.test.cjs"
DESKTOP_RUNTIME_START = DESKTOP_DIR / "src" / "runtime-start.cjs"
DESKTOP_RUNTIME_START_TEST = DESKTOP_DIR / "test" / "runtime-start.test.cjs"
DESKTOP_BACKEND_SHUTDOWN = DESKTOP_DIR / "src" / "backend-shutdown.cjs"
DESKTOP_BACKEND_SHUTDOWN_TEST = DESKTOP_DIR / "test" / "backend-shutdown.test.cjs"
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


def test_desktop_build_generates_and_packages_frozen_build_manifest():
    package = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
    builder = DESKTOP_BUILDER.read_text(encoding="utf-8")

    assert package["scripts"]["build:metadata"] == "node scripts/generate-build-manifest.cjs"
    for script_name in ("build", "build:portable", "build:installer"):
        assert "npm run build:metadata" in package["scripts"][script_name]
        assert package["scripts"][script_name].index("npm run build:metadata") < package["scripts"][script_name].index("electron-builder")
    assert "outputs/build-metadata/desktop-build-manifest.json" in builder.replace("..\\", "../")
    assert "to: build-metadata/desktop-build-manifest.json" in builder
    assert DESKTOP_BUILD_MANIFEST.exists()
    assert DESKTOP_RUNTIME_IDENTITY.exists()
    assert DESKTOP_RUNTIME_IDENTITY_TEST.exists()
    assert DESKTOP_LAUNCH_POLICY.exists()
    assert DESKTOP_LAUNCH_POLICY_TEST.exists()
    assert DESKTOP_RUNTIME_START.exists()
    assert DESKTOP_RUNTIME_START_TEST.exists()


def test_desktop_main_validates_qa_then_locks_selected_user_data_before_runtime_or_window():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")

    assert "classifyLaunchArguments" in source
    assert "const normalUserDataDir = app.getPath('userData')" in source
    assert "createQaRoot: (qaUserDataDir) => fs.mkdirSync(qaUserDataDir, { recursive: true })" in source
    assert "setUserDataPath: (qaUserDataDir) => app.setPath('userData', qaUserDataDir)" in source
    assert "requestSingleInstanceLock: () => app.requestSingleInstanceLock()" in source
    assert "app.on('second-instance'" in runtime_start_source
    assert "focusWindow: () => focusExistingWindow(() => mainWindow)" in source
    assert "async function startDesktopRuntime()" in source
    assert "async function createMainWindow(runtime)" in source

    bootstrap_at = source.index("prepareElectronLaunchOwnership({")
    register_at = source.index("registerPrimaryInstanceLifecycle({")
    assert bootstrap_at < register_at
    assert "function prepareElectronLaunchOwnership" in runtime_start_source


def test_desktop_normal_port_is_fixed_and_legacy_scan_precedes_spawn():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    policy_source = DESKTOP_LAUNCH_POLICY.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")

    assert "selectBackendPort" in source
    assert "inspectLegacyRuntimePorts" in source
    assert "createTcpOccupancyProbe" in source
    assert "createHttpRuntimeProbe" in source
    assert "isIsolatedQa: launchPolicy.isIsolatedQa" in source
    assert "if (!launchPolicy.isIsolatedQa)" in source
    startup_section = source[source.index("async function startDesktopRuntime()"):source.index("async function createMainWindow(runtime)")]
    assert startup_section.index("inspectLegacyRuntimePorts({") < startup_section.index("startBackend(repoRoot, port, backendInstanceId")
    assert "return 8000" in policy_source
    assert "for (let port = 8000; port <= 8079; port += 1)" in policy_source
    assert "AbortController" in policy_source
    assert "maxBodyBytes" in policy_source
    assert "createRuntimeStarter" in runtime_start_source
    assert "createDesktopStartupController" in runtime_start_source
    assert "findFreePort(8000" not in source


def test_desktop_activate_reuses_verified_runtime_without_backend_restart():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    activate_section = runtime_start_source[
        runtime_start_source.index("app.on('activate'"):
        runtime_start_source.index("app.on('window-all-closed'")
    ]

    assert "startupController.onActivate" in activate_section
    assert "startRuntimeOnce" not in activate_section
    assert "startRuntime" not in activate_section
    assert "startBackend" not in activate_section
    assert "registerPrimaryInstanceLifecycle({" in source


def test_desktop_invalid_policy_or_missing_lock_cannot_register_ready_startup():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")

    assert "let launchPolicyValid = false" in source
    assert "launchPolicyValid = launchOwnership.launchPolicyValid" in source
    assert "registerPrimaryInstanceLifecycle({" in source
    assert "launchPolicyValid," in source
    assert "ownsSingleInstanceLock," in source
    assert "if (!launchPolicyValid || !ownsSingleInstanceLock) return false" in runtime_start_source


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
    identity_source = DESKTOP_RUNTIME_IDENTITY.read_text(encoding="utf-8")
    launch_policy_source = DESKTOP_LAUNCH_POLICY.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    shutdown_source = DESKTOP_BACKEND_SHUTDOWN.read_text(encoding="utf-8")
    termination_section = source[
        source.index("function requestBackendTermination"):
        source.index("async function startDesktopRuntime")
    ]

    assert "app.setName('DXM Agent Console')" in source
    assert "function resolveRepoRoot()" in source
    assert "process.resourcesPath" in source
    assert "app/backend/src/main.py" in source
    assert "selectBackendPort" in source
    assert "app/backend/.venv/Scripts/python.exe" in source
    assert "if (app.isPackaged)" in source
    assert "Packaged backend Python is missing" in source
    assert "app.getPath('userData')" in source
    assert "src.desktop_server" in source
    assert "buildBackendEnvironment" in source
    assert "DXM_DATA_DIR" in identity_source
    assert "DXM_RESOURCE_ROOT" in identity_source
    assert "DXM_LAUNCHER_LOG_FILE" in source
    assert "env.DXM_BACKEND_PORT = String(port)" in shutdown_source
    assert "DXM_BACKEND_URL: `http://127.0.0.1:${port}`" in source
    assert "env.DXM_DESKTOP = '1'" in shutdown_source
    assert "DXM_WORKFLOW_ACTION_RUNTIME: 'browser_agent'" in source
    assert "const workflowProfileDir = path.join(dataDir, 'browser_profiles', 'dxm_workflow')" in source
    assert "DXM_WORKFLOW_PROFILE_DIR" in identity_source
    assert "DXM_WORKFLOW_PERSISTENT_PROFILE: '1'" in source
    assert "PYTHONDONTWRITEBYTECODE" in source
    assert "windowsHide: true" in source
    assert "data/desktop-main.log" in source
    assert "app/frontend/dist/index.html" in source
    assert "apiBase=" in source
    assert "backendShutdownController.requestCurrentOrPendingTermination" in termination_section
    assert "if (!ownership)" not in termination_section
    assert "will-quit" in runtime_start_source
    assert "classifyLaunchArguments" in source
    assert "qa-capture" in launch_policy_source
    assert "qa-visible-smoke" in launch_policy_source
    assert "show: !runtime.qaCapturePath" in source
    assert "windowVisible: Boolean(!window.isDestroyed() && window.isVisible())" in source
    assert "QA visible smoke written" in source
    assert "webContents.capturePage()" in source
    assert "nativeExitCoordinator.markFailure()" in termination_section
    assert "taskkill" not in termination_section.lower()
    assert "execFileSync" not in source
    assert "process.kill(" not in termination_section


def test_desktop_main_uses_the_programmatic_host_and_exact_piped_parent_channel():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    shutdown_source = DESKTOP_BACKEND_SHUTDOWN.read_text(encoding="utf-8")
    start_backend_section = source[
        source.index("function startBackend"):
        source.index("function waitForHealth")
    ]
    startup_section = source[
        source.index("async function startDesktopRuntime"):
        source.index("async function createMainWindow")
    ]

    assert DESKTOP_BACKEND_SHUTDOWN.exists()
    assert DESKTOP_BACKEND_SHUTDOWN_TEST.exists()
    assert "require('./backend-shutdown.cjs')" in source
    assert "const args = ['-m', 'src.desktop_server']" in start_backend_section
    assert "stdio: ['pipe', 'pipe', 'pipe']" in start_backend_section
    assert "buildDesktopBackendEnvironment" in start_backend_section
    assert "DXM_RUNTIME_OWNER = 'electron_desktop'" in shutdown_source
    assert "DXM_DESKTOP = '1'" in shutdown_source
    assert "DXM_DESKTOP_PARENT_CHANNEL = 'stdin-v1'" in shutdown_source
    assert "backendShutdownController.registerSpawnSetup" in start_backend_section
    assert "backendShutdownController.handoffSpawnSetup" in start_backend_section
    assert "await backendShutdownController.startParentChannel(ownership)" in start_backend_section
    assert "const ownership = await startBackend(" in startup_section
    assert startup_section.index("const ownership = await startBackend(") < startup_section.index(
        "await waitForHealth(runtimeInfo.apiBase, 45000, ownership)"
    )
    assert "src.main:app" not in start_backend_section
    assert "-m', 'uvicorn" not in start_backend_section


def test_desktop_quit_wiring_waits_once_in_before_quit_and_will_quit_only_finalizes_native_exit():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    shutdown_source = DESKTOP_BACKEND_SHUTDOWN.read_text(encoding="utf-8")
    lifecycle_section = source[source.index("registerPrimaryInstanceLifecycle({"):]

    assert "createBeforeQuitController" in source
    assert "beforeQuitController.handleBeforeQuit" in lifecycle_section
    assert "app.on('before-quit', onBeforeQuit)" in runtime_start_source
    assert "event?.preventDefault?.()" in shutdown_source
    assert "requestCurrentOrPendingTermination({ reason: 'before-quit' })" in shutdown_source
    before_quit_setup = source[
        source.index("const beforeQuitController = createBeforeQuitController({"):
        source.index("const qaDeadlineController =")
    ]
    assert "backendShutdownController.requestCurrentOrPendingTermination(options)" in before_quit_setup
    assert "getCurrentOwnership" not in before_quit_setup
    assert "getPendingTermination" not in before_quit_setup
    assert "onWillQuit: () => {" in lifecycle_section
    will_quit = lifecycle_section[
        lifecycle_section.index("onWillQuit: () => {"):
        lifecycle_section.index("\n  },\n})", lifecycle_section.index("onWillQuit: () => {"))
    ]
    assert "nativeExitCoordinator.finalizeAfterCleanup()" in will_quit
    assert "requestTermination" not in will_quit
    assert "killBackendProcess" not in will_quit


def test_isolated_qa_deadline_arms_once_and_will_quit_cancels_before_native_finalize():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    deadline_section = source[
        source.index("const qaDeadlineController ="):
        source.index("function initializeDesktopLogPath")
    ]
    lifecycle_section = source[source.index("qaDeadlineController?.arm()") :]
    will_quit = lifecycle_section[
        lifecycle_section.index("onWillQuit: () => {"):
        lifecycle_section.index("\n  },\n})", lifecycle_section.index("onWillQuit: () => {"))
    ]

    assert "function createQaDeadlineController" in runtime_start_source
    assert "launchPolicyValid" in deadline_section
    assert "ownsSingleInstanceLock" in deadline_section
    assert "launchPolicy?.isIsolatedQa" in deadline_section
    assert "launchPolicy.deadlineMs !== null" in deadline_section
    assert "deadlineMs: launchPolicy.deadlineMs" in deadline_section
    assert "nativeExitCoordinator.requestQuit({ failed: true })" in deadline_section
    assert lifecycle_section.index("qaDeadlineController?.arm()") < lifecycle_section.index(
        "registerPrimaryInstanceLifecycle({"
    )
    assert will_quit.index("qaDeadlineController?.cancel()") < will_quit.index(
        "nativeExitCoordinator.finalizeAfterCleanup()"
    )


def test_desktop_main_logs_packaged_probe_resource_status_before_backend_start():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    startup_section = source[source.index("async function startDesktopRuntime"):source.index("async function createMainWindow")]

    assert "function logPackagedResourceStatus" in source
    assert "tools/probes/l2_readonly_probe_runner.py" in source
    assert "tools/probes/l2_readonly_probe.py" in source
    assert "config/l2_readonly_allowlist.json" in source
    assert "Packaged resource status:" in source
    assert "logPackagedResourceStatus(repoRoot)" in startup_section
    assert startup_section.index("logPackagedResourceStatus(repoRoot)") < startup_section.index("startBackend(repoRoot, port, backendInstanceId, {")
    assert "QA capture written" in source


def test_desktop_backend_health_check_requires_ok_json_response():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    identity_source = DESKTOP_RUNTIME_IDENTITY.read_text(encoding="utf-8")
    health_section = source[source.index("function waitForHealth"):source.index("function resolveFrontendPath")]
    waiter_section = identity_source[
        identity_source.index("function waitForOwnedBackendHealth"):
        identity_source.index("module.exports")
    ]

    assert "return waitForOwnedBackendHealth({" in health_section
    assert "getCurrentOwnership: () => backendOwnership" in health_section
    assert "const chunks = []" in waiter_section
    assert "JSON.parse(Buffer.concat(chunks).toString('utf8'))" in waiter_section
    assert "payload.status === 'ok'" in waiter_section
    assert "ownership.expectedIdentity" in waiter_section
    assert "payload.instanceId !== verifiedIdentity.instanceId" in waiter_section
    assert "mismatched backend" in waiter_section
    assert "response.statusCode >= 200" in waiter_section
    assert "response.statusCode < 300" in waiter_section
    assert "response.statusCode < 500" not in waiter_section


def test_desktop_backend_health_check_verifies_full_launch_identity_and_self_proof():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    identity_source = DESKTOP_RUNTIME_IDENTITY.read_text(encoding="utf-8")
    health_section = source[source.index("function waitForHealth"):source.index("function resolveFrontendPath")]
    waiter_section = identity_source[
        identity_source.index("function waitForOwnedBackendHealth"):
        identity_source.index("module.exports")
    ]

    assert "waitForOwnedBackendHealth" in health_section
    assert "verifyRuntimeIdentity" in waiter_section
    assert "ownership.expectedIdentity" in waiter_section
    assert "payload.runtimeIdentity" in waiter_section
    assert "setVerifiedBackendIdentity" in waiter_section
    assert "onVerified: (identity)" in health_section
    assert "runtimeInfo.runtimeIdentity" in health_section
    assert "isCurrentOwnedBackendLive(getCurrentOwnership(), ownership)" in waiter_section
    assert "payload.instanceId === expectedInstanceId" not in waiter_section


def test_desktop_backend_start_sets_unique_instance_id_for_health_handshake():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    startup_section = source[source.index("async function startDesktopRuntime"):source.index("async function createMainWindow")]
    start_backend_section = source[source.index("function startBackend"):source.index("function waitForHealth")]

    assert "function createBackendInstanceId()" in source
    assert "const backendInstanceId = createBackendInstanceId()" in startup_section
    assert "instanceId: backendInstanceId" in start_backend_section
    assert "waitForHealth(runtimeInfo.apiBase, 45000, ownership)" in startup_section


def test_desktop_backend_start_owns_exact_child_and_injects_one_launch_identity():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    start_backend_section = source[source.index("function startBackend"):source.index("function waitForHealth")]
    startup_section = source[source.index("async function startDesktopRuntime"):source.index("async function createMainWindow")]

    assert "let backendOwnership = null" in source
    assert "resolveLaunchManifest" in startup_section
    assert "buildId: `direct-${backendInstanceId}`" in startup_section
    assert "resolvePortablePackageSha" in startup_section
    assert "const desktopPackage = require('../package.json')" in source
    assert "expectedPortableAppFilename: desktopPackage.name" in startup_section
    assert "expectedPortableAppFilename: app.getName()" not in startup_section
    assert "buildBackendEnvironment" in start_backend_section
    assert "createExpectedRuntimeIdentity" in start_backend_section
    assert "createBackendOwnership" in start_backend_section
    assert "return ownership" in start_backend_section
    assert "child.pid" in start_backend_section
    assert "DXM_BUILD_MANIFEST_JSON" not in start_backend_section
    assert "const ownership = await startBackend(" in startup_section
    assert "await waitForHealth(runtimeInfo.apiBase, 45000, ownership)" in startup_section


def test_desktop_backend_start_installs_and_awaits_the_exact_spawn_setup_close_barrier():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    shutdown_source = DESKTOP_BACKEND_SHUTDOWN.read_text(encoding="utf-8")
    start_backend_section = source[source.index("async function startBackend"):source.index("function waitForHealth")]

    spawn_index = start_backend_section.index("const child = spawn(")
    try_index = start_backend_section.index("\n  try {", spawn_index)
    setup_authority_index = start_backend_section.index(
        "const spawnSetupAuthority = backendShutdownController.registerSpawnSetup(child"
    )
    pid_validation_index = start_backend_section.index("if (!Number.isInteger(child.pid)")
    pipe_validation_index = start_backend_section.index("if (!child.stdin || !child.stdout || !child.stderr")
    identity_index = start_backend_section.index("const expectedIdentity = createExpectedRuntimeIdentity")
    handoff_index = start_backend_section.index("backendShutdownController.handoffSpawnSetup(")
    release_fact_index = start_backend_section.index("setupCleanupReleased = true")
    start_channel_index = start_backend_section.index(
        "await backendShutdownController.startParentChannel(ownership)"
    )

    assert "createSpawnSetupCleanup" in shutdown_source
    assert "createSpawnSetupCleanup(child" in shutdown_source[
        shutdown_source.index("function registerSpawnSetup"):
        shutdown_source.index("function attachOwnership")
    ]
    assert spawn_index < try_index < setup_authority_index < pid_validation_index
    assert not start_backend_section[
        try_index + len("\n  try {"):setup_authority_index
    ].strip()
    assert setup_authority_index < pipe_validation_index
    assert setup_authority_index < identity_index
    assert identity_index < handoff_index < release_fact_index < start_channel_index
    assert "createSpawnSetupCleanup" not in start_backend_section
    assert "spawnSetupCleanup" not in start_backend_section
    assert "const exactCleanup = startupError?.terminationPromise" in start_backend_section
    assert "|| ownership?.terminationPromise" in start_backend_section
    assert "backendShutdownController.requestCurrentOrPendingTermination({" in start_backend_section
    assert "await exactCleanup" in start_backend_section
    assert start_backend_section.index("startupError?.terminationPromise") < start_backend_section.index(
        "backendShutdownController.requestCurrentOrPendingTermination({",
        start_backend_section.index("catch (startupError)"),
    )
    assert "terminateUnownedSpawnChild" not in start_backend_section


def test_desktop_backend_log_open_gate_precedes_output_identity_handoff_and_start():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    shutdown_source = DESKTOP_BACKEND_SHUTDOWN.read_text(encoding="utf-8")
    start_backend_section = source[
        source.index("async function startBackend"):source.index("function waitForHealth")
    ]

    setup_cleanup_index = start_backend_section.index(
        "const spawnSetupAuthority = backendShutdownController.registerSpawnSetup(child"
    )
    log_stream_index = start_backend_section.index("logStream = fs.createWriteStream(")
    log_gate_index = start_backend_section.index(
        "const logOpenGate = createWritableLogOpenGate(logStream"
    )
    failure_scope_index = start_backend_section.index(
        "const failureScope = classifyWritableLogFailure({"
    )
    stale_return_index = start_backend_section.index("if (failureScope === 'stale')")
    setup_latch_index = start_backend_section.index("if (failureScope === 'setup')")
    current_failure_index = start_backend_section.index(
        "runtimeInfo.lastError = rawStartupErrorDetail(error)",
        setup_latch_index,
    )
    log_wait_index = start_backend_section.index("await logOpenGate.waitUntilOpen()")
    setup_failure_check_index = start_backend_section.index("if (setupLogFailure) throw setupLogFailure")
    stdout_index = start_backend_section.index("child.stdout.on('data'")
    stderr_index = start_backend_section.index("child.stderr.on('data'")
    identity_index = start_backend_section.index("const expectedIdentity = createExpectedRuntimeIdentity")
    handoff_index = start_backend_section.index("backendShutdownController.handoffSpawnSetup(")
    release_index = start_backend_section.index("setupCleanupReleased = true")
    start_index = start_backend_section.index(
        "await backendShutdownController.startParentChannel(ownership)"
    )

    assert "createWritableLogOpenGate" in shutdown_source
    assert "onClose: endLogStream" in start_backend_section[
        setup_cleanup_index:log_stream_index
    ]
    assert log_stream_index < log_gate_index < failure_scope_index
    assert failure_scope_index < stale_return_index < setup_latch_index < current_failure_index
    assert log_gate_index < log_wait_index < setup_failure_check_index
    assert setup_failure_check_index < stdout_index < stderr_index < identity_index
    assert identity_index < handoff_index < release_index < start_index
    assert "failureScope === 'exact-current'" in start_backend_section
    assert "nativeExitCoordinator.markFailure()" in start_backend_section[
        log_gate_index:stdout_index
    ]
    assert "backendShutdownController.requestCurrentOrPendingTermination({" in start_backend_section[
        log_gate_index:stdout_index
    ]
    assert "reason: 'backend-log-error'" in start_backend_section[log_gate_index:stdout_index]


def test_desktop_backend_cleanup_requires_current_exact_live_child_and_two_phase_identity():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    identity_source = DESKTOP_RUNTIME_IDENTITY.read_text(encoding="utf-8")
    shutdown_source = DESKTOP_BACKEND_SHUTDOWN.read_text(encoding="utf-8")
    start_backend_section = source[source.index("function startBackend"):source.index("function waitForHealth")]
    lifecycle_section = shutdown_source[
        shutdown_source.index("function createBackendShutdownController"):
        shutdown_source.index("function createBeforeQuitController")
    ]
    kill_start = lifecycle_section.index("const attemptExactKillOnce")
    kill_section = lifecycle_section[
        kill_start:
        lifecycle_section.index("control.forceFallback", kill_start)
    ]

    assert "backendShutdownController.handoffSpawnSetup" in start_backend_section
    assert "child.on('exit', handleExit)" in lifecycle_section
    assert "child.on('close', handleClose)" in lifecycle_section
    assert "stdin.on('error', handlePipeError)" in lifecycle_section
    assert "const wasCurrent = exactCurrent(ownership)" in lifecycle_section
    assert "if (wasCurrent) setCurrentOwnership(null)" in lifecycle_section
    assert "ownership.exitObserved = true" in lifecycle_section
    assert "ownership.closeObserved = true" in lifecycle_section
    assert "state.endLogStream()" in lifecycle_section
    assert "canTerminateOwnedBackend" in identity_source
    assert "exitCode" in identity_source
    assert "signalCode" in identity_source
    assert "ownership.killAttempted" in kill_section
    assert "!exactCurrentLive(ownership)" in kill_section
    assert "ownership.child.kill()" in kill_section
    assert "setCurrentOwnership(null)" not in kill_section
    assert "taskkill" not in lifecycle_section.lower()
    assert "process.kill(" not in lifecycle_section
    assert "chrome" not in lifecycle_section.lower()


def test_frontend_runtime_types_include_the_frozen_identity_at_all_contract_surfaces():
    source = TYPES_TS.read_text(encoding="utf-8")

    assert "export type RuntimeIdentity = {" in source
    for field in (
        "schemaVersion: string",
        "instanceId: string",
        "gitHead: string",
        "gitDirty: boolean",
        "buildId: string",
        "packageVersion: string",
        "packageSha256: string | null",
        "backendPid: number",
        "browserAgentPid: number",
        "browserExecutionModel: 'in_process_thread'",
        "dataDir: string",
        "workflowProfileDir: string",
        "resourceRoot: string",
        "startedAt: string",
        "fingerprint: string",
    ):
        assert field in source
    desktop_section = source[source.index("export type DesktopRuntimeInfo"):source.index("export type DxmStoredCredential")]
    runtime_section = source[source.index("export type RuntimeStatus"):source.index("export type RuntimeControlAction")]
    assert "backendPid?: number | null" in desktop_section
    assert "runtimeIdentity?: RuntimeIdentity | null" in desktop_section
    assert "runtimeIdentity: RuntimeIdentity" in runtime_section
    assert "backend: { status: string; url?: string; port?: number | null; instanceId?: string | null; runtimeIdentity: RuntimeIdentity; detail?: string }" in runtime_section


def test_desktop_main_surfaces_startup_failures_in_visible_window():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    startup_error_section = source[
        source.index("function createStartupErrorWindow"):
        source.index("const tcpOccupancyProbe")
    ]

    assert "function createStartupErrorWindow(error)" in source
    assert "DXM Agent Console startup failed" in source
    assert "desktop-main.log" in source
    assert "loadStartupErrorContent({" in startup_error_section
    assert "fallbackContentUrl" in startup_error_section
    assert "Startup error window ${stage} content load failed" in startup_error_section
    assert "requestBackendTermination('startup-failure')" in source
    assert "function userStartupErrorMessage" in source
    assert "appendDesktopLog(`Startup failure detail:" in startup_error_section
    assert "const message = userStartupErrorMessage(error)" in startup_error_section
    assert "error.stack || error.message" not in startup_error_section
    assert "处理步骤" in startup_error_section
    assert "presentation.logMessage" in startup_error_section
    assert "未生成启动日志" in runtime_start_source
    assert "旧浏览器后台进程" not in startup_error_section


def test_visible_smoke_failure_sets_native_exit_only_after_will_quit_cleanup():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    visible_start = source.index("if (runtime.qaVisibleSmokePath)")
    visible_section = source[visible_start:source.index("startupController =", visible_start)]
    will_quit_start = source.index("onWillQuit: () => {")
    will_quit_section = source[will_quit_start:source.index("\n  },\n})", will_quit_start)]

    assert "const nativeExitCoordinator = createNativeExitCoordinator({ app })" in source
    assert "nativeExitCoordinator.requestQuit({ failed: true })" in visible_section
    assert "nativeExitCoordinator.requestQuit()" in visible_section
    assert "process.exitCode" not in source
    assert "app.exit(" not in visible_section
    assert source.count("app.exit(1)") == 1
    assert source.index("app.exit(1)") < source.index("let mainWindow")
    assert "nativeExitCoordinator.finalizeAfterCleanup()" in will_quit_section
    assert "requestBackendTermination" not in will_quit_section
    assert ".kill(" not in will_quit_section


def test_desktop_main_window_setup_is_transactional_and_startup_error_window_is_unique():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    main_window_start = source.index("async function createMainWindow(runtime)")
    main_window_section = source[
        main_window_start:
        source.index("startupController =", main_window_start)
    ]
    error_window_section = source[
        source.index("function createStartupErrorWindow"):
        source.index("const tcpOccupancyProbe")
    ]

    assert "createTransactionalWindow({" in main_window_section
    assert "window.destroy()" in runtime_start_source
    assert "if (getCurrentWindow() === window)" in runtime_start_source
    assert error_window_section.index("focusExistingWindow") < error_window_section.index("new BrowserWindow")
    assert "window.once('closed'" in error_window_section
    assert "startupFailureShown" not in source
    failure_handler = source[
        source.index("function handleDesktopStartupFailure"):
        source.index("if (ownsSingleInstanceLock)")
    ]
    assert "createStartupErrorWindow(error)" in failure_handler


def test_desktop_main_surfaces_fixed_port_and_same_data_conflicts_as_actionable_startup_errors():
    source = DESKTOP_MAIN.read_text(encoding="utf-8")
    runtime_start_source = DESKTOP_RUNTIME_START.read_text(encoding="utf-8")
    message_section = source[
        source.index("function userStartupErrorMessage"):
        source.index("function createStartupErrorWindow")
    ]

    assert "createStartupFailurePresentation(error).message" in message_section
    assert "DXM_PORT_8000_OCCUPIED" in runtime_start_source
    assert "本机 8000 端口已被占用" in runtime_start_source
    assert "已有 DXM Agent Console 正在使用同一数据目录" in runtime_start_source
    assert "error?.conflict" in runtime_start_source
    assert "conflict.port" in runtime_start_source
    assert "conflict.pid" in runtime_start_source
    assert "conflict.instanceId" in runtime_start_source


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
    launch_policy_source = DESKTOP_LAUNCH_POLICY.read_text(encoding="utf-8")
    verify_source = VERIFY_DESKTOP_PACKAGE.read_text(encoding="utf-8")

    assert "classifyLaunchArguments" in source
    assert "qa-user-data-dir" in launch_policy_source
    assert "setUserDataPath: (qaUserDataDir) => app.setPath('userData', qaUserDataDir)" in source
    assert "qa-credential-smoke" in launch_policy_source
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
        assert "87FF78089190226C2E98FAA1B4BA60DA25E25C320901B9FD7C0A6207F9C140F8" in source
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
    assert "87FF78089190226C2E98FAA1B4BA60DA25E25C320901B9FD7C0A6207F9C140F8" in source
    assert "至少建议保留 1GB 可用空间" in source


def test_delivery_docs_describe_two_stage_real_browser_scope():
    docs = [
        README,
        PORTABLE_QUICK_GUIDE,
        USER_GUIDE,
    ]
    for path in docs:
        source = path.read_text(encoding="utf-8")
        assert "待认领商品" in source
        assert "商品箱编辑保存" in source
        assert "只保存" in source
        assert "不发布" in source
        assert "真实浏览器" in source
        assert "本地测试商品" not in source


def test_frontend_vite_build_uses_relative_base_for_electron_file_loading():
    source = FRONTEND_VITE_CONFIG.read_text(encoding="utf-8")

    assert "base: './'" in source


def test_frontend_vite_proxy_uses_runtime_backend_target_for_isolated_qa():
    source = FRONTEND_VITE_CONFIG.read_text(encoding="utf-8")

    assert "const backendTarget =" in source
    assert "process.env.DXM_BACKEND_URL" in source
    assert "process.env.DXM_BACKEND_PORT" in source
    assert "target: backendTarget" in source
    assert "target: 'http://127.0.0.1:8000'" not in source
    assert "target: 'ws://127.0.0.1:8000'" not in source


def test_app_shell_presents_agent_console_as_user_first_navigation():
    source = (REPO_ROOT / "app" / "frontend" / "src" / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    index_html = (REPO_ROOT / "app" / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "DXM Agent Console" in index_html
    assert "type WorkbenchPrimaryArea" in source
    assert "const primaryAreas" in source
    primary_block = source[source.index("const primaryAreas"):source.index("const sectionLabels")]
    assert "label: '准备'" in source
    assert "label: '第一段：待认领商品'" in source
    assert "label: '第二段：编辑只保存'" in source
    assert "label: '复盘'" in source
    assert "label: '维护'" in source
    assert "label: '更多'" not in source
    assert "首页" in source
    assert "账号与浏览器" in source
    assert "待认领商品" in source
    assert "商品箱编辑保存" in source
    assert "模板中心" in source
    assert "浏览器现场" in source
    assert "任务记录" in source
    assert "报告与证据" in source
    assert "证据归档" not in primary_block
    assert "系统维护" in source
    assert "id: 'dashboard'" not in primary_block
    assert "{ id: 'start_save', label: '浏览器现场'" in primary_block
    assert "{ id: 'task_history', label: '任务记录'" in primary_block
    assert "{ id: 'exceptions', label: '问题'" not in primary_block
    assert "{ id: 'preflight', label: '运行前检查'" not in primary_block
    assert "{ id: 'real_browser', label: '真实浏览器'" not in primary_block
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
    assert "<strong>保存前安全检查</strong>" in primary_section
    assert "<strong>人工确认</strong>" in primary_section
    assert "<strong>浏览器现场</strong>" in primary_section
    assert "<summary>维护人员查看运行状态</summary>" in focus_section
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
    assert "backendInstanceId?: string | null" in types_source
    assert "instanceId?: string | null" in types_source
    assert "const [desktopRuntime, setDesktopRuntime]" in app_source
    assert "window.dxmDesktop?.getRuntimeInfo" in app_source
    assert "desktopRuntime={desktopRuntime}" in app_source
    assert "desktopRuntime?: DesktopRuntimeInfo | null" in safety_source
    assert "免安装版：已接入本机服务" in safety_source
    assert "backendInstanceMismatch" in safety_source
    assert "桌面服务实例不一致" in safety_source
    assert "desktopRuntime.desktopLogPath" not in safety_source
    assert "desktopRuntime.backendLogPath" not in safety_source
    assert "桌面日志" not in safety_source


def test_frontend_explains_runtime_ownership_for_desktop_exe_users():
    safety_source = SAFETY_STATUS_BAR.read_text(encoding="utf-8")
    workbench_source = WORKBENCH_MODULES_TSX.read_text(encoding="utf-8")
    types_source = TYPES_TS.read_text(encoding="utf-8")

    assert "owner?: 'start_mvp' | 'desktop' | 'direct' | string" in types_source
    assert "managedByDesktop?: boolean" in types_source
    assert "runtimeOwnerLabel" in safety_source
    assert "启动方式" in safety_source
    assert "免安装版已接管" in safety_source
    assert "旧进程/直接启动" in safety_source
    assert "backendPortMismatch" in safety_source
    assert "桌面服务与当前接口不一致" in safety_source
    assert "DXM Agent Console 免安装版" in workbench_source
    assert "关闭并重新打开免安装版 exe" in workbench_source
    assert "请确认是通过 scripts/start-mvp.bat 启动" not in workbench_source
