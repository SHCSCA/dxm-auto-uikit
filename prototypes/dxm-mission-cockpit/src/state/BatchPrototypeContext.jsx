import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { products as fixtureProducts, templates as fixtureTemplates } from "../data/fixtures.js";
import { countTemplateRules, normalizeTemplateSafety, normalizeTemplateSections } from "../data/templateRuleCatalog.js";

const STORAGE_KEY = "dxm-batch-prototype-v14-edit-autopilot";
const MUTATION_LOCK_KEY = `${STORAGE_KEY}:state-mutation`;
const RUN_STEP_MS = 1650;
const RUN_LEASE_MS = 8000;
const SCHEMA_VERSION = 14;

// Compatibility export for the surrounding prototype. This is an observed
// property of the live DXM snapshot, never a local store selector.
export const stores = [
  {
    id: "dxm-live-draft-box-scope",
    name: "随店小秘商品箱现场读回",
    account: "店小秘商品箱当前筛选快照",
    selectable: false,
    identityVerified: false,
    source: "dxm_draft_box_snapshot",
  },
];

const LIVE_SCOPE_STORE = stores[0];

function formatVersion(version) {
  const value = String(version || "—");
  return value.startsWith("v") ? value : `v${value}`;
}

function prototypeDigest(source) {
  let hash = 2166136261;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `fnv32:prototype-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.keys(value).sort().reduce((result, key) => {
    result[key] = stableValue(value[key]);
    return result;
  }, {});
}

function snapshotWithDigest(snapshot) {
  const stableSnapshot = stableValue(snapshot);
  return { ...stableSnapshot, contentDigest: prototypeDigest(JSON.stringify(stableSnapshot)) };
}

export function buildTemplateSnapshot(template) {
  if (!template) return null;
  const sections = normalizeTemplateSections(template.sections);
  const safety = normalizeTemplateSafety(template);
  return snapshotWithDigest({
    templateId: template.id,
    name: template.name,
    version: formatVersion(template.version),
    scope: template.scope || [template.targetPlatform, template.fulfillmentMode, template.category].filter(Boolean).join(" · "),
    ruleCount: countTemplateRules(sections),
    sections: sections.map((section) => ({
      id: section.id,
      label: section.label,
      description: section.description,
      fieldCount: Number(section.fieldCount || section.rules?.length || 0),
      rules: (section.rules || []).map((rule) => ({
        id: rule.id,
        label: rule.label ?? rule.field,
        value: rule.value ?? rule.strategy,
        source: rule.source,
        required: Boolean(rule.required),
      })),
    })),
    approvalRules: safety.approvalRules,
    allowedActions: safety.allowedActions,
    blockedActions: safety.blockedActions,
    safetyPolicy: safety.safetyPolicy,
  });
}

export function buildApprovalFingerprint({ storeId, productIds = [], templateSnapshot }) {
  const orderedProducts = productIds.map((productId, index) => `${index + 1}:${productId}`);
  const source = [
    "edit_batch_once",
    storeId || LIVE_SCOPE_STORE.id,
    String(productIds.length),
    templateSnapshot?.contentDigest || "missing-template-snapshot",
    ...orderedProducts,
  ].join("|");
  return prototypeDigest(source);
}

const productExtras = {
  "product-hud-0618-202624": { sku: "DXM-HUD-C1-0618" },
  "product-inflator-0719-0842": { sku: "DXM-AIR-PUMP-A8" },
  "product-obd-0719-1128": { sku: "DXM-OBD-V519" },
  "product-carplay-0720-1007": { sku: "DXM-CP-A11-2K" },
  "product-dashcam-0720-1014": { sku: "DXM-DC-R9-4K" },
  "product-inverter-0720-1029": { sku: "DXM-INV-300W-CN" },
};

// Fixtures stand in for one frozen live snapshot. They are never exposed as a
// local picker and only become queue rows when the batch is approved.
const prototypeProducts = fixtureProducts.map((product, index) => ({
  ...product,
  ...productExtras[product.id],
  name: product.title,
  category: product.categoryPath?.slice(-1)[0] || product.claimedCategory || "未分类",
  source: "店小秘商品箱 · 当前筛选快照",
  queueStatus: "draft_box",
  storeId: LIVE_SCOPE_STORE.id,
  stageAProof: true,
  snapshotOrdinal: index + 1,
}));

const initialTemplateSnapshot = buildTemplateSnapshot(
  fixtureTemplates.find((template) => template.id === "template-hud-half-managed-v1.3"),
);
const initialProductIds = prototypeProducts.slice(0, 3).map((product) => product.id);
const initialScopeSnapshot = snapshotWithDigest({
  snapshotId: "DXM-SCOPE-20260719-006",
  sourcePage: "速卖通 → 商品箱",
  sourceUrl: "/web/smt/smtProductList/draft",
  filterSummary: "店小秘当前筛选与排序",
  orderedCount: 3,
  storeIdentity: "随商品箱现场读回",
});

const initialBatches = [
  {
    id: "EDT-20260719-006",
    type: "edit",
    title: "汽修与车载电子批量编辑",
    storeId: LIVE_SCOPE_STORE.id,
    storeName: LIVE_SCOPE_STORE.name,
    intakeMode: "dxm_live_snapshot",
    intakeDescription: "店小秘商品箱当前筛选范围 · 已冻结 3 件有序快照",
    sourcePage: "速卖通 → 商品箱",
    scopeSnapshot: initialScopeSnapshot,
    maxItems: 3,
    templateId: "template-hud-half-managed-v1.3",
    templateName: `${initialTemplateSnapshot.name} ${initialTemplateSnapshot.version}`,
    templateVersion: initialTemplateSnapshot.version,
    templateSnapshot: initialTemplateSnapshot,
    templateContentDigest: initialTemplateSnapshot.contentDigest,
    status: "needs_attention",
    owner: "agent",
    approvedBy: "运营小秘 · 整批一次批准",
    approvedAt: "2026-07-19 16:20:31",
    approvalMode: "batch_once",
    autoDispatch: true,
    approvalHash: buildApprovalFingerprint({
      storeId: LIVE_SCOPE_STORE.id,
      productIds: initialProductIds,
      templateSnapshot: initialTemplateSnapshot,
    }),
    createdAt: "2026-07-19 16:20:31",
    updatedAt: "2026-07-19 16:37:19",
    items: [
      { id: "EDT-I-01", ordinal: 1, productId: initialProductIds[0], status: "success", action: "保存回读与未发布证明通过；已自动派发下一件", evidenceCount: 5 },
      { id: "EDT-I-02", ordinal: 2, productId: initialProductIds[1], status: "unknown", action: "保存结果未知，整批停止并等待人工对账", evidenceCount: 3 },
      { id: "EDT-I-03", ordinal: 3, productId: initialProductIds[2], status: "pending", action: "因前项 UNKNOWN 停止派发", evidenceCount: 1 },
    ],
  },
];

const initialBrowser = {
  connected: false,
  liveConnected: false,
  simulation: true,
  status: "needs_attention",
  owner: "agent",
  batchId: "EDT-20260719-006",
  sessionId: "DXM-PROTOTYPE-SESSION-07",
  profile: "prototype-visible-browser",
  currentUrl: "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
  currentAction: "保存结果未知，整批停止并等待人工对账",
  lastReadback: "2026-07-19 16:37:19",
  actionIndex: 0,
  boundRunId: null,
};

const initialState = {
  meta: { schema: SCHEMA_VERSION, revision: 0 },
  products: prototypeProducts,
  batches: initialBatches,
  browser: initialBrowser,
};

function normalizeStoredState(stored, fallback) {
  if (!stored || !Array.isArray(stored.batches)) return fallback;
  return {
    meta: stored.meta || fallback.meta,
    products: Array.isArray(stored.products) ? stored.products : fallback.products,
    batches: stored.batches.filter((batch) => batch.type === "edit"),
    browser: { ...fallback.browser, ...(stored.browser || {}) },
  };
}

function loadInitialState() {
  try {
    return normalizeStoredState(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null"), initialState);
  } catch {
    return initialState;
  }
}

function readLatestStoredState(fallback) {
  try {
    return normalizeStoredState(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null"), fallback);
  } catch {
    return fallback;
  }
}

function persistPrototypeState(nextState) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
    meta: nextState.meta,
    products: nextState.products,
    batches: nextState.batches,
    browser: nextState.browser,
  }));
}

function productById(products, id) {
  return products.find((product) => product.id === id);
}

function itemStats(batch) {
  const items = batch?.items || [];
  return items.reduce((result, item) => {
    result[item.status] = (result[item.status] || 0) + 1;
    return result;
  }, {
    total: Number(batch?.maxItems || items.length),
    success: 0,
    running: 0,
    awaiting_approval: 0,
    pending: 0,
    failed: 0,
    unknown: 0,
    skipped: 0,
  });
}

function isTerminalBatch(status) {
  return ["completed", "completed_with_issues", "stopped", "failed"].includes(status);
}

function formatTimestamp() {
  return new Date().toLocaleString("zh-CN", { hour12: false }).replaceAll("/", "-");
}

function newRun(itemId) {
  const runId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  const startedAt = Date.now();
  return {
    runId,
    itemId,
    startedAt,
    deadlineAt: startedAt + RUN_STEP_MS,
    leaseExpiresAt: startedAt + RUN_LEASE_MS,
  };
}

const BatchPrototypeContext = createContext(null);

export function BatchPrototypeProvider({ children }) {
  const [state, setState] = useState(loadInitialState);
  const stateRef = useRef(state);
  const runTimersRef = useRef(new Map());

  const mutateLatest = useCallback(async (mutator) => {
    const runMutation = () => {
      const latest = readLatestStoredState(stateRef.current);
      const mutation = mutator(latest) || {};
      const candidate = mutation.nextState || latest;
      const nextState = candidate === latest ? latest : {
        ...candidate,
        meta: { schema: SCHEMA_VERSION, revision: Number(latest.meta?.revision || 0) + 1 },
      };
      if (nextState !== latest) persistPrototypeState(nextState);
      if (Number(nextState.meta?.revision || 0) >= Number(stateRef.current.meta?.revision || 0)) {
        stateRef.current = nextState;
        setState(nextState);
      }
      return mutation.result || { ok: true };
    };
    if (window.navigator.locks?.request) {
      return window.navigator.locks.request(MUTATION_LOCK_KEY, { mode: "exclusive" }, runMutation);
    }
    return { ok: false, message: "浏览器不支持安全事务锁；为避免跨窗口覆盖，已阻止本次写入" };
  }, []);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const sync = (event) => {
      if (event.key !== STORAGE_KEY || !event.newValue) return;
      try {
        const stored = JSON.parse(event.newValue);
        if (!Array.isArray(stored.batches)) return;
        const current = stateRef.current;
        if (Number(stored.meta?.revision || 0) <= Number(current.meta?.revision || 0)) return;
        const next = normalizeStoredState(stored, current);
        stateRef.current = next;
        setState(next);
      } catch {
        // Ignore malformed local prototype state from another tab.
      }
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);

  useEffect(() => {
    const recoverExpiredRuns = () => {
      void mutateLatest((current) => {
        const now = Date.now();
        const expiredBatches = current.batches.filter((batch) => batch.status === "running"
          && (!batch.execution?.leaseExpiresAt || batch.execution.leaseExpiresAt <= now));
        if (!expiredBatches.length) return { result: { ok: true, recovered: false } };
        const expiredIds = new Set(expiredBatches.map((batch) => batch.id));
        const nextBatches = current.batches.map((batch) => {
          if (!expiredIds.has(batch.id)) return batch;
          return {
            ...batch,
            status: "needs_attention",
            execution: null,
            items: batch.items.map((item) => item.status === "running" ? {
              ...item,
              status: "unknown",
              action: "执行租约已过期，结果未知；整批停止，禁止自动重试",
              evidenceCount: item.evidenceCount + 1,
            } : item),
            updatedAt: formatTimestamp(),
          };
        });
        const expiredBrowserBatch = expiredBatches.find((batch) => batch.id === current.browser.batchId);
        const browserExpired = expiredBrowserBatch
          && current.browser.boundRunId === expiredBrowserBatch.execution?.runId;
        return {
          nextState: {
            ...current,
            batches: nextBatches,
            browser: browserExpired ? {
              ...current.browser,
              status: "needs_attention",
              boundRunId: null,
              currentAction: "执行租约已过期，写入边界未知；整批停止并等待人工核对",
              lastReadback: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
            } : current.browser,
          },
          result: { ok: true, recovered: true },
        };
      });
    };
    recoverExpiredRuns();
    const timer = window.setInterval(recoverExpiredRuns, 1500);
    return () => window.clearInterval(timer);
  }, [mutateLatest]);

  const scheduleRun = useCallback(function scheduleRun(batchId, runId, delay = RUN_STEP_MS) {
    const timerKey = `${batchId}:${runId}`;
    if (runTimersRef.current.has(timerKey)) return;
    const timer = window.setTimeout(async () => {
      runTimersRef.current.delete(timerKey);
      const result = await mutateLatest((current) => {
        const currentBatch = current.batches.find((batch) => batch.id === batchId);
        if (!currentBatch || currentBatch.status !== "running" || currentBatch.owner !== "agent"
          || currentBatch.execution?.runId !== runId
          || currentBatch.execution.leaseExpiresAt <= Date.now()) {
          return { result: { ok: false, ignored: true } };
        }
        const runningItem = currentBatch.items.find((item) => item.status === "running");
        if (!runningItem || runningItem.id !== currentBatch.execution.itemId) {
          return { result: { ok: false, ignored: true } };
        }

        const isValidationSkip = currentBatch.demoValidationSkipAt === runningItem.ordinal;
        let nextItems = currentBatch.items.map((item) => item.id === runningItem.id ? {
          ...item,
          status: isValidationSkip ? "skipped" : "success",
          action: isValidationSkip
            ? "保存前必填校验失败，已证明未触发写入；隔离后自动继续"
            : "保存回读与未发布证明通过；自动派发下一件",
          evidenceCount: item.evidenceCount + (isValidationSkip ? 2 : 4),
        } : item);

        const hasIssue = nextItems.some((item) => ["skipped", "failed"].includes(item.status));
        const nextPending = nextItems.find((item) => item.status === "pending");
        let nextStatus = "completed";
        let nextExecution = null;
        let currentAction = hasIssue ? "批次完成，包含已隔离的保存前校验异常" : "整批编辑完成";
        let nextRunId = null;

        if (currentBatch.stopAfterCurrent) {
          nextItems = nextItems.map((item) => item.status === "pending" ? {
            ...item,
            status: "skipped",
            action: "操作员停止派发下一件；本件从未启动",
          } : item);
          nextStatus = "stopped";
          currentAction = "当前件已结束；已停止派发后续商品";
        } else if (currentBatch.pauseAfterCurrent && nextPending) {
          nextStatus = "paused";
          currentAction = "当前件已安全结束；自动队列已暂停";
        } else if (nextPending) {
          nextExecution = newRun(nextPending.id);
          nextRunId = nextExecution.runId;
          nextStatus = "running";
          nextItems = nextItems.map((item) => item.id === nextPending.id ? {
            ...item,
            status: "running",
            action: "自动读取商品箱快照身份并逐字段编辑、只保存",
            startedAt: new Date().toISOString(),
          } : item);
          currentAction = `自动派发第 ${nextPending.ordinal} / ${currentBatch.maxItems} 件：逐字段编辑并只保存`;
        } else if (hasIssue) {
          nextStatus = "completed_with_issues";
        }

        return {
          nextState: {
            ...current,
            batches: current.batches.map((batch) => batch.id !== batchId ? batch : {
              ...batch,
              status: nextStatus,
              execution: nextExecution,
              pauseAfterCurrent: false,
              items: nextItems,
              updatedAt: formatTimestamp(),
            }),
            browser: current.browser.batchId === batchId && current.browser.boundRunId === runId ? {
              ...current.browser,
              status: nextStatus === "running" ? "active" : nextStatus,
              boundRunId: nextRunId,
              actionIndex: 0,
              currentAction,
              lastReadback: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
            } : current.browser,
          },
          result: { ok: true, nextRunId, nextDelay: RUN_STEP_MS },
        };
      });
      if (result?.nextRunId) scheduleRun(batchId, result.nextRunId, result.nextDelay);
    }, Math.max(100, delay));
    runTimersRef.current.set(timerKey, timer);
  }, [mutateLatest]);

  useEffect(() => {
    state.batches.forEach((batch) => {
      if (batch.status !== "running" || !batch.execution?.runId) return;
      const delay = Math.max(100, Number(batch.execution.deadlineAt || Date.now() + RUN_STEP_MS) - Date.now());
      scheduleRun(batch.id, batch.execution.runId, delay);
    });
  }, [scheduleRun, state.batches]);

  useEffect(() => () => {
    runTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    runTimersRef.current.clear();
  }, []);

  const createBatch = useCallback(async ({ template, intakeDescription, sourcePage, maxItems, scopeSnapshot }) => {
    return mutateLatest((latest) => {
      const templateSnapshot = buildTemplateSnapshot(template);
      const limit = Number(maxItems || 0);
      if (!Number.isInteger(limit) || limit < 2 || limit > prototypeProducts.length) {
        return { result: { ok: false, message: `当前原型可冻结 2–${prototypeProducts.length} 件商品箱现场样本` } };
      }
      if (!templateSnapshot || template?.status !== "ready") {
        return { result: { ok: false, message: "模板已变化或尚未就绪，请重新选择并批准整批" } };
      }
      const observedProducts = latest.products.filter((product) => product.queueStatus === "draft_box").slice(0, limit);
      if (observedProducts.length !== limit) {
        return { result: { ok: false, message: "店小秘现场快照数量不足，未创建批次" } };
      }

      const suffix = window.crypto?.randomUUID?.().slice(0, 8) || `${Date.now()}-${Math.floor(Math.random() * 10000)}`;
      const id = `EDT-${Date.now()}-${suffix}`;
      const now = formatTimestamp();
      const frozenScope = snapshotWithDigest({
        snapshotId: `DXM-SCOPE-${Date.now()}`,
        sourcePage: sourcePage || "速卖通 → 商品箱",
        sourceUrl: "/web/smt/smtProductList/draft",
        filterSummary: scopeSnapshot?.filterSummary || "店小秘当前筛选与排序",
        orderRule: "按店小秘当前可见顺序严格串行",
        orderedCount: limit,
        storeIdentity: "随每件商品箱身份快照读回，不在本系统选择",
        observedAt: new Date().toISOString(),
        productFingerprints: observedProducts.map((product, index) => prototypeDigest(`${index + 1}|${product.id}|${product.sku}`)),
      });
      const productIds = observedProducts.map((product) => product.id);
      const batch = {
        id,
        type: "edit",
        title: `批量编辑 · 商品箱快照 ${limit} 件`,
        storeId: LIVE_SCOPE_STORE.id,
        storeName: LIVE_SCOPE_STORE.name,
        intakeMode: "dxm_live_snapshot",
        intakeDescription: intakeDescription || `店小秘商品箱当前筛选范围 · 已冻结 ${limit} 件有序快照`,
        sourcePage: sourcePage || "速卖通 → 商品箱",
        scopeSnapshot: frozenScope,
        maxItems: limit,
        templateId: template.id,
        templateName: `${templateSnapshot.name} ${templateSnapshot.version}`,
        templateVersion: templateSnapshot.version,
        templateSnapshot,
        templateContentDigest: templateSnapshot.contentDigest,
        status: "ready",
        owner: "agent",
        approvedBy: "运营小秘 · 整批一次批准",
        approvedAt: now,
        approvalMode: "batch_once",
        autoDispatch: true,
        approvalHash: buildApprovalFingerprint({ storeId: LIVE_SCOPE_STORE.id, productIds, templateSnapshot }),
        createdAt: now,
        updatedAt: now,
        // A pre-save-only validation exception demonstrates the safe isolate-and-
        // continue branch without pretending a write occurred.
        demoValidationSkipAt: limit >= 5 ? 3 : null,
        items: observedProducts.map((product, index) => ({
          id: `${id}-I-${String(index + 1).padStart(2, "0")}`,
          ordinal: index + 1,
          productId: product.id,
          status: "pending",
          action: "已纳入不可变现场快照，等待自动派发",
          evidenceCount: 1,
          observedAt: frozenScope.observedAt,
          source: "dxm_live_scope_snapshot",
          identityFingerprint: frozenScope.productFingerprints[index],
        })),
      };
      return {
        nextState: { ...latest, batches: [batch, ...latest.batches] },
        result: { ok: true, batch },
      };
    });
  }, [mutateLatest]);

  const startBatch = useCallback(async (batchId) => {
    const result = await mutateLatest((latest) => {
      const batch = latest.batches.find((item) => item.id === batchId);
      const anotherRunning = latest.batches.find((item) => item.status === "running" && item.id !== batchId);
      if (anotherRunning) return { result: { ok: false, message: `${anotherRunning.id} 正在运行；全局并发固定为 1` } };
      if (!batch) return { result: { ok: false, message: "未找到批次" } };
      if (batch.type !== "edit") return { result: { ok: false, message: "当前原型只支持批量编辑" } };
      if (batch.status === "running") return { result: { ok: true, alreadyRunning: true, runId: batch.execution?.runId } };
      if (!["ready", "paused"].includes(batch.status)) {
        return { result: { ok: false, message: "当前批次不能启动或恢复自动队列" } };
      }
      if (batch.items.some((item) => item.status === "unknown")) {
        return { result: { ok: false, message: "批次存在 UNKNOWN，必须人工对账，禁止自动重试" } };
      }
      const nextItem = batch.items.find((item) => item.status === "pending");
      if (!nextItem) return { result: { ok: false, message: "没有等待派发的商品" } };

      const execution = newRun(nextItem.id);
      return {
        nextState: {
          ...latest,
          batches: latest.batches.map((item) => item.id !== batchId ? item : {
            ...item,
            status: "running",
            owner: "agent",
            execution,
            pauseAfterCurrent: false,
            stopAfterCurrent: false,
            items: item.items.map((batchItem) => batchItem.id === nextItem.id ? {
              ...batchItem,
              status: "running",
              action: "自动读取商品箱快照身份并逐字段编辑、只保存",
              startedAt: new Date().toISOString(),
            } : batchItem),
            updatedAt: formatTimestamp(),
          }),
          browser: {
            ...latest.browser,
            batchId,
            status: "active",
            owner: "agent",
            boundRunId: execution.runId,
            actionIndex: 0,
            currentAction: `自动派发第 ${nextItem.ordinal} / ${batch.maxItems} 件：逐字段编辑并只保存`,
            currentUrl: "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
          },
        },
        result: { ok: true, batchId, itemId: nextItem.id, runId: execution.runId },
      };
    });
    if (result?.ok && result.runId && !result.alreadyRunning) scheduleRun(batchId, result.runId);
    return result;
  }, [mutateLatest, scheduleRun]);

  // Kept only so the existing standalone browser HUD does not crash. It now
  // starts/resumes the already-approved automatic queue; it never captures or
  // approves one item.
  const captureNextItem = useCallback((batchId) => startBatch(batchId), [startBatch]);

  const requestPauseAfterCurrent = useCallback(async (batchId) => mutateLatest((current) => {
    const target = current.batches.find((batch) => batch.id === batchId);
    if (!target || isTerminalBatch(target.status)) return { result: { ok: false, message: "当前批次不可暂停" } };
    if (target.status === "paused") return { result: { ok: true, alreadyPaused: true } };
    if (target.status !== "running") {
      return {
        nextState: {
          ...current,
          batches: current.batches.map((batch) => batch.id === batchId ? { ...batch, status: "paused", updatedAt: formatTimestamp() } : batch),
        },
        result: { ok: true, paused: true },
      };
    }
    return {
      nextState: {
        ...current,
        batches: current.batches.map((batch) => batch.id === batchId ? {
          ...batch,
          pauseAfterCurrent: true,
          updatedAt: formatTimestamp(),
        } : batch),
        browser: current.browser.batchId === batchId ? {
          ...current.browser,
          currentAction: "已请求在当前件安全结束后暂停；不会派发下一件",
        } : current.browser,
      },
      result: { ok: true, pauseAfterCurrent: true },
    };
  }), [mutateLatest]);

  const requestStopAfterCurrent = useCallback(async (batchId) => mutateLatest((current) => {
    const target = current.batches.find((batch) => batch.id === batchId);
    if (!target || isTerminalBatch(target.status)) return { result: { ok: false, message: "当前批次不可停止派发" } };
    if (target.status === "running") {
      return {
        nextState: {
          ...current,
          batches: current.batches.map((batch) => batch.id === batchId ? {
            ...batch,
            stopAfterCurrent: true,
            pauseAfterCurrent: false,
            updatedAt: formatTimestamp(),
          } : batch),
          browser: current.browser.batchId === batchId ? {
            ...current.browser,
            currentAction: "已请求当前件结束后停止派发后续商品",
          } : current.browser,
        },
        result: { ok: true, stopAfterCurrent: true },
      };
    }
    const nextItems = target.items.map((item) => item.status === "pending" ? {
      ...item,
      status: "skipped",
      action: "操作员停止派发；本件从未启动",
    } : item);
    return {
      nextState: {
        ...current,
        batches: current.batches.map((batch) => batch.id === batchId ? {
          ...batch,
          status: "stopped",
          items: nextItems,
          updatedAt: formatTimestamp(),
        } : batch),
        browser: current.browser.batchId === batchId ? {
          ...current.browser,
          status: "stopped",
          currentAction: "已停止派发；未启动商品保持未写入",
        } : current.browser,
      },
      result: { ok: true, stopped: true },
    };
  }), [mutateLatest]);

  const triggerUnknownDemo = useCallback(async (batchId) => mutateLatest((current) => {
    const target = current.batches.find((batch) => batch.id === batchId);
    const runningItem = target?.items.find((item) => item.status === "running");
    if (!target || target.status !== "running" || !runningItem) {
      return { result: { ok: false, message: "只有当前件正在执行时才能演示 UNKNOWN" } };
    }
    return {
      nextState: {
        ...current,
        batches: current.batches.map((batch) => batch.id !== batchId ? batch : {
          ...batch,
          status: "needs_attention",
          execution: null,
          items: batch.items.map((item) => item.id === runningItem.id ? {
            ...item,
            status: "unknown",
            action: "已模拟保存回执丢失：写入边界未知，整批停止且禁止自动重试",
            evidenceCount: item.evidenceCount + 1,
          } : item),
          updatedAt: formatTimestamp(),
        }),
        browser: {
          ...current.browser,
          batchId,
          status: "needs_attention",
          boundRunId: null,
          currentAction: "UNKNOWN 演示：保存回执丢失，等待同 Session 人工对账",
          lastReadback: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        },
      },
      result: { ok: true, unknown: true, itemId: runningItem.id },
    };
  }), [mutateLatest]);

  const setBatchStatus = useCallback(async (batchId, status, owner) => mutateLatest((current) => {
    const target = current.batches.find((batch) => batch.id === batchId);
    if (!target) return { result: { ok: false, message: "未找到批次" } };
    if (isTerminalBatch(target.status)) return { result: { ok: false, message: "终态批次不可暂停或接管" } };
    const anotherRunning = current.batches.find((batch) => batch.status === "running" && batch.id !== batchId);
    if (anotherRunning) return { result: { ok: false, message: `${anotherRunning.id} 正在使用唯一浏览器` } };

    const interruptsMutation = status === "manual" && target.status === "running";
    const nextItems = target.items.map((item) => item.status === "running" && interruptsMutation ? {
      ...item,
      status: "unknown",
      action: "人工接管发生在可能写入阶段，结果未知；整批停止",
      evidenceCount: item.evidenceCount + 1,
    } : item);
    const hasUnknown = nextItems.some((item) => item.status === "unknown");
    const returningFromManual = status === "paused" && target.status === "manual";
    const nextStatus = hasUnknown ? "needs_attention" : returningFromManual ? "paused" : status;
    return {
      nextState: {
        ...current,
        batches: current.batches.map((batch) => batch.id !== batchId ? batch : {
          ...batch,
          status: nextStatus,
          owner: owner || batch.owner,
          execution: interruptsMutation ? null : batch.execution,
          items: nextItems,
          updatedAt: formatTimestamp(),
        }),
        browser: current.browser.batchId === batchId ? {
          ...current.browser,
          owner: owner || current.browser.owner,
          status: nextStatus,
          boundRunId: interruptsMutation ? null : current.browser.boundRunId,
          currentAction: hasUnknown
            ? "人工接管触发 UNKNOWN；整批停止并等待对账"
            : nextStatus === "manual"
              ? "人工已接管，Agent 停止点击"
              : nextStatus === "paused"
                ? "控制权已交还，自动队列保持暂停"
                : current.browser.currentAction,
        } : current.browser,
      },
      result: { ok: true, interrupted: interruptsMutation, status: nextStatus },
    };
  }), [mutateLatest]);

  const openBrowser = useCallback(async (batchId) => mutateLatest((current) => {
    const target = current.batches.find((batch) => batch.id === batchId);
    if (!target) return { result: { ok: false, message: "未找到批次" } };
    const runningBatch = current.batches.find((batch) => batch.status === "running");
    if (runningBatch && runningBatch.id !== batchId) {
      return { result: { ok: false, message: `${runningBatch.id} 正在使用唯一浏览器，不能重绑到其他批次` } };
    }
    const alreadyBound = current.browser.batchId === batchId;
    const currentAction = target.status === "running"
      ? current.browser.currentAction
      : target.status === "needs_attention"
        ? "结果未知，等待同 Session 人工对账"
        : target.status === "paused"
          ? "自动队列已暂停"
          : target.status === "manual"
            ? "人工已接管，Agent 停止点击"
            : target.status === "stopped"
              ? "已停止派发后续商品"
              : target.status === "completed" || target.status === "completed_with_issues"
                ? "本批次已完成"
                : "整批已批准，等待自动队列启动";
    return {
      nextState: {
        ...current,
        browser: {
          ...current.browser,
          batchId,
          status: target.status === "running" ? "active" : target.status,
          owner: target.owner || "agent",
          boundRunId: target.status === "running" ? target.execution?.runId || null : null,
          actionIndex: alreadyBound ? current.browser.actionIndex : 0,
          currentAction,
          currentUrl: "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
          lastReadback: alreadyBound ? current.browser.lastReadback : "尚未开始本批次原型演示",
        },
      },
      result: { ok: true, batchId },
    };
  }), [mutateLatest]);

  const cycleBrowserAction = useCallback(async () => {
    const editActions = [
      ["核对商品箱当前件与批次身份指纹", "https://www.dianxiaomi.com/web/smt/smtProductList/draft"],
      ["打开当前商品编辑页并核对模板快照", "https://www.dianxiaomi.com/web/smt/edit?step=fields"],
      ["逐字段填写、精确读回并只保存", "https://www.dianxiaomi.com/web/smt/edit?step=save"],
      ["核验保存结果与未发布状态", "https://www.dianxiaomi.com/web/smt/smtProductList/draft?step=readback"],
    ];
    return mutateLatest((current) => {
      const boundBatch = current.batches.find((batch) => batch.id === current.browser.batchId);
      if (!boundBatch || boundBatch.status !== "running" || boundBatch.owner !== "agent"
        || current.browser.boundRunId !== boundBatch.execution?.runId
        || !boundBatch.execution?.leaseExpiresAt
        || boundBatch.execution.leaseExpiresAt <= Date.now()) {
        return { result: { ok: false, message: "当前没有可推进的 Agent 批次" } };
      }
      const nextIndex = (current.browser.actionIndex + 1) % editActions.length;
      return {
        nextState: {
          ...current,
          browser: {
            ...current.browser,
            actionIndex: nextIndex,
            currentAction: editActions[nextIndex][0],
            currentUrl: editActions[nextIndex][1],
            lastReadback: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
          },
        },
        result: { ok: true },
      };
    });
  }, [mutateLatest]);

  const resolveUnknown = useCallback(async (batchId, itemId, outcome, attestation) => mutateLatest((current) => {
    const batch = current.batches.find((item) => item.id === batchId);
    const targetItem = batch?.items.find((item) => item.id === itemId);
    if (!batch || !targetItem || targetItem.status !== "unknown") {
      return { result: { ok: false, message: "未找到待对账商品" } };
    }
    if (!["confirmed_success", "confirmed_no_effect"].includes(outcome)) {
      return { result: { ok: false, message: "请选择明确的人工对账结果" } };
    }
    const hasBoundManualSession = current.browser.batchId === batchId
      && current.browser.owner === "manual"
      && batch.owner === "manual";
    const hasAttestation = attestation?.reviewed === true
      && attestation.browserSessionId === current.browser.sessionId;
    if (!hasBoundManualSession || !hasAttestation) {
      return { result: { ok: false, message: "必须先绑定同一可见 Session、人工接管并确认已核对现场" } };
    }
    const confirmedSuccess = outcome === "confirmed_success";
    const attestedAt = new Date().toISOString();
    const nextItems = batch.items.map((item) => item.id === itemId ? {
      ...item,
      status: confirmedSuccess ? "success" : "failed",
      action: confirmedSuccess ? "人工对账确认动作已生效；原批次封存" : "人工对账确认动作未生效；原批次封存",
      evidenceCount: item.evidenceCount + 2,
      reconciled: true,
      reconciledAt: attestedAt,
      reconciliationEvidence: {
        reviewed: true,
        browserSessionId: attestation.browserSessionId,
        attestedAt,
        outcome,
        reviewer: "运营小秘",
        reviewerIdentityId: "identity-approver-markes",
      },
    } : item.status === "pending" ? {
      ...item,
      status: "skipped",
      action: "原批次因 UNKNOWN 已封存；未自动重试",
    } : item);
    return {
      nextState: {
        ...current,
        batches: current.batches.map((item) => item.id === batchId ? {
          ...item,
          status: "completed_with_issues",
          owner: "agent",
          execution: null,
          items: nextItems,
          updatedAt: formatTimestamp(),
        } : item),
        browser: current.browser.batchId === batchId ? {
          ...current.browser,
          status: "completed_with_issues",
          owner: "agent",
          boundRunId: null,
          currentAction: "人工对账已记录；原批次封存，未知写入未自动重试",
          lastReadback: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        } : current.browser,
      },
      result: { ok: true, message: "人工对账结果已记录；未知写入未被自动重试", status: "completed_with_issues" },
    };
  }), [mutateLatest]);

  const value = useMemo(() => ({
    ...state,
    stores,
    productById: (id) => productById(state.products, id),
    batchById: (id) => state.batches.find((batch) => batch.id === id),
    statsFor: itemStats,
    createBatch,
    captureNextItem,
    setBatchStatus,
    startBatch,
    requestPauseAfterCurrent,
    requestStopAfterCurrent,
    triggerUnknownDemo,
    openBrowser,
    cycleBrowserAction,
    resolveUnknown,
  }), [
    captureNextItem,
    createBatch,
    cycleBrowserAction,
    openBrowser,
    requestPauseAfterCurrent,
    requestStopAfterCurrent,
    resolveUnknown,
    setBatchStatus,
    startBatch,
    state,
    triggerUnknownDemo,
  ]);

  return <BatchPrototypeContext.Provider value={value}>{children}</BatchPrototypeContext.Provider>;
}

export function useBatchPrototype() {
  const context = useContext(BatchPrototypeContext);
  if (!context) throw new Error("useBatchPrototype must be used inside BatchPrototypeProvider");
  return context;
}

export function batchTypeLabel() {
  return "批量编辑商品";
}

export function batchStatusLabel(status) {
  return ({
    ready: "整批已批准",
    awaiting_approval: "等待批次批准",
    running: "自动执行中",
    paused: "当前件后已暂停",
    manual: "人工接管",
    needs_attention: "需人工对账",
    stopped: "已停止派发",
    completed: "已完成",
    completed_with_issues: "已封存（含异常）",
    failed: "已失败",
  })[status] || status;
}

export function itemStatusLabel(status) {
  return ({
    success: "成功",
    running: "当前执行",
    awaiting_approval: "等待批次批准",
    pending: "等待自动派发",
    failed: "失败",
    unknown: "UNKNOWN",
    skipped: "已隔离 / 未派发",
  })[status] || status;
}
