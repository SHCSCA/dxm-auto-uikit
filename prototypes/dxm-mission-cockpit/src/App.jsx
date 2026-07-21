import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Navigate,
  Route,
  Routes,
  HashRouter,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import {
  CheckCircleIcon,
  CodeIcon,
  FileTextIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { AppShell } from "./layout/AppShell.jsx";
import { Drawer, Toast } from "./components/Common.jsx";
import TaskCockpitPage from "./pages/TaskCockpitPage.jsx";
import TemplatesPage from "./pages/TemplatesPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import WorkflowHomePage from "./pages/WorkflowHomePage.jsx";
import BatchFlowPage from "./pages/BatchFlowPage.jsx";
import BatchCockpitPage from "./pages/BatchCockpitPage.jsx";
import BatchRecordsPage from "./pages/BatchRecordsPage.jsx";
import { BrowserLivePage, BrowserWorkspacePage } from "./pages/BrowserPages.jsx";
import { usePrototype } from "./state/PrototypeContext.jsx";
import { countTemplateRules, normalizeTemplateSafety, normalizeTemplateSections } from "./data/templateRuleCatalog.js";

const phaseLabels = {
  claim: "商品箱范围读取",
  draft_box_verify: "范围快照已锁定",
  template_validation: "模板校验",
  edit_save: "编辑只保存",
  unpublished_verify: "未发布验证",
  complete: "已完成",
};

const statusToListStatus = {
  waiting_decision: "approval",
  running: "validating",
  completed: "complete",
  paused: "paused",
  manual_takeover: "manual",
  failed: "blocked",
  draft: "draft",
};

function formatDateTime(value, includeSeconds = true) {
  if (!value) return "—";
  const text = String(value);
  const matched = text.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (matched) return `${matched[1]} ${includeSeconds ? matched[2] : matched[2].slice(0, 5)}`;
  return text;
}

function taskStatus(task, execution, isCurrent, flow) {
  if (isCurrent) return flow;
  if (task.status === "paused") return "stopped";
  if (task.status === "running") {
    if (execution?.phase === "edit_save") return "editing";
    if (execution?.phase === "unpublished_verify") return "verifying";
  }
  return statusToListStatus[task.status] || task.status;
}

function normalizeTask(ctx, task) {
  const product = ctx.entities.products[task.productId];
  const template = ctx.entities.templates[task.templateId];
  const execution = ctx.entities.executionRecords[task.executionId];
  const isCurrent = task.id === ctx.run.taskId;
  const status = taskStatus(task, execution, isCurrent, ctx.flow);
  return {
    ...task,
    id: task.id,
    title: task.title,
    productName: product?.title || "未知商品",
    productTitle: product?.title || "未知商品",
    image: product?.image,
    storeName: task.targetStore,
    store: task.targetStore,
    templateName: template ? `${template.name} v${template.version}` : "未绑定模板",
    sourceName: task.sourceTaskName?.replace("批量复验任务", "历史复验来源"),
    step: phaseLabels[execution?.phase] || (status === "complete" ? "未发布验证" : "模板校验"),
    stage: phaseLabels[execution?.phase] || "模板校验",
    status,
    updatedAt: formatDateTime(task.updatedAt),
    result: status === "complete" ? "保存成功且未发布验证通过" : status === "stopped" ? "已安全停止，等待重新处理" : "等待人工处理当前步骤",
    operator: "运营小秘",
  };
}

function normalizeProduct(product) {
  return {
    ...product,
    name: product.title,
    source: `${product.sourcePlatform || "店小秘"} · 商品箱现场范围`,
    updatedAt: "2026-07-20 10:07",
    state: product.queueStatus === "unclaimed" ? "等待现场读取" : "已进入商品箱范围",
    fingerprint: product.fingerprint,
  };
}

function normalizeTemplate(template) {
  const sections = normalizeTemplateSections(template.sections);
  const scope = template.scope || [template.targetPlatform, template.fulfillmentMode, template.category].filter(Boolean).join(" · ");
  return {
    ...template,
    ...normalizeTemplateSafety(template),
    status: template.status === "active" ? "ready" : template.status === "review" ? "warning" : template.status,
    scope,
    validatedAt: template.validatedAt || formatDateTime(template.updatedAt, false).slice(0, 10),
    rules: countTemplateRules(sections),
    sections,
  };
}

function evidenceIcon(type) {
  if (String(type).includes("unpublished")) return ShieldCheckIcon;
  if (String(type).includes("save") || String(type).includes("readback")) return CheckCircleIcon;
  if (String(type).includes("template")) return CodeIcon;
  return FileTextIcon;
}

function buildDemoEvidence(tasks, flows) {
  return tasks.flatMap((task) => {
    const flow = flows[task.id] || task.status || "approval";
    const base = [
      {
        id: `${task.id}-scope`, taskId: task.id, executionId: `${task.id}-execution`,
        type: "draft_scope_snapshot", title: "商品箱范围快照已锁定", skill: "draft_scope_snapshot@prototype",
        status: "passed", result: "现场范围、模板版本与批次授权一致",
        detail: "本地原型已模拟冻结店小秘商品箱当前范围；未提供本地商品或店铺选择器。",
        capturedAt: "2026-07-20T11:06:30+08:00",
      },
      {
        id: `${task.id}-draft-box`, taskId: task.id, executionId: `${task.id}-execution`,
        type: "draft_box_readback", title: "商品箱现场模拟读回完成", skill: "verify_draft_scope@prototype",
        status: "passed", result: "批次将按现场顺序编排 single_save 子任务",
        detail: "仅生成本地模拟记录；未连接真实店小秘，也未触发保存或发布。",
        capturedAt: "2026-07-20T11:06:31+08:00",
      },
      {
        id: `${task.id}-template`, taskId: task.id, executionId: `${task.id}-execution`,
        type: "template_preflight", title: "模板与批次授权等待批准", skill: "template_preflight@prototype",
        status: "needs_decision", result: "字段映射已模拟，整批一次批准尚未授予",
        detail: "未来批量目标只在批次开始前批准一次；后续商品自动顺序编排，不逐件审核。",
        capturedAt: "2026-07-20T11:06:32+08:00",
      },
    ];
    const hasSaveEvidence = ["verifying", "complete"].includes(flow) || task.step === "未发布验证";
    if (hasSaveEvidence) {
      base.push({
        id: `${task.id}-save`, taskId: task.id, executionId: `${task.id}-execution`,
        type: "draft_save_readback", title: "草稿只保存模拟读回完成", skill: "controlled_single_save@prototype",
        status: "passed", result: "本地模拟字段读回一致",
        detail: "这是交互原型生成的模拟证据；没有向真实店小秘发送保存请求。",
        capturedAt: "2026-07-20T11:06:35+08:00",
      });
    }
    if (flow === "complete") {
      base.push({
        id: `${task.id}-unpublished`, taskId: task.id, executionId: `${task.id}-execution`,
        type: "unpublished_verification", title: "未发布模拟验证通过", skill: "verify_unpublished_state@prototype",
        status: "passed", result: "本地动作账本中的发布动作计数为 0",
        detail: "原型仅验证本地模拟动作账本，不能代表真实店小秘运行结果。",
        capturedAt: "2026-07-20T11:06:38+08:00",
      });
    }
    return base;
  });
}

function buildDemoActivities(entries) {
  return [...entries].reverse().map((entry) => ({
    id: `activity-${entry.id}`,
    tone: entry.status === "passed" ? "done" : "warning",
    title: entry.status === "passed" ? `已完成：${entry.title}` : entry.title,
    description: entry.detail,
    time: formatDateTime(entry.capturedAt).slice(-8),
  }));
}

function EvidenceDrawer({ context, selectedTaskId, evidenceEntries = [] }) {
  const { state, actions } = context;
  const focus = state.ui.evidenceFocus || state.navigation.activeEvidenceId || "all";
  const relevant = evidenceEntries.filter((item) => !selectedTaskId || item.taskId === selectedTaskId);
  const selectedIds = useMemo(() => {
    if (focus === "all") return new Set();
    if (focus === "result") return new Set(relevant.filter((item) => ["draft_save_readback", "unpublished_verification"].includes(item.type)).map((item) => item.id));
    if (focus === "category") return new Set(relevant.filter((item) => item.type === "template_preflight").map((item) => item.id));
    return new Set([focus]);
  }, [focus, relevant]);

  return (
    <Drawer
      open={state.ui.evidenceDrawerOpen}
      onClose={actions.closeEvidence}
      eyebrow="任务证据链"
      title="执行证据与明细"
      testId="global-evidence-drawer"
      footer={(
        <>
          <button type="button" className="secondary-button" onClick={actions.closeEvidence}>返回任务</button>
          <button type="button" className="primary-button" onClick={actions.closeEvidence}>我已查看</button>
        </>
      )}
    >
      <div className="drawer-boundary">
        <ShieldCheckIcon size={21} weight="fill" />
        <div><strong>受控单商品 · 只保存</strong><span>原型只展示本地模拟记录，不连接真实店小秘</span></div>
      </div>
      <div className="evidence-list evidence-list--full">
        {relevant.map((entry) => {
          const Icon = evidenceIcon(entry.type);
          const selected = selectedIds.has(entry.id);
          return (
            <article key={entry.id} className={`evidence-item${selected ? " is-selected" : ""}`}>
              <div className="evidence-item__icon"><Icon size={20} /></div>
              <div className="evidence-item__body">
                <time>{formatDateTime(entry.capturedAt)}</time>
                <strong>{entry.title}</strong>
                <code>Skill · {entry.skill || entry.type}</code>
                <p>{entry.detail}</p>
                <span>{entry.result}</span>
              </div>
            </article>
          );
        })}
        {!relevant.length && (
          <div className="empty-state empty-state--drawer">
            <WarningCircleIcon size={34} weight="duotone" />
            <strong>当前任务还没有可用证据</strong>
            <p>证据缺失时任务不会显示为完成。</p>
          </div>
        )}
      </div>
    </Drawer>
  );
}

function buildActivities(context, taskId) {
  const task = context.entities.tasks[taskId];
  const execution = task ? context.entities.executionRecords[task.executionId] : null;
  if (!execution?.events?.length) return [];
  const newestFirst = [...execution.events].reverse();
  return newestFirst.map((event) => {
    const done = event.type.includes("completed") || event.type === "run.completed";
    const warning = event.type.includes("paused") || event.type.includes("required") || event.type.includes("deferred");
    return {
      id: event.id,
      tone: done ? "done" : warning ? "warning" : "active",
      title: done ? `已完成：${phaseLabels[event.phase] || event.summary}` : warning ? event.summary : `正在执行：${phaseLabels[event.phase] || event.summary}`,
      description: done ? `${event.summary}，相关读回与操作记录已进入证据链。` : "系统保持当前现场，等待满足安全条件后继续。",
      time: formatDateTime(event.at).slice(-8),
    };
  });
}

function Application() {
  const context = usePrototype();
  const location = useLocation();
  const navigate = useNavigate();
  const [toast, setToast] = useState({ message: "", tone: "success" });
  const toastTimer = useRef(null);
  const [createdTasks, setCreatedTasks] = useState([]);
  const [createdTemplates, setCreatedTemplates] = useState(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem("dxm-prototype-templates-v4") || "[]");
      return Array.isArray(stored) ? stored : [];
    } catch {
      return [];
    }
  });
  const [demoFlows, setDemoFlows] = useState({});
  const demoTimers = useRef({});
  const demoRunTokens = useRef({});
  const demoResumeFlows = useRef({});
  const demoInterruptions = useRef({});
  const previousDemoFlows = useRef({});
  const [settings, setSettings] = useState(() => {
    const defaults = {
      operatorLabel: "运营小秘",
      defaultStore: "AliExpress 半托管店铺",
      rememberAccountLocally: true,
      autoOpenEvidence: true,
      evidenceRetentionDays: 30,
    };
    try {
      return { ...defaults, ...JSON.parse(window.localStorage.getItem("dxm-prototype-settings") || "{}") };
    } catch {
      return defaults;
    }
  });
  const previousFlow = useRef(context.flow);

  const notify = useCallback((message, tone = "success") => {
    window.clearTimeout(toastTimer.current);
    setToast({ message, tone });
    toastTimer.current = window.setTimeout(() => setToast({ message: "", tone: "success" }), 2600);
  }, []);

  useEffect(() => () => {
    window.clearTimeout(toastTimer.current);
    Object.values(demoTimers.current).flat().forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    if (!context.state.ui.notice?.message) return;
    notify(context.state.ui.notice.message, context.state.ui.notice.tone || "success");
    context.actions.clearNotice();
  }, [context.actions, context.state.ui.notice, notify]);

  const normalizedTasks = useMemo(() => context.tasks.map((task) => normalizeTask(context, task)), [context]);
  const taskList = useMemo(() => [...createdTasks, ...normalizedTasks], [createdTasks, normalizedTasks]);
  const products = useMemo(() => context.unclaimedProducts.map(normalizeProduct), [context.unclaimedProducts]);
  const templates = useMemo(() => {
    const localIds = new Set(createdTemplates.map((template) => String(template.id)));
    return [
      ...createdTemplates.map(normalizeTemplate),
      ...context.templates.map(normalizeTemplate).filter((template) => !localIds.has(String(template.id))),
    ];
  }, [context.templates, createdTemplates]);
  const demoEvidence = useMemo(() => buildDemoEvidence(createdTasks, demoFlows), [createdTasks, demoFlows]);
  const visibleContextEvidence = useMemo(() => {
    const cutoff = Date.now() - settings.evidenceRetentionDays * 24 * 60 * 60 * 1000;
    return context.evidence.filter((entry) => {
      const timestamp = Date.parse(entry.capturedAt || entry.createdAt || "");
      return !Number.isFinite(timestamp) || timestamp >= cutoff;
    });
  }, [context.evidence, settings.evidenceRetentionDays]);
  const allEvidence = useMemo(() => [...demoEvidence, ...visibleContextEvidence], [demoEvidence, visibleContextEvidence]);
  const runtimeIdentity = useMemo(() => {
    const identity = context.runtimeIdentities.find((item) => item.kind === "agent_runtime") || context.runtimeIdentities[0] || {};
    return {
      ...identity,
      connected: false,
      simulation: true,
      liveConnected: false,
      operator: settings.operatorLabel,
      storeName: settings.defaultStore,
      storeId: "store-ae-half-managed-cn-03",
      browser: "本地原型浏览器（模拟）",
      sessionId: "prototype-session-local",
      status: "本地模拟可用，未连接真实店小秘",
      runtimeId: "DXM-PROTOTYPE-LOCAL",
      buildId: "prototype-option1-full-20260720",
      gitHead: "3356c25（原型基线）",
      backendInstance: "本地交互原型 · 未连接真实服务",
      browserSession: "prototype-session-local",
      verifiedAt: formatDateTime(identity.lastVerifiedAt),
    };
  }, [context.runtimeIdentities, settings.defaultStore, settings.operatorLabel]);

  const updateSettings = useCallback((next) => {
    setSettings(next);
    const persisted = next.rememberAccountLocally ? next : {
      ...next,
      operatorLabel: "运营小秘",
      defaultStore: "AliExpress 半托管店铺",
    };
    window.localStorage.setItem("dxm-prototype-settings", JSON.stringify(persisted));
  }, []);

  useEffect(() => {
    if (previousFlow.current !== "complete" && context.flow === "complete" && settings.autoOpenEvidence) {
      context.actions.openEvidence("result");
    }
    previousFlow.current = context.flow;
  }, [context.actions, context.flow, settings.autoOpenEvidence]);

  useEffect(() => {
    const completedActiveLocalTask = createdTasks.find((task) => (
      task.id === location.pathname.match(/^\/tasks\/([^/]+)$/)?.[1]
      && demoFlows[task.id] === "complete"
      && previousDemoFlows.current[task.id] !== "complete"
    ));
    if (completedActiveLocalTask && settings.autoOpenEvidence) context.actions.openEvidence("result");
    previousDemoFlows.current = { ...demoFlows };
  }, [context.actions, createdTasks, demoFlows, location.pathname, settings.autoOpenEvidence]);

  const requestedSettingsTab = useMemo(() => {
    const tab = new URLSearchParams(location.search).get("tab");
    return ["account", "boundary", "runtime", "help"].includes(tab) ? tab : "account";
  }, [location.search]);

  const requestedRecordsTab = useMemo(() => {
    const tab = new URLSearchParams(location.search).get("tab");
    return ["tasks", "evidences", "issues"].includes(tab) ? tab : "tasks";
  }, [location.search]);

  const updateTemplate = useCallback((change) => {
    if (change?.template) {
      setCreatedTemplates((items) => {
        const next = [change.template, ...items.filter((item) => item.id !== change.template.id)];
        window.localStorage.setItem("dxm-prototype-templates-v4", JSON.stringify(next));
        return next;
      });
    }
  }, []);

  const openTask = useCallback((target) => {
    const id = typeof target === "string" ? target : target?.id || target?.raw?.id;
    if (!id) return;
    const local = createdTasks.find((task) => task.id === id);
    const pendingLocal = Boolean(target?.isDemoCreated || target?.raw?.isDemoCreated);
    if (!local && !pendingLocal && !context.entities.tasks[id]) {
      notify("没有找到这条任务，记录已保留但不能继续执行", "warning");
      return;
    }
    if (!local && !pendingLocal) context.actions.selectTask(id);
    navigate(`/tasks/${id}`);
  }, [context.actions, context.entities.tasks, createdTasks, navigate, notify]);

  const createTask = useCallback(async (payload) => {
    const active = taskList.find((task) => ["approval", "claiming", "claimed", "validating", "editing", "verifying", "paused", "manual", "deferred", "blocked"].includes(task.status));
    if (active) return { ok: false, message: "已有任务正在运行，当前只能保留一个受控任务" };
    const product = products.find((item) => item.id === payload.productId);
    const template = templates.find((item) => item.id === payload.templateId);
    if (!template || template.status !== "ready") {
      return { ok: false, message: "所选模板尚未完成校验，不能绑定或创建任务" };
    }
    const id = `task-demo-${Date.now()}`;
    const task = {
      id,
      title: `批量编辑子任务 - ${product?.name || "店小秘商品箱商品"}`,
      productName: product?.name,
      productTitle: product?.name,
      image: product?.image,
      storeName: runtimeIdentity.storeName,
      store: runtimeIdentity.storeName,
      templateName: `${template?.name || "已选模板"} ${template?.version || ""}`,
      sourceName: "店小秘商品箱现场范围",
      step: "模板校验",
      stage: "模板校验",
      status: "approval",
      updatedAt: "2026-07-20 11:06:32",
      result: "范围快照与模板版本已锁定，等待整批一次批准",
      operator: "运营小秘",
      isDemoCreated: true,
    };
    setCreatedTasks((items) => [task, ...items]);
    setDemoFlows((flows) => ({ ...flows, [id]: "approval" }));
    notify("批次范围与模板版本已锁定；整批批准一次后将自动顺序执行");
    return { ok: true, task };
  }, [notify, products, runtimeIdentity.storeName, taskList, templates]);

  const commitDemoFlow = useCallback((id, flow, heldAt = null) => {
    const stepForFlow = (value) => value === "editing"
      ? "编辑只保存"
      : value === "verifying" || value === "complete"
        ? "未发布验证"
        : value === "approval" || value === "deferred"
          ? "模板校验"
          : null;
    setDemoFlows((items) => ({ ...items, [id]: flow }));
    setCreatedTasks((items) => items.map((task) => task.id === id ? {
      ...task,
      status: flow,
      step: ["paused", "manual"].includes(flow)
        ? (stepForFlow(heldAt) || task.step)
        : (stepForFlow(flow) || task.step),
      stage: ["paused", "manual"].includes(flow)
        ? (stepForFlow(heldAt) || task.stage)
        : (stepForFlow(flow) || task.stage),
      result: flow === "complete" ? "保存成功且未发布验证通过" : task.result,
    } : task));
  }, []);

  const clearDemoTimers = useCallback((id) => {
    (demoTimers.current[id] || []).forEach((timer) => window.clearTimeout(timer));
    delete demoTimers.current[id];
    demoRunTokens.current[id] = (demoRunTokens.current[id] || 0) + 1;
  }, []);

  const updateDemoFlow = useCallback((id, flow, resumeFrom = null) => {
    clearDemoTimers(id);
    const preservedResumeFlow = ["paused", "manual", "deferred"].includes(resumeFrom)
      ? (demoResumeFlows.current[id] || resumeFrom)
      : resumeFrom;
    if (["paused", "manual", "deferred"].includes(flow)) {
      demoResumeFlows.current[id] = preservedResumeFlow || "approval";
    }
    commitDemoFlow(id, flow, preservedResumeFlow);
    return true;
  }, [clearDemoTimers, commitDemoFlow]);

  const runDemoApproval = useCallback((id, startFlow = "editing") => {
    clearDemoTimers(id);
    const token = demoRunTokens.current[id];
    commitDemoFlow(id, startFlow);
    const advance = (delay, flow) => window.setTimeout(() => {
      if (demoRunTokens.current[id] !== token) return;
      commitDemoFlow(id, flow);
    }, delay);
    demoTimers.current[id] = startFlow === "verifying"
      ? [advance(2800, "complete")]
      : [advance(2200, "verifying"), advance(5000, "complete")];
    return true;
  }, [clearDemoTimers, commitDemoFlow]);

  const resumeDemoFlow = useCallback((id) => {
    const resumeFlow = demoResumeFlows.current[id] || "approval";
    if (["editing", "verifying"].includes(resumeFlow)) {
      runDemoApproval(id, resumeFlow);
      return true;
    }
    return updateDemoFlow(id, resumeFlow);
  }, [runDemoApproval, updateDemoFlow]);

  const beginDemoInterruption = useCallback((id, kind, heldFlow, currentFlow) => {
    const phaseFlow = ["paused", "manual", "deferred"].includes(currentFlow)
      ? (demoResumeFlows.current[id] || "approval")
      : currentFlow;
    const stack = demoInterruptions.current[id] || [];
    demoInterruptions.current[id] = [...stack, { kind, previousFlow: currentFlow, phaseFlow }];
    return updateDemoFlow(id, heldFlow, phaseFlow);
  }, [updateDemoFlow]);

  const restoreDemoInterruption = useCallback((id, kind) => {
    const stack = demoInterruptions.current[id] || [];
    const interruption = stack[stack.length - 1];
    if (!interruption || interruption.kind !== kind) return false;
    demoInterruptions.current[id] = stack.slice(0, -1);
    if (["editing", "verifying"].includes(interruption.previousFlow)) {
      return runDemoApproval(id, interruption.previousFlow);
    }
    return updateDemoFlow(id, interruption.previousFlow, interruption.phaseFlow);
  }, [runDemoApproval, updateDemoFlow]);

  const openEvidence = useCallback((focus = "all") => {
    context.actions.openEvidence(focus);
  }, [context.actions]);

  const routedTaskId = location.pathname.match(/^\/tasks\/([^/]+)$/)?.[1];
  const currentTaskIdForEvidence = createdTasks.some((task) => task.id === routedTaskId)
    ? routedTaskId
    : context.navigation.activeTaskId;

  if (location.pathname === "/browser/live") {
    return <BrowserLivePage notify={notify} />;
  }

  return (
    <AppShell
      notify={notify}
      runtimeIdentity={runtimeIdentity}
    >
      <Routes>
        <Route path="/tasks" element={<WorkflowHomePage runtimeIdentity={runtimeIdentity} />} />
        <Route path="/tasks/current" element={<WorkflowHomePage runtimeIdentity={runtimeIdentity} />} />
        <Route path="/edit" element={<BatchFlowPage mode="edit" templates={templates} notify={notify} />} />
        <Route path="/batches/:batchId" element={<BatchCockpitPage notify={notify} />} />
        <Route path="/browser" element={<BrowserWorkspacePage notify={notify} />} />
        <Route path="/tasks/:taskId" element={<Navigate replace to="/tasks/current" />} />
        <Route path="/templates" element={<TemplatesPage templates={templates} onUpdateTemplate={updateTemplate} notify={notify} />} />
        <Route path="/records" element={<BatchRecordsPage notify={notify} />} />
        <Route path="/settings" element={<SettingsPage initialTab={requestedSettingsTab} runtimeIdentity={runtimeIdentity} settings={settings} onUpdateSettings={updateSettings} onOpenIssues={() => navigate("/records?tab=issues")} notify={notify} />} />
        <Route path="/" element={<Navigate replace to="/tasks/current" />} />
        <Route path="*" element={<Navigate replace to="/tasks/current" />} />
      </Routes>

      <EvidenceDrawer context={context} selectedTaskId={currentTaskIdForEvidence} evidenceEntries={allEvidence} />
      <Toast message={toast.message} tone={toast.tone} />
    </AppShell>
  );
}

function CockpitRoute({ context, createdTasks, demoFlows, demoEvidence, openTaskList, openEvidence, notify, updateDemoFlow, resumeDemoFlow, runDemoApproval, beginDemoInterruption, restoreDemoInterruption }) {
  const { taskId } = useParams();
  const requestedId = taskId || context.run.taskId;
  const localTask = createdTasks.find((task) => task.id === requestedId);
  const requestedSourceTask = context.entities.tasks[requestedId];
  const missingRequestedTask = Boolean(taskId && !localTask && !requestedSourceTask);
  const sourceTask = requestedSourceTask || context.entities.tasks[context.run.taskId];
  const task = localTask || normalizeTask(context, sourceTask);
  const isCurrentRun = !localTask && sourceTask.id === context.run.taskId;
  const flow = localTask ? (demoFlows[localTask.id] || "approval") : isCurrentRun ? context.flow : task.status;
  const run = localTask ? { flow } : { ...context.run, flow };
  const evidences = localTask ? demoEvidence.filter((item) => item.taskId === localTask.id) : context.evidence.filter((item) => item.taskId === sourceTask.id);
  const activities = localTask ? buildDemoActivities(evidences) : buildActivities(context, sourceTask.id);

  useEffect(() => {
    if (!localTask && context.entities.tasks[requestedId]) context.actions.selectTask(requestedId);
  }, [context.actions, context.entities.tasks, localTask, requestedId]);

  if (missingRequestedTask) return <Navigate replace to="/tasks/current" />;

  const readOnlyNotice = () => ({ ok: false, message: "历史任务为只读状态，请从记录页查看证据" });
  const approve = () => localTask ? runDemoApproval(localTask.id) : isCurrentRun ? context.actions.approveDecision() : readOnlyNotice();
  const defer = () => localTask ? updateDemoFlow(localTask.id, "deferred", flow) : isCurrentRun ? context.actions.deferDecision() : readOnlyNotice();
  const pause = () => localTask
    ? (flow === "paused" ? restoreDemoInterruption(localTask.id, "pause") : beginDemoInterruption(localTask.id, "pause", "paused", flow))
    : isCurrentRun ? context.actions.pauseRun() : readOnlyNotice();
  const resume = () => localTask
    ? (flow === "paused" ? restoreDemoInterruption(localTask.id, "pause") : resumeDemoFlow(localTask.id))
    : isCurrentRun ? (context.flow === "deferred" ? context.actions.reopenDecision() : context.actions.resumeRun()) : readOnlyNotice();
  const takeover = () => localTask
    ? beginDemoInterruption(localTask.id, "manual_takeover", "manual", flow)
    : isCurrentRun ? context.actions.startTakeover() : readOnlyNotice();
  const returnAgent = () => localTask
    ? restoreDemoInterruption(localTask.id, "manual_takeover")
    : isCurrentRun ? context.actions.returnToAgent() : readOnlyNotice();

  return (
    <TaskCockpitPage
      task={task}
      run={run}
      activities={activities}
      evidences={evidences}
      onApprove={approve}
      onDefer={defer}
      onPause={pause}
      onTakeover={takeover}
      onResume={resume}
      onReturnAgent={returnAgent}
      onOpenEvidence={openEvidence}
      onOpenTasks={openTaskList}
      notify={notify}
      readOnly={!localTask && !isCurrentRun}
    />
  );
}

export function App() {
  return (
    <HashRouter>
      <Application />
    </HashRouter>
  );
}
