import { useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  BrowserIcon,
  CheckCircleIcon,
  CircleNotchIcon,
  ClockIcon,
  FingerprintIcon,
  HandPalmIcon,
  PackageIcon,
  PlayIcon,
  ShieldCheckIcon,
  UserFocusIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { batchStatusLabel, batchTypeLabel, itemStatusLabel, useBatchPrototype } from "../state/BatchPrototypeContext.jsx";

function itemTone(status) {
  if (status === "success") return "success";
  if (["unknown", "failed", "skipped"].includes(status)) return "warning";
  if (status === "running") return "info";
  return "neutral";
}

function BatchSummary({ batch, stats }) {
  const finished = stats.success + stats.failed + stats.unknown + stats.skipped;
  const progress = stats.total ? Math.round((finished / stats.total) * 100) : 0;
  return (
    <section className="cockpit-summary">
      <div className="cockpit-summary__mark is-edit"><PackageIcon size={30} weight="duotone" /></div>
      <div className="cockpit-summary__main"><span className="flow-chip flow-chip--edit">{batchTypeLabel()}</span><h2>{batch.title}</h2><dl><div><dt>店小秘现场快照</dt><dd>{batch.sourcePage || "速卖通 → 商品箱"}<small>{batch.intakeDescription}</small></dd></div><div><dt>冻结范围</dt><dd>{stats.total} 件 · 严格单件串行<small>批次摘要 {batch.approvalHash}</small></dd></div><div><dt>模板与授权</dt><dd>{batch.templateName}<small>整批一次批准；不再逐件审核</small></dd></div></dl></div>
      <div className="cockpit-summary__progress"><strong>{progress}%</strong><span>{finished} / {stats.total} 已有结果</span><div><i style={{ width: `${progress}%` }} /></div></div>
    </section>
  );
}

function BrowserTrustCard({ batch, browser, currentProduct, onOpenDxm, onOpenHud, isBound }) {
  return (
    <section className="browser-trust-card" aria-label="可见浏览器现场">
      <div className="browser-trust-card__session">
        <BrowserIcon size={46} weight="duotone" />
        <span className="live-state"><i className={`live-dot${browser.liveConnected ? "" : " is-simulated"}`} />原型窗口可置前 · 未核验</span>
        <strong>{isBound ? browser.currentUrl : "尚未绑定本批次"}</strong>
        <small>{currentProduct?.name || "等待自动派发商品箱快照中的当前件"}</small>
        <dl><div><dt>批次</dt><dd>{batch.id}</dd></div><div><dt>Session</dt><dd>{isBound ? browser.sessionId : "待绑定"}</dd></div></dl>
      </div>
      <div className="browser-trust-card__copy">
        <div className="batch-eyebrow"><BrowserIcon size={17} />目标合同：唯一真实执行窗口</div>
        <h2>自动执行也必须让用户看得见</h2>
        <p>正式产品会置前唯一的店小秘真实浏览器，并把批次、当前 i/N、商品身份、Session 与动作绑定在同一窗口。控制台不提供第二套商品或店铺选择器。</p>
        <dl><div><dt>Session</dt><dd>{isBound ? browser.sessionId : "打开后绑定"}</dd></div><div><dt>当前动作</dt><dd>{isBound ? browser.currentAction : "尚未绑定到可见窗口"}</dd></div><div><dt>控制权</dt><dd>{batch.owner === "manual" ? "人工接管" : "Agent"}</dd></div></dl>
        <div className="browser-trust-card__actions"><button type="button" className="secondary-button" onClick={onOpenHud}><BrowserIcon size={18} />查看 HUD 合同</button><button type="button" className="primary-button" onClick={onOpenDxm}><ArrowSquareOutIcon size={18} />打开真实店小秘</button></div>
      </div>
    </section>
  );
}

export default function BatchCockpitPage({ notify }) {
  const { batchId } = useParams();
  const navigate = useNavigate();
  const {
    batches,
    batchById,
    productById,
    statsFor,
    browser,
    openBrowser,
    setBatchStatus,
    startBatch,
    requestPauseAfterCurrent,
    requestStopAfterCurrent,
    triggerUnknownDemo,
  } = useBatchPrototype();
  const batch = batchById(batchId);
  const [selectedItemId, setSelectedItemId] = useState(batch?.items.find((item) => ["running", "unknown", "failed"].includes(item.status))?.id || batch?.items[0]?.id || "");
  if (!batch) return <Navigate replace to="/tasks/current" />;

  const stats = statsFor(batch);
  const displayItems = [
    ...batch.items,
    ...Array.from({ length: Math.max(0, stats.total - batch.items.length) }, (_, index) => ({
      id: `${batch.id}-PENDING-${batch.items.length + index + 1}`,
      ordinal: batch.items.length + index + 1,
      status: "pending",
      action: "已冻结在店小秘现场快照中，等待自动派发",
      evidenceCount: 0,
      placeholder: true,
    })),
  ];
  const currentItem = batch.items.find((item) => item.status === "running")
    || batch.items.find((item) => item.status === "unknown")
    || batch.items.find((item) => item.status === "pending")
    || batch.items.at(-1);
  const currentProduct = currentItem?.status === "pending" ? null : productById(currentItem?.productId);
  const selectedItem = displayItems.find((item) => item.id === selectedItemId) || currentItem || displayItems[0];
  const selectedProduct = selectedItem?.productId ? productById(selectedItem.productId) : null;
  const currentOrdinal = currentItem?.ordinal || Math.min(stats.total, stats.success + stats.skipped + stats.failed + 1);
  const hasUnknown = stats.unknown > 0;
  const terminal = ["completed", "completed_with_issues", "stopped", "failed"].includes(batch.status);
  const otherRunningBatch = batches.find((item) => item.status === "running" && item.id !== batch.id);
  const canResume = ["ready", "paused"].includes(batch.status) && !hasUnknown && !otherRunningBatch;
  const statusCopy = (() => {
    if (hasUnknown) return "当前件写入边界未知，整批已经停止；只能在同一 Session 人工对账，不能自动重试。";
    if (otherRunningBatch) return `${otherRunningBatch.id} 正在占用唯一浏览器；当前批次不会并行派发。`;
    if (batch.status === "running" && batch.stopAfterCurrent) return "当前件继续完成安全闭环，随后停止派发所有后续商品。";
    if (batch.status === "running" && batch.pauseAfterCurrent) return "当前件继续完成安全闭环，随后暂停；不会派发下一件。";
    if (batch.status === "running") return `正在自动处理第 ${currentOrdinal} / ${stats.total} 件；正常成功后无需点击，会自动进入下一件。`;
    if (batch.status === "manual") return "人工已接管浏览器，Agent 不再点击；若接管发生在可能写入阶段会进入 UNKNOWN。";
    if (batch.status === "paused") return "当前件已安全结束，自动队列保持暂停；恢复时继续未派发商品，不重复已完成商品。";
    if (batch.status === "stopped") return "已停止派发后续商品；未启动商品保持未写入并记录为未派发。";
    if (batch.status === "completed") return "整批商品均取得保存回读与独立未发布证明。";
    if (batch.status === "completed_with_issues") return "批次已封存；保存前异常已隔离，或 UNKNOWN 已完成人工对账。";
    return "整批授权已形成，等待启动自动串行队列；不会再逐件要求审核。";
  })();

  const openVisibleBrowser = async () => {
    const binding = await openBrowser(batch.id);
    if (!binding?.ok) {
      notify?.(binding?.message || "当前无法绑定可见浏览器", "warning");
      return;
    }
    const url = `${window.location.origin}${window.location.pathname}#/browser/live?batch=${encodeURIComponent(batch.id)}`;
    const opened = window.open(url, "dxm-visible-browser", "popup=yes,width=1280,height=850,left=80,top=60");
    if (!opened) notify?.("浏览器阻止了新窗口；请允许弹窗后重试", "warning");
    else notify?.("已打开独立浏览器现场；本地原型只演示联动");
  };

  const openRealDxmPage = () => {
    const opened = window.open("https://www.dianxiaomi.com/web/smt/smtProductList/draft", "_blank", "noopener,noreferrer");
    if (!opened) notify?.("浏览器阻止了店小秘真实页面；请允许弹窗后重试", "warning");
    else notify?.("已打开店小秘真实商品箱；原型尚未绑定该账号或 Session");
  };

  return (
    <div className="batch-page batch-cockpit" data-testid="batch-cockpit-page">
      <section className="batch-boundary"><ShieldCheckIcon size={22} weight="fill" /><div><strong>整批一次授权 · 单件串行自动编辑</strong><span>正常成功自动继续；保存前无写入异常可隔离，UNKNOWN、身份漂移、Session 丢失或发布风险会整批停止。</span></div><span className="batch-boundary__pill">未来批次目标</span></section>
      <div className="cockpit-toolbar">
        <button type="button" className="back-link" onClick={() => navigate("/tasks/current")}><ArrowLeftIcon size={17} />返回工作台</button>
        <span className={`batch-status is-${["running", "manual"].includes(batch.status) ? "info" : hasUnknown || ["completed_with_issues", "stopped", "failed"].includes(batch.status) ? "warning" : batch.status === "completed" ? "success" : "neutral"}`}>{batchStatusLabel(batch.status)}</span>
        <div className="cockpit-toolbar__actions">
          <button type="button" className="secondary-button" disabled={batch.status !== "running" || batch.pauseAfterCurrent || batch.stopAfterCurrent} onClick={async () => { const result = await requestPauseAfterCurrent(batch.id); notify?.(result?.ok ? "将在当前件安全结束后暂停" : result?.message, result?.ok ? undefined : "warning"); }}><ClockIcon size={18} />当前件后暂停</button>
          <button type="button" className="secondary-button" disabled={terminal || hasUnknown || batch.stopAfterCurrent} onClick={async () => { const result = await requestStopAfterCurrent(batch.id); notify?.(result?.ok ? (result.stopAfterCurrent ? "将在当前件结束后停止派发" : "已停止派发") : result?.message, result?.ok ? undefined : "warning"); }}><WarningCircleIcon size={18} />停止派发下一件</button>
          {batch.owner === "manual" ? <button type="button" className="secondary-button" onClick={async () => { const result = await setBatchStatus(batch.id, "paused", "agent"); notify?.(result?.ok ? "控制权已交还；自动队列保持暂停" : result?.message, result?.ok ? undefined : "warning"); }}><UserFocusIcon size={18} />交还 Agent</button> : <button type="button" className="secondary-button" disabled={terminal || Boolean(otherRunningBatch)} onClick={async () => { const result = await setBatchStatus(batch.id, "manual", "manual"); notify?.(result?.ok ? (result.interrupted ? "人工已接管；当前写入边界未知，整批停止" : "人工已接管，Agent 不再点击") : result?.message, result?.ok ? undefined : "warning"); }}><HandPalmIcon size={18} />人工接管</button>}
          <button type="button" className="secondary-button" onClick={openVisibleBrowser}><BrowserIcon size={18} />查看 HUD 合同</button>
          <button type="button" className="primary-button" onClick={openRealDxmPage}><ArrowSquareOutIcon size={18} />打开真实店小秘</button>
        </div>
      </div>

      <header className="batch-page__header batch-page__header--compact"><div><span className="batch-eyebrow">批量编辑驾驶舱 · {batch.id}</span><h1>{batch.title}</h1><p>{statusCopy}</p></div></header>
      <BatchSummary batch={batch} stats={stats} />

      <section className="cockpit-status-bar">
        <div><span>当前进度</span><strong>{currentOrdinal} / {stats.total}</strong></div><div><span>成功</span><strong>{stats.success}</strong></div><div><span>等待自动派发</span><strong>{stats.pending}</strong></div><div className={stats.failed || stats.skipped ? "is-warning" : ""}><span>失败 / 隔离</span><strong>{stats.failed} / {stats.skipped}</strong></div><div className={stats.unknown ? "is-warning" : ""}><span>UNKNOWN</span><strong>{stats.unknown}</strong></div><div><span>证据</span><strong>{batch.items.reduce((sum, item) => sum + item.evidenceCount, 0)}</strong></div>
        <button type="button" className="secondary-button" disabled={batch.status !== "running"} onClick={async () => { const result = await triggerUnknownDemo(batch.id); notify?.(result?.ok ? "已触发 UNKNOWN 演示：整批停止，等待人工对账" : result?.message, result?.ok ? "warning" : "warning"); }}><WarningCircleIcon size={18} />触发 UNKNOWN 演示</button>
        <button type="button" className="primary-button" disabled={!canResume} onClick={async () => { const result = await startBatch(batch.id); notify?.(result?.ok ? "自动串行队列已恢复" : result?.message, result?.ok ? undefined : "warning"); }}>{batch.status === "running" ? <CircleNotchIcon size={18} className="spin" /> : <PlayIcon size={18} weight="fill" />}{batch.status === "running" ? "自动推进中" : batch.status === "paused" ? "恢复自动队列" : "启动已批准队列"}</button>
      </section>

      <section className="item-approval-callout"><FingerprintIcon size={23} weight="duotone" /><div><strong>批次授权已锁定，不再逐件审核</strong><span>{batch.approvedBy} · {batch.approvedAt || batch.createdAt} · CONFIRM_DXM_SAVE_ONLY。后台仍按单件 single_save 子任务串行执行。</span></div></section>

      {hasUnknown && <section className="unknown-stop" role="alert"><WarningCircleIcon size={24} weight="fill" /><div><strong>批次已因 UNKNOWN 整体停止</strong><span>禁止自动重试未知写入。必须在同一个真实浏览器 Session 和证据记录中人工核对；当前原型演示的是未来对账路径。</span></div><button type="button" className="secondary-button" onClick={() => navigate("/records?tab=issues")}>进入人工对账</button></section>}

      <BrowserTrustCard batch={batch} browser={browser} currentProduct={currentProduct} onOpenDxm={openRealDxmPage} onOpenHud={openVisibleBrowser} isBound={browser.batchId === batch.id} />

      <section className="batch-work-area">
        <div className="batch-items-card">
          <div className="batch-section__head"><div><span className="batch-eyebrow"><PackageIcon size={16} />single_save 子任务队列</span><h2>自动串行执行序列</h2></div><span>队列来自店小秘现场快照，不是本地商品选择</span></div>
          <div className="batch-items-list">
            {displayItems.map((item, index) => {
              const product = item.productId ? productById(item.productId) : null;
              return (
                <button type="button" key={item.id} className={`batch-item-row${selectedItem?.id === item.id ? " is-selected" : ""}`} onClick={() => setSelectedItemId(item.id)}>
                  <span className="batch-item-row__order">{String(index + 1).padStart(2, "0")}</span>
                  <span className="batch-item-row__main"><strong>{product?.name || `店小秘现场快照第 ${index + 1} 件`}</strong><small>{product?.sku ? `${product.sku} · ` : "身份随现场读回 · "}{item.action}</small></span>
                  <span className={`item-status is-${itemTone(item.status)}`}>{item.status === "running" ? <CircleNotchIcon size={15} className="spin" /> : item.status === "success" ? <CheckCircleIcon size={15} weight="fill" /> : item.status === "unknown" ? <WarningCircleIcon size={15} weight="fill" /> : <ClockIcon size={15} />}{itemStatusLabel(item.status)}</span>
                  <span className="evidence-count">{item.evidenceCount} 条证据</span>
                </button>
              );
            })}
          </div>
        </div>
        <aside className="item-detail-card" aria-label="当前商品详情">
          <div className="item-detail-card__head"><span className={`item-status is-${itemTone(selectedItem?.status)}`}>{itemStatusLabel(selectedItem?.status)}</span><small>{selectedItem?.id}</small></div>
          <div className="item-detail-card__product">{selectedProduct?.image ? <img src={selectedProduct.image} alt="" /> : <PackageIcon size={34} weight="duotone" />}<div><strong>{selectedProduct?.name || "商品由店小秘现场快照提供"}</strong><span>{selectedProduct?.sku || "本系统没有可选商品记录"}</span></div></div>
          <dl><div><dt>店小秘来源</dt><dd>{batch.sourcePage}</dd></div><div><dt>身份来源</dt><dd>{selectedItem?.status === "pending" ? "已在不可变批次快照中，等待派发时复核" : "商品箱行身份与批次指纹已绑定"}</dd></div><div><dt>当前动作</dt><dd>{selectedItem?.action}</dd></div><div><dt>证据数量</dt><dd>{selectedItem?.evidenceCount || 0} 条</dd></div></dl>
          <div className="item-evidence-contract"><ShieldCheckIcon size={19} weight="fill" /><span>保存回读和未发布证明分开记录，缺一不可；UNKNOWN 时不自动重试。</span></div>
        </aside>
      </section>
      <footer className="prototype-footer"><span>{batch.id}</span><span>批次批准：{batch.approvedBy} · 后续无需逐件点击</span><span>未来批次编排目标 · 生产仍为 single_save 子任务</span></footer>
    </div>
  );
}
