import { useMemo, useState } from "react";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BrowsersIcon,
  CaretRightIcon,
  CheckCircleIcon,
  CheckIcon,
  ClipboardTextIcon,
  LockKeyIcon,
  PlusIcon,
  ShieldCheckIcon,
  StorefrontIcon,
  UserIcon,
  WarningCircleIcon,
  XIcon,
} from "@phosphor-icons/react";

const filterOptions = [
  { id: "all", label: "全部" },
  { id: "attention", label: "等待我处理" },
  { id: "running", label: "运行中" },
  { id: "blocked", label: "需人工处理" },
  { id: "complete", label: "已完成" },
  { id: "stopped", label: "已终止" },
];

const statusCopy = {
  draft: ["待配置", "neutral"],
  awaiting_claim_approval: ["待批准认领", "warning"],
  claiming: ["正在认领", "info"],
  claimed: ["已入商品箱", "success"],
  validating: ["正在校验模板", "info"],
  approval: ["待批准编辑", "warning"],
  editing: ["正在编辑只保存", "info"],
  verifying: ["正在验证未发布", "info"],
  complete: ["已完成", "success"],
  paused: ["已停止推进", "warning"],
  manual: ["需人工处理", "danger"],
  blocked: ["需人工处理", "danger"],
  stopped: ["已终止", "neutral"],
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

const defaultTasks = [
  {
    id: "DXM-20260720-001",
    title: "真实单商品只保存 - HUD全流程复验",
    productName: "HUD 抬头显示设备",
    storeName: "AliExpress 半托管店铺",
    templateName: "HUD_半托管_只保存_通用模板 v1.3",
    step: "模板校验",
    status: "approval",
    updatedAt: "2026-07-20 10:24:36",
  },
  {
    id: "DXM-20260719-004",
    title: "单商品只保存 - 配件复验",
    productName: "车载电子配件",
    storeName: "AliExpress 半托管店铺",
    templateName: "半托管_电子配件模板 v1.2",
    step: "未发布验证",
    status: "complete",
    updatedAt: "2026-07-19 16:42:09",
  },
];

function SafetyBanner() {
  return (
    <section className="safety-banner" aria-label="安全边界" data-testid="tasks-safety-banner">
      <div className="safety-banner__message">
        <ShieldCheckIcon size={24} weight="fill" aria-hidden="true" />
        <strong>只保存，不发布</strong>
        <span className="safety-banner__divider" aria-hidden="true" />
        <span>商品与店铺均来自店小秘现场；每次只读取并处理 1 件，所有真实动作均需人工批准。</span>
      </div>
      <div className="safety-banner__mode">
        <ShieldCheckIcon size={18} aria-hidden="true" />
        安全模式
      </div>
    </section>
  );
}

function getTaskGroup(status) {
  if (["approval", "awaiting_claim_approval", "paused"].includes(status)) return "attention";
  if (["claiming", "claimed", "validating", "editing", "verifying"].includes(status)) return "running";
  if (["manual", "blocked"].includes(status)) return "blocked";
  if (status === "complete") return "complete";
  if (status === "stopped") return "stopped";
  return "all";
}

function TaskList({ tasks, filter, onFilter, onOpenTask, onStartCreate, activeTask }) {
  const filteredTasks = useMemo(
    () => tasks.filter((task) => filter === "all" || getTaskGroup(task.status) === filter),
    [filter, tasks],
  );

  return (
    <>
      <div className="page-heading tasks-page__heading">
        <div>
          <h1>任务</h1>
          <p>本系统不提供商品清单；每次从店小秘当前页面读取 1 件并单独批准。</p>
        </div>
        <button
          type="button"
          className="primary-button"
          onClick={onStartCreate}
          disabled={Boolean(activeTask)}
          data-testid="new-single-task-button"
          aria-describedby={activeTask ? "active-task-limit" : undefined}
        >
          <PlusIcon size={18} weight="bold" aria-hidden="true" />
          新建现场单件任务
        </button>
      </div>

      {activeTask && (
        <div className="task-limit-notice" id="active-task-limit" role="status" data-testid="active-task-limit">
          <LockKeyIcon size={20} aria-hidden="true" />
          <div>
            <strong>已有任务正在运行</strong>
            <span>为确保授权和证据绑定同一个商品，当前只能运行一个任务。</span>
          </div>
          <button type="button" className="secondary-button" onClick={() => onOpenTask(activeTask.id)}>
            查看当前任务
          </button>
        </div>
      )}

      <section className="tasks-card card" aria-labelledby="task-list-title">
        <div className="tasks-card__toolbar">
          <div>
            <h2 id="task-list-title">任务列表</h2>
            <span>{filteredTasks.length} 个任务</span>
          </div>
          <div className="filter-tabs" role="tablist" aria-label="筛选任务状态" onKeyDown={handleTablistKeyDown}>
            {filterOptions.map((option) => (
              <button
                key={option.id}
                type="button"
                role="tab"
                aria-selected={filter === option.id}
                tabIndex={filter === option.id ? 0 : -1}
                className={filter === option.id ? "is-active" : ""}
                onClick={() => onFilter(option.id)}
                data-testid={`task-filter-${option.id}`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        {filteredTasks.length ? (
          <div className="tasks-table-wrap">
            <table className="tasks-table">
              <thead>
                <tr>
                  <th scope="col">任务</th>
                  <th scope="col">目标店铺</th>
                  <th scope="col">模板版本</th>
                  <th scope="col">当前步骤</th>
                  <th scope="col">状态</th>
                  <th scope="col">最后更新</th>
                  <th scope="col"><span className="sr-only">操作</span></th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task) => {
                  const status = statusCopy[task.status] || [task.status || "待配置", "neutral"];
                  return (
                    <tr key={task.id} data-testid={`task-row-${task.id}`}>
                      <td>
                        <button type="button" className="task-name-button" onClick={() => onOpenTask(task.id)}>
                          <strong>{task.title}</strong>
                          <span>{task.productName}</span>
                        </button>
                      </td>
                      <td>{task.storeName}</td>
                      <td>{task.templateName}</td>
                      <td>{task.step}</td>
                      <td><span className={`status-badge status-badge--${status[1]}`}>{status[0]}</span></td>
                      <td><time>{task.updatedAt}</time></td>
                      <td>
                        <button
                          type="button"
                          className="table-action"
                          onClick={() => onOpenTask(task.id)}
                          aria-label={`进入任务：${task.title}`}
                          data-testid={`open-task-${task.id}`}
                        >
                          {task.status === "complete" ? "查看结果" : task.status === "blocked" ? "查看问题" : "进入任务"}
                          <CaretRightIcon size={16} aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state" data-testid="empty-task-list">
            <ClipboardTextIcon size={42} weight="duotone" aria-hidden="true" />
            <strong>{tasks.length ? "没有符合条件的任务" : "还没有任务"}</strong>
            <p>{tasks.length ? "尝试切换其他状态筛选。" : "先在店小秘准备当前商品与目标店铺，再创建第一个现场单件任务。"}</p>
            {!tasks.length && <button type="button" className="primary-button" onClick={onStartCreate}>新建任务</button>}
          </div>
        )}
      </section>
    </>
  );
}

function WizardStepper({ step }) {
  const steps = ["运行身份", "店小秘现场", "批准本件"];
  return (
    <ol className="wizard-stepper" aria-label="新建任务进度" data-testid="new-task-stepper">
      {steps.map((label, index) => {
        const number = index + 1;
        const complete = number < step;
        const active = number === step;
        return (
          <li key={label} className={`${complete ? "is-complete" : ""} ${active ? "is-active" : ""}`} aria-current={active ? "step" : undefined}>
            <span>{complete ? <CheckIcon size={15} weight="bold" /> : number}</span>
            <strong>{label}</strong>
          </li>
        );
      })}
    </ol>
  );
}

function RuntimeStep({ runtimeIdentity }) {
  const connected = runtimeIdentity?.connected !== false;
  const simulation = runtimeIdentity?.simulation === true;
  return (
    <section className="wizard-panel" aria-labelledby="runtime-step-title" data-testid="wizard-step-runtime">
      <div className="wizard-panel__intro">
        <span className="wizard-panel__icon"><UserIcon size={25} weight="duotone" /></span>
        <div>
          <h2 id="runtime-step-title">核对运行身份与可见 Session</h2>
          <p>这里不选择商品或店铺；本次授权只绑定随后从店小秘现场读回的单件任务。</p>
        </div>
      </div>
      <div className={`runtime-card${connected ? " is-connected" : " is-disconnected"}`}>
        <div className="runtime-card__status">
          {connected ? <CheckCircleIcon size={24} weight="fill" /> : <WarningCircleIcon size={24} weight="fill" />}
          <div>
            <strong>{simulation ? "本地模拟运行身份" : connected ? "运行身份已连接" : "尚未连接可见浏览器"}</strong>
            <span>{simulation ? "可演练逐件合同；未连接、读取或修改真实店小秘。" : connected ? "可在同一可见 Session 中读取店小秘当前商品与店铺。" : "连接前不会读取或修改店小秘。"}</span>
          </div>
        </div>
        <dl className="runtime-facts">
          <div><dt>运行账号</dt><dd>{runtimeIdentity?.operator || "运营小秘"}</dd></div>
          <div><dt>店铺来源</dt><dd>店小秘认领弹窗现场读回</dd></div>
          <div><dt>{simulation ? "原型会话" : "可见浏览器"}</dt><dd>{runtimeIdentity?.browser || "DXM 可见浏览器 · 会话 8A21"}</dd></div>
          <div><dt>授权范围</dt><dd>当前店铺 · 当前任务 · 仅认领</dd></div>
        </dl>
      </div>
    </section>
  );
}

function DxmSceneStep({ confirmed, onConfirm }) {
  return (
    <section className="wizard-panel" aria-labelledby="product-step-title" data-testid="wizard-step-dxm-scene">
      <div className="wizard-panel__intro">
        <span className="wizard-panel__icon"><StorefrontIcon size={25} weight="duotone" /></span>
        <div>
          <h2 id="product-step-title">准备店小秘当前商品与店铺</h2>
          <p>商品筛选、当前行和认领店铺都留在店小秘；本系统没有可勾选的商品或店铺列表。</p>
        </div>
      </div>
      <div className="runtime-card is-connected">
        <div className="runtime-card__status">
          <BrowsersIcon size={24} weight="fill" />
          <div><strong>唯一真实店小秘浏览器</strong><span>执行时读取待认领商品页当前行，并在认领弹窗核对当前选中店铺。</span></div>
        </div>
        <dl className="runtime-facts">
          <div><dt>商品来源</dt><dd>店小秘待认领商品页当前行</dd></div>
          <div><dt>目标店铺</dt><dd>店小秘认领弹窗当前选中项</dd></div>
          <div><dt>本系统商品清单</dt><dd>不存在</dd></div>
          <div><dt>继续方式</dt><dd>当前件闭合后显式开始下一件</dd></div>
        </dl>
        <label className="approval-consent">
          <input type="checkbox" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} data-testid="dxm-scene-confirmed" />
          <span>我已在店小秘中准备好当前筛选、排序和认领店铺；任何现场变化都以真实浏览器为准。</span>
        </label>
      </div>
    </section>
  );
}

function ApprovalStep({ runtimeIdentity, consent, onConsent }) {
  return (
    <section className="wizard-panel" aria-labelledby="approval-step-title" data-testid="wizard-step-approval">
      <div className="wizard-panel__intro">
        <span className="wizard-panel__icon"><ShieldCheckIcon size={25} weight="duotone" /></span>
        <div>
          <h2 id="approval-step-title">确认本次任务边界</h2>
          <p>本次批准只覆盖执行时从店小秘现场读回的当前 1 件；后续编辑和下一件都必须重新批准。</p>
        </div>
      </div>
      <div className="approval-summary card">
        <dl>
          <div><dt>商品</dt><dd>店小秘当前唯一命中商品（执行时读回）</dd></div>
          <div><dt>目标店铺</dt><dd>店小秘认领弹窗当前选中项（执行时读回）</dd></div>
          <div><dt>允许动作</dt><dd>认领并移入商品箱</dd></div>
          <div><dt>商品数量</dt><dd>1</dd></div>
          <div><dt>{runtimeIdentity?.simulation ? "原型会话" : "浏览器会话"}</dt><dd>{runtimeIdentity?.sessionId || "8A21（本次有效）"}</dd></div>
          <div><dt>后续编辑</dt><dd>仍需第二次人工批准</dd></div>
          <div><dt>发布能力</dt><dd className="safe-value">不可用</dd></div>
        </dl>
        <label className="approval-consent">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => onConsent(event.target.checked)}
            data-testid="claim-approval-consent"
          />
          <span>我确认只为店小秘当前读回的 1 件商品生成本件授权，并理解本次批准不包含下一件、编辑或发布。</span>
        </label>
      </div>
    </section>
  );
}

function NewTaskWizard({ runtimeIdentity, onCancel, onCreateTask, notify }) {
  const [step, setStep] = useState(1);
  const [sceneConfirmed, setSceneConfirmed] = useState(false);
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const connected = runtimeIdentity?.connected !== false;
  const canContinue = step === 1 ? connected : step === 2 ? sceneConfirmed : consent;

  const goNext = () => {
    if (!canContinue || step >= 3) return;
    setError("");
    setStep((current) => current + 1);
  };

  const submit = async () => {
    if (!consent || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await onCreateTask?.({
        runtimeIdentityId: runtimeIdentity?.id,
        scope: "claim_only",
        quantity: 1,
        sourcePage: "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        selectionSource: "dxm_live_current_row",
        approval: {
          action: "claim_to_product_box",
          approved: true,
          sessionId: runtimeIdentity?.sessionId,
        },
      });
      if (result === false || result?.ok === false) throw new Error(result?.message || "创建任务失败");
      notify?.("本件授权已记录；执行时只读取店小秘当前 1 件商品");
    } catch (submitError) {
      setError(submitError?.message || "创建任务失败，请重新确认运行身份。 ");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="new-task-wizard card" aria-labelledby="new-task-title" data-testid="new-task-wizard">
      <header className="wizard-header">
        <div>
          <span>受控单商品任务</span>
          <h1 id="new-task-title">新建现场认领任务</h1>
          <p>商品与店铺都在店小秘中准备；本系统只负责当前单件的授权、执行和留证。</p>
        </div>
        <button type="button" className="icon-button" onClick={onCancel} aria-label="关闭新建任务" data-testid="cancel-new-task">
          <XIcon size={20} />
        </button>
      </header>
      <WizardStepper step={step} />
      <div className="wizard-body">
        {step === 1 && <RuntimeStep runtimeIdentity={runtimeIdentity} />}
        {step === 2 && <DxmSceneStep confirmed={sceneConfirmed} onConfirm={setSceneConfirmed} />}
        {step === 3 && (
          <ApprovalStep
            runtimeIdentity={runtimeIdentity}
            consent={consent}
            onConsent={setConsent}
          />
        )}
      </div>
      <footer className="wizard-footer">
        <div aria-live="polite">
          {error && <p className="form-error" role="alert">{error}</p>}
          {!error && step === 1 && !connected && <p className="form-hint">请先连接可见浏览器。</p>}
          {!error && step === 2 && !sceneConfirmed && <p className="form-hint">请先确认店小秘当前筛选、排序和认领店铺已准备好。</p>}
        </div>
        <div>
          {step > 1 && (
            <button type="button" className="secondary-button" onClick={() => setStep((current) => current - 1)} data-testid="wizard-back">
              <ArrowLeftIcon size={17} />返回
            </button>
          )}
          {step < 3 ? (
            <button type="button" className="primary-button" onClick={goNext} disabled={!canContinue} data-testid="wizard-next">
              下一步<ArrowRightIcon size={17} />
            </button>
          ) : (
            <button
              type="button"
              className="primary-button"
              onClick={submit}
              disabled={!consent || submitting}
              data-testid="approve-claim-button"
            >
              <ShieldCheckIcon size={18} weight="fill" />
              {submitting ? "正在记录批准…" : "批准并开始本件"}
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}

export default function TasksPage({
  tasks = defaultTasks,
  runtimeIdentity = { connected: true },
  onOpenTask = () => {},
  onCreateTask = () => {},
  notify = () => {},
}) {
  const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState(false);
  const safeTasks = Array.isArray(tasks) ? tasks : defaultTasks;
  const activeTask = safeTasks.find((task) => ["claiming", "claimed", "validating", "approval", "editing", "verifying", "paused", "manual", "deferred", "blocked"].includes(task.status));

  const startCreate = () => {
    if (activeTask) {
      notify("已有任务正在运行，请先处理当前任务");
      return;
    }
    setCreating(true);
  };

  const createTask = async (payload) => {
    const result = await onCreateTask(payload);
    if (result?.ok === false) return result;
    setCreating(false);
    if (result?.task?.id || result?.id) onOpenTask(result?.task || result);
    return result;
  };

  return (
    <div className="task-workspace tasks-page" data-testid="tasks-page">
      <SafetyBanner />
      {creating ? (
        <NewTaskWizard
          runtimeIdentity={runtimeIdentity}
          onCancel={() => setCreating(false)}
          onCreateTask={createTask}
          notify={notify}
        />
      ) : (
        <TaskList
          tasks={safeTasks}
          filter={filter}
          onFilter={setFilter}
          onOpenTask={onOpenTask}
          onStartCreate={startCreate}
          activeTask={activeTask}
        />
      )}
      <footer className="app-footer">
        <span>© 2026 店小秘 DXM</span>
        <span>只保存，不发布。系统不提供任何发布能力。</span>
      </footer>
    </div>
  );
}
