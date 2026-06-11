# DXM Electron Agent Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows Electron exe skeleton for DXM Agent Console that launches the local backend, loads the existing React workbench, exposes centralized runtime logs, and makes real browser control the primary user workflow.

**Architecture:** Electron owns the desktop lifecycle and starts the Python FastAPI backend as a hidden child process. The renderer loads the existing Vite production UI with an explicit `apiBase`, while the current Python automation and Playwright DXM flows remain the trusted automation engine. This first desktop slice avoids rewriting the backend to IPC, but creates the packaging and UX boundary needed for a real user-facing agent console.

**Tech Stack:** Electron, electron-builder, Node child_process, React/Vite frontend, existing FastAPI backend, existing Playwright automation.

---

## File Structure

- Create `app/desktop/package.json`: desktop app scripts and Electron dependencies.
- Create `app/desktop/src/main.cjs`: Electron main process, backend lifecycle, port selection, window creation, app logs.
- Create `app/desktop/src/preload.cjs`: safe bridge exposing desktop runtime metadata.
- Create `app/desktop/electron-builder.yml`: Windows exe packaging configuration.
- Create `scripts/start-desktop.bat`: user-facing dev launcher for the Electron console.
- Modify `app/frontend/vite.config.ts`: allow Electron file loading with relative asset paths while preserving dev proxy.
- Modify `app/frontend/src/components/AppShell.tsx`: reduce navigation to user workflow groups.
- Modify `app/frontend/src/components/WorkbenchModules.tsx`: add Agent-first summary copy and make advanced evidence details secondary.
- Modify `app/backend/src/services/agent_console.py`: stabilize browser session lifecycle so completed/running sessions are not closed by repeated starts.
- Add/modify tests:
  - `app/backend/tests/test_desktop_package_contract.py`
  - `app/backend/tests/test_agent_console.py`
  - frontend contract assertions in `test_frontend_demo_workflow_contract.py`

---

## Task 1: Electron Desktop Skeleton

**Files:**
- Create: `app/desktop/package.json`
- Create: `app/desktop/src/main.cjs`
- Create: `app/desktop/src/preload.cjs`
- Create: `app/desktop/electron-builder.yml`
- Create: `scripts/start-desktop.bat`
- Test: `app/backend/tests/test_desktop_package_contract.py`

- [ ] **Step 1: Write contract tests**

Create tests asserting the desktop skeleton exists, starts the backend hidden, passes `apiBase`, and has build scripts.

- [ ] **Step 2: Implement minimal Electron main process**

Main process responsibilities:
- Resolve repo root by walking up until `app/backend/src/main.py` exists.
- Find free backend port starting at `8000`.
- Start backend via `app/backend/.venv/Scripts/python.exe -m uvicorn src.main:app`.
- Set `DXM_DATA_DIR` to repo `data`.
- Load `app/frontend/dist/index.html?apiBase=http://127.0.0.1:<port>`.
- Write logs to `data/desktop-main.log`.
- Kill child backend on app exit.

- [ ] **Step 3: Add desktop launcher**

`scripts/start-desktop.bat` should build the frontend, then run `npm --prefix app/desktop run dev`.

- [ ] **Step 4: Verify**

Run:

```powershell
cd app/backend
.\.venv\Scripts\python.exe -m pytest tests/test_desktop_package_contract.py -q
```

Expected: PASS.

---

## Task 2: Desktop Build Contract

**Files:**
- Modify: `app/frontend/vite.config.ts`
- Modify: `app/desktop/package.json`
- Test: `app/backend/tests/test_desktop_package_contract.py`

- [ ] **Step 1: Make Vite dist Electron-safe**

Set `base: './'` so `file://.../dist/index.html` loads JS/CSS assets correctly.

- [ ] **Step 2: Add build command**

`app/desktop/package.json` scripts:
- `build:frontend`: `npm --prefix ../frontend run build`
- `dev`: `electron .`
- `build`: `npm run build:frontend && electron-builder --config electron-builder.yml`

- [ ] **Step 3: Verify**

Run:

```powershell
npm --prefix app/frontend run build
```

Expected: Vite build PASS and generated `dist/index.html` uses relative asset paths.

---

## Task 3: Real Browser Session Stability

**Files:**
- Modify: `app/backend/src/services/agent_console.py`
- Test: `app/backend/tests/test_agent_console.py`

- [ ] **Step 1: Add tests**

Tests should assert:
- Repeated start for the same active session does not close a visible browser unless `force_restart=true`.
- A completed task can reopen the visible browser without marking the console as blocked.
- Launch errors persist in `last_error` and keep the session recoverable.

- [ ] **Step 2: Implement session reuse**

Change `AgentConsoleService.start()` to:
- Reuse active same-task browser session when visible.
- Only close current browser when starting a different task or when `force_restart=true`.
- Add state field `recoverable` when launch fails.

- [ ] **Step 3: Verify**

Run:

```powershell
cd app/backend
.\.venv\Scripts\python.exe -m pytest tests/test_agent_console.py -q
```

Expected: PASS.

---

## Task 4: Agent-First UX Shell

**Files:**
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/frontend/src/components/SafetyStatusBar.tsx`
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: Collapse navigation**

Primary nav should be:
- `开始`
- `商品配置`
- `Agent 执行`
- `结果`

Evidence, exceptions, L2/L3, HAR, hashes remain available only through advanced disclosures.

- [ ] **Step 2: Add one primary action model**

Top bar and guide page should expose one clear CTA:
- `打开真实店小秘`
- `继续执行`
- `人工确认只保存`
- `查看保存结果`

- [ ] **Step 3: Rewrite status language**

Replace user-facing “阻断” defaults with actionable language:
- `需要登录真实店小秘`
- `需要核对配置`
- `需要人工确认`
- `只保存可执行`

Keep “阻断” only inside advanced safety details.

- [ ] **Step 4: Verify**

Run frontend contract tests and browser QA:

```powershell
cd app/backend
.\.venv\Scripts\python.exe -m pytest tests/test_frontend_demo_workflow_contract.py -q
cd ..\..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1 -Url http://127.0.0.1:5174 -OutDir outputs\browser-check-electron-ux
```

Expected: PASS.

---

## Task 5: Desktop Runtime Verification

**Files:**
- Create/modify: `scripts/qa-desktop-check.ps1`
- Test: `app/backend/tests/test_desktop_package_contract.py`

- [ ] **Step 1: Add desktop smoke script**

Script should:
- Build frontend.
- Start Electron in dev mode.
- Confirm backend `/health` returns OK.
- Confirm Electron log contains loaded `apiBase`.
- Confirm no immediate backend/browser process exit.

- [ ] **Step 2: Verify**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-desktop-check.ps1
```

Expected: PASS and artifact written under `outputs/desktop-check`.

---

## Task 6: Final Delivery Gate

**Files:**
- Modify: `scripts/final-delivery-check.ps1`
- Modify: `docs/product/用户交付使用说明-20260526.md`

- [ ] **Step 1: Add desktop checks to final delivery**

Final delivery should include:
- Existing backend full pytest.
- Frontend production build.
- Browser QA.
- Desktop smoke check.
- Final report center QA.

- [ ] **Step 2: Update user instructions**

User-facing instruction should lead with:

```text
双击 DXM Agent.exe
点击“打开真实店小秘”
人工登录
核对商品配置
点击“人工确认只保存”
查看保存结果
```

- [ ] **Step 3: Final verification**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\final-delivery-check.ps1 -ExpectedRealDxmWriteReadiness READY -OutDir outputs\final-delivery-check-electron
```

Expected: `ok=true`, `localWorkbenchCheck=PASS`, desktop smoke PASS, Browser QA PASS.

---

## Self-Review

- Spec coverage: covers exe skeleton, bat replacement, UI simplification, browser stability, user workflow, desktop verification.
- Placeholder scan: no placeholder tasks are left; every task has concrete files and commands.
- Scope check: this is a multi-stage desktop migration. The first deliverable is a working Electron shell over the current backend; full backend-to-IPC rewrite is intentionally out of this slice.
