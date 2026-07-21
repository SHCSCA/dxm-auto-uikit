import { useMemo, useRef, useState } from "react";
import {
  ArrowLeftIcon,
  BrowsersIcon,
  CaretRightIcon,
  CheckCircleIcon,
  CheckIcon,
  ClockIcon,
  FilesIcon,
  HandPalmIcon,
  HouseIcon,
  LockKeyIcon,
  MagnifyingGlassIcon,
  PauseIcon,
  PlayIcon,
  ShieldCheckIcon,
  SpinnerGapIcon,
  StorefrontIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

const defaultTask = {
  id: "DXM-20260720-001",
  title: "真实单商品只保存 - HUD全流程复验 - 0618-202624",
  productName: "HUD 抬头显示设备",
  image: "/assets/hud-clock-product.png",
  storeName: "AliExpress 半托管店铺",
  templateName: "HUD_半托管_只保存_通用模板 v1.3",
  sourceName: "历史复验来源 - 0618（半托管）",
  updatedAt: "2026-07-20 10:24:36",
};

const defaultActivities = [
  {
    id: "validate",
    tone: "active",
    title: "正在执行：模板校验",
    description: "正在校验商品信息与所选模板的匹配度、必填字段、类目与属性等…",
    time: "10:24:36",
  },
  {
    id: "draft",
    tone: "done",
    title: "已完成：已入商品箱",
    description: "商品已从待认领队列移入当前商品箱，开始加工流程。",
    time: "09:21:13",
  },
  {
    id: "claim",
    tone: "done",
    title: "已完成：待认领",
    description: "运营小秘已认领该商品，并完成商品箱精确回读。",
    time: "09:18:45",
  },
  {
    id: "edit",
    tone: "pending",
    title: "待执行：编辑只保存",
    description: "校验通过并获得第二次批准后，编辑为店小秘内部草稿，仅保存。",
  },
  {
    id: "unpublished",
    tone: "pending",
    title: "待执行：未发布验证",
    description: "独立确认无发布动作、无发布入口调用，商品仍为内部草稿。",
  },
];

const progressSteps = [
  { id: 1, label: "待认领", time: "2026-07-20 09:18" },
  { id: 2, label: "已入商品箱", time: "2026-07-20 09:21" },
  { id: 3, label: "模板校验" },
  { id: 4, label: "编辑只保存" },
  { id: 5, label: "未发布验证" },
];

const stageByPhase = {
  claim: { id: 1, label: "待认领" },
  draft_box_verify: { id: 2, label: "已入商品箱" },
  template_validation: { id: 3, label: "模板校验" },
  edit_save: { id: 4, label: "编辑只保存" },
  unpublished_verify: { id: 5, label: "未发布验证" },
  complete: { id: 5, label: "未发布验证" },
};

const stageByLabel = Object.fromEntries(
  Object.values(stageByPhase).map((stage) => [stage.label, stage]),
);

function SafetyBanner() {
  return (
    <section className="safety-banner" aria-label="安全边界" data-testid="cockpit-safety-banner">
      <div className="safety-banner__message">
        <ShieldCheckIcon size={24} weight="fill" aria-hidden="true" />
        <strong>只保存，不发布</strong>
        <span className="safety-banner__divider" aria-hidden="true" />
        <span>所有处理均为内部草稿，仅保存，不发布到任何平台或店铺。</span>
      </div>
      <div className="safety-banner__mode">
        <ShieldCheckIcon size={18} aria-hidden="true" />
        安全模式
      </div>
    </section>
  );
}

function resolveFlow(task, run) {
  return run?.flow || run?.status || task?.flow || task?.status || "approval";
}

function resolveStage(task, run, flow) {
  const interruptions = Array.isArray(run?.interruptions) ? run.interruptions : [];
  const interruption = interruptions[interruptions.length - 1];
  const phase = interruption?.phase || run?.phase;
  if (stageByPhase[phase]) return stageByPhase[phase];

  const taskStage = task?.stage || task?.step;
  if (stageByLabel[taskStage]) return stageByLabel[taskStage];
  if (flow === "editing") return stageByPhase.edit_save;
  if (flow === "verifying" || flow === "complete") return stageByPhase.unpublished_verify;
  return stageByPhase.template_validation;
}

function getFlowPresentation(flow) {
  return {
    approval: ["进行中", "info"],
    deferred: ["等待处理", "warning"],
    editing: ["正在只保存", "info"],
    verifying: ["正在安全验证", "info"],
    complete: ["已完成", "success"],
    paused: ["已暂停", "warning"],
    manual: ["人工接管", "warning"],
    blocked: ["需人工处理", "danger"],
    stopped: ["已终止", "danger"],
  }[flow] || ["进行中", "info"];
}

function TaskSummary({ task, flow, onContinue }) {
  const status = getFlowPresentation(flow);
  const cta = flow === "complete" ? "查看结果" : flow === "stopped" ? "查看历史证据" : flow === "paused" ? "恢复任务" : flow === "blocked" ? "查看问题" : "继续处理";
  return (
    <>
      <div className="page-heading cockpit-heading">
        <div className="cockpit-heading__title">
          <h1>当前任务</h1>
          <span className={`status-badge status-badge--${status[1]}`}>{status[0]}</span>
        </div>
      </div>
      <section className="task-card card" aria-labelledby="current-task-title">
        <div className="task-card__image">
          <img src={task.image || "/assets/hud-clock-product.png"} alt={task.productName || "当前任务商品"} />
        </div>
        <div className="task-card__body">
          <h2 id="current-task-title">{task.title}</h2>
          <dl className="task-meta">
            <div>
              <StorefrontIcon size={20} aria-hidden="true" />
              <dt>目标店铺</dt>
              <dd>{task.storeName}</dd>
            </div>
            <div>
              <FilesIcon size={20} aria-hidden="true" />
              <dt>选择模板</dt>
              <dd>{task.templateName}</dd>
            </div>
            <div>
              <HouseIcon size={20} aria-hidden="true" />
              <dt>来源任务</dt>
              <dd>{task.sourceName}</dd>
            </div>
          </dl>
        </div>
        <div className="task-card__actions">
          <button
            type="button"
            className="primary-button task-continue"
            onClick={onContinue}
            data-testid="continue-task-button"
          >
            {cta}
            <CaretRightIcon size={20} weight="bold" aria-hidden="true" />
          </button>
          <span>上次更新：{task.updatedAt}</span>
        </div>
      </section>
    </>
  );
}

function TaskProgress({ flow, stage }) {
  const heldFlow = ["paused", "manual", "deferred", "blocked", "stopped"].includes(flow);
  const currentStep = flow === "complete" ? 5 : stage.id;
  const completedThrough = flow === "complete" ? 5 : Math.max(0, currentStep - 1);
  const activeStep = flow === "complete" || heldFlow ? null : currentStep;
  const heldStep = heldFlow ? currentStep : null;
  const segmentTone = (segment) => {
    if (segment + 1 <= completedThrough) return "success";
    if (segment === completedThrough && (activeStep || heldStep)) return "active";
    return "pending";
  };

  return (
    <section className="progress-card card" aria-labelledby="progress-title" data-testid="task-progress">
      <h2 id="progress-title">处理进度</h2>
      <div className="progress-visual">
        <div className="progress-segments" aria-hidden="true">
          {[1, 2, 3, 4].map((segment) => (
            <span key={segment} className={`progress-segment progress-segment--${segmentTone(segment)}`} />
          ))}
        </div>
        <ol className="progress-track">
          {progressSteps.map((step) => {
            const complete = step.id <= completedThrough;
            const active = step.id === activeStep;
            const locked = step.id > (activeStep || heldStep || 5);
            const held = step.id === heldStep;
            return (
              <li
                key={step.id}
                className={`${complete ? "is-complete" : ""} ${active ? "is-active" : ""} ${held ? "is-held" : ""}`}
                data-testid={`progress-step-${step.id}`}
                aria-current={active || held ? "step" : undefined}
              >
                <div className="progress-track__rail" aria-hidden="true">
                  <span className="progress-track__node">{complete ? <CheckIcon size={18} weight="bold" /> : step.id}</span>
                </div>
                <div className="progress-track__label">
                  <strong>{step.id} &nbsp;{step.label}</strong>
                  {locked && <LockKeyIcon size={15} aria-label="尚未解锁" />}
                </div>
                <span className="progress-track__meta">
                  {held
                    ? flow === "manual" ? "人工接管中" : flow === "stopped" ? "已终止" : "已停止推进"
                    : active ? "进行中" : step.time || (complete ? "已完成" : "未开始")}
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

function getCurrentActivity(flow, stage) {
  return {
    editing: ["active", "正在执行：编辑只保存", "Agent 已获得本次单商品批准，正在逐字段填写并精确回读，仅触发保存草稿动作。"],
    verifying: ["active", "正在执行：未发布验证", "正在独立检查保存结果、页面状态与发布边界，确认商品仍为内部草稿。"],
    complete: ["done", "已完成：保存与未发布验证", "草稿保存回读成功；独立证据确认商品未发布。"],
    deferred: ["warning", "已暂缓：等待你的决定", "模板校验结果已保留，不会继续执行编辑或保存动作。"],
    paused: ["warning", `任务已暂停：${stage.label}`, `Agent 已停止推进，当前停留在「${stage.label}」，浏览器现场和证据保持不变。`],
    manual: ["warning", `人工接管：${stage.label}`, `Agent 已让出浏览器操作权，当前停留在「${stage.label}」，不会继续执行页面动作。`],
    blocked: ["warning", "任务已安全停止", "当前证据不足，后续编辑、保存和验证步骤均未执行。"],
    stopped: ["warning", "历史任务已终止", "这是只读历史状态；系统不会从中断位置继续执行或自动重试。"],
  }[flow];
}

function ActivityTimeline({ flow, stage, activities, evidenceCount, onOpenEvidence }) {
  const rendered = useMemo(() => {
    const current = getCurrentActivity(flow, stage);
    if (!current) return activities.slice(0, 5);
    return [
      {
        id: `dynamic-${flow}`,
        tone: current[0],
        title: current[1],
        description: current[2],
        time: "刚刚",
      },
      ...activities.filter((item) => item.id !== "validate"),
    ].slice(0, 5);
  }, [activities, flow, stage]);

  return (
    <section className="activity-card card" aria-labelledby="activity-title" data-testid="agent-activity-timeline">
      <h2 id="activity-title">Agent 正在做什么</h2>
      <div className="timeline">
        {rendered.map((item) => (
          <article className={`timeline-item timeline-item--${item.tone}`} key={item.id} data-testid={`activity-${item.id}`}>
            <div className="timeline-item__icon" aria-hidden="true">
              {item.tone === "done" ? (
                <CheckIcon size={16} weight="bold" />
              ) : item.tone === "warning" ? (
                <PauseIcon size={15} weight="fill" />
              ) : item.tone === "active" ? (
                <MagnifyingGlassIcon size={17} weight="bold" />
              ) : (
                <span />
              )}
            </div>
            <div className="timeline-item__content">
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </div>
            {item.time && <time>{item.time}</time>}
          </article>
        ))}
      </div>
      <button
        type="button"
        className="card-link"
        onClick={() => onOpenEvidence("all")}
        data-testid="evidence-all-button"
      >
        查看全部执行证据（{evidenceCount} 条）
        <CaretRightIcon size={17} aria-hidden="true" />
      </button>
    </section>
  );
}

function DecisionPanel({
  flow,
  stage,
  loading,
  highlighted,
  onApprove,
  onDefer,
  onResume,
  onReturnAgent,
  onOpenEvidence,
}) {
  if (flow === "complete") {
    return (
      <section className="decision-card card" aria-labelledby="decision-title" data-testid="decision-complete">
        <div className="decision-card__heading">
          <h2 id="decision-title">处理结果</h2>
          <span className="approval-badge approval-badge--success">已完成</span>
        </div>
        <div className="decision-box decision-box--success">
          <div className="decision-title-row">
            <CheckCircleIcon size={31} weight="fill" aria-hidden="true" />
            <div>
              <strong>草稿已保存，且确认未发布</strong>
              <p>保存结果、字段精确回读与未发布证明已分别核验。</p>
            </div>
          </div>
          <div className="result-pair">
            <span><CheckIcon size={16} weight="bold" />保存后字段精确回读</span>
            <span><ShieldCheckIcon size={17} weight="fill" />未发布证明通过</span>
          </div>
          <button type="button" className="primary-button decision-wide" onClick={() => onOpenEvidence("result")} data-testid="view-result-button">
            查看完整结果
          </button>
        </div>
        <button type="button" className="card-link" onClick={() => onOpenEvidence("all")}>查看证据与明细 <CaretRightIcon size={17} /></button>
      </section>
    );
  }

  if (flow === "editing" || flow === "verifying") {
    return (
      <section className="decision-card card" aria-labelledby="decision-title" aria-busy="true" data-testid="decision-running">
        <div className="decision-card__heading">
          <h2 id="decision-title">Agent 正在处理</h2>
          <span className="approval-badge approval-badge--info">安全执行中</span>
        </div>
        <div className="decision-box decision-box--running">
          <SpinnerGapIcon size={32} weight="bold" className="spin" aria-hidden="true" />
          <strong>{flow === "editing" ? "正在编辑并只保存" : "正在独立验证未发布"}</strong>
          <p>{flow === "editing" ? "逐字段填写、精确回读并核对，不触发任何发布动作。" : "正在交叉检查保存证据和页面发布状态。"}</p>
          <div className="running-meter" aria-hidden="true"><span className={flow === "verifying" ? "is-wide" : ""} /></div>
        </div>
        <button type="button" className="card-link" onClick={() => onOpenEvidence("all")}>查看实时证据 <CaretRightIcon size={17} /></button>
      </section>
    );
  }

  if (["paused", "manual", "deferred", "blocked", "stopped"].includes(flow)) {
    const copy = {
      paused: [PauseIcon, `任务已暂停：${stage.label}`, `Agent 不会继续推进。当前停留在「${stage.label}」，恢复后从该阶段继续。`, "恢复 Agent 任务", onResume],
      manual: [HandPalmIcon, `人工接管：${stage.label}`, `系统保持「${stage.label}」的浏览器现场，不会替你继续点击或保存。`, "交还给 Agent", onReturnAgent],
      deferred: [ClockIcon, "本次决定已暂缓", "模板校验结果已保存，后续步骤仍保持锁定。", "重新处理决定", onResume],
      blocked: [WarningCircleIcon, "证据不足，任务已停止", "系统不会猜测继续。请先查看证据并处理当前问题。", "查看阻断证据", () => onOpenEvidence("blocked")],
      stopped: [WarningCircleIcon, "历史任务已终止", "该记录只供审计查看，不提供恢复、重试或继续处理。", "查看历史证据", () => onOpenEvidence("all")],
    }[flow];
    const StateIcon = copy[0];
    return (
      <section className="decision-card card" aria-labelledby="decision-title" data-testid={`decision-${flow}`}>
        <div className="decision-card__heading">
          <h2 id="decision-title">需要你处理</h2>
          <span className="approval-badge">等待处理</span>
        </div>
        <div className="decision-box decision-box--waiting">
          <div className="decision-title-row">
            <StateIcon size={31} weight="fill" aria-hidden="true" />
            <div><strong>{copy[1]}</strong><p>{copy[2]}</p></div>
          </div>
          <button type="button" className="primary-button decision-wide" onClick={copy[4]} data-testid={`${flow}-primary-action`}>{copy[3]}</button>
        </div>
        <button type="button" className="card-link" onClick={() => onOpenEvidence(flow === "blocked" ? "blocked" : "category")}>
          查看证据与明细 <CaretRightIcon size={17} />
        </button>
      </section>
    );
  }

  return (
    <section
      className={`decision-card card${highlighted ? " is-highlighted" : ""}`}
      aria-labelledby="decision-title"
      tabIndex="-1"
      data-testid="template-approval-panel"
    >
      <div className="decision-card__heading">
        <h2 id="decision-title">需要你决定</h2>
        <span className="approval-badge">需审批</span>
      </div>
      <div className="decision-box">
        <div className="decision-title-row">
          <WarningCircleIcon size={31} weight="fill" aria-hidden="true" />
          <div>
            <strong>模板校验发现类目不一致</strong>
            <p>商品类目与模板类目存在差异，请确认是否按模板规则调整。</p>
          </div>
        </div>
        <div className="impact-box">
          <strong>影响</strong>
          <ul>
            <li>可能导致部分属性字段映射不准确</li>
            <li>不影响只保存流程的安全性</li>
          </ul>
        </div>
        <div className="decision-actions">
          <button type="button" className="secondary-button" onClick={onDefer} disabled={Boolean(loading)} data-testid="defer-decision-button">
            {loading === "defer" ? "处理中…" : "暂不处理，稍后再看"}
          </button>
          <button type="button" className="primary-button" onClick={onApprove} disabled={Boolean(loading)} data-testid="approve-template-button">
            {loading === "approve" && <SpinnerGapIcon size={17} className="spin" aria-hidden="true" />}
            {loading === "approve" ? "正在确认…" : "确认按模板处理"}
          </button>
        </div>
      </div>
      <button type="button" className="card-link" onClick={() => onOpenEvidence("category")} data-testid="evidence-category-button">
        查看证据与明细
        <CaretRightIcon size={17} aria-hidden="true" />
      </button>
    </section>
  );
}

export default function TaskCockpitPage({
  task = defaultTask,
  run = { flow: "approval" },
  activities = defaultActivities,
  evidences = [],
  onApprove = () => {},
  onDefer = () => {},
  onPause = () => {},
  onTakeover = () => {},
  onResume = () => {},
  onReturnAgent = () => {},
  onOpenEvidence = () => {},
  onOpenTasks = () => {},
  notify = () => {},
  readOnly = false,
}) {
  const safeTask = { ...defaultTask, ...(task || {}) };
  const safeActivities = Array.isArray(activities) ? activities : defaultActivities;
  const flow = resolveFlow(safeTask, run);
  const stage = resolveStage(safeTask, run, flow);
  const evidenceCount = Array.isArray(evidences) ? evidences.length : 0;
  const [loading, setLoading] = useState("");
  const [highlighted, setHighlighted] = useState(false);
  const decisionRef = useRef(null);

  const invoke = async (kind, action, successMessage) => {
    if (loading) return;
    setLoading(kind);
    try {
      const result = await action?.(safeTask.id);
      if (result === false || result?.ok === false) throw new Error(result?.message || "操作未完成");
      notify(successMessage, "success");
    } catch (error) {
      notify(error?.message || "操作未完成，请查看当前证据", "warning");
    } finally {
      setLoading("");
    }
  };

  const continueTask = () => {
    if (flow === "complete") {
      onOpenEvidence("result");
      return;
    }
    if (flow === "paused" || flow === "deferred") {
      invoke("resume", onResume, `任务已恢复到「${stage.label}」`);
      return;
    }
    if (flow === "blocked" || flow === "stopped") {
      onOpenEvidence(flow === "blocked" ? "blocked" : "all");
      return;
    }
    setHighlighted(true);
    decisionRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    decisionRef.current?.focus({ preventScroll: true });
    window.setTimeout(() => setHighlighted(false), 1200);
  };

  const pauseTask = () => {
    if (flow === "complete") {
      notify("任务已完成，无需暂停");
      return;
    }
    if (flow === "paused") {
      invoke("resume", onResume, `任务已恢复到「${stage.label}」`);
      return;
    }
    const result = onPause(safeTask.id);
    if (result === false || result?.ok === false) notify(result?.message || "该任务不能暂停", "warning");
    else notify("任务已安全暂停，现场与证据保持不变");
  };

  const takeover = () => {
    const result = onTakeover(safeTask.id);
    if (result === false || result?.ok === false) notify(result?.message || "该任务不能人工接管", "warning");
    else notify("Agent 已暂停并让出可见浏览器操作权");
  };

  return (
    <div className="task-workspace task-cockpit-page" data-testid="task-cockpit-page">
      <SafetyBanner />
      <div className="cockpit-toolbar" aria-label="任务操作">
        <button type="button" className="back-link" onClick={onOpenTasks} data-testid="back-to-tasks-button">
          <ArrowLeftIcon size={17} aria-hidden="true" />返回任务列表
        </button>
        <div className="cockpit-toolbar__actions">
          <span className="runtime-chip"><BrowsersIcon size={17} />本地原型 · 未连接店小秘</span>
          <button type="button" className="secondary-button" onClick={pauseTask} disabled={readOnly || flow === "complete" || flow === "stopped"} data-testid="pause-agent-button">
            {flow === "paused" ? <PlayIcon size={17} /> : <PauseIcon size={17} />}
            {flow === "paused" ? "恢复 Agent" : "暂停 Agent"}
          </button>
          <button type="button" className="secondary-button" onClick={takeover} disabled={readOnly || flow === "manual" || flow === "complete" || flow === "stopped"} data-testid="manual-takeover-button">
            <HandPalmIcon size={17} />人工接管
          </button>
        </div>
      </div>
      <TaskSummary task={safeTask} flow={flow} onContinue={continueTask} />
      <TaskProgress flow={flow} stage={stage} />
      <div className="work-grid" ref={decisionRef}>
        <ActivityTimeline
          flow={flow}
          stage={stage}
          activities={safeActivities}
          evidenceCount={evidenceCount}
          onOpenEvidence={onOpenEvidence}
        />
        <DecisionPanel
          flow={flow}
          stage={stage}
          loading={loading}
          highlighted={highlighted}
          onApprove={() => invoke("approve", onApprove, "批准已记录，开始只保存加工")}
          onDefer={() => invoke("defer", onDefer, "决定已暂缓，后续步骤保持锁定")}
          onResume={() => invoke("resume", onResume, `任务已恢复到「${stage.label}」`)}
          onReturnAgent={() => onReturnAgent(safeTask.id)}
          onOpenEvidence={onOpenEvidence}
        />
      </div>
      <footer className="app-footer">
        <span>© 2026 店小秘 DXM</span>
        <span>只保存，不发布。系统不提供任何发布能力。</span>
      </footer>
    </div>
  );
}
