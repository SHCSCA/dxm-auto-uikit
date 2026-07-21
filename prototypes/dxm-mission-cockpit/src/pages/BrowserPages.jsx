import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import {
  ArrowClockwiseIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowSquareOutIcon,
  BrowserIcon,
  CheckCircleIcon,
  HandPalmIcon,
  LockKeyIcon,
  PlayIcon,
  ShieldCheckIcon,
  UserFocusIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { batchStatusLabel, batchTypeLabel, useBatchPrototype } from "../state/BatchPrototypeContext.jsx";

function browserWindowUrl(batchId) {
  return `${window.location.origin}${window.location.pathname}#/browser/live?batch=${encodeURIComponent(batchId)}`;
}

function realDxmUrl(batch) {
  return "https://www.dianxiaomi.com/web/smt/smtProductList/draft";
}

function openRealDxm(batch, notify) {
  const opened = window.open(realDxmUrl(batch), "_blank", "noopener,noreferrer");
  if (!opened) notify?.("浏览器阻止了店小秘真实页面；请允许弹窗后重试", "warning");
  else notify?.("已打开店小秘真实页面；原型尚未绑定该账号或 Session");
}

async function openStandalone(batchId, notify, openBrowser) {
  const binding = await openBrowser(batchId);
  if (!binding?.ok) {
    notify?.(binding?.message || "当前无法绑定可见浏览器", "warning");
    return;
  }
  const opened = window.open(browserWindowUrl(batchId), "dxm-visible-browser", "popup=yes,width=1280,height=850,left=80,top=60");
  if (!opened) notify?.("浏览器阻止了新窗口；请允许弹窗后重试", "warning");
  else notify?.("已打开独立窗口合同演示；原型不会伪造店小秘商品页面");
}

function currentItemFor(batch) {
  return batch?.items.find((item) => item.status === "running")
    || batch?.items.find((item) => ["unknown", "failed"].includes(item.status))
    || batch?.items.find((item) => item.status === "pending")
    || batch?.items.at(-1);
}

export function BrowserWorkspacePage({ notify }) {
  const {
    batches,
    browser,
    batchById,
    productById,
    openBrowser,
    requestPauseAfterCurrent,
    setBatchStatus,
    startBatch,
  } = useBatchPrototype();
  const activeBatch = batchById(browser.batchId) || batches[0];
  const currentItem = currentItemFor(activeBatch);
  const currentProduct = currentItem?.status === "pending" ? null : productById(currentItem?.productId);
  const currentOrdinal = currentItem?.ordinal || activeBatch.items.length;
  const totalItems = Number(activeBatch.maxItems || activeBatch.items.length);
  const isTerminal = ["completed", "completed_with_issues", "stopped", "failed"].includes(activeBatch.status);
  const hasUnknown = activeBatch.items.some((item) => item.status === "unknown");
  const otherRunningBatch = batches.find((item) => item.status === "running" && item.id !== activeBatch.id);
  const canResume = ["ready", "paused"].includes(activeBatch.status) && !otherRunningBatch && !hasUnknown;

  return (
    <div className="batch-page browser-workspace" data-testid="browser-workspace-page">
      <section className="batch-boundary"><ShieldCheckIcon size={22} weight="fill" /><div><strong>目标合同：唯一真实店小秘浏览器</strong><span>正式产品中，用户看到的独立 Chrome 必须就是执行 mutation 的同一个 Session；控制台不会再提供本地商品选择器或第二套模拟页面。</span></div><span className="batch-boundary__pill">唯一 Session</span></section>
      <header className="batch-page__header"><div><span className="batch-eyebrow"><BrowserIcon size={17} />浏览器现场</span><h1>批量编辑的唯一真实浏览器</h1><p>整批批准后，后台按 single_save 子任务逐件串行执行；正常保存回读通过会自动进入下一件，用户无需逐件操作。</p></div><div className="browser-header-actions"><button type="button" className="secondary-button" onClick={() => openStandalone(activeBatch.id, notify, openBrowser)}><BrowserIcon size={18} />查看 HUD 合同</button><button type="button" className="primary-button" onClick={() => openRealDxm(activeBatch, notify)}><ArrowSquareOutIcon size={18} />打开真实店小秘</button></div></header>

      <section className="browser-session-hero">
        <div className="browser-session-hero__status"><span className={`live-dot${browser.liveConnected ? "" : " is-simulated"}`} /><div><strong>{browser.liveConnected ? "真实浏览器已连接" : "本地原型会话 · 未核验"}</strong><small>{browser.liveConnected ? "唯一执行 Session 已完成后端核验" : "当前不代表真实 Chrome；正式版本显示 PID、CDP 与运行实例指纹"}</small></div></div>
        <dl>
          <div><dt>绑定批次计划</dt><dd>{activeBatch.id}<small>{batchTypeLabel(activeBatch.type)}</small></dd></div>
          <div><dt>店小秘来源</dt><dd>{activeBatch.sourcePage || "等待真实页面"}<small>{activeBatch.intakeDescription}</small></dd></div>
          <div><dt>{isTerminal ? "最近结果" : `当前进度 ${currentOrdinal} / ${totalItems}`}</dt><dd>{currentProduct?.name || "等待自动派发"}<small>{currentProduct?.sku || "商品身份由店小秘现场读回"}</small></dd></div>
          <div><dt>Session 指纹</dt><dd><code>{browser.sessionId}</code></dd></div>
          <div><dt>控制权</dt><dd>{activeBatch.owner === "manual" ? "人工" : "Agent"}</dd></div>
          <div><dt>动作边界</dt><dd>只保存<small>发布能力不可用</small></dd></div>
          <div><dt>最近读回</dt><dd>{browser.lastReadback}<small>成功后自动继续</small></dd></div>
        </dl>
      </section>

      <section className="browser-console-grid">
        <article className="browser-action-card">
          <div className="batch-section__head"><div><span className="batch-eyebrow">自动串行现场 · {currentOrdinal} / {totalItems}</span><h2>{browser.currentAction}</h2></div><span className={`batch-status is-${activeBatch.status === "needs_attention" || hasUnknown ? "warning" : "info"}`}>{batchStatusLabel(activeBatch.status)}</span></div>
          <div className="browser-location"><LockKeyIcon size={18} weight="fill" /><span>{browser.currentUrl}</span></div>
          <ol className="browser-action-list">
            <li className={browser.liveConnected ? "is-done" : "is-warning"}>{browser.liveConnected ? <CheckCircleIcon size={18} weight="fill" /> : <WarningCircleIcon size={18} weight="fill" />}<span><strong>{browser.liveConnected ? "批次授权与运行身份已核验" : "运行身份尚未接入核验"}</strong><small>{browser.liveConnected ? "批次快照、模板、店铺与 Profile 均已锁定" : "以下为未来批次目标，不代表真实账号或 Session"}</small></span></li>
            <li className={browser.liveConnected ? "is-active" : ""}><PlayIcon size={18} weight="fill" /><span><strong>{browser.currentAction}</strong><small>{browser.liveConnected ? "逐字段编辑并只保存，等待页面稳定与读回" : "原型只演示自动队列合同，不读取真实页面"}</small></span></li>
            <li><span className="step-number">3</span><span><strong>保存回读与未发布证明</strong><small>结果明确则自动派发下一件；异常按安全边界隔离或停批</small></span></li>
          </ol>
        </article>
        <article className="browser-controls-card">
          <h2>自动队列控制</h2><p>控制只作用于批次队列：可恢复自动执行、要求当前件安全结束后暂停，或人工接管。运行中接管会把写入边界标为 UNKNOWN。</p>
          <div className="browser-control-grid">
            <button type="button" disabled={!canResume} onClick={async () => { const result = await startBatch(activeBatch.id); notify?.(result?.ok ? "自动串行队列已恢复" : result?.message, result?.ok ? undefined : "warning"); }}><PlayIcon size={20} /><strong>恢复自动队列</strong><span>从下一件未派发商品继续</span></button>
            <button type="button" disabled={activeBatch.status !== "running" || activeBatch.pauseAfterCurrent || activeBatch.stopAfterCurrent} onClick={async () => { const result = await requestPauseAfterCurrent(activeBatch.id); notify?.(result?.ok ? "将在当前件安全结束后暂停" : result?.message, result?.ok ? undefined : "warning"); }}><UserFocusIcon size={20} /><strong>当前件后暂停</strong><span>不会中断正在写入的本件</span></button>
            {activeBatch.owner === "manual" ? <button type="button" disabled={isTerminal || hasUnknown} onClick={async () => { const result = await setBatchStatus(activeBatch.id, "paused", "agent"); notify?.(result?.ok ? "控制权已交还；队列保持暂停" : result?.message, result?.ok ? undefined : "warning"); }}><UserFocusIcon size={20} /><strong>交还 Agent</strong><span>交还后由操作员恢复队列</span></button> : <button type="button" disabled={isTerminal || Boolean(otherRunningBatch)} onClick={async () => { const result = await setBatchStatus(activeBatch.id, "manual", "manual"); if (!result?.ok) notify?.(result?.message, "warning"); else notify?.(result?.interrupted ? "已人工接管；当前写入边界未知，必须对账" : "已人工接管"); }}><HandPalmIcon size={20} /><strong>人工接管</strong><span>运行中接管需对账</span></button>}
          </div>
          <div className="browser-truth-note"><WarningCircleIcon size={19} /><span>这里展示的是未来批次编排目标；当前生产后端仍按受控 single_save 子任务执行，且浏览器所有权尚需统一。</span></div>
        </article>
      </section>

      <section className="browser-batch-picker">
        <div className="batch-section__head"><div><span className="batch-eyebrow">会话绑定</span><h2>切换批次前必须重新核验</h2></div><span>不能把旧浏览器授权复用到新批次</span></div>
        <div className="browser-batch-list">{batches.map((batch) => <button type="button" key={batch.id} className={batch.id === activeBatch.id ? "is-selected" : ""} onClick={async () => { const result = await openBrowser(batch.id); if (!result?.ok) notify?.(result?.message, "warning"); }}><span className={`flow-chip flow-chip--${batch.type}`}>{batchTypeLabel(batch.type)}</span><strong>{batch.title}</strong><small>{batch.sourcePage || batch.storeName} · 上限 {batch.maxItems || batch.items.length} 件</small><ArrowRightIcon size={17} /></button>)}</div>
      </section>
      <footer className="prototype-footer"><span>唯一独立浏览器现场</span><span>控制台不复制店小秘商品页面</span><span>本地原型 · 未连接真实店小秘</span></footer>
    </div>
  );
}

export function BrowserLivePage({ notify }) {
  const location = useLocation();
  const { batches, browser, batchById, productById, cycleBrowserAction, requestPauseAfterCurrent, setBatchStatus, startBatch } = useBatchPrototype();
  const requestedId = new URLSearchParams(location.search).get("batch");
  const requestedBatch = batchById(requestedId);
  const conflictingRunningBatch = batches.find((item) => item.status === "running" && item.id !== requestedBatch?.id);
  const batch = conflictingRunningBatch || requestedBatch || batchById(browser.batchId) || batches[0];
  const currentItem = currentItemFor(batch);
  const currentProduct = currentItem?.status === "pending" ? null : productById(currentItem?.productId);
  const currentOrdinal = currentItem?.ordinal || batch.items.length;
  const totalItems = Number(batch.maxItems || batch.items.length);
  const isAgentRunning = batch.status === "running" && batch.owner === "agent";
  const isTerminal = ["completed", "completed_with_issues", "stopped", "failed"].includes(batch.status);
  const otherRunningBatch = batches.find((item) => item.status === "running" && item.id !== batch.id);
  const hasUnknown = batch.items.some((item) => item.status === "unknown");
  const canResume = ["ready", "paused"].includes(batch.status) && !otherRunningBatch && !hasUnknown;
  const primaryLabel = batch.status === "running" ? "当前件后暂停" : batch.status === "paused" ? "恢复自动队列" : "启动已批准队列";

  useEffect(() => {
    if (!isAgentRunning) return undefined;
    const timer = window.setInterval(() => { void cycleBrowserAction(); }, 2800);
    return () => window.clearInterval(timer);
  }, [cycleBrowserAction, isAgentRunning]);

  const runPrimary = async () => {
    const result = batch.status === "running" ? await requestPauseAfterCurrent(batch.id) : await startBatch(batch.id);
    if (!result?.ok) notify?.(result?.message, "warning");
    else notify?.(batch.status === "running" ? "将在当前件安全结束后暂停" : "已恢复整批自动串行队列");
  };

  return (
    <div className="visible-browser-window" data-testid="visible-browser-live-page">
      <header className="visible-browser-chrome">
        <div className="browser-tab"><BrowserIcon size={17} weight="fill" /><span>店小秘真实浏览器合同 · {batch.id}</span></div>
        <div className="browser-toolbar"><button type="button" aria-label="后退（原型不可用）" disabled><ArrowLeftIcon size={17} /></button><button type="button" aria-label="前进（原型不可用）" disabled><ArrowRightIcon size={17} /></button><button type="button" aria-label="刷新当前现场" disabled={!isAgentRunning} onClick={() => { void cycleBrowserAction(); }}><ArrowClockwiseIcon size={17} /></button><div className="browser-address"><LockKeyIcon size={15} weight="fill" /><span>{browser.currentUrl}</span></div><span className="browser-profile">运营</span></div>
      </header>
      <section className="prototype-browser-warning"><WarningCircleIcon size={18} weight="fill" /><span><strong>{conflictingRunningBatch ? `唯一浏览器仍绑定运行中批次 ${conflictingRunningBatch.id}` : "原型不会渲染模拟店小秘页面"}</strong>正式产品将在这一个独立窗口中打开真实店小秘；当前未连接账号，因此只展示 Session 与 Agent HUD 合同。</span></section>
      <main className="real-browser-shell">
        <section className="real-browser-evidence">
          <header>
            <div><span>{batchTypeLabel(batch.type)}</span><h1>{browser.liveConnected ? "店小秘真实页面已连接" : "真实页面证据与接管位置"}</h1><p>{browser.liveConnected ? "当前画面来自真实执行 Session。" : "下方截图来自当前项目已有店小秘测试证据，不是本系统仿造页面；正式接入后，这里由真实 Chrome 页面替换。"}</p></div>
            <button type="button" className="secondary-button" onClick={() => openRealDxm(batch, notify)}><ArrowSquareOutIcon size={17} />打开真实店小秘</button>
          </header>
          <figure>
            <figcaption><ShieldCheckIcon size={17} weight="fill" /><span>当前项目真实证据 · 半托管字段读回</span><em>非实时</em></figcaption>
            <img src="/assets/dxm-real-evidence-semi-managed.png" alt="当前项目中店小秘半托管价格、库存、重量和包装尺寸字段的真实页面证据" />
          </figure>
          <dl>
            <div><dt>目标页面</dt><dd>{batch.sourcePage || "等待绑定"}</dd></div>
            <div><dt>当前商品引用</dt><dd>{currentProduct?.name || "尚未读取"}</dd></div>
            <div><dt>自动队列进度</dt><dd>{currentOrdinal} / {totalItems}</dd></div>
            <div><dt>写入状态</dt><dd>{batchStatusLabel(batch.status)} · 只保存</dd></div>
          </dl>
          <p className="real-browser-evidence__note"><WarningCircleIcon size={17} weight="fill" />证据截图只用于说明当前项目已经接触到的真实店小秘字段；商品、店铺与操作仍以另行打开的真实店小秘页面为准。</p>
        </section>
        <aside className="browser-hud">
          <div className="browser-hud__head"><span className={`live-dot${browser.liveConnected ? "" : " is-simulated"}`} /><div><strong>DXM Agent HUD · 原型</strong><small>{batch.id} · 未经后端核验</small></div></div>
          <div className="browser-hud__current"><span>整批已批准 · 自动串行队列</span><strong>{browser.currentAction}</strong><small>{currentProduct?.name || "商品由店小秘现场读取"}</small></div>
          <dl><div><dt>店小秘来源</dt><dd>{batch.sourcePage}</dd></div><div><dt>进度</dt><dd>{currentOrdinal} / {totalItems}</dd></div><div><dt>控制权</dt><dd>{batch.owner === "manual" ? "人工" : "Agent"}</dd></div><div><dt>动作边界</dt><dd className="safe-text">只保存 · 禁止发布</dd></div></dl>
          <div className="browser-hud__actions">
            {isTerminal ? <button type="button" disabled><ShieldCheckIcon size={17} />终态只读</button> : batch.owner === "manual" ? <button type="button" disabled={hasUnknown} onClick={async () => { const result = await setBatchStatus(batch.id, "paused", "agent"); if (!result?.ok) notify?.(result?.message, "warning"); }}><UserFocusIcon size={17} />交还 Agent</button> : <button type="button" disabled={Boolean(otherRunningBatch)} onClick={async () => { const result = await setBatchStatus(batch.id, "manual", "manual"); if (!result?.ok) notify?.(result?.message, "warning"); }}><HandPalmIcon size={17} />人工接管</button>}
            <button type="button" disabled={isTerminal || batch.owner === "manual" || hasUnknown || (batch.status === "running" ? batch.pauseAfterCurrent || batch.stopAfterCurrent : !canResume)} onClick={runPrimary}><PlayIcon size={17} />{primaryLabel}</button>
          </div>
          <p><ShieldCheckIcon size={16} weight="fill" />批次只批准一次；本件保存回读明确后自动继续，运行中接管会进入 UNKNOWN。</p>
        </aside>
      </main>
    </div>
  );
}
