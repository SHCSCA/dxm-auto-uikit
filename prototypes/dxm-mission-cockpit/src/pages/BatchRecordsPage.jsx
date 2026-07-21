import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRightIcon,
  ArrowSquareOutIcon,
  BrowserIcon,
  CheckCircleIcon,
  CubeIcon,
  FileTextIcon,
  HandPalmIcon,
  MagnifyingGlassIcon,
  PackageIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { batchStatusLabel, batchTypeLabel, itemStatusLabel, useBatchPrototype } from "../state/BatchPrototypeContext.jsx";

const tabs = [
  ["batches", "批次"],
  ["items", "商品子任务"],
  ["evidence", "逐项证据"],
  ["issues", "问题与 UNKNOWN"],
];

function handleTabs(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const controls = [...event.currentTarget.querySelectorAll('[role="tab"]')];
  const index = controls.indexOf(document.activeElement);
  const next = event.key === "Home" ? 0 : event.key === "End" ? controls.length - 1 : (Math.max(index, 0) + (event.key === "ArrowRight" ? 1 : -1) + controls.length) % controls.length;
  event.preventDefault();
  controls[next]?.focus();
  controls[next]?.click();
}

function evidenceEntries(item) {
  const normalEntries = ["模板内容快照", "保存结果页面读回", "未发布状态证明"];
  const hasException = ["unknown", "failed", "skipped"].includes(item.status);
  const evidenceMetadata = {
    "模板内容快照": ["模板快照", "当前模板版本快照"],
    "保存结果页面读回": ["页面读回", "可见浏览器 Session"],
    "未发布状态证明": ["安全证明", "商品箱状态读回"],
    "异常与停止记录": ["异常记录", "批次安全状态机"],
    "人工对账补充证明": ["人工确认", "人工对账登记"],
  };
  const reconciliation = item.reconciliationEvidence;
  const manualEntryCount = reconciliation ? Math.min(2, item.evidenceCount) : 0;
  const baseEntryCount = Math.max(0, item.evidenceCount - manualEntryCount);
  const baseEntries = Array.from({ length: baseEntryCount }, (_, index) => {
    const isLastException = hasException && index === baseEntryCount - 1;
    const name = isLastException ? "异常与停止记录" : normalEntries[index % normalEntries.length];
    return {
      id: `${item.id}-EV-${String(index + 1).padStart(2, "0")}`,
      name,
      state: item.status === "unknown" && index === item.evidenceCount - 1 ? "未闭合" : "已记录",
      capturedAt: item.batch.updatedAt,
      type: (evidenceMetadata[name] || ["原型记录"])[0],
      source: (evidenceMetadata[name] || [null, "本地原型状态"])[1],
      note: "当前为本地交互原型元数据，不是店小秘真实截图或 DOM 读回。正式接入后，此处必须链接不可变证据载荷与摘要。",
    };
  });
  if (!reconciliation) return baseEntries;
  const capturedAt = new Date(reconciliation.attestedAt).toLocaleString("zh-CN", { hour12: false });
  const manualEntries = [
    {
      name: "可见 Session 人工核对",
      type: "人工 attestation",
      note: `已核对 Session ${reconciliation.browserSessionId}。当前为本地原型 attestation；正式接入后必须链接不可变现场证据与摘要。`,
    },
    {
      name: "人工对账结论",
      type: "人工决策",
      note: `人工结论：${reconciliation.outcome === "confirmed_success" ? "已生效" : "未生效"}。未知写入未被自动重试。`,
    },
  ].slice(0, manualEntryCount).map((entry, index) => ({
    ...entry,
    id: `${item.id}-EV-${String(baseEntryCount + index + 1).padStart(2, "0")}`,
    state: "已记录",
    capturedAt,
    source: `${reconciliation.reviewer} · ${reconciliation.reviewerIdentityId} · Session ${reconciliation.browserSessionId}`,
  }));
  return [...baseEntries, ...manualEntries];
}

function batchStatusTone(status) {
  if (["needs_attention", "completed_with_issues", "failed"].includes(status)) return "warning";
  if (status === "completed") return "success";
  return "info";
}

function resultSummary(stats) {
  return `${stats.success} 成功 · ${stats.failed} 失败 · ${stats.skipped} 跳过 · ${stats.pending} 等待 · ${stats.unknown} UNKNOWN`;
}

function browserWindowUrl(batchId) {
  return `${window.location.origin}${window.location.pathname}#/browser/live?batch=${encodeURIComponent(batchId)}`;
}

export default function BatchRecordsPage({ notify }) {
  const navigate = useNavigate();
  const { batches, browser, productById, statsFor, openBrowser, setBatchStatus, resolveUnknown } = useBatchPrototype();
  const initial = new URLSearchParams(window.location.hash.split("?")[1] || "").get("tab");
  const [tab, setTab] = useState(tabs.some(([id]) => id === initial) ? initial : "batches");
  const [query, setQuery] = useState("");
  const [issueBusyId, setIssueBusyId] = useState("");
  const [attestations, setAttestations] = useState({});
  const editBatches = batches.filter((batch) => batch.type === "edit");
  const boundBatchOwner = editBatches.find((batch) => batch.id === browser.batchId)?.owner;
  useEffect(() => {
    setAttestations({});
  }, [boundBatchOwner, browser.batchId, browser.owner, browser.sessionId]);
  const search = query.trim().toLowerCase();
  const items = useMemo(() => editBatches.flatMap((batch) => batch.items.map((item) => ({ ...item, batch, product: productById(item.productId) }))), [editBatches, productById]);
  const filteredBatches = editBatches.filter((batch) => `${batch.id} ${batch.title} ${batch.storeName}`.toLowerCase().includes(search));
  const filteredItems = items.filter((item) => `${item.id} ${item.product?.name} ${item.product?.sku} ${item.batch.id}`.toLowerCase().includes(search));
  const issues = filteredItems.filter((item) => item.status === "unknown" || (item.status === "failed" && !item.reconciled));
  const prepareVisibleReview = async (item) => {
    const opened = window.open(browserWindowUrl(item.batch.id), "dxm-visible-browser", "popup=yes,width=1280,height=850,left=80,top=60");
    if (!opened) {
      notify?.("浏览器阻止了可见现场窗口；请允许弹窗后再进行人工对账", "warning");
      return;
    }
    setIssueBusyId(item.id);
    try {
      const binding = await openBrowser(item.batch.id);
      if (!binding?.ok) {
        opened.close();
        notify?.(binding?.message || "当前无法绑定可见浏览器", "warning");
        return;
      }
      const takeover = await setBatchStatus(item.batch.id, "manual", "manual");
      if (!takeover?.ok) {
        notify?.(takeover?.message || "当前无法完成人工接管", "warning");
        return;
      }
      opened.focus();
      setAttestations({});
      notify?.("可见 Session 已绑定并交由人工；请在窗口中核对后完成确认");
    } finally {
      setIssueBusyId("");
    }
  };

  const reconcile = async (item, outcome) => {
    const attestation = attestations[item.id];
    const reviewReady = browser.batchId === item.batch.id && browser.owner === "manual" && item.batch.owner === "manual";
    const reviewedCurrentSession = reviewReady && attestation?.reviewed && attestation.browserSessionId === browser.sessionId;
    if (!reviewedCurrentSession) {
      notify?.("请先在当前可见 Session 完成人工核对并勾选确认", "warning");
      return;
    }
    setIssueBusyId(item.id);
    try {
      const result = await resolveUnknown(item.batch.id, item.id, outcome, {
        reviewed: true,
        browserSessionId: browser.sessionId,
      });
      notify?.(result?.message, result?.ok ? undefined : "warning");
      if (result?.ok) setAttestations({});
    } finally {
      setIssueBusyId("");
    }
  };

  return (
    <div className="batch-page batch-records" data-testid="batch-records-page">
      <section className="batch-boundary"><ShieldCheckIcon size={22} weight="fill" /><div><strong>批次结果不能掩盖单商品事实</strong><span>模板快照、保存回读、未发布证明与异常按批次 → 商品 → 阶段分层记录；UNKNOWN 不会显示为成功。</span></div><span className="batch-boundary__pill">可追溯</span></section>
      <header className="batch-page__header"><div><span className="batch-eyebrow"><FileTextIcon size={17} />记录与问题</span><h1>批量编辑执行记录</h1><p>整批只批准一次，后台自动生成并串行执行 single_save 子任务；正常成功自动继续，异常可下钻到证据。</p></div><label className="batch-search batch-search--header"><MagnifyingGlassIcon size={18} /><span className="sr-only">搜索记录</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索批次、已读回商品或 SKU" /></label></header>
      <div className="records-tabs" role="tablist" aria-label="记录类型" onKeyDown={handleTabs}>{tabs.map(([id, label]) => <button type="button" role="tab" aria-selected={tab === id} tabIndex={tab === id ? 0 : -1} className={tab === id ? "is-active" : ""} key={id} onClick={() => setTab(id)}>{label}{id === "issues" && issues.length > 0 ? <span>{issues.length}</span> : null}</button>)}</div>

      {tab === "batches" && <section className="records-panel"><div className="batch-section__head"><div><span className="batch-eyebrow"><CubeIcon size={16} />编辑批次层</span><h2>批量编辑总览</h2></div><span>{filteredBatches.length} 个结果</span></div><div className="batch-table-wrap"><table className="batch-table"><thead><tr><th>批次</th><th>店小秘现场来源</th><th>商品结果</th><th>整批授权摘要</th><th>状态</th><th>操作</th></tr></thead><tbody>{filteredBatches.map((batch) => { const stats = statsFor(batch); return <tr key={batch.id}><td><strong>{batch.title}</strong><small className="cell-subtitle">{batch.id}</small></td><td><span className="flow-chip flow-chip--edit">{batchTypeLabel(batch.type)}</span><small className="cell-subtitle">{batch.storeName}</small></td><td>{resultSummary(stats)}</td><td><code>{batch.approvalHash}</code></td><td><span className={`batch-status is-${batchStatusTone(batch.status)}`}>{batchStatusLabel(batch.status)}</span></td><td><button type="button" className="table-action" onClick={() => navigate(`/batches/${batch.id}`)}>查看<ArrowRightIcon size={16} /></button></td></tr>; })}</tbody></table></div></section>}

      {tab === "items" && <section className="records-panel"><div className="batch-section__head"><div><span className="batch-eyebrow"><PackageIcon size={16} />商品层</span><h2>逐商品子任务</h2></div><span>{filteredItems.length} 个结果</span></div><div className="batch-table-wrap"><table className="batch-table"><thead><tr><th>商品</th><th>所属批次</th><th>当前结果</th><th>动作</th><th>证据</th></tr></thead><tbody>{filteredItems.map((item) => <tr key={item.id}><td><strong>{item.product?.name}</strong><small className="cell-subtitle">{item.product?.sku}</small></td><td><button className="table-link" type="button" onClick={() => navigate(`/batches/${item.batch.id}`)}>{item.batch.id}</button></td><td><span className={`item-status is-${item.status === "success" ? "success" : ["unknown", "failed"].includes(item.status) ? "warning" : item.status === "running" ? "info" : "neutral"}`}>{itemStatusLabel(item.status)}</span></td><td>{item.action}</td><td>{item.evidenceCount} 条</td></tr>)}</tbody></table></div></section>}

      {tab === "evidence" && <section className="records-panel"><div className="batch-section__head"><div><span className="batch-eyebrow"><ShieldCheckIcon size={16} />证据层</span><h2>批量编辑证据合同</h2></div><span>模板快照 → 保存回读 → 未发布证明 → 异常</span></div><div className="evidence-contract-grid">{filteredItems.filter((item) => item.evidenceCount > 0).map((item) => { const nonSuccess = ["unknown", "failed"].includes(item.status); return <article key={item.id} className={nonSuccess ? "is-incomplete" : ""}><div>{nonSuccess ? <WarningCircleIcon size={20} weight="fill" /> : <CheckCircleIcon size={20} weight="fill" />}<span><strong>{item.product?.name}</strong><small>{item.batch.id} · {item.id}</small></span></div><dl><div><dt>阶段</dt><dd>批量编辑 · 保存回读与未发布证明</dd></div><div><dt>证据数量</dt><dd>{item.evidenceCount} 条</dd></div><div><dt>证据等级</dt><dd>{item.status === "success" ? "保存回读 + 未发布证明" : item.reconciled ? "人工对账已闭合" : "部分证据，结果未闭合"}</dd></div></dl><ul className="evidence-entry-list">{evidenceEntries(item).map((entry) => <li key={entry.id}><details><summary><span className="evidence-entry-id">{entry.id.split("-").slice(-2).join("-")}</span><span><strong>{entry.name}</strong><small>{entry.state} · {entry.capturedAt}</small></span><span className="evidence-entry-action">查看详情</span></summary><dl className="evidence-entry-detail"><div><dt>完整 ID</dt><dd><code>{entry.id}</code></dd></div><div><dt>记录时间</dt><dd>{entry.capturedAt}</dd></div><div><dt>类型 / 状态</dt><dd>{entry.type} · {entry.state}</dd></div><div><dt>来源</dt><dd>{entry.source}</dd></div></dl><p className="evidence-prototype-note">{entry.note}</p></details></li>)}</ul></article>; })}</div></section>}

      {tab === "issues" && <section className="records-panel"><div className="batch-section__head"><div><span className="batch-eyebrow"><WarningCircleIcon size={16} />人工处理</span><h2>问题与 UNKNOWN</h2></div><span>{issues.length} 个阻断</span></div>{issues.length ? <div className="issues-list">{issues.map((item) => { const reviewReady = browser.batchId === item.batch.id && browser.owner === "manual" && item.batch.owner === "manual"; const attestation = attestations[item.id]; const reviewedCurrentSession = reviewReady && attestation?.reviewed && attestation.browserSessionId === browser.sessionId; const busy = issueBusyId === item.id; return <article key={item.id}><WarningCircleIcon size={24} weight="fill" /><div className="issue-copy"><strong>{item.product?.name}</strong><span>{item.action}</span><small>{item.batch.id} · 核对后封存原批次；后续商品不会自动执行</small></div><div className="issue-reconciliation"><ol className="issue-review-steps"><li className={reviewReady ? "is-done" : "is-current"}><BrowserIcon size={17} /><span><strong>打开可见现场并人工接管</strong><small>{reviewReady ? `已绑定 ${browser.sessionId}` : "结论按钮保持锁定"}</small></span></li><li className={reviewedCurrentSession ? "is-done" : reviewReady ? "is-current" : ""}><ShieldCheckIcon size={17} /><span><strong>人工核对当前 Session</strong><small>核对商品、店铺、页面结果与动作账本</small></span></li></ol><button type="button" className="secondary-button issue-open-session" disabled={busy} onClick={() => prepareVisibleReview(item)}><ArrowSquareOutIcon size={17} />{reviewReady ? "置前当前可见现场" : "打开现场并人工接管"}</button><label className={`issue-session-attestation${reviewReady ? "" : " is-disabled"}`}><input type="checkbox" disabled={!reviewReady || busy} checked={Boolean(reviewedCurrentSession)} onChange={(event) => setAttestations((current) => ({ ...current, [item.id]: event.target.checked ? { reviewed: true, browserSessionId: browser.sessionId } : null }))} /><span><strong>我已核对当前可见 Session</strong><small>{reviewReady ? browser.sessionId : "请先完成可见浏览器绑定与人工接管"}</small></span></label>{reviewedCurrentSession ? <div className="issue-actions issue-conclusion-actions"><button type="button" className="primary-button" disabled={busy} onClick={() => reconcile(item, "confirmed_success")}>确认已生效并封存</button><button type="button" className="secondary-button" disabled={busy} onClick={() => reconcile(item, "confirmed_no_effect")}>确认未生效并封存</button></div> : <p className="issue-locked-copy"><HandPalmIcon size={16} />完成上述两步后，才可登记人工结论。</p>}<button type="button" className="table-action issue-detail-link" onClick={() => navigate(`/batches/${item.batch.id}`)}>查看批次详情<ArrowRightIcon size={16} /></button></div></article>; })}</div> : <div className="batch-empty"><CheckCircleIcon size={34} weight="duotone" /><strong>没有待处理问题</strong><span>所有商品结果均已明确。</span></div>}</section>}
      <footer className="prototype-footer"><span>编辑批次 → single_save 子任务 → 阶段 → 证据</span><span>UNKNOWN 不自动重试</span><span>未来批次目标 · 生产仍为 single_save</span></footer>
    </div>
  );
}
