import { useNavigate } from "react-router-dom";
import {
  ArrowRightIcon,
  BrowserIcon,
  CheckCircleIcon,
  ClipboardTextIcon,
  CubeIcon,
  PencilSimpleLineIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { batchStatusLabel, useBatchPrototype } from "../state/BatchPrototypeContext.jsx";

function WorkspaceCard({ icon: Icon, eyebrow, title, description, count, countLabel, bullets, actionLabel, onOpen }) {
  return (
    <article className="flow-card flow-card--edit">
      <div className="flow-card__top">
        <div className="flow-card__icon"><Icon size={27} weight="duotone" /></div>
        <span className="flow-card__step">{eyebrow}</span>
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="flow-card__metric"><strong>{count}</strong><span>{countLabel}</span></div>
      <ul>{bullets.map((bullet) => <li key={bullet}><CheckCircleIcon size={16} weight="fill" />{bullet}</li>)}</ul>
      <button type="button" className="primary-button flow-card__button" onClick={onOpen}>
        {actionLabel}<ArrowRightIcon size={18} weight="bold" />
      </button>
    </article>
  );
}

function statusTone(status) {
  if (status === "completed") return "success";
  if (["needs_attention", "completed_with_issues", "failed"].includes(status)) return "warning";
  if (["running", "manual"].includes(status)) return "info";
  return "neutral";
}

function shortFingerprint(value) {
  if (!value) return "等待冻结";
  return value.length > 22 ? `${value.slice(0, 22)}…` : value;
}

export default function WorkflowHomePage({ runtimeIdentity }) {
  const navigate = useNavigate();
  const { batches, browser, statsFor } = useBatchPrototype();
  const editBatches = batches.filter((batch) => batch.type === "edit");
  const activeBatch = editBatches.find((batch) => ["running", "manual", "needs_attention"].includes(batch.status)) || editBatches[0] || null;
  const activeStats = activeBatch ? statsFor(activeBatch) : { total: 0, success: 0, failed: 0, unknown: 0, skipped: 0, pending: 0 };
  const activeExceptions = activeStats.failed + activeStats.unknown;

  return (
    <div className="batch-page workflow-home" data-testid="workflow-home-page">
      <section className="batch-boundary" aria-label="批量编辑产品边界">
        <ShieldCheckIcon size={22} weight="fill" />
        <div>
          <strong>未来批量目标：一次批准，连续自动编辑</strong>
          <span>从店小秘商品箱读取并冻结当前范围；本系统不选择商品或店铺。正常成功自动继续，UNKNOWN、身份漂移或发布风险立即停止。</span>
        </div>
        <span className="batch-boundary__pill">生产仍为 single_save</span>
      </section>

      <header className="batch-page__header">
        <div>
          <div className="batch-eyebrow"><ClipboardTextIcon size={17} />编辑工作台</div>
          <h1>批量编辑店小秘商品箱</h1>
          <p>运营人员先在真实店小秘中筛好商品范围，再在这里锁定范围快照和模板版本；整批只批准一次，系统随后按顺序编排受控 single_save 子任务。</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => navigate("/browser")}>
          <BrowserIcon size={18} />查看浏览器现场
        </button>
      </header>

      <section className="flow-card-grid" aria-label="批量编辑准备区">
        <WorkspaceCard
          icon={BrowserIcon}
          eyebrow="01 · 现场范围"
          title="店小秘商品箱当前范围"
          description="商品、店铺与筛选条件都来自同一个可见店小秘 Session；系统只读取现场并生成不可变范围快照。"
          count={activeStats.total || "—"}
          countLabel={activeStats.total ? "件已进入当前范围快照" : "等待从真实商品箱读取"}
          bullets={[
            `来源页面：${activeBatch?.sourcePage || "店小秘商品箱"}`,
            `店铺读回：${activeBatch?.storeName || "等待同一 Session 核验"}`,
            `范围指纹：${shortFingerprint(activeBatch?.approvalHash)}`,
          ]}
          actionLabel="打开商品箱现场"
          onOpen={() => navigate("/browser")}
        />
        <WorkspaceCard
          icon={PencilSimpleLineIcon}
          eyebrow="02 · 模板与授权"
          title={activeBatch?.templateName || "选择已校验模板版本"}
          description="模板版本、范围快照和只保存边界共同冻结为一个批次授权；批准后安全结果会自动连续推进。"
          count="1"
          countLabel="次批次批准"
          bullets={[
            "成功项完成读回后自动进入下一件",
            "保存前校验异常可隔离并记录",
            "结果未知或现场漂移时停止整批并对账",
          ]}
          actionLabel="配置批量编辑"
          onOpen={() => navigate("/edit")}
        />
      </section>

      <section className="trust-strip" aria-label="可见浏览器信任说明">
        <div className="trust-strip__icon"><BrowserIcon size={28} weight="duotone" /></div>
        <div className="trust-strip__copy">
          <strong>真实店小秘浏览器是唯一商品现场</strong>
          <span>执行中持续显示批次进度、当前商品、Session 与控制权；本系统不会复制商品清单，也不会提供本地店铺选择器。</span>
        </div>
        <div className={`trust-strip__state is-${browser.status}`}>
          <span className={`live-dot${browser.liveConnected ? "" : " is-simulated"}`} />
          <strong>{browser.liveConnected ? "真实浏览器已绑定" : "原型现场可演示"}</strong>
          <small>{browser.liveConnected ? browser.sessionId : "未经生产后端核验"}</small>
        </div>
      </section>

      <section className="batch-section">
        <div className="batch-section__head">
          <div><span className="batch-eyebrow"><CubeIcon size={16} />执行与异常</span><h2>编辑批次记录</h2></div>
          <span>{activeBatch ? `当前 ${activeStats.success}/${activeStats.total} 完成 · ${activeExceptions} 个需处理异常` : "等待创建首个编辑批次"}</span>
        </div>
        <div className="batch-table-wrap">
          <table className="batch-table">
            <thead><tr><th>批次</th><th>店小秘现场范围</th><th>模板 / 授权</th><th>执行结果</th><th>异常</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              {editBatches.map((batch) => {
                const stats = statsFor(batch);
                const exceptions = stats.failed + stats.unknown;
                return (
                  <tr key={batch.id}>
                    <td><button type="button" className="table-link table-link--stack" onClick={() => navigate(`/batches/${batch.id}`)}><strong>{batch.title}</strong><span>{batch.id}</span></button></td>
                    <td><strong>{stats.total} 件</strong><span className="cell-subtitle">{batch.sourcePage || "店小秘商品箱"} · {batch.storeName}</span></td>
                    <td><strong>{batch.templateName || "未冻结模板"}</strong><span className="cell-subtitle">整批一次批准</span></td>
                    <td><span className="result-count result-count--success">{stats.success} 成功</span>{stats.skipped > 0 && <span className="result-count">{stats.skipped} 隔离</span>}{stats.pending > 0 && <span className="result-count">{stats.pending} 等待</span>}</td>
                    <td>{exceptions > 0 ? <span className="result-count result-count--unknown"><WarningCircleIcon size={14} />{exceptions} 需对账</span> : <span className="result-count result-count--success">0</span>}</td>
                    <td><span className={`batch-status is-${statusTone(batch.status)}`}>{exceptions > 0 ? <WarningCircleIcon size={15} /> : null}{batchStatusLabel(batch.status)}</span></td>
                    <td><button type="button" className="table-action" onClick={() => navigate(`/batches/${batch.id}`)}>查看批次<ArrowRightIcon size={16} /></button></td>
                  </tr>
                );
              })}
              {!editBatches.length && (
                <tr><td colSpan="7"><strong>还没有编辑批次</strong><span className="cell-subtitle">先在店小秘商品箱准备范围，再创建批量编辑计划。</span></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <footer className="prototype-footer">
        <span>© 2026 店小秘 DXM</span>
        <span>未来批量目标原型 · 当前生产以受控 single_save 顺序编排</span>
        <span>{runtimeIdentity?.operator || "运营小秘"} · 只保存，不发布</span>
      </footer>
    </div>
  );
}
