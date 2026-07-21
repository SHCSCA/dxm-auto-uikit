import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowSquareOutIcon,
  BrowserIcon,
  CheckCircleIcon,
  CheckSquareIcon,
  FingerprintIcon,
  ListNumbersIcon,
  PlayIcon,
  ShieldCheckIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { buildApprovalFingerprint, buildTemplateSnapshot, useBatchPrototype } from "../state/BatchPrototypeContext.jsx";

const steps = ["读取商品箱", "冻结批次范围", "锁定编辑模板", "整批一次批准"];
const scene = {
  title: "读取店小秘商品箱当前现场",
  source: "速卖通 → 商品箱",
  url: "/web/smt/smtProductList/draft",
  current: "商品箱当前筛选、排序与可见商品顺序",
  target: "商品身份、店铺归属与当前浏览器 Session 随现场读回",
  note: "先在店小秘中准备商品范围；本系统只冻结现场快照，不提供本地商品或店铺选择器。",
};

function formatVersion(version) {
  const value = String(version || "—");
  return value.startsWith("v") ? value : `v${value}`;
}

function templateRuleCount(template) {
  return (template.sections || []).reduce((total, section) => total + (section.rules?.length || section.fieldCount || 0), 0);
}

function Stepper({ step }) {
  return (
    <ol className="batch-stepper" aria-label="创建批量编辑步骤">
      {steps.map((label, index) => {
        const number = index + 1;
        const state = number < step ? "done" : number === step ? "active" : "pending";
        return <li key={label} className={`is-${state}`}><span>{number < step ? <CheckCircleIcon size={17} weight="fill" /> : number}</span><strong>{label}</strong></li>;
      })}
    </ol>
  );
}

function DxmSceneStep({ confirmed, onConfirm, onOpenBrowser }) {
  return (
    <section className="builder-panel" aria-labelledby="scene-step-title">
      <div className="builder-panel__head">
        <div className="builder-panel__icon"><BrowserIcon size={24} /></div>
        <div><span>步骤 1</span><h2 id="scene-step-title">{scene.title}</h2><p>{scene.note}</p></div>
      </div>

      <div className="dxm-scene-grid">
        <article className="dxm-scene-card dxm-scene-card--primary">
          <div className="dxm-scene-card__head"><BrowserIcon size={20} weight="duotone" /><span>店小秘真实页面</span></div>
          <strong>{scene.source}</strong>
          <code>{scene.url}</code>
          <p>在可见浏览器中完成筛选与排序后再读取。商品主数据始终留在店小秘，控制台不复制一套商品管理页面。</p>
          <button type="button" className="secondary-button" onClick={onOpenBrowser}><ArrowSquareOutIcon size={17} />打开真实店小秘</button>
        </article>
        <article className="dxm-scene-card">
          <div className="dxm-scene-card__head"><FingerprintIcon size={20} weight="duotone" /><span>将被冻结的现场事实</span></div>
          <dl>
            <div><dt>商品范围</dt><dd>{scene.current}</dd></div>
            <div><dt>身份边界</dt><dd>{scene.target}</dd></div>
            <div><dt>主数据归属</dt><dd>店小秘</dd></div>
          </dl>
        </article>
      </div>

      <div className="dxm-readback-strip" data-testid="dxm-scene-readback">
        <span className={`live-dot${confirmed ? "" : " is-simulated"}`} />
        <div>
          <strong>{confirmed ? "商品箱筛选快照已读取" : "等待读取当前店小秘商品箱"}</strong>
          <span>{confirmed ? "已记录来源页、筛选摘要、顺序与现场时间；下一步只设置停止上限。" : "当前为可交互原型；正式接入时由真实浏览器 Session 返回签名快照。"}</span>
        </div>
        <button type="button" className={confirmed ? "secondary-button" : "primary-button"} onClick={onConfirm}>
          {confirmed ? <CheckCircleIcon size={18} weight="fill" /> : <BrowserIcon size={18} />}{confirmed ? "重新读取快照" : "模拟读取商品箱现场"}
        </button>
      </div>

      <div className="builder-note"><WarningCircleIcon size={18} weight="fill" /><span>这是未来批次编排目标。当前生产后端仍只放行受控的 single_save 子任务，尚未宣称支持整批无人值守。</span></div>
    </section>
  );
}

function ScopeStep({ maxItems, onMaxItems, confirmed, onConfirm }) {
  return (
    <section className="builder-panel" aria-labelledby="scope-step-title">
      <div className="builder-panel__head">
        <div className="builder-panel__icon"><ListNumbersIcon size={24} /></div>
        <div><span>步骤 2</span><h2 id="scope-step-title">冻结有序批次范围</h2><p>不在本系统挑商品，只冻结店小秘当前筛选结果的前 N 件及其顺序。</p></div>
      </div>

      <div className="dxm-scope-layout">
        <div className="dxm-scope-field">
          <label htmlFor="batch-max-items">冻结当前范围前</label>
          <select id="batch-max-items" value={maxItems} onChange={(event) => onMaxItems(Number(event.target.value))}>
            {[3, 5, 6].map((value) => <option key={value} value={value}>{value} 件</option>)}
          </select>
          <small>这是对店小秘现场结果的停止上限，不是本地商品清单；批准后顺序不可静默变化。</small>
        </div>
        <dl className="dxm-scope-facts">
          <div><dt>来源页</dt><dd>{scene.source}</dd></div>
          <div><dt>取件顺序</dt><dd>店小秘当前筛选与排序</dd></div>
          <div><dt>执行并发</dt><dd>严格 1 件</dd></div>
          <div><dt>继续方式</dt><dd>成功后自动派发下一件</dd></div>
        </dl>
      </div>

      <ol className="single-item-loop" aria-label="自动串行编辑合同">
        <li><span>1</span><strong>整批批准一次</strong><small>冻结范围与模板</small></li>
        <li><ArrowRightIcon size={17} /></li>
        <li><span>2</span><strong>自动读取当前件</strong><small>一次只锁定 1 件</small></li>
        <li><ArrowRightIcon size={17} /></li>
        <li><span>3</span><strong>逐字段编辑并只保存</strong><small>独立 single_save 子任务</small></li>
        <li><ArrowRightIcon size={17} /></li>
        <li><span>4</span><strong>安全结果后自动继续</strong><small>无需逐件点击</small></li>
      </ol>

      <label className={`approval-consent${confirmed ? " is-checked" : ""}`}>
        <input type="checkbox" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} />
        <CheckSquareIcon size={22} weight={confirmed ? "fill" : "regular"} />
        <span><strong>我已在店小秘中准备好当前筛选与顺序</strong><small>批准后若商品身份、筛选摘要或 Session 漂移，整批停止并要求人工对账。</small></span>
      </label>
    </section>
  );
}

function RulesStep({ templates, templateId, onTemplate, maxItems }) {
  const readyTemplates = templates.filter((template) => template.status === "ready");
  return (
    <section className="builder-panel" aria-labelledby="rules-step-title">
      <div className="builder-panel__head"><div className="builder-panel__icon"><FingerprintIcon size={24} /></div><div><span>步骤 3</span><h2 id="rules-step-title">锁定当前项目字段模板</h2><p>模板版本与内容摘要进入批次授权；执行中模板变化会使未派发商品停止。</p></div></div>
      <div className="template-choice-grid">
        {readyTemplates.map((template) => (
          <label key={template.id} className={`template-choice${templateId === template.id ? " is-selected" : ""}`}>
            <input type="radio" name="template" value={template.id} checked={templateId === template.id} onChange={() => onTemplate(template.id)} />
            <span><strong>{template.name}</strong><small>{formatVersion(template.version)} · {template.scope}</small></span>
            <em>{templateRuleCount(template)} 个真实字段</em>
          </label>
        ))}
      </div>
      <div className="execution-contract">
        <div><ShieldCheckIcon size={21} weight="fill" /><strong>{maxItems} 件共用一次批次授权，后台严格单件串行</strong></div>
        <ul>
          <li>批准后不再要求用户逐件审核或手动触发后续商品。</li>
          <li>每件仍是独立 single_save 安全子任务；上一件结束后才允许派发下一件。</li>
          <li>保存前、可证明未写入的校验失败可隔离并继续；保存回读与未发布证明必须分别成立。</li>
          <li>UNKNOWN、身份漂移、Session 丢失或发布风险会整批停止，禁止自动重试。</li>
        </ul>
      </div>
    </section>
  );
}

function ApprovalStep({ maxItems, template, consent, onConsent }) {
  const templateSnapshot = buildTemplateSnapshot(template);
  const approvalHash = buildApprovalFingerprint({
    storeId: "dxm-live-draft-box-scope",
    productIds: Array.from({ length: maxItems }, (_, index) => `live-snapshot-ordinal-${index + 1}`),
    templateSnapshot,
  });
  return (
    <section className="builder-panel" aria-labelledby="approval-step-title">
      <div className="builder-panel__head"><div className="builder-panel__icon"><ShieldCheckIcon size={24} /></div><div><span>步骤 4</span><h2 id="approval-step-title">一次批准整个批次</h2><p>这次确认同时绑定商品箱现场快照、顺序、模板版本、只保存边界和自动串行策略。</p></div></div>
      <dl className="approval-facts">
        <div><dt>流程</dt><dd>批量编辑商品</dd></div>
        <div><dt>店小秘来源</dt><dd>{scene.source}<small>{scene.url}</small></dd></div>
        <div><dt>商品与店铺</dt><dd>随现场快照读回<small>本系统不提供商品或店铺选择器</small></dd></div>
        <div><dt>冻结范围</dt><dd>{maxItems} 件<small>严格单件串行，成功后自动继续</small></dd></div>
        <div><dt>模板快照</dt><dd>{templateSnapshot ? `${templateSnapshot.name} ${templateSnapshot.version}` : "未选择"}<small>{templateSnapshot?.ruleCount || 0} 个当前项目字段</small></dd></div>
        <div><dt>批准摘要预览</dt><dd><code>{approvalHash}</code><small>创建时会由实际有序商品指纹生成最终摘要</small></dd></div>
      </dl>
      <label className={`approval-consent${consent ? " is-checked" : ""}`}>
        <input type="checkbox" checked={consent} onChange={(event) => onConsent(event.target.checked)} />
        <CheckSquareIcon size={22} weight={consent ? "fill" : "regular"} />
        <span><strong>我批准按当前快照和模板连续编辑这 {maxItems} 件商品</strong><small>正常结果自动继续；我只会在异常、暂停、接管或停止派发时再次介入。</small></span>
      </label>
    </section>
  );
}

export default function BatchFlowPage({ templates = [], notify }) {
  const navigate = useNavigate();
  const { createBatch, startBatch } = useBatchPrototype();
  const [step, setStep] = useState(1);
  const [sceneConfirmed, setSceneConfirmed] = useState(false);
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [maxItems, setMaxItems] = useState(5);
  const [templateId, setTemplateId] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const titleRef = useRef(null);

  const selectedTemplate = templates.find((template) => template.id === templateId);

  const openRealDxmPage = () => {
    const opened = window.open(`https://www.dianxiaomi.com${scene.url}`, "_blank", "noopener,noreferrer");
    if (!opened) notify?.("浏览器阻止了店小秘页面；请允许弹窗后重试", "warning");
    else notify?.("已打开店小秘真实商品箱；当前原型不会读取账号或代替你操作");
  };

  const moveTo = (nextStep) => {
    setError("");
    setStep(nextStep);
    window.requestAnimationFrame(() => titleRef.current?.focus());
  };

  const next = () => {
    if (step === 1 && !sceneConfirmed) return setError("请先读取当前店小秘商品箱现场");
    if (step === 2 && !scopeConfirmed) return setError("请确认已在店小秘中准备当前筛选与顺序");
    if (step === 3 && (!selectedTemplate || selectedTemplate.status !== "ready")) return setError("请选择一个已就绪、包含当前项目字段的模板版本");
    moveTo(Math.min(4, step + 1));
  };

  const submit = async () => {
    if (!consent) return setError("请先批准整个批次的现场快照、模板与自动串行边界");
    setSubmitting(true);
    const result = await createBatch({
      template: selectedTemplate,
      maxItems,
      intakeDescription: `${scene.source}当前筛选范围 · 已冻结 ${maxItems} 件有序快照`,
      sourcePage: scene.source,
      scopeSnapshot: { filterSummary: "店小秘当前筛选与排序" },
    });
    if (!result?.ok) {
      setSubmitting(false);
      setConsent(false);
      setError(result?.message || "批次创建失败，请重新读取店小秘现场");
      notify?.(result?.message || "批次创建失败", "warning");
      return;
    }
    const started = await startBatch(result.batch.id);
    setSubmitting(false);
    if (!started?.ok) {
      notify?.(`${result.batch.id} 已批准，但自动队列未启动：${started?.message || "未知原因"}`, "warning");
    } else {
      notify?.(`${result.batch.id} 已整批批准；自动串行编辑已开始`);
    }
    navigate(`/batches/${result.batch.id}`);
  };

  return (
    <div className="batch-page batch-builder batch-builder--edit" data-testid="edit-batch-builder">
      <section className="batch-boundary" aria-label="批次安全边界"><ShieldCheckIcon size={22} weight="fill" /><div><strong>批量编辑 · 依附店小秘商品箱现场</strong><span>范围由店小秘当前筛选快照提供；本系统只锁定模板、自动串行边界与证据。</span></div><span className="batch-boundary__pill">整批一次批准</span></section>
      <header className="batch-page__header">
        <div><button type="button" className="back-link" onClick={() => navigate("/tasks/current")}><ArrowLeftIcon size={17} />返回工作台</button><h1 tabIndex="-1" ref={titleRef}>创建批量编辑任务</h1><p>冻结一次店小秘现场，批准一次；随后后台严格单件串行，安全完成后自动进入下一件。</p></div>
        <div className="builder-progress-copy"><strong>{step} / 4</strong><span>{steps[step - 1]}</span></div>
      </header>
      <Stepper step={step} />

      {step === 1 && <DxmSceneStep confirmed={sceneConfirmed} onConfirm={() => { setSceneConfirmed(true); setConsent(false); notify?.("已记录一次本地原型快照；未连接真实店小秘"); }} onOpenBrowser={openRealDxmPage} />}
      {step === 2 && <ScopeStep maxItems={maxItems} onMaxItems={(value) => { setMaxItems(value); setConsent(false); }} confirmed={scopeConfirmed} onConfirm={setScopeConfirmed} />}
      {step === 3 && <RulesStep templates={templates} templateId={templateId} onTemplate={(value) => { setTemplateId(value); setConsent(false); }} maxItems={maxItems} />}
      {step === 4 && <ApprovalStep maxItems={maxItems} template={selectedTemplate} consent={consent} onConsent={setConsent} />}

      {error && <div className="builder-error" role="alert"><WarningCircleIcon size={19} weight="fill" />{error}</div>}
      <div className="builder-actions">
        <button type="button" className="secondary-button" onClick={() => step === 1 ? navigate("/tasks/current") : moveTo(step - 1)}>{step === 1 ? "取消" : "上一步"}</button>
        {step < 4 ? <button type="button" className="primary-button" onClick={next}>下一步：{steps[step]}<ArrowRightIcon size={18} /></button> : <button type="button" className="primary-button" onClick={submit} disabled={!consent || submitting}><PlayIcon size={18} weight="fill" />{submitting ? "正在冻结并启动…" : `批准 ${maxItems} 件并开始自动编辑`}</button>}
      </div>
      <footer className="prototype-footer"><span>商品主数据在店小秘</span><span>一次批准 · 单件串行 · 正常自动继续</span><span>目标原型 · 生产仍为 single_save 子任务</span></footer>
    </div>
  );
}
