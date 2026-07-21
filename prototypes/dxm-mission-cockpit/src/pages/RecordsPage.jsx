import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  ClockIcon,
  FileMagnifyingGlassIcon,
  FilesIcon,
  FunnelIcon,
  MagnifyingGlassIcon,
  ShieldCheckIcon,
  StorefrontIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";

const statusMeta = {
  completed: { label: "已完成", tone: "success" },
  verified: { label: "已确认", tone: "success" },
  waiting: { label: "等待处理", tone: "warning" },
  open: { label: "需处理", tone: "warning" },
  blocked: { label: "已阻断", tone: "warning" },
  unknown: { label: "需人工对账", tone: "warning" },
  running: { label: "进行中", tone: "info" },
};

function handleTablistKeyDown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = [...event.currentTarget.querySelectorAll('[role="tab"]:not(:disabled)')];
  if (!tabs.length) return;
  const currentIndex = Math.max(0, tabs.indexOf(document.activeElement));
  const nextIndex = event.key === "Home"
    ? 0
    : event.key === "End"
      ? tabs.length - 1
      : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault();
  tabs[nextIndex].focus();
  tabs[nextIndex].click();
}

function taskStatus(value) {
  const normalized = String(value ?? "waiting").toLowerCase();
  if (["completed", "complete", "success", "passed", "done"].includes(normalized)) return "completed";
  if (["running", "processing", "active", "editing", "verifying", "validating", "manual"].includes(normalized)) return "running";
  if (["failed", "blocked", "stopped", "error"].includes(normalized)) return "blocked";
  if (["unknown", "dispatching"].includes(normalized)) return "unknown";
  return "waiting";
}

function normalizeTask(task, index) {
  const fallback = {};
  const status = taskStatus(task?.status ?? fallback.status);
  return {
    id: task?.id ?? task?.task_id ?? fallback.id,
    title: task?.title ?? task?.name ?? fallback.title,
    productTitle: task?.productTitle ?? task?.product_title ?? task?.payload?.product_title ?? fallback.productTitle,
    store: task?.store ?? task?.store_name ?? task?.payload?.store_name ?? fallback.store,
    stage: task?.stage ?? task?.current_step_name ?? (task?.mode === "claim_only" ? "待认领入箱" : fallback.stage),
    status,
    updatedAt: task?.updatedAt ?? task?.updated_at ?? task?.created_at ?? fallback.updatedAt,
    result: task?.result ?? task?.summary ?? task?.error_message ?? fallback.result,
    operator: task?.operator ?? task?.approved_by ?? fallback.operator,
    raw: task,
  };
}

function normalizeEvidence(evidence, index, taskLookup) {
  const fallback = {};
  const task = taskLookup.get(evidence?.taskId ?? evidence?.task_id);
  const rawStatus = String(evidence?.status ?? fallback.status ?? "waiting").toLowerCase();
  return {
    id: evidence?.id ?? evidence?.evidence_id ?? fallback.id ?? `evidence-${index}`,
    taskId: evidence?.taskId ?? evidence?.task_id ?? fallback.taskId ?? "—",
    title: evidence?.title ?? evidence?.name ?? fallback.title ?? "未命名证据",
    type: evidence?.type ?? evidence?.evidence_type ?? fallback.type ?? "未分类",
    status: ["verified", "passed", "success", "completed"].includes(rawStatus) ? "verified" : rawStatus === "unknown" ? "unknown" : "waiting",
    store: evidence?.store ?? evidence?.store_name ?? task?.store ?? fallback.store ?? "—",
    time: evidence?.time ?? evidence?.capturedAt ?? evidence?.captured_at ?? evidence?.createdAt ?? evidence?.created_at ?? fallback.time ?? "—",
    detail: evidence?.detail ?? evidence?.summary ?? evidence?.result ?? fallback.detail ?? "暂无补充说明",
    source: evidence?.source ?? evidence?.skill ?? evidence?.skill_id ?? fallback.source ?? "未提供来源",
    raw: evidence,
  };
}

function normalizeIssue(issue, index, taskLookup) {
  const fallback = {};
  const task = taskLookup.get(issue?.taskId ?? issue?.task_id);
  const rawStatus = String(issue?.status ?? fallback.status ?? "open").toLowerCase();
  return {
    id: issue?.id ?? issue?.issue_id ?? fallback.id ?? `issue-${index}`,
    taskId: issue?.taskId ?? issue?.task_id ?? fallback.taskId ?? "—",
    title: issue?.title ?? issue?.human_title ?? fallback.title ?? "未命名问题",
    status: ["resolved", "closed", "completed"].includes(rawStatus) ? "completed" : rawStatus === "unknown" ? "unknown" : rawStatus === "blocked" ? "blocked" : "open",
    severity: issue?.severity ?? issue?.risk_level ?? fallback.severity ?? "medium",
    store: issue?.store ?? issue?.store_name ?? task?.store ?? fallback.store ?? "—",
    time: issue?.time ?? issue?.createdAt ?? issue?.created_at ?? fallback.time ?? "—",
    step: issue?.step ?? issue?.fieldDomain ?? issue?.field_domain ?? task?.stage ?? fallback.step ?? "—",
    detail: issue?.detail ?? issue?.summary ?? issue?.message ?? fallback.detail ?? "暂无补充说明",
    suggestion: issue?.suggestion ?? issue?.suggestedAction ?? issue?.next_action ?? fallback.suggestion ?? "请人工核对证据后处理",
    raw: issue,
  };
}

const ui = {
  header: { display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 18 },
  headerCopy: { margin: "5px 0 0", color: "var(--muted)", fontSize: 13 },
  tabs: { display: "flex", gap: 4, padding: 4, width: "max-content", border: "1px solid var(--border)", borderRadius: 8, background: "#f5f7fa" },
  tab: { minHeight: 36, padding: "0 14px", border: 0, borderRadius: 6, color: "#5c697d", background: "transparent", display: "inline-flex", alignItems: "center", gap: 7, cursor: "pointer", fontWeight: 650 },
  toolbar: { padding: 14, display: "grid", gridTemplateColumns: "minmax(260px, 1fr) 170px 220px auto", gap: 10, alignItems: "center" },
  inputWrap: { minHeight: 42, padding: "0 12px", border: "1px solid var(--border)", borderRadius: 7, background: "#fff", display: "flex", alignItems: "center", gap: 9 },
  input: { width: "100%", padding: 0, border: 0, outline: 0, color: "var(--ink)", background: "transparent", fontSize: 13 },
  select: { minHeight: 42, padding: "0 11px", border: "1px solid var(--border)", borderRadius: 7, color: "#415168", background: "#fff", font: "inherit" },
  table: { overflow: "hidden" },
  tableHead: { minHeight: 42, padding: "0 16px", borderBottom: "1px solid var(--border)", color: "#7b8798", background: "#f8fafc", display: "grid", alignItems: "center", gap: 12, fontSize: 11.5, fontWeight: 700 },
  taskColumns: { gridTemplateColumns: "minmax(260px,1.5fr) minmax(160px,.8fr) 125px 115px 128px" },
  evidenceColumns: { gridTemplateColumns: "minmax(260px,1.45fr) 140px minmax(190px,1fr) 130px 128px" },
  issueColumns: { gridTemplateColumns: "minmax(260px,1.45fr) 130px minmax(230px,1fr) 125px 128px" },
  row: { width: "100%", minHeight: 72, padding: "11px 16px", border: 0, borderBottom: "1px solid #edf1f5", color: "var(--ink)", background: "#fff", display: "grid", alignItems: "center", gap: 12, textAlign: "left", cursor: "pointer" },
  primaryText: { display: "grid", gap: 4, minWidth: 0 },
  title: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13.5 },
  meta: { color: "var(--muted)", fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  empty: { minHeight: 230, display: "grid", placeItems: "center", color: "var(--muted)", fontSize: 13 },
  drawerContent: { minHeight: 0, overflow: "auto", padding: 20, display: "grid", alignContent: "start", gap: 16 },
  detailGrid: { display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 },
  detailField: { padding: 11, border: "1px solid #e1e7ef", borderRadius: 7, background: "#f8fafc", display: "grid", gap: 5 },
  detailLabel: { color: "#8490a1", fontSize: 10.5, fontWeight: 700 },
  detailValue: { color: "#26364d", fontSize: 12.5, lineHeight: 1.55, overflowWrap: "anywhere" },
  note: { padding: 13, border: "1px solid #dbe4ef", borderRadius: 8, background: "#f8fafc", display: "grid", gap: 6 },
};

function SafetyStrip() {
  return (
    <section className="safety-banner" aria-label="历史记录安全边界" data-testid="records-safety-boundary">
      <div className="safety-banner__message">
        <ShieldCheckIcon size={24} weight="fill" aria-hidden="true" />
        <strong>记录真实发生的每一步</strong>
        <span className="safety-banner__divider" aria-hidden="true" />
        <span>保存成功和未发布必须分别有证据；结果不确定时只能人工对账。</span>
      </div>
      <div className="safety-banner__mode"><ShieldCheckIcon size={18} aria-hidden="true" />证据模式</div>
    </section>
  );
}

function StatusBadge({ status }) {
  const meta = statusMeta[status] ?? statusMeta.waiting;
  return <span className={`status-badge status-badge--${meta.tone}`}>{meta.label}</span>;
}

function DetailField({ label, value }) {
  return <div style={ui.detailField}><span style={ui.detailLabel}>{label}</span><strong style={ui.detailValue}>{value || "—"}</strong></div>;
}

export function RecordsPage({ initialTab = "tasks", tasks = [], evidences = [], issues = [], onOpenTask, notify }) {
  const [activeTab, setActiveTab] = useState(() => ["tasks", "evidences", "issues"].includes(initialTab) ? initialTab : "tasks");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [storeFilter, setStoreFilter] = useState("all");
  const [drawer, setDrawer] = useState(null);
  const [seenIssues, setSeenIssues] = useState(() => new Set());
  const drawerRef = useRef(null);
  const drawerCloseRef = useRef(null);
  const drawerTriggerRef = useRef(null);

  const taskRows = useMemo(() => tasks.map(normalizeTask), [tasks]);
  const taskLookup = useMemo(() => new Map(taskRows.map((task) => [task.id, task])), [taskRows]);
  const evidenceRows = useMemo(() => evidences.map((item, index) => normalizeEvidence(item, index, taskLookup)), [evidences, taskLookup]);
  const issueRows = useMemo(() => issues.map((item, index) => normalizeIssue(item, index, taskLookup)), [issues, taskLookup]);

  useEffect(() => {
    if (["tasks", "evidences", "issues"].includes(initialTab)) changeTab(initialTab);
  }, [initialTab]);

  const activeRows = activeTab === "tasks" ? taskRows : activeTab === "evidences" ? evidenceRows : issueRows;
  const stores = useMemo(() => Array.from(new Set([...taskRows, ...evidenceRows, ...issueRows].map((item) => item.store).filter(Boolean))), [taskRows, evidenceRows, issueRows]);

  const filteredRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return activeRows.filter((item) => {
      const haystack = `${item.title} ${item.id} ${item.taskId ?? ""} ${item.store ?? ""} ${item.productTitle ?? ""} ${item.detail ?? ""}`.toLowerCase();
      const matchesQuery = !normalizedQuery || haystack.includes(normalizedQuery);
      const matchesStatus = statusFilter === "all" || item.status === statusFilter;
      const matchesStore = storeFilter === "all" || item.store === storeFilter;
      return matchesQuery && matchesStatus && matchesStore;
    });
  }, [activeRows, query, statusFilter, storeFilter]);

  const changeTab = (tab) => {
    setActiveTab(tab);
    setStatusFilter("all");
    setQuery("");
  };

  const openDetail = (kind, item) => {
    drawerTriggerRef.current = document.activeElement;
    setDrawer({ kind, item });
  };
  const closeDrawer = () => {
    setDrawer(null);
    window.setTimeout(() => drawerTriggerRef.current?.focus?.(), 0);
  };

  const locateEvidence = () => {
    if (!drawer?.item?.id) return;
    const evidenceId = drawer.item.id;
    setActiveTab("evidences");
    setStatusFilter("all");
    setStoreFilter("all");
    setQuery(evidenceId);
    closeDrawer();
    notify?.("已在保存证据列表中定位该记录", "info");
  };

  useEffect(() => {
    if (!drawer) return undefined;
    drawerCloseRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDrawer();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = [...drawerRef.current.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter((node) => !node.disabled);
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawer]);

  const markIssueSeen = (issue) => {
    setSeenIssues((current) => new Set([...current, issue.id]));
    notify?.("已记录人工查看；问题状态不会被自动改成已解决");
  };

  const tabs = [
    { id: "tasks", label: "任务记录", count: taskRows.length, icon: ClockIcon },
    { id: "evidences", label: "保存证据", count: evidenceRows.length, icon: FilesIcon },
    { id: "issues", label: "问题处理", count: issueRows.length, icon: WarningCircleIcon },
  ];

  const currentColumns = activeTab === "tasks" ? ui.taskColumns : activeTab === "evidences" ? ui.evidenceColumns : ui.issueColumns;

  return (
    <div className="secondary-view" data-testid="records-page">
      <SafetyStrip />

      <header style={ui.header}>
        <div>
          <div className="page-heading" style={{ height: "auto", minHeight: 64 }}><h1>历史</h1><span className="status-badge status-badge--info">可审计</span></div>
          <p style={ui.headerCopy}>按任务回看结果、保存证据和问题处理，不用工程术语解释运营事实。</p>
        </div>
        <div style={ui.tabs} role="tablist" aria-label="历史记录类型" data-testid="records-tabs" onKeyDown={handleTablistKeyDown}>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const selected = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={selected}
                tabIndex={selected ? 0 : -1}
                style={{ ...ui.tab, color: selected ? "#075ccf" : "#5c697d", background: selected ? "#fff" : "transparent", boxShadow: selected ? "0 1px 2px rgba(15,23,42,.08)" : "none" }}
                onClick={() => changeTab(tab.id)}
                data-testid={`records-tab-${tab.id}`}
              >
                <Icon size={17} weight={selected ? "fill" : "regular"} aria-hidden="true" />{tab.label}<span style={{ color: "#8a96a8", fontSize: 11 }}>{tab.count}</span>
              </button>
            );
          })}
        </div>
      </header>

      <section className="card" style={ui.toolbar} aria-label="历史记录筛选" data-testid="records-filter-bar">
        <label style={ui.inputWrap}>
          <MagnifyingGlassIcon size={18} color="#758398" aria-hidden="true" />
          <span className="sr-only">搜索历史记录</span>
          <input style={ui.input} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、商品、证据或问题" aria-label="搜索任务、商品、证据或问题" data-testid="records-search-input" />
        </label>
        <label style={{ display: "grid" }}><span className="sr-only">按状态筛选</span>
          <select style={ui.select} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="按状态筛选" data-testid="records-status-filter">
            <option value="all">全部状态</option>
            <option value="completed">已完成</option>
            <option value="verified">已确认</option>
            <option value="running">进行中</option>
            <option value="waiting">等待处理</option>
            <option value="open">需处理</option>
            <option value="blocked">已阻断</option>
            <option value="unknown">需人工对账</option>
          </select>
        </label>
        <label style={{ display: "grid" }}><span className="sr-only">按店铺筛选</span>
          <select style={ui.select} value={storeFilter} onChange={(event) => setStoreFilter(event.target.value)} aria-label="按店铺筛选" data-testid="records-store-filter">
            <option value="all">全部店铺</option>
            {stores.map((store) => <option value={store} key={store}>{store}</option>)}
          </select>
        </label>
        <span style={{ color: "var(--muted)", fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}><FunnelIcon size={16} aria-hidden="true" />{filteredRows.length} 条</span>
      </section>

      <section className="card" style={ui.table} aria-label={tabs.find((tab) => tab.id === activeTab)?.label} data-testid={`records-${activeTab}-table`}>
        <div style={{ ...ui.tableHead, ...currentColumns }} aria-hidden="true">
          {activeTab === "tasks" && <><span>任务与商品</span><span>店铺</span><span>当前步骤</span><span>状态</span><span>最近更新</span></>}
          {activeTab === "evidences" && <><span>证据</span><span>类型</span><span>店铺</span><span>状态</span><span>生成时间</span></>}
          {activeTab === "issues" && <><span>问题</span><span>发生步骤</span><span>处理建议</span><span>状态</span><span>发生时间</span></>}
        </div>

        {filteredRows.map((item) => {
          const kind = activeTab === "tasks" ? "task" : activeTab === "evidences" ? "evidence" : "issue";
          return (
            <button
              key={item.id}
              type="button"
              style={{ ...ui.row, ...currentColumns }}
              onClick={() => openDetail(kind, item)}
              aria-label={`查看${item.title}详情`}
              data-testid={`${kind}-record-${item.id}`}
            >
              {activeTab === "tasks" && <>
                <span style={ui.primaryText}><strong style={ui.title}>{item.title}</strong><small style={ui.meta}>{item.productTitle} · #{item.id}</small></span>
                <span style={ui.meta}>{item.store}</span><span style={{ fontSize: 12.5 }}>{item.stage}</span><StatusBadge status={item.status} /><span style={ui.meta}>{item.updatedAt}</span>
              </>}
              {activeTab === "evidences" && <>
                <span style={ui.primaryText}><strong style={ui.title}>{item.title}</strong><small style={ui.meta}>{item.source} · 任务 #{item.taskId}</small></span>
                <span style={{ fontSize: 12.5 }}>{item.type}</span><span style={ui.meta}>{item.store}</span><StatusBadge status={item.status} /><span style={ui.meta}>{item.time}</span>
              </>}
              {activeTab === "issues" && <>
                <span style={ui.primaryText}><strong style={ui.title}>{item.title}</strong><small style={ui.meta}>任务 #{item.taskId} · {item.store}</small></span>
                <span style={{ fontSize: 12.5 }}>{item.step}</span><span style={ui.meta}>{item.suggestion}</span><StatusBadge status={seenIssues.has(item.id) ? "waiting" : item.status} /><span style={ui.meta}>{item.time}</span>
              </>}
            </button>
          );
        })}
        {!filteredRows.length && (
          <div style={ui.empty} data-testid="records-no-results">
            {activeRows.length
              ? "没有符合当前筛选条件的记录。"
              : activeTab === "evidences"
                ? "当前没有保存证据；系统不会用示例记录替代真实证据。"
                : activeTab === "issues"
                  ? "当前没有问题记录。"
                  : "当前没有任务记录。"}
          </div>
        )}
      </section>

      {drawer && (
        <div className="drawer-layer" role="presentation" data-testid="record-detail-drawer-layer">
          <button className="drawer-backdrop" type="button" aria-label="关闭记录详情" onClick={closeDrawer} />
          <aside ref={drawerRef} className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="record-detail-title" data-testid="record-detail-drawer">
            <header className="drawer-header">
              <div><span>{drawer.kind === "task" ? "任务记录" : drawer.kind === "evidence" ? "保存证据" : "问题处理"}</span><h2 id="record-detail-title">{drawer.item.title}</h2></div>
              <button ref={drawerCloseRef} type="button" className="icon-button" onClick={closeDrawer} aria-label="关闭"><XIcon size={18} /></button>
            </header>

            <div className="drawer-boundary">
              {drawer.kind === "issue" ? <WarningCircleIcon size={22} color="var(--warning)" weight="fill" aria-hidden="true" /> : <ShieldCheckIcon size={22} weight="fill" aria-hidden="true" />}
              <div>
                <strong>{drawer.kind === "issue" ? "问题已阻断后续动作" : "该记录来自当前任务证据链"}</strong>
                <span>{drawer.kind === "issue" ? "处理问题不会自动重试真实动作；结果未知时必须人工对账。" : "保存成功与未发布证明分别记录，不能互相替代。"}</span>
              </div>
            </div>

            <div style={ui.drawerContent}>
              <div style={ui.detailGrid}>
                <DetailField label={drawer.kind === "task" ? "任务编号" : "关联任务"} value={drawer.kind === "task" ? `#${drawer.item.id}` : `#${drawer.item.taskId}`} />
                <DetailField label="当前状态" value={(statusMeta[drawer.item.status] ?? statusMeta.waiting).label} />
                <DetailField label="目标店铺" value={drawer.item.store} />
                <DetailField label="发生时间" value={drawer.item.updatedAt ?? drawer.item.time} />
              </div>

              {drawer.kind === "task" && <>
                <DetailField label="商品" value={drawer.item.productTitle} />
                <DetailField label="当前步骤" value={drawer.item.stage} />
                <DetailField label="任务结果" value={drawer.item.result} />
                <DetailField label="当前操作者" value={drawer.item.operator} />
              </>}

              {drawer.kind === "evidence" && <>
                <DetailField label="证据类型" value={drawer.item.type} />
                <DetailField label="证据来源" value={drawer.item.source} />
                <div style={ui.note}><strong style={{ fontSize: 12.5 }}>证据说明</strong><span style={{ color: "#64748b", fontSize: 12, lineHeight: 1.65 }}>{drawer.item.detail}</span></div>
              </>}

              {drawer.kind === "issue" && <>
                <DetailField label="发生步骤" value={drawer.item.step} />
                <div style={{ ...ui.note, borderColor: "#f1d3a7", background: "#fff8eb" }}><strong style={{ color: "#92580a", fontSize: 12.5 }}>发生了什么</strong><span style={{ color: "#7c5a2a", fontSize: 12, lineHeight: 1.65 }}>{drawer.item.detail}</span></div>
                <div style={ui.note}><strong style={{ fontSize: 12.5 }}>建议处理</strong><span style={{ color: "#64748b", fontSize: 12, lineHeight: 1.65 }}>{drawer.item.suggestion}</span></div>
              </>}
            </div>

            <footer className="drawer-footer">
              <button type="button" className="secondary-button" onClick={closeDrawer} data-testid="close-record-detail">关闭</button>
              {drawer.kind === "task" && <button type="button" className="primary-button" onClick={() => { onOpenTask?.(drawer.item.raw ?? drawer.item); notify?.("已打开任务上下文"); }} data-testid="open-record-task"><ArrowSquareOutIcon size={18} />打开任务</button>}
              {drawer.kind === "evidence" && <button type="button" className="primary-button" onClick={locateEvidence} data-testid="locate-record-evidence"><FileMagnifyingGlassIcon size={18} />定位证据</button>}
              {drawer.kind === "issue" && <button type="button" className="primary-button" onClick={() => markIssueSeen(drawer.item)} data-testid="acknowledge-record-issue"><CheckCircleIcon size={18} />标记已查看</button>}
            </footer>
          </aside>
        </div>
      )}
    </div>
  );
}

export default RecordsPage;
