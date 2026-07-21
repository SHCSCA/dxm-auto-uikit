import { useEffect, useMemo, useState } from "react";
import {
  BellIcon,
  BookOpenIcon,
  BrowsersIcon,
  CheckCircleIcon,
  FilesIcon,
  HandPalmIcon,
  LockKeyIcon,
  ShieldCheckIcon,
  SlidersIcon,
  SpinnerGapIcon,
  StorefrontIcon,
  UserCircleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";

const tabs = [
  { id: "account", label: "账号与浏览器", icon: BrowsersIcon },
  { id: "boundary", label: "安全边界", icon: ShieldCheckIcon },
  { id: "runtime", label: "运行身份", icon: UserCircleIcon },
  { id: "help", label: "使用帮助", icon: BookOpenIcon },
];

function handleTablistKeyDown(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabButtons = [...event.currentTarget.querySelectorAll('[role="tab"]:not(:disabled)')];
  if (!tabButtons.length) return;
  const currentIndex = Math.max(0, tabButtons.indexOf(document.activeElement));
  const nextIndex = event.key === "Home"
    ? 0
    : event.key === "End"
      ? tabButtons.length - 1
      : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabButtons.length) % tabButtons.length;
  event.preventDefault();
  tabButtons[nextIndex].focus();
  tabButtons[nextIndex].click();
}

const boundaryItems = [
  {
    id: "save-only",
    title: "只保存，不发布",
    detail: "最终动作固定为保存草稿；发布、提交审核与上架动作不在任务能力范围内。",
  },
  {
    id: "serial-items",
    title: "整批一次批准，单件串行执行",
    detail: "批次冻结后只批准一次；系统严格按顺序逐件编辑并自动继续，每件仍绑定独立结果与证据。",
  },
  {
    id: "two-confirmations",
    title: "商品范围来自店小秘现场",
    detail: "商品筛选、排序和店铺范围都由运营人员在店小秘中准备；本系统只读取并冻结现场范围，不提供本地商品或店铺选择。",
  },
  {
    id: "visible-browser",
    title: "真实可见浏览器",
    detail: "运营人员始终能看到页面、账号和当前步骤，系统不切换为隐藏运行。",
  },
  {
    id: "fail-closed",
    title: "证据不足即停止",
    detail: "遇到 UNKNOWN、身份不一致或保存证据缺失时，任务进入人工对账，不自动重试。",
  },
];

const helpSteps = [
  ["01", "准备批量编辑", "在店小秘中完成商品筛选、排序和店铺范围准备；本系统不提供本地商品或店铺选择。"],
  ["02", "读取并冻结范围", "系统从可见的店小秘现场读取当前结果，冻结商品顺序、店铺范围和模板版本。"],
  ["03", "整批一次批准", "核对账号、Session、批次摘要和模板快照；确认无身份漂移后，只需批准整个批次一次。"],
  ["04", "自动串行编辑", "系统严格逐件编辑并自动继续，正常成功不打扰运营人员，每件仍保留独立结果与证据。"],
  ["05", "仅在异常时介入", "保存前校验失败可隔离；UNKNOWN、身份漂移、发布风险或证据缺失会停止批次并进入人工对账。"],
];

const ui = {
  tabs: {
    display: "flex",
    gap: 6,
    padding: 5,
    border: "1px solid var(--border)",
    borderRadius: 10,
    background: "#eef1f5",
    overflowX: "auto",
  },
  tab: {
    minHeight: 38,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    padding: "0 14px",
    border: 0,
    borderRadius: 7,
    background: "transparent",
    color: "var(--muted)",
    font: "inherit",
    fontWeight: 700,
    whiteSpace: "nowrap",
    cursor: "pointer",
  },
  activeTab: {
    background: "#ffffff",
    color: "var(--ink)",
    boxShadow: "0 1px 2px rgba(15, 23, 42, 0.08)",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1.45fr) minmax(260px, 0.75fr)",
    gap: 16,
    alignItems: "start",
  },
  cardHeader: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    paddingBottom: 14,
    borderBottom: "1px solid var(--border)",
  },
  eyebrow: {
    margin: "0 0 5px",
    color: "var(--blue-dark)",
    fontSize: 12,
    fontWeight: 800,
    letterSpacing: ".08em",
    textTransform: "uppercase",
  },
  title: {
    margin: 0,
    color: "var(--ink)",
    fontSize: 18,
    lineHeight: 1.35,
  },
  description: {
    margin: "6px 0 0",
    color: "var(--muted)",
    fontSize: 13,
    lineHeight: 1.65,
  },
  formGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 14,
    marginTop: 16,
  },
  field: {
    display: "grid",
    gap: 7,
    color: "var(--ink)",
    fontSize: 13,
    fontWeight: 700,
  },
  input: {
    width: "100%",
    minHeight: 42,
    boxSizing: "border-box",
    border: "1px solid var(--border)",
    borderRadius: 8,
    background: "#fff",
    color: "var(--ink)",
    padding: "0 12px",
    font: "inherit",
    outline: "none",
  },
  preference: {
    display: "flex",
    alignItems: "flex-start",
    gap: 10,
    padding: "13px 0",
    borderBottom: "1px solid var(--border)",
  },
  checkbox: {
    width: 17,
    height: 17,
    marginTop: 2,
    accentColor: "var(--blue)",
    cursor: "pointer",
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
    marginTop: 16,
  },
  note: {
    display: "flex",
    gap: 10,
    padding: 13,
    border: "1px solid #cbd5e1",
    borderRadius: 9,
    background: "#f8fafc",
    color: "var(--muted)",
    fontSize: 12,
    lineHeight: 1.65,
  },
  boundary: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
    marginTop: 16,
  },
  boundaryItem: {
    display: "grid",
    gridTemplateColumns: "36px minmax(0, 1fr)",
    gap: 11,
    padding: 15,
    border: "1px solid var(--border)",
    borderRadius: 10,
    background: "#fff",
  },
  lock: {
    width: 36,
    height: 36,
    display: "grid",
    placeItems: "center",
    borderRadius: 8,
    background: "var(--blue-soft)",
    color: "var(--blue-dark)",
  },
  runtimeList: {
    display: "grid",
    gap: 0,
    margin: "14px 0 0",
  },
  runtimeRow: {
    display: "grid",
    gridTemplateColumns: "180px minmax(0, 1fr)",
    gap: 16,
    alignItems: "center",
    minHeight: 49,
    borderBottom: "1px solid var(--border)",
  },
  runtimeLabel: {
    color: "var(--muted)",
    fontSize: 13,
  },
  runtimeValue: {
    margin: 0,
    color: "var(--ink)",
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
    fontSize: 13,
    overflowWrap: "anywhere",
  },
  helpGrid: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1.25fr) minmax(250px, .75fr)",
    gap: 16,
    alignItems: "start",
  },
  helpStep: {
    display: "grid",
    gridTemplateColumns: "42px minmax(0, 1fr)",
    gap: 12,
    padding: "14px 0",
    borderBottom: "1px solid var(--border)",
  },
  number: {
    color: "var(--blue-dark)",
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
    fontSize: 15,
    fontWeight: 800,
  },
};

function asText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function pickSafeSettings(settings) {
  const source = settings && typeof settings === "object" ? settings : {};
  return {
    operatorLabel: asText(source.operatorLabel ?? source.operator_label, "运营小秘"),
    defaultStore: asText(source.defaultStore ?? source.default_store, "以店小秘现场读回为准"),
    rememberAccountLocally: Boolean(
      source.rememberAccountLocally ?? source.remember_account_locally ?? true,
    ),
    autoOpenEvidence: Boolean(source.autoOpenEvidence ?? source.auto_open_evidence ?? true),
    evidenceRetentionDays: Number(
      source.evidenceRetentionDays ?? source.evidence_retention_days ?? 30,
    ),
  };
}

function SettingsPage({
  initialTab = "account",
  runtimeIdentity = {},
  settings = {},
  onUpdateSettings,
  onOpenIssues,
  notify,
}) {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [draft, setDraft] = useState(() => pickSafeSettings(settings));
  const [saving, setSaving] = useState(false);
  const [showLoginGuide, setShowLoginGuide] = useState(false);
  const [runtimeCheckedAt, setRuntimeCheckedAt] = useState("");

  useEffect(() => {
    setDraft(pickSafeSettings(settings));
  }, [settings]);

  useEffect(() => {
    if (["account", "boundary", "runtime", "help"].includes(initialTab)) {
      setActiveTab(initialTab);
    }
  }, [initialTab]);

  const runtimeRows = useMemo(() => {
    const identity = runtimeIdentity && typeof runtimeIdentity === "object" ? runtimeIdentity : {};
    return [
      ["运行状态", asText(identity.status ?? identity.runtimeStatus, "等待运行")],
      ["运行身份", asText(identity.runtimeId ?? identity.runtime_id, "尚未生成")],
      ["构建版本", asText(identity.buildId ?? identity.build_id, "未提供")],
      ["Git 提交", asText(identity.gitHead ?? identity.git_head, "未提供")],
      ["后端实例", asText(identity.backendInstance ?? identity.backend_instance, "未连接")],
      ["浏览器会话", asText(identity.browserSession ?? identity.browser_session, "未连接")],
      ["最近本机核对", runtimeCheckedAt || asText(identity.verifiedAt ?? identity.verified_at, "尚未核验")],
    ];
  }, [runtimeCheckedAt, runtimeIdentity]);

  function updateDraft(key, value) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function saveSafeSettings(event) {
    event?.preventDefault?.();
    setSaving(true);
    try {
      await onUpdateSettings?.({ ...draft });
      notify?.("本机偏好已保存，任务安全边界保持不变。", "success");
    } catch (error) {
      notify?.(error?.message || "设置保存失败，请稍后重试。", "warning");
    } finally {
      setSaving(false);
    }
  }

  function renderAccountSettings() {
    return (
      <div style={ui.grid} data-testid="settings-account-panel">
        <form
          className="card"
          style={{ padding: 18 }}
          onSubmit={saveSafeSettings}
          data-testid="settings-account-form"
        >
          <div style={ui.cardHeader}>
            <div>
              <p style={ui.eyebrow}>LOCAL PREFERENCES</p>
              <h2 style={ui.title}>账号提示与浏览器偏好</h2>
              <p style={ui.description}>
                这里只保存运营显示偏好，不保存密码、Cookie，也不会改变任务执行权限。
              </p>
            </div>
            <UserCircleIcon size={28} weight="duotone" aria-hidden="true" />
          </div>

          <div style={ui.formGrid}>
            <label style={ui.field}>
              运营显示名称
              <input
                style={ui.input}
                value={draft.operatorLabel}
                onChange={(event) => updateDraft("operatorLabel", event.target.value)}
                data-testid="settings-operator-label"
                aria-label="运营显示名称"
              />
            </label>
            <label style={ui.field}>
              店铺核对提示
              <input
                style={ui.input}
                value={draft.defaultStore}
                onChange={(event) => updateDraft("defaultStore", event.target.value)}
                data-testid="settings-default-store"
                aria-label="店铺核对提示"
              />
            </label>
            <label style={ui.field}>
              证据本机保留天数
              <select
                style={ui.input}
                value={draft.evidenceRetentionDays}
                onChange={(event) =>
                  updateDraft("evidenceRetentionDays", Number(event.target.value))
                }
                data-testid="settings-evidence-retention"
                aria-label="证据本机保留天数"
              >
                <option value={7}>7 天</option>
                <option value={30}>30 天</option>
                <option value={90}>90 天</option>
              </select>
            </label>
          </div>

          <div style={{ marginTop: 8 }}>
            <label style={ui.preference}>
              <input
                type="checkbox"
                style={ui.checkbox}
                checked={draft.rememberAccountLocally}
                onChange={(event) =>
                  updateDraft("rememberAccountLocally", event.target.checked)
                }
                data-testid="settings-remember-account"
              />
              <span>
                <strong>记住账号提示</strong>
                <span style={{ ...ui.description, display: "block", marginTop: 3 }}>
                  仅记住账号标签和店铺提示，登录凭据仍由真实浏览器管理。
                </span>
              </span>
            </label>
            <label style={{ ...ui.preference, borderBottom: 0 }}>
              <input
                type="checkbox"
                style={ui.checkbox}
                checked={draft.autoOpenEvidence}
                onChange={(event) => updateDraft("autoOpenEvidence", event.target.checked)}
                data-testid="settings-auto-open-evidence"
              />
              <span>
                <strong>任务结束后自动打开证据</strong>
                <span style={{ ...ui.description, display: "block", marginTop: 3 }}>
                  只改变界面跳转，不影响任务执行或保存行为。
                </span>
              </span>
            </label>
          </div>

          <div style={ui.actions}>
            <button
              className="primary-button"
              type="submit"
              disabled={saving}
              data-testid="save-safe-settings"
            >
              {saving ? <SpinnerGapIcon className="spin" size={16} /> : <CheckCircleIcon size={16} />}
              {saving ? "保存中" : "保存本机偏好"}
            </button>
            <button
              className="secondary-button"
              type="button"
              onClick={() => {
                updateDraft("rememberAccountLocally", false);
                notify?.("已清除表单中的账号记住状态，保存后生效。", "info");
              }}
              data-testid="clear-account-hint"
            >
              清除账号提示
            </button>
          </div>
        </form>

        <aside className="card" style={{ padding: 18 }} aria-label="浏览器账号说明">
          <BrowsersIcon size={30} color="var(--blue-dark)" weight="duotone" aria-hidden="true" />
          <h2 style={{ ...ui.title, marginTop: 12 }}>真实接入时由浏览器负责登录</h2>
          <p style={ui.description}>
            本地原型不读取登录状态；未来接入真实店小秘时，也只使用可见浏览器，不托管密码、不复制 Cookie。
          </p>
          <div style={{ ...ui.note, marginTop: 14 }}>
            <LockKeyIcon size={19} weight="duotone" aria-hidden="true" />
            <span>切换账号或店铺后，应先在工作台重新核验运行身份，并重新读取、冻结和批准当前批次。</span>
          </div>
          <button
            className="secondary-button"
            type="button"
            style={{ width: "100%", marginTop: 14 }}
            onClick={() => setShowLoginGuide((value) => !value)}
            aria-expanded={showLoginGuide}
            data-testid="show-browser-login-guide"
          >
            {showLoginGuide ? "收起未来登录检查说明" : "查看未来登录检查说明"}
          </button>
          {showLoginGuide && (
            <div style={{ ...ui.note, marginTop: 10 }} role="status" data-testid="browser-login-guide">
              <CheckCircleIcon size={19} color="var(--success)" weight="fill" aria-hidden="true" />
              <span>未来接入时依次核对可见浏览器账号、目标店铺与本次会话；任何一项不一致都返回任务台停止继续。</span>
            </div>
          )}
        </aside>
      </div>
    );
  }

  function renderBoundarySettings() {
    return (
      <div className="card" style={{ padding: 18 }} data-testid="settings-boundary-panel">
        <div style={ui.cardHeader}>
          <div>
            <p style={ui.eyebrow}>NON-NEGOTIABLE BOUNDARY</p>
            <h2 style={ui.title}>任务边界由产品能力锁定</h2>
            <p style={ui.description}>
              以下规则不是用户偏好，因此这里没有开关。版本更新也必须继续满足这些约束。
            </p>
          </div>
          <span className="status-badge status-badge--success">
            <ShieldCheckIcon size={15} weight="fill" aria-hidden="true" />
            已锁定
          </span>
        </div>

        <div style={ui.boundary} data-testid="settings-boundary-list">
          {boundaryItems.map((item) => (
            <article key={item.id} style={ui.boundaryItem} data-testid={`boundary-${item.id}`}>
              <span style={ui.lock} aria-hidden="true">
                <LockKeyIcon size={18} weight="duotone" />
              </span>
              <div>
                <h3 style={{ ...ui.title, fontSize: 14 }}>{item.title}</h3>
                <p style={ui.description}>{item.detail}</p>
              </div>
            </article>
          ))}
        </div>

        <div className="safety-banner" style={{ marginTop: 16 }} role="note">
          <div className="safety-banner__message">
            <HandPalmIcon size={19} weight="duotone" aria-hidden="true" />
            <span>
              本原型定义未来批量编辑目标：整批一次批准，随后严格单件串行并自动继续，只有异常才需要人工介入。当前生产后端仍由受控 single_save 子任务顺序编排，不代表原生 batch_save 已放行；始终只保存、不发布。
            </span>
          </div>
          <div className="safety-banner__divider" aria-hidden="true" />
          <div className="safety-banner__mode">
            <LockKeyIcon size={15} weight="fill" aria-hidden="true" />
            FAIL CLOSED
          </div>
        </div>
      </div>
    );
  }

  function renderRuntimeIdentity() {
    return (
      <div style={ui.grid} data-testid="settings-runtime-panel">
        <section className="card" style={{ padding: 18 }} data-testid="settings-runtime-identity">
          <div style={ui.cardHeader}>
            <div>
              <p style={ui.eyebrow}>CURRENT RUNTIME</p>
              <h2 style={ui.title}>当前运行身份</h2>
              <p style={ui.description}>
                原型展示未来核验方式：界面、后端和真实浏览器必须属于同一次运行，不能拿旧证据继续执行。
              </p>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() => {
                const checkedAt = new Date().toLocaleString("zh-CN", { hour12: false });
                setRuntimeCheckedAt(checkedAt);
                notify?.("已重新核对本地原型运行身份", "info");
              }}
              data-testid="refresh-runtime-identity"
            >
              <SpinnerGapIcon size={16} aria-hidden="true" />
              重新核对
            </button>
          </div>

          <dl style={ui.runtimeList}>
            {runtimeRows.map(([label, value]) => (
              <div style={ui.runtimeRow} key={label}>
                <dt style={ui.runtimeLabel}>{label}</dt>
                <dd style={ui.runtimeValue}>{value}</dd>
              </div>
            ))}
          </dl>

        </section>

        <aside className="card" style={{ padding: 18 }} aria-label="运行身份判断原则">
          <SlidersIcon size={30} color="var(--blue-dark)" weight="duotone" aria-hidden="true" />
          <h2 style={{ ...ui.title, marginTop: 12 }}>核验优先于继续</h2>
          <p style={ui.description}>
            任一身份字段缺失、过期或前后不一致，都应当停在当前步骤，交由运营人员判断。
          </p>
          <div style={{ ...ui.note, marginTop: 14 }}>
            <WarningCircleIcon size={19} color="var(--warning)" weight="fill" aria-hidden="true" />
            <span>“未提供”和“未连接”不是成功状态，不能作为继续保存的依据。</span>
          </div>
        </aside>
      </div>
    );
  }

  function renderHelp() {
    return (
      <div style={ui.helpGrid} data-testid="settings-help">
        <section className="card" style={{ padding: 18 }}>
          <div style={ui.cardHeader}>
            <div>
              <p style={ui.eyebrow}>OPERATOR PLAYBOOK</p>
              <h2 style={ui.title}>一次安全的受监督批次</h2>
              <p style={ui.description}>商品范围来自店小秘现场并冻结为不可变批次；运营人员整批批准一次后，系统严格逐件串行并自动继续，只有异常才暂停等待介入。</p>
            </div>
            <FilesIcon size={28} weight="duotone" aria-hidden="true" />
          </div>
          <div>
            {helpSteps.map(([number, title, description]) => (
              <article style={ui.helpStep} key={number}>
                <span style={ui.number}>{number}</span>
                <div>
                  <h3 style={{ ...ui.title, fontSize: 14 }}>{title}</h3>
                  <p style={ui.description}>{description}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="card" style={{ padding: 18 }} aria-label="常见问题">
          <BookOpenIcon size={30} color="var(--blue-dark)" weight="duotone" aria-hidden="true" />
          <h2 style={{ ...ui.title, marginTop: 12 }}>遇到异常怎么办</h2>
          <div style={{ marginTop: 14 }}>
            <h3 style={{ ...ui.title, fontSize: 14 }}>页面与任务商品不一致</h3>
            <p style={ui.description}>立即停止，不刷新重试；在记录页创建问题并保留当前截图。</p>
          </div>
          <div style={{ marginTop: 14 }}>
            <h3 style={{ ...ui.title, fontSize: 14 }}>看不到保存证据</h3>
            <p style={ui.description}>将结果视为 UNKNOWN，不凭页面外观推断保存成功。</p>
          </div>
          <div style={{ marginTop: 14 }}>
            <h3 style={{ ...ui.title, fontSize: 14 }}>需要更换账号</h3>
            <p style={ui.description}>只能在当前单件尚未开始时停止计划再切换账号；若写入中断，立即记为 UNKNOWN 并人工对账，不能恢复续跑。</p>
          </div>
          <button
            className="secondary-button"
            type="button"
            style={{ width: "100%", marginTop: 16 }}
            onClick={() => onOpenIssues?.()}
            data-testid="open-issue-help"
          >
            查看问题处理说明
          </button>
        </aside>
      </div>
    );
  }

  return (
    <section className="secondary-view" aria-labelledby="settings-page-title" data-testid="settings-page">
      <div className="safety-banner" role="note">
        <div className="safety-banner__message">
          <ShieldCheckIcon size={19} weight="duotone" aria-hidden="true" />
          <span>
            设置页只管理账号提示、证据展示和运营提醒；任务能力始终保持批次受监督、逐商品串行、只保存。
          </span>
        </div>
        <div className="safety-banner__divider" aria-hidden="true" />
        <div className="safety-banner__mode">
          <StorefrontIcon size={15} weight="fill" aria-hidden="true" />
          店小秘专用
        </div>
      </div>

      <header className="page-heading">
        <div>
          <p style={ui.eyebrow}>MISSION CONTROL</p>
          <h1 id="settings-page-title">系统设置</h1>
          <p>配置安全范围内的本机体验，并核对当前任务运行身份。</p>
        </div>
        <span className="status-badge status-badge--info">
          <BellIcon size={15} weight="fill" aria-hidden="true" />
          安全偏好
        </span>
      </header>

      <nav
        style={ui.tabs}
        aria-label="系统设置分类"
        role="tablist"
        data-testid="settings-tabs"
        onKeyDown={handleTablistKeyDown}
      >
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const selected = activeTab === tab.id;
          return (
            <button
              type="button"
              key={tab.id}
              style={{ ...ui.tab, ...(selected ? ui.activeTab : {}) }}
              onClick={() => setActiveTab(tab.id)}
              aria-selected={selected}
              tabIndex={selected ? 0 : -1}
              aria-controls={`settings-panel-${tab.id}`}
              role="tab"
              data-testid={`settings-tab-${tab.id}`}
            >
              <Icon size={16} weight={selected ? "fill" : "regular"} aria-hidden="true" />
              {tab.label}
            </button>
          );
        })}
      </nav>

      <div
        id={`settings-panel-${activeTab}`}
        role="tabpanel"
        aria-label={tabs.find((tab) => tab.id === activeTab)?.label}
      >
        {activeTab === "account" && renderAccountSettings()}
        {activeTab === "boundary" && renderBoundarySettings()}
        {activeTab === "runtime" && renderRuntimeIdentity()}
        {activeTab === "help" && renderHelp()}
      </div>
    </section>
  );
}

export { SettingsPage };
export default SettingsPage;
