import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { patchJson, postJson } from '../api'
import type {
  AcceptanceGap,
  AgentConsoleActionEvent,
  AgentConsoleControlCommand,
  AgentConsoleSession,
  ConfigPreview,
  ConfigPreviewGroup,
  DeliveryWorkspace,
  DesktopRuntimeInfo,
  DxmReferenceTemplateSection,
  Evidence,
  EvidencePoint,
  ExceptionItem,
  FinalDeliveryCheckSummary,
  LogItem,
  Product,
  RealTaskCreateRequest,
  RegressionGate,
  Report,
  RuntimeLogResponse,
  RuntimeLogItem,
  RuntimeLogSource,
  RuntimeStatus,
  RuntimeControlAction,
  RuntimeControlResponse,
  RunStep,
  Store,
  Task,
  Template,
} from '../types'
import { demoTemplateSeeds, evidenceGrade, humanLevel, humanTaskStatus, referenceSectionLabels, toArtifactUrl } from '../workspace'
import {
  L2ProbeResourceRepairPanel,
  ReadonlyRecheckHelpCard,
  RealModeReleasePlanPanel,
  SingleSaveRecoveryGuide,
  TaskCurrentActionPanel,
} from './workbench/ProductTaskPanels'
import { humanOperatorMessage, humanOperatorTitle } from './workbench/workbenchCopy'
export { DxmAccessPage } from './workbench/DxmAccessPage'
export { HelpPage as HelpCenter } from './workbench/HelpPage'
export { IssuesPage as ExceptionQueue } from './workbench/IssuesPage'
export { ResultsPage as ReportCenter } from './workbench/ResultsPage'
export { SystemSettingsPage as SystemSettings } from './workbench/SystemSettingsPage'
export { ConfigCenter as ConfigCenterView }
export { ExecutionConsole as ExecutionConsoleView }

type CommonProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
}

type ConfigCenterProps = CommonProps & {
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  configPreviewLoading: boolean
  onConfigSaved: () => void | Promise<void>
  onRefreshConfigPreview: () => void | Promise<void>
  onShowTasks: () => void
}

type DxmLoginDraft = {
  username: string
  password: string
  rememberCredential: boolean
}

type DxmCredentialState = {
  available: boolean
  loaded: boolean
  saved: boolean
  message: string
}

type L2RunnerState = {
  status: 'idle' | 'running' | 'passed' | 'failed'
  runId: string | null
  exitCode: number | null
  message: string
  line: string | null
  updatedAt: string | null
}

type ConsolePrimaryPathCode = 'login' | 'select_task' | 'completed' | 'running' | 'not_draft' | 'unreleased' | 'config' | 'l2' | 'l2_resource' | 'l3' | 'busy' | 'ready'

type ConsolePrimaryPath = {
  code: ConsolePrimaryPathCode
  title: string
  reason: string
  detail: string
  next: string
  ctaLabel: string
  action: 'dxm_login' | 'tasks' | 'config' | 'run_l2' | 'reports' | 'start_browser' | 'launcher_logs' | 'current_execution'
  browserStatus: string
  blocksBrowserStart: boolean
  saveBlocked: boolean
}

type ConfigSectionSaveState = {
  status: 'clean' | 'dirty' | 'saving' | 'saved' | 'failed'
  scope?: string
  savedAt?: string
  message?: string
}

type DxmAccessPageProps = {
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  dxmLoginDraft: DxmLoginDraft
  dxmCredentialState: DxmCredentialState
  busy: boolean
  onDxmLoginDraftChange: (draft: DxmLoginDraft) => void
  onClearSavedDxmCredential: () => void
  onOpenDxmLogin: () => void
  onContinueDxmLogin: () => void
  onNavigateDxmTarget: (target: 'data_acquisition' | 'draft_box') => void
  onShowConsole: () => void
}

export const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])
const LEGACY_QA_REAL_MUTATION_TASK_NAME = ['QA guarded', 'real mutation task'].join(' ')
const RELEASED_SINGLE_SAVE_STORE_NAMES = new Set(['Dang Kang'])
export const DXM_LOGGED_IN_STATUSES = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])
const READONLY_PRECHECK_CTA = '运行真实只读检查'
const READONLY_PRECHECK_PURPOSE = '真实只读检查会打开店小秘采集页和采集箱，只读取页面，不领取、不保存、不发布；通过后才能打开执行浏览器。'

const realWriteReleasePrerequisites = [
  {
    title: '真实只读检查通过',
    detail: '采集页和采集箱都要完成只读检查；检查过程中不能出现领取、保存、发布或异常跳转。',
  },
  {
    title: '异常放行必须人工复核',
    detail: '如果页面出现新接口或新按钮，必须先人工确认风险并重新检查，不能自动绕过。',
  },
  {
    title: '人工确认单商品只保存',
    detail: '只有真实只读检查通过后，才允许启动一次单商品只保存。',
  },
  {
    title: '保存结果必须可核对',
    detail: '需要拿到店小秘保存成功、未发布和页面记录后，才认为本次只保存完成。',
  },
]

type TaskCenterProps = CommonProps & {
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  configPreviewLoading: boolean
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  busy: boolean
  demoEnabled: boolean
  l3ApprovedBy: string
  onL3ApprovedByChange: (value: string) => void
  onSelectTask: (taskId: number) => void
  onCreateRealTask: (request: RealTaskCreateRequest) => void | Promise<void>
  onBootstrapDemo: () => void
  onStartTask: () => void
  onRunL2Probe: () => void
  onShowConfig: () => void
  onShowConsole: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}

type ExecutionConsoleProps = CommonProps & {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  configPreviewLoading: boolean
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  desktopRuntime: DesktopRuntimeInfo | null
  runtimeLogs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  runtimeLogSource: RuntimeLogSource
  runtimeLogError: string | null
  runtimeLogLevel: 'all' | 'info' | 'warning' | 'error'
  runtimeLogQuery: string
  l2RunnerState: L2RunnerState
  lastRuntimeControlResult: RuntimeControlResponse | null
  busy: boolean
  dxmLoginDraft: DxmLoginDraft
  dxmCredentialState: DxmCredentialState
  onDxmLoginDraftChange: (draft: DxmLoginDraft) => void
  onClearSavedDxmCredential: () => void
  onRuntimeLogSourceChange: (source: RuntimeLogSource) => void
  onRuntimeLogLevelChange: (level: 'all' | 'info' | 'warning' | 'error') => void
  onRuntimeLogQueryChange: (query: string) => void
  onStartAgentConsole: () => void
  onOpenDxmLogin: () => void
  onContinueDxmLogin: () => void
  onNavigateDxmTarget: (target: 'data_acquisition' | 'draft_box') => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
  onRequestAgentConsoleTakeover: () => void
  onReleaseAgentConsoleTakeover: () => void
  onControlAgentConsoleBrowser: (command: AgentConsoleControlCommand) => void
  onRuntimeControl: (action: RuntimeControlAction) => void
  onShowTasks: () => void
  onShowConfig: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}

function DxmLoginInlineForm({
  draft,
  credentialState,
  runtimeStatus,
  runtimeStatusError,
  busy,
  compact = false,
  onDraftChange,
  onClearSavedCredential,
  onSubmit,
  onContinue,
}: {
  draft: DxmLoginDraft
  credentialState: DxmCredentialState
  runtimeStatus?: RuntimeStatus | null
  runtimeStatusError?: string | null
  busy: boolean
  compact?: boolean
  onDraftChange: (draft: DxmLoginDraft) => void
  onClearSavedCredential: () => void
  onSubmit: () => void
  onContinue: () => void
}) {
  const canSubmit = Boolean(draft.username.trim() && draft.password && !busy)
  const loginSubmitDisabledReason = busy
    ? '正在处理当前操作，请等待完成后再打开真实登录页。'
    : !draft.username.trim() || !draft.password
      ? '先填写店小秘账号和密码，才会打开真实登录页。'
      : ''
  const loginState = humanDxmLoginState(runtimeStatus, runtimeStatusError)
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canSubmit) return
    onSubmit()
  }
  const accountFields = (
    <>
      <label>
        <span>店小秘账号</span>
        <input
          value={draft.username}
          autoComplete="username"
          placeholder="输入 DXM 账号"
          required
          disabled={busy}
          onChange={(event) => onDraftChange({ ...draft, username: event.target.value })}
        />
      </label>
      <label>
        <span>店小秘密码</span>
        <input
          type="password"
          value={draft.password}
          autoComplete="current-password"
          placeholder="仅本次登录使用"
          required
          disabled={busy}
          onChange={(event) => onDraftChange({ ...draft, password: event.target.value })}
        />
      </label>
      <label className="operator-inline-form__remember">
        <input
          type="checkbox"
          checked={draft.rememberCredential}
          disabled={busy || !credentialState.available}
          onChange={(event) => onDraftChange({ ...draft, rememberCredential: event.target.checked })}
        />
        <span>记住账号密码</span>
      </label>
      <small className={`operator-inline-form__credential-state ${credentialState.saved ? 'is-saved' : credentialState.available ? 'is-available' : 'is-disabled'}`}>
        {credentialState.message}
      </small>
      <CredentialStorageFacts credentialState={credentialState} />
      <LoginRecoverySteps loginState={loginState} />
      {!canSubmit && loginSubmitDisabledReason && <small aria-label="不能打开登录页的原因">不能打开登录页的原因：{loginSubmitDisabledReason}</small>}
    </>
  )
  const loginStateBlock = loginState ? (
    <div className={`operator-inline-form__login-state is-${loginState.tone}`} aria-label="DXM 登录状态">
      <strong>{loginState.label}</strong>
      <span>{loginState.detail}</span>
      <small>{loginState.next}</small>
    </div>
  ) : null
  const actions = (
    <div className="operator-inline-form__actions">
      <button className="button button--primary" type="submit" disabled={!canSubmit} title={!canSubmit ? loginSubmitDisabledReason : undefined}>
        打开真实登录页
      </button>
      <button className="button button--quiet" type="button" onClick={onContinue} disabled={busy}>
        验证码完成后检测登录状态
      </button>
      <button className="button button--quiet" type="button" onClick={onClearSavedCredential} disabled={busy || !credentialState.loaded}>
        清除已记住账号
      </button>
    </div>
  )

  return (
    <form className={`operator-inline-form ${compact ? 'operator-inline-form--compact' : ''}`} onSubmit={submit}>
      <div className="operator-inline-form__head">
        <strong>登录/人工处理真实浏览器</strong>
        <span>这里只打开真实店小秘窗口，不启动保存；窗口会显式可见，用户可输入验证码、查看错误并手动调整。</span>
      </div>
      {compact ? (
        <>
          {loginStateBlock}
          {actions}
          <details className="operator-inline-form__account-drawer inline-disclosure" open={false}>
            <summary>
              账号密码与保存设置
              <span>{canSubmit ? (credentialState.saved ? '已记住' : credentialState.available ? '可记住' : '仅本次') : '先展开填写'}</span>
            </summary>
            <div className="operator-inline-form__account-grid">
              {accountFields}
            </div>
          </details>
        </>
      ) : (
        <>
          {accountFields}
          {loginStateBlock}
          {actions}
        </>
      )}
    </form>
  )
}

function LoginRecoverySteps({ loginState }: { loginState: ReturnType<typeof humanDxmLoginState> }) {
  if (!loginState || loginState.label !== '登录未通过') return null
  const steps = [
    '保持真实浏览器窗口打开',
    '修正验证码或账号密码',
    '再次点击“验证码完成后检测登录状态”',
    '仍失败时重新点击“打开真实登录页”',
  ]
  return (
    <div className="operator-inline-form__recovery-steps" aria-label="登录恢复步骤">
      <strong>登录恢复步骤</strong>
      <ol>
        {steps.map((step) => <li key={step}>{step}</li>)}
      </ol>
    </div>
  )
}

function CredentialStorageFacts({ credentialState }: { credentialState: DxmCredentialState }) {
  const facts = credentialState.available
    ? [
        ['存储', '本机加密保存可用'],
        ['下次', credentialState.saved ? '下次打开免安装版会自动填入' : '勾选后下次打开免安装版会自动填入'],
        ['范围', '只保存在当前 Windows 用户目录'],
      ]
    : [
        ['存储', '当前预览不能保存密码'],
        ['处理', '请从桌面免安装版打开'],
        ['结果', '不会写入本机密码'],
      ]

  return (
    <div className={`operator-inline-form__credential-facts ${credentialState.available ? 'is-available' : 'is-disabled'}`} aria-label="账号记住状态">
      {facts.map(([label, value]) => (
        <span key={label}>
          <b>{label}</b>
          <small>{value}</small>
        </span>
      ))}
    </div>
  )
}

function humanDxmLoginState(runtimeStatus?: RuntimeStatus | null, runtimeStatusError?: string | null) {
  if (runtimeStatusError) {
    return {
      tone: 'danger',
      label: '运行状态接口不可用',
      detail: runtimeStatusError,
      next: '请先确认本机后端仍在运行，查看实时日志后重试；不要把接口失败当成 DXM 未登录。',
    }
  }
  const status = runtimeStatus?.dxmLogin?.status
  if (!status) return null
  const currentUrl = compactDxmLoginUrl(runtimeStatus?.dxmLogin?.currentUrl)
  if (DXM_LOGGED_IN_STATUSES.has(status) || status === 'workflow_navigation') {
    return {
      tone: 'ok',
      label: status === 'workflow_navigation' ? 'DXM 已进入业务页' : 'DXM 已登录',
      detail: currentUrl ? `真实浏览器停留位置：${currentUrl}` : '真实店小秘登录态已可用。',
      next: '下一步：进入采集箱或运行真实只读检查。',
    }
  }
  if (status === 'waiting_captcha') {
    return {
      tone: 'warn',
      label: '登录还没完成，不是系统故障',
      detail: currentUrl ? `请保持真实浏览器打开并继续处理：${currentUrl}` : '账号密码已填入真实浏览器，等待你完成验证码。',
      next: '完成验证码后点击“验证码完成后检测登录状态”。',
    }
  }
  if (status === 'login_failed' || status.includes('failed')) {
    return {
      tone: 'danger',
      label: '登录未通过',
      detail: runtimeStatus?.dxmLogin?.lastError || (currentUrl ? `真实浏览器停留位置：${currentUrl}` : '未检测到有效登录态。'),
      next: '真实浏览器窗口会保留；如果验证码已完成仍失败，请修正验证码或账号密码后再次检测；重新打开登录页会复用当前账号输入。',
    }
  }
  return {
    tone: 'warn',
    label: `DXM 状态：${status}`,
    detail: currentUrl ? `真实浏览器停留位置：${currentUrl}` : '登录状态还未完成确认。',
    next: '按当前页面提示继续登录，完成后检测登录状态。',
  }
}

function compactDxmLoginUrl(url?: string | null) {
  if (!url) return ''
  try {
    const parsed = new URL(url)
    return `${parsed.hostname}${parsed.pathname}`
  } catch {
    return url.length > 80 ? `${url.slice(0, 77)}...` : url
  }
}

function L3ApprovalInlineForm({
  approvedBy,
  busy,
  disabledReason = '',
  onApprovedByChange,
  onSubmit,
}: {
  approvedBy: string
  busy: boolean
  disabledReason?: string
  onApprovedByChange: (value: string) => void
  onSubmit: () => void
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit()
  }

  return (
    <form className="operator-inline-form operator-inline-form--approval" onSubmit={submit}>
      <div className="operator-inline-form__head">
        <strong>人工确认真实保存</strong>
        <span>只启动单商品只保存任务，不会发布。</span>
      </div>
      <label>
        <span>批准人标识</span>
        <input
          value={approvedBy}
          placeholder="例如 ops-owner"
          required
          disabled={busy}
          onChange={(event) => onApprovedByChange(event.target.value)}
        />
      </label>
      <div className="operator-inline-form__actions">
        <button className="button button--primary" type="submit" disabled={busy || !approvedBy.trim()}>
          {disabledReason ? `暂不能启动只保存：${disabledReason}` : '申请并启动单商品只保存'}
        </button>
        {disabledReason && <small>{disabledReason}</small>}
      </div>
    </form>
  )
}

export function RegressionGateGrid({ gates }: { gates: RegressionGate[] }) {
  return (
    <div className="regression-gate-grid">
      {gates.map((gate) => (
        <div key={gate.level} className={`regression-gate ${gateStatusTone(gate.status)}`}>
          <div className="regression-gate__head">
            <strong>{gate.level}</strong>
            <span className={`status-pill ${gateStatusPill(gate.status)}`}>{humanGateStatus(gate.status)}</span>
          </div>
          <h3>{gate.title}</h3>
          <p>{gate.detail}</p>
          <div className="regression-gate__meta">
            <span>证据 {gate.evidenceLevel}</span>
            <span>{gate.requiresApproval ? '需批准' : '本地门禁'}</span>
          </div>
          {gate.command && <code>{gate.command}</code>}
        </div>
      ))}
    </div>
  )
}

type ConfigSectionCode =
  | 'taskBasic'
  | 'category'
  | 'sku'
  | 'pricing'
  | 'image'
  | 'logistics'
  | 'compliance'
  | 'semiManaged'
  | 'dxmReference'
type EditableConfigField = {
  name: string
  label: string
  placeholder: string
  previewPath?: string
  usage?: 'direct' | 'template' | 'advisory'
  valueKind?: 'text' | 'list'
}
type EditableConfigSection = {
  code: ConfigSectionCode
  templateType: string
  previewSection: string
  title: string
  detail: string
  fields: EditableConfigField[]
}

const editableConfigSections: EditableConfigSection[] = [
  {
    code: 'taskBasic',
    templateType: 'task_basic',
    previewSection: 'task_basic',
    title: '店铺与任务基础',
    detail: '控制当前任务绑定店铺、类目和认领标记；执行模式在创建任务时选择。',
    fields: [
      { name: 'store_name', label: '店铺', placeholder: '例如：Dang Kang', usage: 'direct' },
      { name: 'category_name', label: '绑定类目', placeholder: '例如：立牌类谷子', usage: 'direct' },
      { name: 'claim_mark', label: '认领标记', placeholder: '用于区分 DXM 草稿箱记录', usage: 'direct' },
    ],
  },
  {
    code: 'category',
    templateType: 'category',
    previewSection: 'category',
    title: '类目与标题',
    detail: '控制 DXM 类目匹配和商品标题基础信息。',
    fields: [
      { name: 'category_name', label: '目标类目', placeholder: '例如：立牌类谷子', usage: 'direct' },
      { name: 'category_keyword', label: '类目关键词', placeholder: '用于 DXM 搜索类目', usage: 'direct' },
      { name: 'template_category_id', label: 'DXM 类目 ID', placeholder: '店小秘编辑页类目 ID', usage: 'advisory' },
      { name: 'title_override', label: '标题覆盖', placeholder: '留空则使用商品标题', usage: 'advisory' },
      { name: 'title_cleaning_rule', label: '标题清洗规则', placeholder: '删除平台词 / 保留英文', usage: 'advisory' },
      { name: 'title_strategy', label: '标题策略', placeholder: '保留原始标题 / 清洗关键词', usage: 'advisory' },
    ],
  },
  {
    code: 'sku',
    templateType: 'sku',
    previewSection: 'sku',
    title: 'SKU / 价格 / 库存',
    detail: 'SKU 规则、库存和变种属性策略，价格细项在下一分区微调。',
    fields: [
      { name: 'sku_code', label: 'SKU 编码', placeholder: 'SKU-001', usage: 'direct' },
      { name: 'stock', label: '库存', placeholder: '100', usage: 'direct' },
      { name: 'jit_stock', label: 'JIT 库存', placeholder: '100', usage: 'direct' },
      { name: 'normal_stock', label: '普通库存', placeholder: '100', usage: 'advisory' },
      { name: 'template_sku_rule', label: 'SKU 规则', placeholder: '使用商品 SKU / 自动生成', usage: 'advisory' },
      { name: 'sku_attribute_strategy', label: 'SKU 属性策略', placeholder: '按 DXM 默认属性映射', usage: 'advisory' },
      { name: 'variant_strategy', label: '变种策略', placeholder: '按商品变种 / 单规格', usage: 'advisory' },
    ],
  },
  {
    code: 'pricing',
    templateType: 'pricing',
    previewSection: 'pricing',
    title: '价格策略',
    detail: '商品价、供货价和价格处理策略。',
    fields: [
      { name: 'product_price', label: '商品价', placeholder: '7.99', usage: 'direct' },
      { name: 'supply_price', label: '供货价', placeholder: '5.20', usage: 'direct' },
      { name: 'price_source', label: '价格来源', placeholder: '商品 payload / 固定模板', usage: 'advisory' },
      { name: 'price_multiplier', label: '价格倍率', placeholder: '1.15', usage: 'advisory' },
      { name: 'fixed_price', label: '固定价格', placeholder: '7.99', usage: 'advisory' },
      { name: 'price_strategy', label: '价格策略', placeholder: '按模板固定价 / 商品导入价', usage: 'advisory' },
    ],
  },
  {
    code: 'image',
    templateType: 'image',
    previewSection: 'image',
    title: '图片与素材',
    detail: '主图、欧盟外包装图和营销图策略。',
    fields: [
      { name: 'eu_outer_package_filename', label: 'EU 外包装图', placeholder: 'outer-package.jpg', usage: 'direct' },
      { name: 'marketing_images_strategy', label: '营销图策略', placeholder: '使用商品图补齐 3:4', usage: 'direct' },
      { name: 'main_image_strategy', label: '主图策略', placeholder: '保留 800x800 合规主图', usage: 'advisory' },
      { name: 'fallback_strategy', label: '缺图回退策略', placeholder: '使用 EU 外包装图补齐', usage: 'advisory' },
      { name: 'invalid_image_strategy', label: '无效图处理', placeholder: '删除 0x0 / 保留合规图', usage: 'advisory' },
      { name: 'local_asset_path', label: '本地素材目录', placeholder: 'C:\\path\\to\\assets', usage: 'advisory' },
    ],
  },
  {
    code: 'logistics',
    templateType: 'logistics',
    previewSection: 'logistics',
    title: '包装物流',
    detail: '重量、尺寸和物流属性会直接影响编辑页填写。',
    fields: [
      { name: 'weight', label: '重量 kg', placeholder: '0.03', usage: 'direct' },
      { name: 'length', label: '长 cm', placeholder: '10', usage: 'direct' },
      { name: 'width', label: '宽 cm', placeholder: '10', usage: 'direct' },
      { name: 'height', label: '高 cm', placeholder: '2', usage: 'direct' },
      { name: 'logistics_attribute', label: '物流属性', placeholder: '普货', usage: 'direct' },
      { name: 'freight_template', label: '运费模板', placeholder: '半托管运费模板', usage: 'template' },
      { name: 'service_template', label: '服务模板', placeholder: '无忧服务模板', usage: 'template' },
      { name: 'package_gross_weight', label: '包装毛重 kg', placeholder: '0.05', usage: 'advisory' },
    ],
  },
  {
    code: 'compliance',
    templateType: 'compliance',
    previewSection: 'compliance',
    title: '合规 / 海关',
    detail: '缺失合规字段时真实保存会被前置校验阻断。',
    fields: [
      { name: 'customs_name', label: '报关品名', placeholder: 'Acrylic stand', usage: 'direct' },
      { name: 'material', label: '材质', placeholder: 'Acrylic', usage: 'advisory' },
      { name: 'purpose', label: '用途', placeholder: 'Decoration', usage: 'advisory' },
      { name: 'brand', label: '品牌', placeholder: '无品牌 / 品牌名', usage: 'advisory' },
      { name: 'statement', label: '合规声明', placeholder: '符合平台合规要求', usage: 'advisory' },
    ],
  },
  {
    code: 'semiManaged',
    templateType: 'semi_managed',
    previewSection: 'semi_managed',
    title: '半托管',
    detail: '供货价、库存、原包装和条码策略。',
    fields: [
      { name: 'product_price', label: '商品价', placeholder: '7.99', usage: 'direct' },
      { name: 'supply_price', label: '供货价', placeholder: '5.20', usage: 'direct' },
      { name: 'jit_stock', label: 'JIT 库存', placeholder: '100', usage: 'direct' },
      { name: 'is_original_box', label: '是否原包装', placeholder: '否', usage: 'direct' },
      { name: 'length', label: '半托管长 cm', placeholder: '10', usage: 'direct' },
      { name: 'width', label: '半托管宽 cm', placeholder: '10', usage: 'direct' },
      { name: 'height', label: '半托管高 cm', placeholder: '2', usage: 'direct' },
      { name: 'goods_code_strategy', label: '货号策略', placeholder: '使用 SKU', usage: 'direct' },
      { name: 'barcode_strategy', label: '条码策略', placeholder: '自动生成/留空', usage: 'direct' },
    ],
  },
  {
    code: 'dxmReference',
    templateType: 'dxm_reference',
    previewSection: 'dxm_reference',
    title: '店小秘引用模板',
    detail: '店小秘编辑页 8 段下拉模板引用，执行时按 resolved 结果匹配真实模板；尺码模板按类目属性规则处理。',
    fields: [
      { name: 'dxm_reference_templates.attribute_info.names', previewPath: 'dxm_reference_templates_resolved.attribute_info.names', label: '属性信息模板', placeholder: '每行一个属性信息模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.description.names', previewPath: 'dxm_reference_templates_resolved.description.names', label: '描述模板', placeholder: '每行一个描述模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.freight.names', previewPath: 'dxm_reference_templates_resolved.freight.names', label: '运费模板', placeholder: '每行一个运费模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.service.names', previewPath: 'dxm_reference_templates_resolved.service.names', label: '服务模板', placeholder: '每行一个服务模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.eu_responsible.names', previewPath: 'dxm_reference_templates_resolved.eu_responsible.names', label: '欧盟责任人', placeholder: '每行一个欧盟责任人', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.manufacturer.names', previewPath: 'dxm_reference_templates_resolved.manufacturer.names', label: '制造商', placeholder: '每行一个制造商', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.compliance.names', previewPath: 'dxm_reference_templates_resolved.compliance.names', label: '合规模板', placeholder: '每行一个合规模板', usage: 'template', valueKind: 'list' },
      { name: 'dxm_reference_templates.semi_managed.names', previewPath: 'dxm_reference_templates_resolved.semi_managed.names', label: '半托管模板', placeholder: '每行一个半托管模板', usage: 'template', valueKind: 'list' },
    ],
  },
]

function uniqueConfigSections<T extends { section: EditableConfigSection }>(items: T[]) {
  const seen = new Set<ConfigSectionCode>()
  const result: T[] = []
  for (const item of items) {
    if (seen.has(item.section.code)) continue
    seen.add(item.section.code)
    result.push(item)
  }
  return result
}

function getNestedConfigValue(payload: Record<string, unknown>, path: string) {
  let current: unknown = payload
  for (const part of path.split('.')) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return current
}

function setNestedConfigValue(target: Record<string, unknown>, path: string, value: unknown) {
  const parts = path.split('.')
  let cursor = target
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      cursor[part] = value
      return
    }
    const next = cursor[part]
    if (!next || typeof next !== 'object' || Array.isArray(next)) {
      cursor[part] = {}
    }
    cursor = cursor[part] as Record<string, unknown>
  })
  return target
}

function parseEditableConfigFieldValue(field: EditableConfigField, rawValue: string): unknown {
  if (field.valueKind !== 'list') return rawValue
  return rawValue
    .replace(/\r\n/g, '\n')
    .replace(/[，,；;]/g, '\n')
    .replace(/\s\/\s/g, '\n')
    .split('\n')
    .map((item) => item.trim())
    .filter((item, index, items) => item && items.indexOf(item) === index)
}

function editableConfigDraftValue(value: unknown, field: EditableConfigField) {
  if (value === undefined || value === null) return ''
  if (Array.isArray(value)) return field.valueKind === 'list' ? value.join('\n') : value.join(' / ')
  return String(value)
}

type TemplateBinding = {
  store_name?: string
  category_name?: string
  platform?: string
}

function textValue(value: unknown) {
  return typeof value === 'string' ? value.trim() : value === undefined || value === null ? '' : String(value).trim()
}

function findSelectedTaskProduct(products: Product[], selectedTask: Task | null) {
  const productIds = Array.isArray(selectedTask?.payload?.product_ids) ? selectedTask.payload.product_ids : []
  const firstProductId = productIds.length ? Number(productIds[0]) : null
  if (firstProductId !== null && Number.isFinite(firstProductId)) {
    const matched = products.find((product) => product.id === firstProductId)
    if (matched) return matched
  }
  return products[0] ?? null
}

function normalizedIdentity(value: unknown) {
  return textValue(value).toLowerCase()
}

function uniqueByStoreIdentity(stores: Store[]) {
  const seen = new Set<string>()
  const unique: Store[] = []
  for (const store of stores) {
    const key = [normalizedIdentity(store.name), normalizedIdentity(store.platform)].join('|')
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(store)
  }
  return unique
}

function productSourceIdentity(product: Product) {
  const productRecord = product as Product & { payload?: Record<string, unknown>; source_url?: unknown; url?: unknown; source_urls?: unknown }
  const payload = productRecord.payload && typeof productRecord.payload === 'object' ? productRecord.payload : {}
  const directUrl = textValue(productRecord.source_url) || textValue(productRecord.url)
  const payloadUrl = textValue(payload.source_url) || textValue(payload.url)
  const sourceUrls = Array.isArray(payload.source_urls) ? payload.source_urls : Array.isArray(productRecord.source_urls) ? productRecord.source_urls : []
  return payloadUrl || directUrl || textValue(sourceUrls[0])
}

function productDisplayIdentity(product: Product) {
  const title = normalizedIdentity(product.title)
  if (!title) return `id:${product.id}`
  const source = normalizedIdentity(productSourceIdentity(product))
  const fallback = `sku:${textValue(product.sku_count)}`
  return [title, normalizedIdentity(product.category_name), source || fallback].join('|')
}

function uniqueByProductIdentity(products: Product[]) {
  const seen = new Set<string>()
  const unique: Product[] = []
  for (const product of products) {
    const key = productDisplayIdentity(product)
    if (seen.has(key)) continue
    seen.add(key)
    unique.push(product)
  }
  return unique
}

function buildCurrentTemplateBinding(workspace: DeliveryWorkspace, selectedTask: Task | null, product: Product | null): TemplateBinding {
  const storeName = textValue(selectedTask?.payload?.store_name) || textValue(workspace.stores[0]?.name)
  const store = workspace.stores.find((item) => item.name === storeName) ?? workspace.stores[0]
  const categoryName = textValue(selectedTask?.payload?.category_name) || textValue(product?.category_name)
  const platform = textValue(store?.platform) || 'AliExpress'
  return {
    ...(storeName ? { store_name: storeName } : {}),
    ...(categoryName ? { category_name: categoryName } : {}),
    ...(platform ? { platform } : {}),
  }
}

function templateBindingScopeLabel(binding: TemplateBinding) {
  const store = binding.store_name || '全店铺'
  const category = binding.category_name || '全类目'
  const platform = binding.platform || '全平台'
  return `店铺：${store} / 类目：${category} / 平台：${platform}`
}

function templateBindingCandidate(record: Record<string, unknown>, keys: string[]) {
  return keys.find((key) => Object.prototype.hasOwnProperty.call(record, key))
}

function templateBindingValues(value: unknown) {
  const values = Array.isArray(value) ? value : [value]
  return values
    .map((item) => textValue(item))
    .filter(Boolean)
}

function templateBindingRecord(template: Template) {
  const rawBinding = template.payload?.binding
  if (!rawBinding || typeof rawBinding !== 'object' || Array.isArray(rawBinding)) return null
  return rawBinding as Record<string, unknown>
}

function templateBindingValueMatches(expected: unknown, actual: string | undefined) {
  if (expected === undefined || expected === null || expected === '') return true
  const normalized = templateBindingValues(expected).map((item) => item.toLowerCase())
  return normalized.includes('*') || normalized.includes('all') || normalized.includes(textValue(actual).toLowerCase())
}

function templateBindingValueStrictlyMatches(expected: unknown, actual: string | undefined) {
  const actualValue = textValue(actual).toLowerCase()
  if (!actualValue) return false
  const normalized = templateBindingValues(expected).map((item) => item.toLowerCase())
  if (!normalized.length || normalized.includes('*') || normalized.includes('all')) return false
  return normalized.includes(actualValue)
}

function templateBindingValueExactlyMatches(expected: unknown, actual: string | undefined) {
  const actualValue = textValue(actual).toLowerCase()
  const expectedValues = templateBindingValues(expected).map((item) => item.toLowerCase())
  if (!expectedValues.length && !actualValue) return true
  if (!expectedValues.length || !actualValue) return false
  if (expectedValues.includes('*') || expectedValues.includes('all')) return false
  return expectedValues.length === 1 && expectedValues.includes(actualValue)
}

function templateBindingSpecificityValue(expected: unknown, actual: string | undefined) {
  const actualValue = textValue(actual).toLowerCase()
  const normalized = templateBindingValues(expected).map((item) => item.toLowerCase())
  if (!actualValue || !normalized.length || normalized.includes('*') || normalized.includes('all')) return 0
  if (!normalized.includes(actualValue)) return 0
  return normalized.length === 1 ? 3 : 2
}

function templateBindingField(record: Record<string, unknown>, keys: string[]) {
  return record[templateBindingCandidate(record, keys) ?? '']
}

function templateHasExactBinding(template: Template, binding: TemplateBinding) {
  const record = templateBindingRecord(template)
  if (!record) return false
  return (
    templateBindingValueMatches(templateBindingField(record, ["store_name", "store", "stores", "store_names"]), binding.store_name)
    && templateBindingValueMatches(templateBindingField(record, ["category_name", "category", "categories", "category_names"]), binding.category_name)
    && templateBindingValueMatches(templateBindingField(record, ["platform", "platforms"]), binding.platform)
  )
}

function templateHasStrictBinding(template: Template, binding: TemplateBinding) {
  const record = templateBindingRecord(template)
  if (!record) return false
  return (
    templateBindingValueExactlyMatches(templateBindingField(record, ["store_name", "store", "stores", "store_names"]), binding.store_name)
    && templateBindingValueExactlyMatches(templateBindingField(record, ["category_name", "category", "categories", "category_names"]), binding.category_name)
    && templateBindingValueExactlyMatches(templateBindingField(record, ["platform", "platforms"]), binding.platform)
  )
}

function findScopedTemplate(templates: Template[], templateType: string, binding: TemplateBinding) {
  return templates
    .filter((template) => template.template_type === templateType && templateSelectableForBinding(template, binding))
    .sort((left, right) => compareTemplateBindingSpecificity(left, right, binding))[0]
}

function findExactScopedTemplate(templates: Template[], templateType: string, binding: TemplateBinding) {
  return templates.find((template) => template.template_type === templateType && templateHasStrictBinding(template, binding))
}

function exactScopedTemplatesForSection(templates: Template[], section: EditableConfigSection, binding: TemplateBinding) {
  return templates.filter((template) => template.template_type === section.templateType && templateHasStrictBinding(template, binding))
}

function defaultTestTemplateName(section: EditableConfigSection) {
  return `默认测试模板 / ${section.title}`
}

function isDefaultTestTemplate(template: Template) {
  return String(template.template_name || '').startsWith('默认测试模板')
}

function templateBindingSpecificity(template: Template, binding: TemplateBinding) {
  const record = templateBindingRecord(template)
  if (!record) return 0
  return (
    templateBindingSpecificityValue(templateBindingField(record, ["store_name", "store", "stores", "store_names"]), binding.store_name)
    + templateBindingSpecificityValue(templateBindingField(record, ["category_name", "category", "categories", "category_names"]), binding.category_name)
    + templateBindingSpecificityValue(templateBindingField(record, ["platform", "platforms"]), binding.platform)
  )
}

function compareTemplateBindingSpecificity(left: Template, right: Template, binding: TemplateBinding) {
  const scoreDiff = templateBindingSpecificity(right, binding) - templateBindingSpecificity(left, binding)
  return scoreDiff || left.template_name.localeCompare(right.template_name, 'zh-CN') || right.id - left.id
}

function templateSelectableForBinding(template: Template, binding: TemplateBinding) {
  const rawBinding = templateBindingRecord(template)
  if (!rawBinding) return true
  return templateHasExactBinding(template, binding)
}

function templateBindingDisplayValue(value: unknown) {
  const values = templateBindingValues(value)
  if (!values.length) return '未限制'
  if (values.includes('*') || values.map((item) => item.toLowerCase()).includes('all')) return '全部'
  return values.join('、')
}

function templateFilterReason(template: Template, binding: TemplateBinding) {
  if (!template.is_enabled) return '停用：模板已关闭，不会进入当前任务候选。'
  const record = templateBindingRecord(template)
  if (!record) return '可用：未限制店铺、类目或平台。'
  const checks = [
    {
      label: '店铺',
      mismatch: '店铺不匹配',
      expected: templateBindingField(record, ["store_name", "store", "stores", "store_names"]),
      actual: binding.store_name,
    },
    {
      label: '类目',
      mismatch: '类目不匹配',
      expected: templateBindingField(record, ["category_name", "category", "categories", "category_names"]),
      actual: binding.category_name,
    },
    {
      label: '平台',
      mismatch: '平台不匹配',
      expected: templateBindingField(record, ["platform", "platforms"]),
      actual: binding.platform,
    },
  ]
  const failed = checks.find((check) => !templateBindingValueMatches(check.expected, check.actual))
  if (failed) {
    return `${failed.mismatch}：模板 ${failed.label}=${templateBindingDisplayValue(failed.expected)}，当前 ${failed.label}=${textValue(failed.actual) || '未设置'}。`
  }
  return '可用：匹配当前店铺、类目和平台。'
}

function templateMatchSummary(template: Template | undefined, binding: TemplateBinding) {
  if (!template) return '尚未选择已保存模板；可先套用默认测试模板或保存当前分区。'
  if (!templateBindingRecord(template)) return '当前命中全局模板，未限制店铺、类目或平台。'
  const score = templateBindingSpecificity(template, binding)
  return score > 0
    ? `当前命中精确模板，匹配强度 ${score}。`
    : '当前命中可用模板，但未形成精确店铺/类目/平台绑定。'
}

function templateTraceSummaries(trace: unknown[]) {
  return trace
    .map((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return ''
      const record = item as Record<string, unknown>
      const name = textValue(record.template_name) || textValue(record.template_type) || '未命名模板'
      const scope = textValue(record.binding_scope)
      const type = textValue(record.template_type)
      return `${name}${type ? ` / ${type}` : ''}${scope ? ` / ${scope}` : ''}`
    })
    .filter(Boolean)
    .slice(0, 4)
}

function sectionTemplateOptions(templates: Template[], section: EditableConfigSection, binding: TemplateBinding) {
  return templates
    .filter((template) => template.template_type === section.templateType && template.is_enabled && templateSelectableForBinding(template, binding))
    .sort((left, right) => compareTemplateBindingSpecificity(left, right, binding))
}

function templateOptionLabel(template: Template) {
  const fieldCount = countNestedConfigValues(template.payload)
  return `#${template.id} ${template.template_name} / ${template.binding_scope} / ${fieldCount} 项配置`
}

function withTemplateBinding(payload: Record<string, unknown>, binding: TemplateBinding) {
  const cleanBinding = Object.fromEntries(
    Object.entries(binding).filter(([, value]) => textValue(value)),
  )
  return Object.keys(cleanBinding).length ? { ...payload, binding: cleanBinding } : payload
}

function templatePayloadForSection(template: Template | Omit<Template, 'id'> | undefined, section: EditableConfigSection) {
  const payload = template?.payload
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {}
  const record = { ...(payload as Record<string, unknown>) }
  delete record.binding
  const grouped = record[section.templateType]
  if (grouped && typeof grouped === 'object' && !Array.isArray(grouped)) {
    return { ...record, ...(grouped as Record<string, unknown>) }
  }
  return record
}

function defaultTemplatePayloadForSection(section: EditableConfigSection, binding: TemplateBinding) {
  const seed = demoTemplateSeeds.find((template) => template.template_type === section.templateType)
  const payload = templatePayloadForSection(seed, section)
  const defaultsByType: Record<string, Record<string, unknown>> = {
    task_basic: {
      store_name: binding.store_name || 'Dang Kang',
      category_name: binding.category_name || '立牌类谷子',
      claim_mark: 'DXM 单商品只保存',
    },
    category: {
      category_name: binding.category_name || '立牌类谷子',
      category_keyword: '立牌',
      title_strategy: '保留原始标题并清洗平台词',
    },
    sku: {
      sku_code: '沿用店小秘生成',
      stock: '200',
      jit_stock: '100',
      goods_code_strategy: '沿用店小秘生成',
      barcode_strategy: '留空',
    },
    pricing: {
      product_price: '7.01',
      supply_price: '5.20',
      declared_value: '1',
      stock: '200',
      price_strategy: '按默认配置固定价',
    },
    image: {
      source: '图片银行（速卖通）',
      eu_outer_package_filename: '微信图片_202504092228421.jpg',
      marketing_images_strategy: '使用 EU 外包装图补齐 3:4',
      main_image_strategy: '保留 800x800 合规主图',
      invalid_image_strategy: '删除 0x0 无效图',
    },
    logistics: {
      weight: '0.03',
      length: '10',
      width: '10',
      height: '2',
      logistics_attribute: '普货',
      freight_template: '石油40g普货包裹.',
      service_template: 'Service Template for New Sellers',
      package_gross_weight: '0.057',
    },
    compliance: {
      customs_name: '钥匙扣',
      material: 'Acrylic',
      purpose: 'Decoration',
      brand: '无品牌',
      statement: '符合平台合规要求',
      eu_responsible_names: ['Jacqueiline Marti'],
      manufacturer_names: ['jiyang county thunder', 'Jiyang County thunder'],
      customs_product_names: ['钥匙扣', 'keychain'],
    },
    semi_managed: {
      product_price: '7.01',
      supply_price: '5.20',
      countries: '全选',
      original_box: '否',
      is_original_box: '否',
      jit_stock: '100',
      barcode_strategy: '留空',
      length: '10',
      width: '10',
      height: '2',
      goods_code_strategy: '沿用店小秘生成',
    },
  }
  return { ...payload, ...(defaultsByType[section.templateType] ?? {}) }
}

function buildSectionDraftFromPayload(section: EditableConfigSection, payload: Record<string, unknown>) {
  return Object.fromEntries(section.fields.map((field) => [
    field.name,
    editableConfigDraftValue(getNestedConfigValue(payload, field.name) ?? payload[field.name], field),
  ]))
}

function buildEditableConfigDraft(templates: Template[], configPreview: ConfigPreview | null, binding: TemplateBinding) {
  const draft = {} as Record<ConfigSectionCode, Record<string, string>>
  editableConfigSections.forEach((section) => {
    const template = findScopedTemplate(templates, section.templateType, binding)
    const payload = template?.payload ?? {}
    const preview = configPreview?.fieldGroups.find((group) => group.section === section.previewSection)
    draft[section.code] = Object.fromEntries(section.fields.map((field) => [
      field.name,
      (() => {
        const previewField = fieldPreview(preview, field)
        if (previewField && previewField.value !== undefined && previewField.value !== null && String(previewField.value).trim() !== '') {
          return editableConfigDraftValue(previewField.value, field)
        }
        const payloadValue = getNestedConfigValue(payload, field.name) ?? payload[field.name]
        return editableConfigDraftValue(payloadValue, field)
      })(),
    ]))
  })
  return draft
}

function ConfigReadinessPanel({
  configPreview,
  configPreviewError,
  selectedTask,
  incompleteGroups,
}: {
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  selectedTask: Task | null
  incompleteGroups: ConfigPreviewGroup[]
}) {
  if (!selectedTask) {
    return <EmptyState title="先选择任务" detail="选择单商品只保存任务后，这里会显示执行前配置是否完整。" />
  }
  if (configPreviewError) {
    return (
      <div className="config-readiness is-danger" role="alert">
        <strong>配置检查接口不可用</strong>
        <span>{humanConfigError(configPreviewError)}</span>
        <span>请先确认本机后端仍在运行，再重新检查配置；系统不会把接口失败当成字段已补齐。</span>
      </div>
    )
  }
  if (!configPreview) {
    return <div className="config-readiness is-warn"><strong>本次任务配置检查未加载</strong><span>请刷新工作台，或确认后端 /api/config/preview 可用。</span></div>
  }
  const missing = configPreview.missing.slice(0, 8)
  return (
    <div className={`config-readiness ${configPreview.ok ? 'is-ok' : 'is-warn'}`}>
      <div>
        <strong>{configPreview.ok ? '配置可用于当前任务' : '配置还不能启动真实保存'}</strong>
        <span>任务 #{configPreview.taskId} / {humanTaskModeLabel(configPreview.mode)} / {configPreview.ok ? '可进入保存判断' : `待补 ${incompleteGroups.length || missing.length} 项`}</span>
      </div>
      {missing.length > 0 && (
        <div className="missing-strip">
          {missing.map((item) => <span key={item}>{item}</span>)}
        </div>
      )}
    </div>
  )
}

function NextRequiredConfigFields({
  section,
  preview,
  configOk,
  loading,
  onEditRequiredSection,
}: {
  section: EditableConfigSection
  preview: ConfigPreviewGroup | undefined
  configOk: boolean
  loading: boolean
  onEditRequiredSection: () => void
}) {
  const missingFields = (preview?.fields ?? [])
    .filter((field) => field.missing)
    .slice(0, 5)
  const fallbackFields = section.fields.slice(0, 4).map((field) => ({
    label: field.label,
    path: field.previewPath ?? field.name,
    source: '等待检查',
  }))
  const fields = missingFields.length
    ? missingFields.map((field) => ({ label: field.label, path: field.path, source: field.source }))
    : fallbackFields

  return (
    <div
      className={`next-required-fields ${configOk ? 'is-ok' : 'is-warn'}`}
      aria-label="下一步必填字段"
      data-config-next-required={section.code}
    >
      <div>
        <strong>{configOk ? '当前任务配置已就绪' : `下一步必填字段：${section.title}`}</strong>
        <span>{configOk ? '需要微调时再展开下方分区。' : '只显示当前最需要处理的字段；完整字段放在下方分区。'}</span>
        {!configOk && (
          <button className="button button--secondary next-required-fields__action" type="button" onClick={onEditRequiredSection}>
            编辑当前必填分区
          </button>
        )}
      </div>
      <div className="next-required-fields__list">
        {loading ? (
          <span>正在读取配置检查结果...</span>
        ) : fields.map((field) => (
          <span key={`${field.path}:${field.label}`}>
            <b>{field.label}</b>
            <code>{field.path}</code>
            {!configOk && <small>{field.source}</small>}
          </span>
        ))}
      </div>
    </div>
  )
}

function sourceBadgeText(source: string) {
  if (source.startsWith('任务：') || source.startsWith('任务覆盖')) return '执行取值来自：本次任务'
  if (source.startsWith('商品：') || source.includes('商品 payload')) return '执行取值来自：商品原始数据'
  if (source.startsWith('模板：')) {
    return source.includes('默认测试模板') ? '执行取值来自：默认测试模板' : '执行取值来自：店铺模板'
  }
  if (source === '系统默认值') return '执行取值来自：默认测试模板'
  return source ? `执行取值来自：${source}` : '执行取值来自：未设置'
}

function formatPreviewValue(value: unknown) {
  if (value === undefined || value === null || String(value).trim() === '') return '空'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function templateSourceNameFromPreview(preview: ConfigPreviewGroup | undefined) {
  const source = (preview?.fields ?? [])
    .map((field) => field.source)
    .find((item) => item.startsWith('模板：'))
  return source ? source.replace(/^模板：/, '') : ''
}

function EffectiveValuePreview({
  configPreview,
  sourcePriorityLabels,
  title,
}: {
  configPreview: ConfigPreview | null
  sourcePriorityLabels: string[]
  title: string
}) {
  const fields = (configPreview?.fieldGroups ?? [])
    .flatMap((group) => group.fields.map((field) => ({ ...field, groupLabel: group.label })))
    .filter((field) => field.required || field.value !== undefined)
    .slice(0, 14)

  return (
    <details className="module-card span-3 disclosure-card effective-value-preview">
      <summary>
        {title}
        <span>{configPreview?.taskId ? `任务 #${configPreview.taskId}，展开查看最终取值来源` : '等待任务'}</span>
      </summary>
      <div className="source-legend" aria-label="取值优先级">
        {sourcePriorityLabels.map((label) => <span key={label}>{label}</span>)}
      </div>
      {!configPreview ? (
        <EmptyState title="暂无预览" detail="选择任务后，会展示执行器最终写入 DXM 编辑页的字段值。" />
      ) : (
        <div className="effective-value-grid">
          {fields.map((field) => (
            <div className={field.missing ? 'effective-value-item is-missing' : 'effective-value-item'} key={`${field.path}:${field.groupLabel}`}>
              <span>{field.groupLabel}</span>
              <strong>{field.label}</strong>
              <code>{formatPreviewValue(field.value)}</code>
              <small>{sourceBadgeText(field.source)}</small>
              <details className="section-execution-preview__technical">
                <summary>字段来源详情</summary>
                <small>{field.path}</small>
              </details>
            </div>
          ))}
        </div>
      )}
    </details>
  )
}

function previewSummary(section: EditableConfigSection, preview?: ConfigPreviewGroup, configOk = false) {
  if (!preview) return `${section.detail} / 等待检查`
  if (!preview.templatePresent) return `${section.detail} / 未保存模板`
  if (!preview.complete) {
    const missingCount = preview.missing.length || preview.fields.filter((field) => field.missing).length
    return configOk
      ? `${section.detail} / 辅助缺 ${missingCount} 项，不阻断启动`
      : `${section.detail} / 缺 ${missingCount} 项`
  }
  return `${section.detail} / 页面填写值会进入执行取值，带 * 字段参与启动门禁`
}

function fieldPreview(preview: ConfigPreviewGroup | undefined, field: EditableConfigField) {
  return preview?.fields.find((item) => item.path === (field.previewPath ?? field.name) || item.name === field.name)
}

function fieldSourceText(field: ReturnType<typeof fieldPreview>) {
  if (!field) return '来源：等待检查'
  if (field.missing) return `缺失：${field.label}`
  const value = field.value === undefined || field.value === null || String(field.value).trim() === '' ? '空' : String(field.value)
  return `当前值：${value} / ${sourceBadgeText(field.source)}`
}

function fieldUsageLabel(usage?: EditableConfigField['usage']) {
  if (usage === 'direct') return '执行取值'
  if (usage === 'template') return '模板匹配'
  if (usage === 'advisory') return '辅助配置'
  return ''
}

function configSectionState(preview: ConfigPreviewGroup | undefined, configOk = false) {
  if (!preview) return { label: '等待检查', className: 'is-pending' }
  if (!preview.templatePresent) return { label: '缺模板', className: 'is-incomplete' }
  if (!preview.complete) {
    return configOk
      ? { label: '辅助待补', className: 'is-advisory' }
      : { label: '待补字段', className: 'is-incomplete' }
  }
  return { label: '已就绪', className: 'is-complete' }
}

function countPreviewTaskOverrideFields(preview: ConfigPreviewGroup | undefined) {
  return (preview?.fields ?? []).filter((field) => field.source === '任务覆盖' || field.source.startsWith('任务覆盖')).length
}

function countTaskOverrideFields(task: Task | null, templateType: string) {
  const overrides = task?.payload?.template_overrides
  if (!overrides || typeof overrides !== 'object' || Array.isArray(overrides)) return 0
  return countNestedConfigValues((overrides as Record<string, unknown>)[templateType])
}

function countNestedConfigValues(value: unknown): number {
  if (value === undefined || value === null) return 0
  if (Array.isArray(value)) return value.some((item) => countNestedConfigValues(item) > 0) ? 1 : 0
  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).reduce<number>((total, child) => total + countNestedConfigValues(child), 0)
  }
  return String(value).trim() ? 1 : 0
}

function hasConfigDraftChanged(current: Record<string, string> | undefined, baseline: Record<string, string> | undefined) {
  const keys = new Set([...Object.keys(current ?? {}), ...Object.keys(baseline ?? {})])
  for (const key of keys) {
    if ((current?.[key] ?? '') !== (baseline?.[key] ?? '')) return true
  }
  return false
}

function TemplateMatchExplanation({
  activeTemplateName,
  activeTemplateSourceName,
  allTemplates,
  activeTemplate,
  availableTemplates,
  binding,
  currentScopeLabel,
  persisted,
  templateTrace,
}: {
  activeTemplateName: string
  activeTemplateSourceName: string
  activeTemplate?: Template
  allTemplates: Template[]
  availableTemplates: Template[]
  binding: TemplateBinding
  currentScopeLabel: string
  persisted: boolean
  templateTrace: unknown[]
}) {
  const availableIds = new Set(availableTemplates.map((template) => template.id))
  const filteredTemplates = allTemplates.filter((template) => !availableIds.has(template.id))
  const disabledCount = filteredTemplates.filter((template) => !template.is_enabled).length
  const bindingMismatchCount = filteredTemplates.length - disabledCount
  const traceSummaries = templateTraceSummaries(templateTrace)
  const filteredSummaries = filteredTemplates.slice(0, 4).map((template) => `${template.template_name}：${templateFilterReason(template, binding)}`)
  const effectiveTemplateName = activeTemplateSourceName || activeTemplateName || (persisted ? '配置检查已命中模板' : '尚未命中已保存模板')

  return (
    <div className="template-match-explanation" aria-label="模板命中解释">
      <strong>模板命中解释</strong>
      <span>当前匹配范围：{currentScopeLabel}</span>
      <span>当前命中：{effectiveTemplateName}</span>
      <small>{templateMatchSummary(activeTemplate, binding)}</small>
      <div className="template-match-explanation__facts">
        <span><b>可选模板</b><strong>{availableTemplates.length}</strong></span>
        <span><b>筛除模板</b><strong>{filteredTemplates.length}</strong></span>
        <span><b>停用</b><strong>{disabledCount}</strong></span>
        <span><b>范围不匹配</b><strong>{bindingMismatchCount}</strong></span>
      </div>
      <details className="inline-disclosure template-match-explanation__details">
        <summary>查看筛除原因和后端命中记录</summary>
        <div className="template-match-explanation__lists">
          <div>
            <b>筛除原因</b>
            {filteredSummaries.length ? (
              filteredSummaries.map((item) => <small key={item}>{item}</small>)
            ) : (
              <small>当前分区没有被筛除的模板。</small>
            )}
          </div>
          <div>
            <b>后端命中记录</b>
            {traceSummaries.length ? (
              traceSummaries.map((item) => <small key={item}>{item}</small>)
            ) : (
              <small>等待本次任务配置检查返回 templateTrace。</small>
            )}
          </div>
        </div>
      </details>
    </div>
  )
}

export function ConfigCenter({ workspace, selectedTask, configPreview, configPreviewError, configPreviewLoading, onConfigSaved, onRefreshConfigPreview, onShowTasks }: ConfigCenterProps) {
  const product = findSelectedTaskProduct(workspace.products, selectedTask)
  const currentTemplateBinding = useMemo(
    () => buildCurrentTemplateBinding(workspace, selectedTask, product),
    [workspace, selectedTask, product],
  )
  const currentTemplateScopeLabel = templateBindingScopeLabel(currentTemplateBinding)
  const configContextKey = `${selectedTask?.id ?? 'no-task'}|${currentTemplateScopeLabel}`
  const enabledTemplates = workspace.templates.filter((item) => item.is_enabled)
  const templateResults = workspace.templateResolution?.dxm_reference_template_results ?? {}
  const hasStores = workspace.stores.length > 0
  const hasProducts = workspace.products.length > 0
  const previewGroups = new Map((configPreview?.fieldGroups ?? []).map((group) => [group.section, group]))
  const incompleteGroups = (configPreview?.fieldGroups ?? []).filter((group) => group.required && !group.complete)
  const initialConfigDraft = useMemo(() => buildEditableConfigDraft(workspace.templates, configPreview, currentTemplateBinding), [workspace.templates, configPreview, currentTemplateBinding])
  const [configDraft, setConfigDraft] = useState(initialConfigDraft)
  const [savingSection, setSavingSection] = useState<string | null>(null)
  const [configMessage, setConfigMessage] = useState<string | null>(null)
  const [defaultTemplatePackState, setDefaultTemplatePackState] = useState<string>('尚未套用默认测试模板')
  const [selectedTemplateBySection, setSelectedTemplateBySection] = useState<Record<ConfigSectionCode, string>>({} as Record<ConfigSectionCode, string>)
  const [lastSavedTemplateBySection, setLastSavedTemplateBySection] = useState<Record<ConfigSectionCode, { id: number; name: string; savedAt: string }>>({} as Record<ConfigSectionCode, { id: number; name: string; savedAt: string }>)
  const [sectionSaveState, setSectionSaveState] = useState<Record<ConfigSectionCode, ConfigSectionSaveState>>({} as Record<ConfigSectionCode, ConfigSectionSaveState>)
  const sectionsWithPreview = editableConfigSections.map((section) => ({
    section,
    preview: previewGroups.get(section.previewSection),
  }))
  const sectionsBlockingStart = sectionsWithPreview.filter(({ preview }) => preview && (!preview.templatePresent || (preview.required && !preview.complete)))
  const sectionsWithAdvisoryGaps = sectionsWithPreview.filter(({ preview }) => preview && preview.templatePresent && !preview.complete && !preview.required)
  const advisoryGapCount = sectionsWithAdvisoryGaps.length
  const sectionsReady = sectionsWithPreview.filter(({ preview }) => Boolean(preview && preview.complete && preview.templatePresent))
  const nextConfigSection = sectionsBlockingStart[0]?.section ?? editableConfigSections[0]
  const nextConfigPreview = sectionsBlockingStart[0]?.preview ?? previewGroups.get(nextConfigSection.previewSection)
  const [activeConfigSectionCode, setActiveConfigSectionCode] = useState<ConfigSectionCode>(nextConfigSection.code)
  const selectedConfigSection = sectionsWithPreview.find(({ section }) => section.code === activeConfigSectionCode)
    ?? sectionsWithPreview.find(({ section }) => section.code === nextConfigSection.code)
    ?? sectionsWithPreview[0]
  const primaryConfigSections = uniqueConfigSections([
    selectedConfigSection,
    ...sectionsBlockingStart,
    ...sectionsWithAdvisoryGaps,
    ...sectionsReady,
    ...sectionsWithPreview,
  ]).slice(0, 4)
  const primaryConfigSectionCodes = new Set(primaryConfigSections.map(({ section }) => section.code))
  const secondaryConfigSections = sectionsWithPreview.filter(({ section }) => !primaryConfigSectionCodes.has(section.code))
  const activeTaskOverrideFieldCount = countTaskOverrideFields(selectedTask, selectedConfigSection.section.templateType)
  const activePreviewOverrideFieldCount = countPreviewTaskOverrideFields(selectedConfigSection.preview)
  const activeSectionAllTemplates = workspace.templates.filter((template) => template.template_type === selectedConfigSection.section.templateType)
  const activeSectionTemplateOptions = sectionTemplateOptions(workspace.templates, selectedConfigSection.section, currentTemplateBinding)
  const filteredTemplateChoiceCount = Math.max(0, activeSectionAllTemplates.length - activeSectionTemplateOptions.length)
  const activeSelectedTemplateId = selectedTemplateBySection[selectedConfigSection.section.code] ?? ''
  const activeSelectedTemplate = activeSectionTemplateOptions.find((template) => String(template.id) === activeSelectedTemplateId)
  const activeTemplateSourceName = templateSourceNameFromPreview(selectedConfigSection.preview)
  const activeSectionAlreadyPersisted = Boolean(selectedConfigSection.preview?.templatePresent)
  const activeSelectedTemplateLabel = activeSelectedTemplateId === '__default_test__'
    ? '默认测试模板（当前分区）'
    : activeSelectedTemplate
      ? templateOptionLabel(activeSelectedTemplate)
      : '未选择模板'
  const activePendingTemplateActionLabel = activeSelectedTemplateId
    ? `待套用：${activeSelectedTemplateLabel}`
    : '未选择待套用模板'
  const activeLastSavedTemplate = lastSavedTemplateBySection[selectedConfigSection.section.code]
  const activeLastSavedTemplateLabel = activeLastSavedTemplate
    ? `#${activeLastSavedTemplate.id} ${activeLastSavedTemplate.name} / ${activeLastSavedTemplate.savedAt}`
    : '本分区尚无最近保存记录'
  const activeTemplateUsageLabel = activeTemplateSourceName
    || (activeSectionAlreadyPersisted ? '配置检查已命中模板' : '尚未命中已保存模板')
  const activeTemplateTrace = configPreview?.templateTrace?.length
    ? configPreview.templateTrace
    : workspace.templateResolution?.template_trace ?? []
  const activeSectionSaveState = sectionSaveState[selectedConfigSection.section.code]
  const activeSectionDirty = hasConfigDraftChanged(configDraft[selectedConfigSection.section.code], initialConfigDraft[selectedConfigSection.section.code])
  const templateSaveDisabled = !selectedTask
  const templateMatchExplanation = {
    allTemplates: activeSectionAllTemplates,
    availableTemplates: activeSectionTemplateOptions,
    binding: currentTemplateBinding,
    currentScopeLabel: currentTemplateScopeLabel,
    activeTemplate: activeSelectedTemplate,
    activeTemplateName: activeSelectedTemplateLabel,
    activeTemplateSourceName,
    persisted: activeSectionAlreadyPersisted,
    templateTrace: activeTemplateTrace,
  }
  const activeSectionStatus = activeSectionSaveState?.status ?? (activeSectionDirty ? 'dirty' : 'clean')
  const activeSectionStatusTitle = activeSectionStatus === 'dirty'
    ? '未保存的修改'
    : activeSectionStatus === 'saved'
      ? '已保存'
      : activeSectionStatus === 'saving'
        ? '保存中'
        : activeSectionStatus === 'failed'
          ? '保存失败'
          : activeSectionAlreadyPersisted
            ? '已保存模板'
            : '未保存模板'
  const activeSectionStatusMessage = activeSectionSaveState?.message
    ?? (activeSectionStatus === 'dirty'
      ? '当前分区有改动，尚未保存；未保存的修改不会进入执行。'
      : activeSectionAlreadyPersisted
        ? '当前分区来自已保存模板或任务覆盖，未修改。'
        : '当前分区还没有已保存模板，请套用默认测试模板或手动保存。')
  const currentTemplateDisplayLabel = activeTaskOverrideFieldCount > 0
    ? '本次任务覆盖'
    : activeTemplateSourceName
      ? activeTemplateSourceName.includes('默认测试模板') ? '默认测试模板' : '店铺模板'
      : activeSelectedTemplateId === '__default_test__'
        ? '默认测试模板'
        : activeSectionAlreadyPersisted
          ? '店铺模板'
          : '默认测试模板'
  const executionValueStatusLabel = activeSectionDirty
    ? '未保存的修改不会进入执行'
    : selectedTask
      ? '执行会使用这些值'
      : '选择任务后核对执行取值'
  const configCoverageLabels = ['店铺与任务基础', '类目与标题', 'SKU / 价格 / 库存', '价格策略', '图片与素材', '包装物流', '合规 / 海关', '半托管', '店小秘引用模板']
  const effectivePreviewTitle = '本次任务实际取值预览'
  const sourcePriorityLabels = ['本次任务', '店铺模板', '默认测试模板', '商品原始数据']
  const fieldUsageLegend = ['执行取值', '模板匹配', '辅助配置']
  const configReadyForReview = Boolean(configPreview?.ok)
  const configCoverageFieldIds = [
    'dxm_reference_templates.attribute_info.names',
    'dxm_reference_templates.description.names',
    'dxm_reference_templates.freight.names',
    'dxm_reference_templates.service.names',
    'dxm_reference_templates.eu_responsible.names',
    'dxm_reference_templates.manufacturer.names',
    'dxm_reference_templates.compliance.names',
    'dxm_reference_templates.semi_managed.names',
    '尺码模板',
    'price_multiplier',
    'local_asset_path',
    'brand',
  ]

  useEffect(() => {
    setConfigDraft(initialConfigDraft)
  }, [initialConfigDraft])

  useEffect(() => {
    setActiveConfigSectionCode(nextConfigSection.code)
  }, [nextConfigSection.code, selectedTask?.id])

  useEffect(() => {
    setSelectedTemplateBySection({} as Record<ConfigSectionCode, string>)
    setLastSavedTemplateBySection({} as Record<ConfigSectionCode, { id: number; name: string; savedAt: string }>)
    setSectionSaveState({} as Record<ConfigSectionCode, ConfigSectionSaveState>)
    setConfigMessage(null)
    setDefaultTemplatePackState('尚未套用默认测试模板')
  }, [configContextKey])

  function updateConfigField(sectionCode: ConfigSectionCode, fieldName: string, value: string) {
    setConfigDraft((current) => ({
      ...current,
      [sectionCode]: {
        ...(current[sectionCode] ?? {}),
        [fieldName]: value,
      },
    }))
    setSectionSaveState((current) => ({
      ...current,
      [sectionCode]: {
        status: 'dirty',
        message: '未保存的修改',
      },
    }))
  }

  function selectNextMissingConfigSection(savedSectionCode: ConfigSectionCode) {
    const blockingSections = sectionsBlockingStart.map(({ section }) => section)
    const currentIndex = blockingSections.findIndex((section) => section.code === savedSectionCode)
    const orderedCandidates = currentIndex >= 0
      ? [...blockingSections.slice(currentIndex + 1), ...blockingSections.slice(0, currentIndex)]
      : blockingSections
    const nextSection = orderedCandidates.find((section) => section.code !== savedSectionCode)
      ?? sectionsWithAdvisoryGaps[0]?.section
      ?? sectionsWithPreview.find(({ section }) => section.code !== savedSectionCode)?.section
      ?? nextConfigSection
    setActiveConfigSectionCode(nextSection.code)
  }

  async function saveConfigSection(section: EditableConfigSection, scope: 'template' | 'task' = 'template', continueToNextMissingSection = false) {
    setSavingSection(`${scope}:${section.code}`)
    setSectionSaveState((current) => ({
      ...current,
      [section.code]: {
        status: 'saving',
        scope: scope === 'task' ? '本次任务' : '店铺模板',
        message: '保存中...',
      },
    }))
    setConfigMessage(null)
    try {
      const payload = section.fields.reduce<Record<string, unknown>>((acc, field) => {
        const rawValue = configDraft[section.code]?.[field.name] ?? ''
        setNestedConfigValue(acc, field.name, parseEditableConfigFieldValue(field, rawValue))
        return acc
      }, {})
      if (scope === 'task') {
        if (!selectedTask) throw new Error('请先选择任务')
        await patchJson<Task>(`/api/tasks/${selectedTask.id}/config-overrides`, {
          section: section.templateType,
          values: payload,
        })
        const savedAt = new Date().toLocaleString('zh-CN', { hour12: false })
        setSectionSaveState((current) => ({
          ...current,
          [section.code]: {
            status: 'saved',
            scope: '本次任务',
            savedAt,
            message: `已保存到本次任务；保存时间 ${savedAt}`,
          },
        }))
        setConfigMessage(`${section.title} 已保存为本次任务覆盖；页面填写值会进入执行取值，带 * 字段参与启动门禁，辅助配置不作为启动门禁必填。`)
        await onConfigSaved()
        if (continueToNextMissingSection) {
          selectNextMissingConfigSection(section.code)
        }
        return
      }
      const existing = findExactScopedTemplate(workspace.templates, section.templateType, currentTemplateBinding)
      const body = {
        template_type: section.templateType,
        template_name: section.title,
        binding_scope: currentTemplateScopeLabel,
        payload: withTemplateBinding(payload, currentTemplateBinding),
        is_enabled: true,
      }
      const savedTemplate = existing
        ? await patchJson<Template>(`/api/templates/${existing.id}`, body)
        : await postJson<Template>('/api/templates', body)
      const savedAt = new Date().toLocaleString('zh-CN', { hour12: false })
      setSelectedTemplateBySection((current) => ({ ...current, [section.code]: String(savedTemplate.id) }))
      setLastSavedTemplateBySection((current) => ({
        ...current,
        [section.code]: {
          id: savedTemplate.id,
          name: savedTemplate.template_name,
          savedAt,
        },
      }))
      setSectionSaveState((current) => ({
        ...current,
        [section.code]: {
          status: 'saved',
          scope: '店铺模板',
          savedAt,
          message: `${existing ? '已覆盖' : '已新建'}店铺模板 #${savedTemplate.id} ${savedTemplate.template_name}；保存时间 ${savedAt}`,
        },
      }))
      setConfigMessage(`${section.title} ${existing ? '已覆盖' : '已新建'}店铺模板 #${savedTemplate.id}，影响范围：${currentTemplateScopeLabel}；后续匹配该范围的任务会按该模板取值，辅助配置会进入执行取值但不作为启动门禁必填。`)
      await onConfigSaved()
      if (continueToNextMissingSection) {
        selectNextMissingConfigSection(section.code)
      }
    } catch (error) {
      const message = humanConfigError(error instanceof Error ? error.message : `${section.title} 保存失败`)
      setSectionSaveState((current) => ({
        ...current,
        [section.code]: {
          status: 'failed',
          scope: scope === 'task' ? '本次任务' : '店铺模板',
          message,
        },
      }))
      setConfigMessage(message)
    } finally {
      setSavingSection(null)
    }
  }

  function continueToNextMissingSection(section: EditableConfigSection, scope: 'template' | 'task') {
    void saveConfigSection(section, scope, true)
  }

  function applyTemplateToDraft(section: EditableConfigSection, templateId: string) {
    const payload = templateId === '__default_test__'
      ? defaultTemplatePayloadForSection(section, currentTemplateBinding)
      : templatePayloadForSection(workspace.templates.find((template) => String(template.id) === templateId), section)
    setSelectedTemplateBySection((current) => ({ ...current, [section.code]: templateId }))
    setConfigDraft((current) => ({
      ...current,
      [section.code]: buildSectionDraftFromPayload(section, payload),
    }))
    setSectionSaveState((current) => ({
      ...current,
      [section.code]: {
        status: 'dirty',
        message: templateId === '__default_test__' ? '已套用默认测试模板，尚未保存' : '已套用模板，尚未保存',
      },
    }))
  }

  function handleTemplateSelection(section: EditableConfigSection, templateId: string) {
    setSelectedTemplateBySection((current) => ({ ...current, [section.code]: templateId }))
  }

  async function applyDefaultTemplatePack() {
    if (!selectedTask) {
      setDefaultTemplatePackState('先选择任务，避免误存为全店/全类目模板。')
      setConfigMessage('先选择任务，避免误存为全店/全类目模板。')
      return
    }
    const confirmMessage = `确认套用默认测试模板？将默认测试模板单独保存到当前店铺/类目范围：${currentTemplateScopeLabel}。它是示例/测试模板，不代表已配置完成；不会覆盖已有正式店铺模板，如已有默认测试模板则更新默认测试模板。`
    if (!window.confirm(confirmMessage)) {
      setDefaultTemplatePackState('已取消套用默认测试模板')
      return
    }
    setSavingSection('template:default-pack')
    setDefaultTemplatePackState('正在保存默认测试模板...')
    setConfigMessage(null)
    try {
      const nextDraft = { ...configDraft }
      const nextSelectedTemplates = { ...selectedTemplateBySection }
      const nextLastSavedTemplates = { ...lastSavedTemplateBySection }
      let preservedFormalTemplateCount = 0
      for (const section of editableConfigSections) {
        const payload = defaultTemplatePayloadForSection(section, currentTemplateBinding)
        nextDraft[section.code] = buildSectionDraftFromPayload(section, payload)
        const exactScopedTemplates = exactScopedTemplatesForSection(workspace.templates, section, currentTemplateBinding)
        const existingDefaultTestTemplate = exactScopedTemplates.find(isDefaultTestTemplate)
        const existingFormalTemplate = exactScopedTemplates.find((template) => !isDefaultTestTemplate(template))
        if (existingFormalTemplate) preservedFormalTemplateCount += 1
        const body = {
          template_type: section.templateType,
          template_name: defaultTestTemplateName(section),
          binding_scope: currentTemplateScopeLabel,
          payload: withTemplateBinding(payload, currentTemplateBinding),
          is_enabled: true,
        }
        const savedTemplate = existingDefaultTestTemplate
          ? await patchJson<Template>(`/api/templates/${existingDefaultTestTemplate.id}`, body)
          : await postJson<Template>('/api/templates', body)
        nextSelectedTemplates[section.code] = String(savedTemplate.id)
        nextLastSavedTemplates[section.code] = {
          id: savedTemplate.id,
          name: savedTemplate.template_name,
          savedAt: new Date().toLocaleString('zh-CN', { hour12: false }),
        }
      }
      const savedAt = new Date().toLocaleString('zh-CN', { hour12: false })
      setConfigDraft(nextDraft)
      setSelectedTemplateBySection(nextSelectedTemplates)
      setLastSavedTemplateBySection(nextLastSavedTemplates)
      setSectionSaveState(() => Object.fromEntries(
        editableConfigSections.map((section) => [
          section.code,
          {
            status: 'saved',
            scope: '店铺模板',
            savedAt,
            message: `默认测试模板已单独保存；保存时间 ${savedAt}`,
          },
        ]),
      ) as Record<ConfigSectionCode, ConfigSectionSaveState>)
      setDefaultTemplatePackState(`默认测试模板已保存；保存时间 ${savedAt}；已生成 ${Object.keys(nextLastSavedTemplates).length} 套分区模板`)
      setConfigMessage(`默认测试模板已写入当前店铺/类目范围：${currentTemplateScopeLabel}。这些是示例值，不代表已配置完成；真实执行前请按当前商品继续核对分区字段。${preservedFormalTemplateCount ? `已保留 ${preservedFormalTemplateCount} 套已有正式模板未覆盖。` : ''}`)
      await onConfigSaved()
    } catch (error) {
      const message = humanConfigError(error instanceof Error ? error.message : '默认测试模板保存失败')
      setDefaultTemplatePackState('默认测试模板保存失败')
      setConfigMessage(message)
    } finally {
      setSavingSection(null)
    }
  }

  async function runConfigPrecheck() {
    setConfigMessage('正在运行配置检查：读取当前任务、店铺、商品和模板；不会操作店小秘。')
    try {
      await onRefreshConfigPreview()
      setConfigMessage('配置检查已刷新；字段来源、缺失项和执行取值已按当前任务重新计算。')
    } catch (error) {
      setConfigMessage(humanConfigError(error instanceof Error ? error.message : '配置检查刷新失败'))
    }
  }

  return (
    <section className="module-layout" aria-label="填写编辑页">
      <div className="module-card span-3 config-focus-card">
        <ModuleHead title="填写编辑页" meta={configPreviewError ? '配置检查接口异常' : configPreviewLoading ? '正在检查配置' : '告诉 Agent 到店小秘编辑页怎么填'} />
        <div className="content-density-summary config-density-summary" data-config-density-summary>
          <div>
            <strong>{configPreviewError ? '配置检查接口不可用' : configPreview?.ok ? '配置已通过本次任务检查' : `先补：${nextConfigSection.title}`}</strong>
            <span>
              {configPreviewError
                ? '请先确认本机后端仍在运行，再重新检查配置。'
                : configPreview?.ok
                ? '下方可直接微调填写编辑页取值；详情和下一步字段已收起。'
                : previewSummary(nextConfigSection, nextConfigPreview)}
            </span>
          </div>
          <div className="content-density-summary__meta">
            <span className={`status-pill ${configPreview?.ok ? 'ok' : 'warn'}`}>
              {configPreview?.ok ? '可用于当前任务' : `${incompleteGroups.length || sectionsBlockingStart.length} 个分区待补`}
            </span>
            <small>{selectedTask ? `当前任务 #${selectedTask.id}` : '先到“选择商品”选择任务后，可保存为本次任务覆盖。'}</small>
            {configPreview?.ok && advisoryGapCount > 0 && <small>{advisoryGapCount} 个分区有辅助字段待补</small>}
            <small>当前模板范围：{currentTemplateScopeLabel}</small>
          </div>
        </div>
        <div className="config-precheck-action" aria-label="本次任务配置检查操作">
          <div>
            <strong>检查本次配置</strong>
            <span>配置检查会读取当前任务、店铺、商品和模板，判断执行器会填写哪些值；不会操作店小秘。</span>
            {!selectedTask && <small>先选择任务后才能运行配置检查并保存为任务覆盖。</small>}
          </div>
          <div className="config-precheck-action__buttons">
            {!selectedTask && (
              <button className="button button--primary" type="button" onClick={onShowTasks}>
                去选择商品
              </button>
            )}
            <button
              className="button button--secondary"
              type="button"
              onClick={() => { void runConfigPrecheck() }}
              disabled={configPreviewLoading || !selectedTask}
              title={!selectedTask ? '先选择任务后才能运行配置检查。' : undefined}
            >
              {configPreviewLoading ? '正在运行...' : configPreview ? '刷新配置检查' : '检查本次配置'}
            </button>
          </div>
        </div>
        <details className="inline-disclosure config-assist-drawer">
          <summary>
            配置详情与下一步字段
            <span>{configPreview?.ok ? '配置就绪，按需展开复核' : `下一步必填字段：${nextConfigSection.title}`}</span>
          </summary>
          {(!hasStores || !hasProducts) && (
            <EmptyState
              title="暂无真实店铺/商品配置"
              detail="当前未从接口读取到 stores/products，不展示 Dang Kang 或立牌类谷子默认值以免误判为已配置。"
            />
          )}
          <NextRequiredConfigFields
            section={nextConfigSection}
            preview={nextConfigPreview}
            configOk={Boolean(configPreview?.ok)}
            loading={configPreviewLoading}
            onEditRequiredSection={() => setActiveConfigSectionCode(nextConfigSection.code)}
          />
          <div className="config-coverage-strip" aria-label="店小秘编辑页分区" data-field-coverage={configCoverageFieldIds.join('|')}>
            {configCoverageLabels.map((label) => <span key={label}>{label}</span>)}
          </div>
          <div className="config-usage-legend" aria-label="字段用途">
            {fieldUsageLegend.map((label) => <span key={label}>{label}</span>)}
          </div>
          <details className="inline-disclosure config-context-summary">
            <summary>查看店铺、商品、图片与执行模式</summary>
            <div className="config-matrix">
              <ConfigItem label="店铺" value={workspace.stores[0]?.name ?? '未配置真实店铺'} hint={workspace.stores[0]?.platform ?? '等待 /api/stores 返回'} empty={!hasStores} />
              <ConfigItem label="类目" value={product?.category_name ?? '未绑定真实商品类目'} hint="用于匹配属性和模板范围" empty={!hasProducts} />
              <ConfigItem label="图片银行" value={product?.image?.eu_outer_package_filename ?? '未绑定真实外包装图'} hint="欧盟外包装/标签实拍图" empty={!hasProducts} />
              <ConfigItem label="执行模式" value="真实单商品只保存" hint="受控真实浏览器执行，只保存不发布" />
            </div>
            <ConfigReadinessPanel
              configPreview={configPreview}
              configPreviewError={configPreviewError}
              selectedTask={selectedTask}
              incompleteGroups={incompleteGroups}
            />
          </details>
        </details>
      </div>

      <div className="module-card span-3">
        <ModuleHead title="填写编辑页" meta="告诉 Agent 到店小秘编辑页怎么填，当前只展开一个分区" />
        <div className="config-template-console config-template-console--compact" aria-label="配置模板控制台">
          <div className="config-template-console__production-status" aria-label="配置中心生产状态">
            <span><b>当前使用模板</b><strong>{currentTemplateDisplayLabel}</strong></span>
            <span><b>保存状态</b><strong>{activeSectionStatusTitle}</strong></span>
            <span title={activeSectionDirty ? '执行取值：未保存的修改不会进入执行，请先保存为本次任务或店铺模板。' : '执行取值：执行会使用这些值，来自已保存配置。'}><b>执行取值</b><strong>{executionValueStatusLabel}</strong></span>
          </div>
          <div className={`config-save-state config-save-state--compact is-${activeSectionStatus}`} aria-label="当前分区保存状态">
            <b>{activeSectionStatusTitle}</b>
            <span>{activeSectionStatusMessage}</span>
          </div>
          <details className="inline-disclosure config-template-console__template-drawer">
            <summary>模板选择与示例/测试工具：当前分区模板 / 套用到表单 / 默认测试模板</summary>
          <div className="config-template-console__main">
            <label>
              <span>当前分区模板</span>
              <select
                value={activeSelectedTemplateId}
                onChange={(event) => handleTemplateSelection(selectedConfigSection.section, event.target.value)}
                data-config-template-selector={selectedConfigSection.section.code}
              >
                <option value="" disabled>请选择要套用的模板</option>
                {activeSectionTemplateOptions.map((template) => (
                  <option key={template.id} value={template.id}>
                    {templateOptionLabel(template)}
                  </option>
                ))}
              </select>
              <small>选择模板不会改表单，点击套用后才会填入当前分区。</small>
              <small>精确店铺/类目模板优先；全局模板只作为读取候选，不会被保存覆盖。</small>
            </label>
            <button
              className="button button--quiet"
              type="button"
              onClick={() => applyTemplateToDraft(selectedConfigSection.section, activeSelectedTemplateId)}
              disabled={!activeSelectedTemplateId}
            >
              套用到表单
            </button>
          </div>
          <div className="config-template-console__primary-actions" aria-label="默认测试模板">
            <div className="config-template-console__default-status">
              <b>默认测试模板</b>
              <strong>示例/测试模板</strong>
              <span>{defaultTemplatePackState}</span>
            </div>
            <div className="config-template-console__default-actions is-secondary">
              <button
                className="button button--quiet"
                type="button"
                onClick={() => applyTemplateToDraft(selectedConfigSection.section, '__default_test__')}
              >
                套用默认测试模板
              </button>
              <button
                className="button button--secondary"
                type="button"
                onClick={() => { void applyDefaultTemplatePack() }}
                disabled={savingSection === 'template:default-pack' || templateSaveDisabled}
                title={templateSaveDisabled ? '先选择任务，避免误存为全店/全类目模板。' : '保存为店铺模板会影响后续匹配当前店铺/类目的任务。'}
              >
                {savingSection === 'template:default-pack' ? '保存默认测试模板中...' : '保存默认测试模板'}
              </button>
            </div>
            <small>默认测试模板只用于快速试填示例字段，不代表已配置完成；真实执行前必须核对当前商品字段，再保存为本次任务或店铺模板。</small>
          </div>
          </details>
          <details className="inline-disclosure config-template-console__details">
            <summary>模板匹配详情</summary>
            <div className="config-template-console__status-bar" aria-label="模板使用状态">
              <strong>模板使用状态</strong>
              <span><b>当前使用</b><small>{activeTemplateUsageLabel}</small></span>
              <span><b>待套用</b><small>{activePendingTemplateActionLabel}</small></span>
              <span><b>最近保存</b><small>{activeLastSavedTemplateLabel}</small></span>
              <span><b>保存状态</b><small>{activeSectionStatusTitle}</small></span>
              <span><b>保存范围</b><small>{currentTemplateScopeLabel}</small></span>
            </div>
            <p className="config-template-console__explain">默认测试模板会单独保存到当前店铺/类目范围，不会覆盖已有正式店铺模板；它是示例/测试模板，不代表已配置完成。只有“当前使用”才代表本次执行会读取的模板。点击套用后才会写入表单，保存后才会影响执行。刚保存的模板会自动选中，后续可从下拉框再次套用。</p>
            <div className="config-template-console__detail-grid">
              <div className="config-template-source config-template-source--detail" aria-label="当前模板来源详情">
                <strong>当前生效模板</strong>
                <span>{activeTemplateSourceName || (activeSectionAlreadyPersisted ? '已由配置检查命中模板' : '尚未命中已保存模板')}</span>
                <small>可选模板 {activeSectionTemplateOptions.length} 套；已筛除不匹配或禁用模板 {filteredTemplateChoiceCount} 套。</small>
                <small>选择模板不会改表单，点击套用后才会填入当前分区，保存后才会生效。</small>
              </div>
              <div className="template-match-explanation-shell" aria-label="模板命中解释">
                <TemplateMatchExplanation {...templateMatchExplanation} />
              </div>
              <div className={`config-save-state is-${activeSectionStatus}`} aria-label="当前分区保存详情">
                <b>保存状态</b>
                <strong>{activeSectionStatusTitle}</strong>
                <span>{activeSectionStatusMessage}</span>
                {activeSectionSaveState?.savedAt && <small>保存时间：{activeSectionSaveState.savedAt} / 保存位置：{activeSectionSaveState.scope}</small>}
              </div>
            </div>
          </details>
        </div>
        {configMessage && <div className="config-save-message">{configMessage}</div>}
        {configReadyForReview && (
          <div className="config-ready-review" aria-label="配置已就绪摘要">
            <div>
              <strong>配置已就绪，默认无需继续填写</strong>
              <span>执行器会按当前检查取值填写店小秘编辑页；需要改本次任务时，再展开下方“微调当前配置”。</span>
            </div>
            <div className="config-ready-review__facts">
              <span><b>配置检查</b><strong>通过</strong></span>
              <span><b>可编辑分区</b><strong>{editableConfigSections.length} 个</strong></span>
              <span><b>当前范围</b><strong>{currentTemplateScopeLabel}</strong></span>
            </div>
          </div>
        )}
        <details className="inline-disclosure config-edit-drawer" open={!configReadyForReview}>
          <summary>{configReadyForReview ? '微调当前配置' : `继续填写：${selectedConfigSection.section.title}`}</summary>
          <div className="editable-config-grid editable-config-grid--focused">
            <EditableConfigSectionCard
              key={selectedConfigSection.section.code}
              section={selectedConfigSection.section}
              preview={selectedConfigSection.preview}
              configDraft={configDraft}
              savingSection={savingSection}
              saveState={sectionSaveState[selectedConfigSection.section.code]}
              selectedTask={selectedTask}
              templateSaveDisabled={templateSaveDisabled}
              configOk={Boolean(configPreview?.ok)}
              openByDefault={true}
              onFieldChange={updateConfigField}
              onSave={saveConfigSection}
              onSaveAndContinue={continueToNextMissingSection}
              onApplyDefaultTemplate={applyTemplateToDraft}
            />
          </div>
          <div className="config-section-tabs config-section-tabs--primary" role="tablist" aria-label="DXM 编辑页常用分区导航">
            {primaryConfigSections.map(({ section, preview }) => {
              const state = configSectionState(preview, Boolean(configPreview?.ok))
              const active = section.code === selectedConfigSection.section.code
              return (
                <button
                  key={section.code}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`${active ? 'is-active' : ''} ${state.className}`}
                  onClick={() => setActiveConfigSectionCode(section.code)}
                >
                  <strong>{section.title}</strong>
                  <span>{state.label}</span>
                </button>
              )
            })}
          </div>
          {secondaryConfigSections.length > 0 && (
            <details className="inline-disclosure config-section-more-drawer">
              <summary>更多编辑页分区（{secondaryConfigSections.length}）</summary>
              <div className="config-section-tabs config-section-tabs--secondary" role="tablist" aria-label="DXM 编辑页更多分区导航">
                {secondaryConfigSections.map(({ section, preview }) => {
                  const state = configSectionState(preview, Boolean(configPreview?.ok))
                  const active = section.code === selectedConfigSection.section.code
                  return (
                    <button
                      key={section.code}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      className={`${active ? 'is-active' : ''} ${state.className}`}
                      onClick={() => setActiveConfigSectionCode(section.code)}
                    >
                      <strong>{section.title}</strong>
                      <span>{state.label}</span>
                    </button>
                  )
                })}
              </div>
            </details>
          )}
          <div className="selected-config-section-note">
            <strong>正在编辑分区：{selectedConfigSection.section.title}</strong>
            <span>{previewSummary(selectedConfigSection.section, selectedConfigSection.preview, Boolean(configPreview?.ok))}</span>
            <div className="config-save-proof" aria-label="配置保存闭环">
              <strong>保存闭环</strong>
              <span>
                {selectedTask
                  ? activeTaskOverrideFieldCount > 0
                    ? `本次任务已保存 ${activeTaskOverrideFieldCount} 个字段；检查结果中 ${activePreviewOverrideFieldCount} 个字段正在按任务覆盖取值，执行器启动时读取同一份检查取值。`
                    : '尚未保存本次任务覆盖；当前分区会先按商品和店铺模板取值，保存后这里会显示任务覆盖字段数。'
                  : '选择任务后，可保存为本次任务覆盖并在这里核对执行取值。'}
              </span>
            </div>
          </div>
          <SectionExecutionValuePreview section={selectedConfigSection.section} preview={selectedConfigSection.preview} />
          <p className="config-section-switch-hint">只展示当前分区；常用分区在上方，低频字段收进“更多编辑页分区”。</p>
        </details>
      </div>

      <EffectiveValuePreview configPreview={configPreview} sourcePriorityLabels={sourcePriorityLabels} title={effectivePreviewTitle} />

      <details className="module-card span-3 disclosure-card">
        <summary>高级模板映射（{Object.keys(templateResults).length} 段已有执行结果）</summary>
        <ReferenceTemplateMap sections={workspace.dxmReferenceTemplates} />
      </details>

      <details className="module-card span-3 disclosure-card">
        <summary>模板清单（{workspace.templates.length} 条）</summary>
        <div className="table-wrap">
          <table>
            <caption>配置模板清单</caption>
            <thead>
              <tr>
                <th scope="col">类型</th>
                <th scope="col">模板名</th>
                <th scope="col">绑定范围</th>
                <th scope="col">状态</th>
              </tr>
            </thead>
            <tbody>
              {workspace.templates.map((template) => (
                <TemplateRow key={template.id} template={template} />
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}

function SectionExecutionValuePreview({
  section,
  preview,
}: {
  section: EditableConfigSection
  preview: ConfigPreviewGroup | undefined
}) {
  const fields = section.fields
    .map((field) => fieldPreview(preview, field))
    .filter((field): field is ConfigPreviewGroup['fields'][number] => Boolean(field))
    .slice(0, 10)

  return (
    <div className="section-execution-preview" aria-label="当前分区执行取值核对">
      <div className="section-execution-preview__head">
        <strong>当前分区执行取值核对</strong>
        <span>执行时按这些值填写店小秘编辑页</span>
      </div>
      {fields.length ? (
        <div className="section-execution-preview__grid">
          {fields.map((field) => (
            <div key={field.path} className={field.missing ? 'section-execution-preview__item is-missing' : 'section-execution-preview__item'}>
              <span>{field.label}</span>
              <code>{formatPreviewValue(field.value)}</code>
              <small>{sourceBadgeText(field.source)}</small>
              <details className="section-execution-preview__technical">
                <summary>字段来源详情</summary>
                <small>{field.path}</small>
              </details>
            </div>
          ))}
        </div>
      ) : (
        <span className="section-execution-preview__empty">等待配置检查返回当前分区字段。</span>
      )}
    </div>
  )
}

function EditableConfigSectionCard({
  section,
  preview,
  configDraft,
  savingSection,
  saveState,
  selectedTask,
  templateSaveDisabled,
  configOk,
  openByDefault,
  onFieldChange,
  onSave,
  onSaveAndContinue,
  onApplyDefaultTemplate,
}: {
  section: EditableConfigSection
  preview: ConfigPreviewGroup | undefined
  configDraft: Record<ConfigSectionCode, Record<string, string>>
  savingSection: string | null
  saveState?: ConfigSectionSaveState
  selectedTask: Task | null
  templateSaveDisabled: boolean
  configOk: boolean
  openByDefault: boolean
  onFieldChange: (sectionCode: ConfigSectionCode, fieldName: string, value: string) => void
  onSave: (section: EditableConfigSection, scope: 'template' | 'task') => void | Promise<void>
  onSaveAndContinue: (section: EditableConfigSection, scope: 'template' | 'task') => void
  onApplyDefaultTemplate: (section: EditableConfigSection, templateId: string) => void
}) {
  const state = configSectionState(preview, configOk)
  const pillClass = state.className === 'is-complete' ? 'ok' : state.className === 'is-advisory' ? 'info' : 'warn'
  const taskSaveDisabled = !selectedTask || savingSection === `task:${section.code}`
  const templateDisabledReason = templateSaveDisabled
    ? '先选择任务，避免误存为全店/全类目模板。'
    : savingSection === `template:${section.code}`
      ? '正在保存，请等待当前操作完成。'
      : '保存为店铺模板会影响后续匹配当前店铺/类目的任务。'
  const continueDisabled = taskSaveDisabled || !preview
  const receiptStatus = saveState?.status ?? 'clean'
  const receiptTitle = receiptStatus === 'dirty'
    ? '有未保存的修改'
    : receiptStatus === 'saving'
      ? '正在保存'
      : receiptStatus === 'saved'
        ? '最近一次保存成功'
        : receiptStatus === 'failed'
          ? '最近一次保存失败'
          : '等待保存'
  const receiptMessage = saveState?.message ?? '保存后这里会显示最近一次保存结果。'
  const disabledReason = !selectedTask
    ? '先选择任务，才能保存为本次任务并继续。'
    : !preview
      ? '先运行本次任务配置检查，系统才能知道下一缺失分区。'
      : savingSection === `task:${section.code}`
        ? '正在保存，请等待当前操作完成。'
        : ''
  const visibleConfigFields = section.fields.filter((field) => {
    const previewField = fieldPreview(preview, field)
    return Boolean(
      previewField?.missing
      || previewField?.required
      || field.usage === 'direct'
      || field.usage === 'template',
    )
  })
  const primaryConfigFields = visibleConfigFields.length ? visibleConfigFields : section.fields.slice(0, Math.min(4, section.fields.length))
  const primaryConfigFieldNames = new Set(primaryConfigFields.map((field) => field.name))
  const secondaryConfigFields = section.fields.filter((field) => !primaryConfigFieldNames.has(field.name))
  function renderConfigField(field: EditableConfigField) {
    const previewField = fieldPreview(preview, field)
    return (
      <label key={field.name}>
        <span>
          {field.label}{previewField?.required ? ' *' : ''}
          {field.usage && <em className={`field-usage field-usage--${field.usage}`}>{fieldUsageLabel(field.usage)}</em>}
        </span>
        {field.valueKind === 'list' ? (
          <textarea
            value={configDraft[section.code]?.[field.name] ?? ''}
            placeholder={field.placeholder}
            rows={3}
            onChange={(event) => onFieldChange(section.code, field.name, event.target.value)}
          />
        ) : (
          <input
            value={configDraft[section.code]?.[field.name] ?? ''}
            placeholder={field.placeholder}
            onChange={(event) => onFieldChange(section.code, field.name, event.target.value)}
          />
        )}
        {field.valueKind === 'list' && <small className="field-source">每行一个；会按顺序匹配店小秘模板。</small>}
        <small className={previewField?.missing ? 'field-source is-missing' : 'field-source'}>
          {fieldSourceText(previewField)}
        </small>
      </label>
    )
  }
  return (
    <details className={`editable-config-section ${state.className}`} open={openByDefault}>
      <summary className="editable-config-section__head">
        <div>
          <strong>{section.title}</strong>
          <span>{previewSummary(section, preview, configOk)}</span>
        </div>
        <span className={`status-pill ${pillClass}`}>{state.label}</span>
      </summary>
      <div className="editable-config-section__field-group-head">
        <strong>当前重点字段</strong>
        <span>{preview?.complete ? '配置已完整；仅展示执行会直接用到的字段。' : '优先处理缺失、必填和执行取值字段。'}</span>
      </div>
      <div className="editable-config-section__fields editable-config-section__fields--primary">
        {primaryConfigFields.map(renderConfigField)}
      </div>
      {secondaryConfigFields.length > 0 && (
        <details className="inline-disclosure editable-config-section__more-fields">
          <summary>更多字段与辅助配置</summary>
          <div className="editable-config-section__fields">
            {secondaryConfigFields.map(renderConfigField)}
          </div>
        </details>
      )}
      {preview?.missing.length ? (
        <div className="missing-strip">
          {preview.missing.slice(0, 4).map((item) => <span key={item}>{item}</span>)}
        </div>
      ) : null}
      <div className="config-save-scope-explainer" aria-label="保存方式说明">
        <span>
          <strong>保存到本次任务</strong>
          <small>只影响当前任务；执行器会优先读取这份任务覆盖。</small>
        </span>
        <span>
          <strong>保存为店铺模板</strong>
          <small>影响后续匹配当前店铺/类目的任务，不覆盖全局模板。</small>
        </span>
      </div>
      <div className="editable-config-section__actions">
        {!configOk && (
          <button
            className="button button--primary"
            type="button"
            onClick={() => onSaveAndContinue(section, 'task')}
            disabled={continueDisabled}
            title={disabledReason || undefined}
          >
            {savingSection === `task:${section.code}` ? '保存中...' : '仅本次任务使用并继续'}
          </button>
        )}
        <button
          className="button button--secondary"
          type="button"
          onClick={() => void onSave(section, 'task')}
          disabled={taskSaveDisabled}
          title={!selectedTask ? '先选择任务，才能保存为本次任务。' : undefined}
        >
          {savingSection === `task:${section.code}` ? '保存中...' : '仅本次任务使用'}
        </button>
        <button
          className="button button--quiet"
          type="button"
          onClick={() => void onSave(section, 'template')}
          disabled={templateSaveDisabled || savingSection === `template:${section.code}`}
          title={templateDisabledReason}
        >
          {savingSection === `template:${section.code}` ? '保存中...' : '保存为店铺模板（后续任务可用）'}
        </button>
        <button
          className="button button--quiet"
          type="button"
          onClick={() => onApplyDefaultTemplate(section, '__default_test__')}
          title="默认测试模板是示例/测试模板，不代表已配置完成。"
        >
          套用默认测试模板
        </button>
      </div>
      <div className={`config-section-save-receipt is-${receiptStatus}`} aria-label="当前分区保存回执">
        <strong>{receiptTitle}</strong>
        <span>{receiptMessage}</span>
        {(saveState?.scope || saveState?.savedAt) && (
          <small>
            {saveState.scope ? `保存位置：${saveState.scope}` : '保存位置：待确认'}
            {saveState.savedAt ? ` / 保存时间：${saveState.savedAt}` : ''}
          </small>
        )}
      </div>
      <small className="config-section-save-hint">本次任务只影响当前批次；店铺模板会影响后续匹配当前店铺/类目的任务。</small>
      {disabledReason && <small className="config-action-disabled-reason" aria-label="不能继续的原因">不能继续的原因：{disabledReason}</small>}
    </details>
  )
}

export function TaskCenterView({ workspace, selectedTask, configPreview, configPreviewError, configPreviewLoading, runtimeStatus, runtimeStatusError, busy, demoEnabled, l3ApprovedBy, onL3ApprovedByChange, onSelectTask, onCreateRealTask, onBootstrapDemo, onStartTask, onRunL2Probe, onShowConfig, onShowConsole, onShowEvidence, onShowReports }: TaskCenterProps) {
  const uniqueStoreOptions = useMemo(() => uniqueByStoreIdentity(workspace.stores), [workspace.stores])
  const uniqueProductOptions = useMemo(() => uniqueByProductIdentity(workspace.products), [workspace.products])
  const [draftStoreId, setDraftStoreId] = useState(() => uniqueStoreOptions[0]?.id ? String(uniqueStoreOptions[0].id) : '')
  const [draftMode, setDraftMode] = useState<RealTaskCreateRequest['mode']>('single_save')
  const [draftProductIds, setDraftProductIds] = useState<number[]>([])
  const [showAllTasks, setShowAllTasks] = useState(false)
  const needsApproval = selectedTask ? requiresManualApproval(selectedTask) : false
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)
  const needsRealL2 = selectedTask ? requiresRealL2(selectedTask) : false
  const selectedTaskIsDryRun = selectedTask?.mode === 'dry_run'
  const selectedRealDxmMutationTask = Boolean(selectedTask && isRealDxmMutationTask(selectedTask))
  const selectedTaskNeedsEditConfig = selectedTask?.mode === 'single_save'
  const dxmLoggedIn = !runtimeStatusError && DXM_LOGGED_IN_STATUSES.has(runtimeStatus?.dxmLogin?.status ?? '')
  const selectedTaskIsUnreleasedRealMode = selectedTask ? isUnreleasedRealDxmMutationTask(selectedTask) : false
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const selectedTaskNotDraft = Boolean(selectedTask && selectedTask.status !== 'draft')
  const l2BlocksStart = needsRealL2 && l2Gate?.status !== 'passed'
  const l3BlocksStart = selectedTaskNeedsEditConfig && needsRealL2 && l3Gate?.status === 'blocked'
  const loginBlocksStart = selectedRealDxmMutationTask && !dxmLoggedIn
  const configPreviewForSelectedTask = selectedTask && configPreview?.taskId === selectedTask.id ? configPreview : null
  const configPreviewTaskMismatch = Boolean(selectedTask && configPreview && configPreview.taskId !== selectedTask.id)
  const configPreviewLoadingBlocksStart = Boolean(selectedTaskNeedsEditConfig && configPreviewLoading)
  const configUnknownBlocksStart = Boolean(selectedTaskNeedsEditConfig && !configPreviewForSelectedTask && !configPreviewLoading)
  const configBlocksStart = Boolean(selectedTaskNeedsEditConfig && configPreviewForSelectedTask && !configPreviewForSelectedTask.ok)
  const l2DiagnosticSummaries = summarizeL2Diagnostics(l2Gate)
  const selectedStore = uniqueStoreOptions.find((store) => String(store.id) === draftStoreId)
  const draftProductIdSet = new Set(draftProductIds)
  const selectedDraftProducts = uniqueProductOptions.filter((product) => draftProductIdSet.has(product.id))
  const primaryProductCandidates = uniqueProductOptions.slice(0, 4)
  const selectedStoreReleasedForSingleSave = Boolean(selectedStore && RELEASED_SINGLE_SAVE_STORE_NAMES.has(selectedStore.name))
  const storeBlocksSingleSave = Boolean(selectedStore && draftMode !== 'probe' && !selectedStoreReleasedForSingleSave)
  const singleSaveProductCountInvalid = draftMode === 'single_save' && selectedDraftProducts.length !== 1
  const canCreateSingleSaveTask = Boolean(selectedStore && selectedDraftProducts.length === 1 && !busy && !storeBlocksSingleSave)
  const quickCreateSingleSaveDisabledReason = busy
    ? '正在处理当前操作，请稍候。'
    : !selectedStore
      ? '请选择真实店铺。'
      : selectedDraftProducts.length === 0
        ? '请先选择 1 个商品后再创建单商品只保存任务。'
        : selectedDraftProducts.length !== 1
        ? `单商品只保存一次只能选 1 个商品；当前已选 ${selectedDraftProducts.length} 个。`
        : storeBlocksSingleSave
          ? '当前版本仅放行 Dang Kang；其它店铺需联系管理员完成店铺放行配置。'
          : ''
  const unreleasedReleaseItems = workspace.realModeReleasePlan.modes.filter((item) => item.mode === 'claim_only' || item.mode === 'batch_save')
  const latestSingleSaveTask = [...workspace.tasks]
    .filter(isStartableSingleSaveTask)
    .sort((a, b) => b.id - a.id)[0] ?? null
  const compactTaskRows = useMemo(() => {
    const seen = new Set<string>()
    const rows: Task[] = []
    for (const task of workspace.tasks) {
      const key = getTaskDisplayKey(task)
      if (seen.has(key)) continue
      seen.add(key)
      rows.push(task)
    }
    return rows
  }, [workspace.tasks])
  const defaultTaskRows = compactTaskRows.filter((task) => !isAuxiliaryTask(task))
  const compactVisibleTaskRows = defaultTaskRows.slice(0, 6)
  const visibleTaskRows = showAllTasks
    ? workspace.tasks
    : selectedTask && isAuxiliaryTask(selectedTask)
      ? [selectedTask, ...compactVisibleTaskRows].slice(0, 12)
    : selectedTask && !compactVisibleTaskRows.some((task) => task.id === selectedTask.id)
      ? [selectedTask, ...compactVisibleTaskRows.filter((task) => task.id !== selectedTask.id)].slice(0, 12)
      : compactVisibleTaskRows
  const collapsedTaskCount = Math.max(workspace.tasks.length - compactTaskRows.length, 0)
  const hiddenTaskCount = Math.max(workspace.tasks.length - visibleTaskRows.length, 0)
  const canToggleTaskHistory = workspace.tasks.length > visibleTaskRows.length || showAllTasks
  const canCreateRealTask = Boolean(selectedStore && selectedDraftProducts.length > 0 && !busy && !storeBlocksSingleSave && !singleSaveProductCountInvalid)
  const needsSingleSaveRecovery = Boolean(selectedTask && !selectedTaskNotDraft && (selectedTaskIsUnreleasedRealMode || loginBlocksStart || configUnknownBlocksStart || configPreviewLoadingBlocksStart || configBlocksStart || l2BlocksStart || l3BlocksStart))
  const startDisabled = busy || !selectedTask || selectedTaskNotDraft || selectedTaskIsUnreleasedRealMode || loginBlocksStart || configUnknownBlocksStart || configPreviewLoadingBlocksStart || configBlocksStart || l2BlocksStart || l3BlocksStart
  const startLabel = !selectedTask
    ? '请选择任务'
    : selectedTask.status === 'completed'
      ? '任务已完成，查看保存结果'
      : selectedTask.status === 'running'
        ? '任务运行中'
        : selectedTask.status === 'failed'
          ? '重新创建单商品只保存任务'
        : selectedTask.status !== 'draft'
          ? '任务非草稿，禁止启动'
          : selectedTaskIsUnreleasedRealMode
            ? '未发布，禁止启动'
            : runtimeStatusError && loginBlocksStart
              ? '运行状态不可用，先查看日志'
            : loginBlocksStart
              ? 'DXM 未登录，先打开真实浏览器登录'
              : configPreviewTaskMismatch
                ? '配置属于其它任务，重新检查本次任务'
              : configPreviewError && configUnknownBlocksStart
                ? '配置检查接口不可用'
              : configUnknownBlocksStart
                ? '先检查本次任务配置'
                : configPreviewLoadingBlocksStart
                  ? '正在检查配置，稍候启动'
                  : configBlocksStart
                    ? '配置未完成，禁止启动'
                    : l2BlocksStart
                      ? l2StartLabel(l2Gate?.status)
                      : l3BlocksStart
                        ? '人工确认未完成，禁止启动'
                        : selectedTask?.mode === 'claim_only'
                          ? '启动采集认领'
                        : needsApproval
                          ? '批准并启动单商品只保存'
                          : needsRealL2
                            ? '启动保存核验任务'
                            : '启动开发自检任务'
  const historyTaskHint = canToggleTaskHistory
    ? showAllTasks
      ? '历史任务已展开。'
      : `还有 ${hiddenTaskCount} 个历史任务可展开。`
    : workspace.tasks.length
      ? '当前已显示可用任务。'
      : '暂无历史任务；先创建单商品只保存任务。'
  const blockedStartButtonLabel = startDisabled
    ? startLabel.includes('禁止启动')
      ? startLabel
      : `暂不能启动只保存：${startLabel}`
    : '可开始只保存'
  const taskActionDiagnosis = {
    create: quickCreateSingleSaveDisabledReason || '可创建单商品只保存任务',
    history: historyTaskHint,
    start: blockedStartButtonLabel,
  }

  useEffect(() => {
    const firstStore = uniqueStoreOptions[0]
    if (!firstStore) {
      if (draftStoreId) setDraftStoreId('')
      return
    }
    if (!draftStoreId || !uniqueStoreOptions.some((store) => String(store.id) === draftStoreId)) {
      setDraftStoreId(String(firstStore.id))
    }
  }, [draftStoreId, uniqueStoreOptions])

  useEffect(() => {
    const availableIds = new Set(uniqueProductOptions.map((product) => product.id))
    setDraftProductIds((current) => {
      const kept = current.filter((id) => availableIds.has(id))
      if (kept.length) return kept.length === current.length ? current : kept
      return []
    })
  }, [uniqueProductOptions])

  function selectSingleDraftProduct(productId: number) {
    setDraftProductIds([productId])
    setDraftMode('single_save')
  }

  function submitRealTask() {
    if (!canCreateRealTask || !selectedStore) return
    void onCreateRealTask({
      storeId: selectedStore.id,
      mode: draftMode,
      productIds: selectedDraftProducts.map((product) => product.id),
    })
  }

  function submitSingleSaveTask() {
    if (!canCreateSingleSaveTask || !selectedStore) return
    setDraftMode('single_save')
    void onCreateRealTask({
      storeId: selectedStore.id,
      mode: 'single_save',
      productIds: selectedDraftProducts.map((product) => product.id),
    })
  }

  return (
    <section className="module-layout" aria-label="选择商品">
      <div className="module-card span-1 task-quick-actions" aria-label="选择商品主操作">
        <ModuleHead title="选择商品" meta="首屏只处理任务选择" />
        <div className="task-product-selection" aria-label="选择商品">
          <div className="task-product-selection__head">
            <span>选择商品</span>
            <strong>{selectedDraftProducts[0]?.title ?? '请先选择 1 个商品'}</strong>
            <small>当前交付只允许单商品只保存；点击候选会替换本次选择，不会启动批量、发布或无人值守。</small>
          </div>
          <label className="task-product-selection__store">
            <span>店铺</span>
            <select value={draftStoreId} onChange={(event) => setDraftStoreId(event.target.value)} disabled={busy || uniqueStoreOptions.length === 0}>
              {uniqueStoreOptions.map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name} / {store.platform}{RELEASED_SINGLE_SAVE_STORE_NAMES.has(store.name) ? '' : '（未放行单商品只保存）'}
                </option>
              ))}
              {!uniqueStoreOptions.length && <option value="">等待真实店铺</option>}
            </select>
          </label>
          <div className="task-product-selection__list">
            {primaryProductCandidates.map((product) => (
              <button
                key={product.id}
                className={`task-product-choice ${selectedDraftProducts[0]?.id === product.id ? 'is-selected' : ''}`}
                type="button"
                onClick={() => selectSingleDraftProduct(product.id)}
                disabled={busy}
                aria-pressed={selectedDraftProducts[0]?.id === product.id}
              >
                <strong>{product.title}</strong>
                <span>{selectedStore?.name ?? '待选店铺'} / {product.category_name || '未指定类目'}</span>
                <small>SKU {product.sku_count}，图片 {product.image_count}，来源状态 {product.status}</small>
              </button>
            ))}
            {!uniqueProductOptions.length && <EmptyState title="暂无商品" detail="请先导入真实商品；普通模式不使用本地演示商品。" />}
          </div>
          {uniqueProductOptions.length > primaryProductCandidates.length && (
            <small className="task-product-selection__more">
              还有 {uniqueProductOptions.length - primaryProductCandidates.length} 个商品在下方“查看更多商品”里；本次只选择 1 个商品创建任务。
            </small>
          )}
        </div>
        <div className="task-quick-actions__buttons task-quick-actions__buttons--single">
          <button
            className="button button--primary"
            type="button"
            onClick={submitSingleSaveTask}
            disabled={Boolean(quickCreateSingleSaveDisabledReason)}
            aria-describedby={quickCreateSingleSaveDisabledReason ? 'task-quick-create-single-save-reason' : undefined}
            title={quickCreateSingleSaveDisabledReason || undefined}
            data-testid="task-quick-create-single-save"
          >
            创建单商品只保存任务
          </button>
          {quickCreateSingleSaveDisabledReason && (
            <small id="task-quick-create-single-save-reason" className="task-quick-actions__reason">
              {quickCreateSingleSaveDisabledReason}
            </small>
          )}
        </div>
        <details className="task-quick-actions__diagnosis inline-disclosure" aria-label="任务按钮不可点击原因">
          <summary>为什么不能开始只保存</summary>
          <span>
            <strong>创建任务</strong>
            <small>{taskActionDiagnosis.create}</small>
          </span>
          <span>
            <strong>开始只保存</strong>
            <small>{taskActionDiagnosis.start}</small>
          </span>
        </details>
        <div className="task-quick-actions__status">
          <span>当前任务</span>
          <strong>{selectedTask ? displayTaskName(selectedTask) : '未选择任务'}</strong>
          <small>{selectedTask ? `${humanTaskModeLabel(selectedTask.mode)} / ${humanTaskStatus(selectedTask.status)}` : '先创建单商品只保存任务'}</small>
        </div>
        <p>
          {!quickCreateSingleSaveDisabledReason
            ? `将使用 ${selectedStore?.name ?? '当前店铺'} 和已选 ${selectedDraftProducts.length} 个商品创建草稿任务。`
            : quickCreateSingleSaveDisabledReason}
        </p>
      </div>

      <div className="module-card span-2">
        <ModuleHead title="当前任务" meta={showAllTasks ? `${workspace.tasks.length} 个批次` : `${visibleTaskRows.length} 个常用批次`} />
        <TaskCurrentActionPanel
          selectedTask={selectedTask}
          workspace={workspace}
          configPreview={configPreviewForSelectedTask}
          l2Gate={l2Gate}
          l3Gate={l3Gate}
          startLabel={startLabel}
          startDisabled={startDisabled}
          busy={busy}
          l2ProbeResourceState={l2ProbeResourceState}
          onStartTask={onStartTask}
          onRunL2Probe={onRunL2Probe}
          onShowConfig={onShowConfig}
          onShowConsole={onShowConsole}
          onShowEvidence={onShowEvidence}
          onShowReports={onShowReports}
        />
        {!selectedTaskCompleted && needsSingleSaveRecovery && (
          <SingleSaveRecoveryGuide
            selectedTask={selectedTask}
            latestSingleSaveTask={latestSingleSaveTask}
            selectedTaskIsUnreleasedRealMode={selectedTaskIsUnreleasedRealMode}
            configBlocksStart={configBlocksStart}
            l2BlocksStart={l2BlocksStart}
            l3BlocksStart={l3BlocksStart}
            canCreateRealTask={canCreateRealTask}
            busy={busy}
            l2ProbeResourceState={l2ProbeResourceState}
            onSelectSingleSave={() => latestSingleSaveTask && onSelectTask(latestSingleSaveTask.id)}
            onCreateSingleSave={submitSingleSaveTask}
            onRunL2Probe={onRunL2Probe}
            onShowConfig={onShowConfig}
            onShowReports={onShowReports}
          />
        )}
        {!selectedTaskCompleted && (configBlocksStart || configPreviewLoading || configPreviewError || configPreviewTaskMismatch) && (
          <div className={`gate-note ${configBlocksStart ? 'gate-note--danger' : ''}`}>
            <strong>{configPreviewError ? '配置检查接口不可用' : configPreviewTaskMismatch ? '配置属于其它任务' : configPreviewLoading ? '正在检查配置' : '配置检查未通过'}</strong>
            <span>{configPreviewError ? humanConfigError(configPreviewError) : configPreviewTaskMismatch ? '请重新检查本次任务配置，避免沿用上一任务的配置结果。' : configPreviewLoading ? '正在读取当前任务的 DXM 编辑页字段来源。' : `请先补齐：${configPreviewForSelectedTask?.missing.slice(0, 6).join('、') || '填写编辑页配置'}`}</span>
            {(configBlocksStart || configPreviewTaskMismatch) && (
              <div className="next-step-actions">
                <button className="button button--secondary" type="button" onClick={onShowConfig}>去填写编辑页</button>
              </div>
            )}
          </div>
        )}
        {!selectedTaskCompleted && l2BlocksStart && (
          <ReadonlyRecheckHelpCard
            l2Gate={l2Gate}
            l3BlocksStart={l3BlocksStart}
            summaries={l2DiagnosticSummaries}
            busy={busy}
            demoEnabled={demoEnabled}
            selectedTask={selectedTask}
            selectedTaskIsDryRun={selectedTaskIsDryRun}
            l2ProbeResourceState={l2ProbeResourceState}
            onRunL2Probe={onRunL2Probe}
            onShowConsole={onShowConsole}
            onShowEvidence={onShowEvidence}
            onShowReports={onShowReports}
          />
        )}
        {!selectedTaskCompleted && !l2BlocksStart && l3BlocksStart && (
          <div className="gate-note gate-note--danger">
            <strong>真实保存已阻断</strong>
            <span>{humanGateDetail(l2Gate?.detail) ?? '需要商品采集页与草稿箱页两个真实只读检查均通过。'}</span>
            <span>真实只读检查通过后才启动采集认领；人工确认未完成前不启动单商品只保存；批量保存当前未开放。</span>
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onShowConsole}>查看阻断说明</button>
              <button className="button button--secondary" type="button" onClick={onShowReports} data-section="reports">查看评审与检查计划</button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
            </div>
          </div>
        )}
        {!selectedTaskCompleted && l2BlocksStart && l2DiagnosticSummaries.length > 0 && (
          <details className="inline-disclosure l2-block-summary">
            <summary>真实只读检查诊断摘要</summary>
            {l2DiagnosticSummaries.slice(0, 2).map((item) => (
              <span key={item.target}>{item.targetLabel}：{humanDiagnosticNavigation(item.navigation)}，{item.failedChecks.slice(0, 2).map(humanFailedCheckLabel).join(' / ') || '页面检查未满足'}。下一步：{item.nextAction}</span>
            ))}
          </details>
        )}
        {!selectedTaskCompleted && needsApproval && !selectedTaskNotDraft && (
          <div className="gate-note">
            <span>采集认领可直接启动第一段流程；单商品只保存会先请求后端批准令牌；批量保存当前未开放。</span>
            <L3ApprovalInlineForm
              approvedBy={l3ApprovedBy}
              busy={busy || startDisabled}
              onApprovedByChange={onL3ApprovedByChange}
              onSubmit={onStartTask}
              disabledReason={startDisabled ? startLabel : ''}
            />
          </div>
        )}
      </div>

      <details className="module-card span-2 task-support-drawer disclosure-card">
        <summary>
          更多任务操作与记录
          <span>历史任务、更多商品和高级诊断继续折叠，不抢占首屏</span>
        </summary>
        <div className="task-support-drawer__content">
          <details className="inline-disclosure task-create-drawer">
            <summary>创建真实任务</summary>
            <div className="real-task-card" aria-label="创建真实任务" data-publish-scene="SMT_SEMI_MANAGED_SAVE_ONLY">
              <div className="real-task-card__head">
                <div>
                  <strong>选择店铺、商品和执行范围</strong>
                  <span>保存路径固定为只保存不发布；批量/无人值守仍需单独验收。</span>
                </div>
                <span className="guard-chip">发布动作未开放</span>
              </div>
              <div className="real-task-form">
                <label>
                  <span>店铺</span>
                  <select value={draftStoreId} onChange={(event) => setDraftStoreId(event.target.value)} disabled={busy || uniqueStoreOptions.length === 0}>
                    {uniqueStoreOptions.map((store) => (
                      <option key={store.id} value={store.id}>
                        {store.name} / {store.platform}{RELEASED_SINGLE_SAVE_STORE_NAMES.has(store.name) ? '' : '（未放行单商品只保存）'}
                      </option>
                    ))}
                    {!uniqueStoreOptions.length && <option value="">等待真实店铺</option>}
                  </select>
                </label>
                <div className="real-task-mode" role="radiogroup" aria-label="执行模式">
                  <button className="is-selected" type="button" aria-pressed="true">
                    <strong>单商品只保存</strong>
                    <span>当前交付唯一可创建路径</span>
                  </button>
                  <button type="button" disabled aria-disabled="true">
                    <strong>批量保存未放行</strong>
                    <span>批量/无人值守需单独验收</span>
                  </button>
                </div>
              </div>
              {draftMode !== 'probe' && storeBlocksSingleSave && (
                <div className="guard-note guard-note--warn">
                  单商品只保存当前只放行 {Array.from(RELEASED_SINGLE_SAVE_STORE_NAMES).join('、')}；其它店铺需联系管理员完成店铺放行配置，真实只读检查只生成证据，不会自动解锁店铺。
                </div>
              )}
              {singleSaveProductCountInvalid && (
                <div className="guard-note guard-note--warn">
                  单商品只保存一次只能选择 1 个商品；当前已选 {selectedDraftProducts.length} 个。真实只读检查可多选，真实保存请保留 1 个商品。
                </div>
              )}
              <div className="real-task-products" aria-label="选择商品">
                {uniqueProductOptions.slice(0, 6).map((product) => (
                  <label key={product.id} className="real-task-product">
                    <input
                      type="radio"
                      name="single-save-product"
                      checked={selectedDraftProducts[0]?.id === product.id}
                      onChange={() => selectSingleDraftProduct(product.id)}
                      disabled={busy}
                    />
                    <span>{product.title}</span>
                    <small>{product.category_name || '未指定类目'} / SKU {product.sku_count}</small>
                  </label>
                ))}
                {uniqueProductOptions.length > 6 && <span className="toolbar-note">还有 {uniqueProductOptions.length - 6} 个商品保留在队列；当前版本每次只创建 1 个商品的只保存任务。</span>}
                {!uniqueProductOptions.length && <EmptyState title="暂无商品" detail="请先导入真实商品；普通模式不使用本地演示商品。" />}
              </div>
              <div className="task-start-strip">
                <button
                  className="button button--primary"
                  type="button"
                  onClick={submitRealTask}
                  disabled={!canCreateRealTask}
                  data-testid="real-task-create"
                >
                  创建真实任务
                </button>
                <span className="toolbar-note">{selectedDraftProducts.length ? `已选择 ${selectedDraftProducts.length} 个商品` : '先选择商品'}</span>
              </div>
            </div>
            {demoEnabled && (
              <div className="toolbar task-start-strip" aria-label="开发模式任务">
                <button className="button button--quiet" type="button" onClick={onBootstrapDemo} disabled={busy}>
                  创建开发自检批次
                </button>
                <span className="toolbar-note">开发模式，不触达 DXM</span>
              </div>
            )}
          </details>
          <details className="inline-disclosure task-history-drawer">
            <summary>选择其它任务 / 历史批次</summary>
            {workspace.tasks.length > 0 && (
              <div className="task-list-toolbar">
                <div className="task-list-summary">
                  <strong>任务列表</strong>
                  <span>
                    默认显示单商品只保存相关批次，辅助/历史批次默认隐藏{collapsedTaskCount > 0 ? `，已合并 ${collapsedTaskCount} 条重复批次` : ''}。
                  </span>
                </div>
                {canToggleTaskHistory && (
                  <button className="button button--quiet" type="button" onClick={() => setShowAllTasks((value) => !value)}>
                    {showAllTasks ? '收起历史任务' : `显示全部历史任务（${workspace.tasks.length}）`}
                  </button>
                )}
                {!showAllTasks && hiddenTaskCount > 0 && <small>已隐藏 {hiddenTaskCount} 条历史记录，不影响真实任务数据。</small>}
              </div>
            )}
            <div className="task-list">
              {visibleTaskRows.map((task) => (
                <button
                  key={task.id}
                  type="button"
                  className={`task-row ${selectedTask?.id === task.id ? 'is-selected' : ''}`}
                  onClick={() => onSelectTask(task.id)}
                  data-task-id={task.id}
                  data-task-mode={task.mode}
                >
                  <div>
                    <strong>{displayTaskName(task)}</strong>
                    <span>{task.payload.store_name ?? workspace.stores[0]?.name ?? '未绑定店铺'} / {task.payload.category_name ?? '未指定类目'}</span>
                  </div>
                  <div className="task-row__meta">
                    <span>{humanTaskStatus(task.status)}</span>
                    <small>{task.completed_jobs}/{Math.max(task.total_jobs, 1)} 完成</small>
                  </div>
                </button>
              ))}
              {!workspace.tasks.length && (
                <EmptyState title="暂无真实任务" detail={demoEnabled ? '开发模式可创建本地自检批次；普通使用请先导入商品并创建单商品只保存任务。' : '请先导入商品并创建单商品只保存任务，普通模式不展示本地自检入口。'} />
              )}
            </div>
          </details>
          <details className="inline-disclosure task-product-drawer">
            <summary>查看更多商品</summary>
            <div className="product-queue-card">
              <ModuleHead title="商品队列" meta={`${uniqueProductOptions.length} 个商品`} />
              <div className="product-list">
                {uniqueProductOptions.map((product) => (
                  <ProductCard key={product.id} product={product} />
                ))}
                {!uniqueProductOptions.length && (
                  <EmptyState title="暂无商品" detail="真实导入后这里展示待保存队列；开发自检数据仅开发模式可用。" />
                )}
              </div>
            </div>
          </details>
          <details className="inline-disclosure task-release-drawer">
            <summary>查看未发布模式边界</summary>
            <RealModeReleasePlanPanel items={unreleasedReleaseItems} />
          </details>
          <details className="inline-disclosure task-acceptance-drawer">
            <summary>查看任务验收口径</summary>
            <div>
              <ModuleHead title="任务验收口径" meta="运营可读" />
              <div className="acceptance-strip">
                <span>先验证配置完整性</span>
                <span>真实只读检查通过后才允许人工确认保存</span>
                <span>保留截图与结构化证据</span>
                <span>异常进入人工池</span>
                <span>最后生成报告</span>
              </div>
            </div>
          </details>
          <details className="inline-disclosure task-decision-drawer">
            <summary>启动条件说明</summary>
            <div className="gate-decision">
              <DecisionRow
                label="真实只读检查"
                status={l2Gate?.status ?? 'not_run'}
                detail="只有真实页面检查通过后，才允许进入真实保存启动判断；离线证据、部分通过、失败或未运行都不能启动真实保存。"
              />
              {l2DiagnosticSummaries.length > 0 && (
                <div className="l2-diagnostics" aria-label="L2 失败诊断">
                  <div className="l2-diagnostics__head">
                    <strong>只读失败诊断</strong>
                    <span>仅用于定位问题，不放行真实保存</span>
                  </div>
                {l2DiagnosticSummaries.map((item) => (
                  <article key={item.target} className="l2-diagnostic-card">
                    <div className="l2-diagnostic-card__title">
                      <strong>{item.targetLabel}</strong>
                      <span>{item.navigation}</span>
                    </div>
                    <div className="l2-diagnostic-card__chips">
                      {item.failedChecks.slice(0, 4).map((check) => (
                        <span key={check} className="guard-chip guard-chip--danger">{check}</span>
                      ))}
                    </div>
                    <ul>
                      <li><strong>最终地址</strong>{item.navigation}</li>
                      <li><strong>失败检查</strong>{item.failedChecks.slice(0, 4).map(humanFailedCheckLabel).join(' / ') || '页面检查未满足'}</li>
                      <li><strong>请求情况</strong>{item.requestSummary}</li>
                      <li><strong>下一步</strong>{item.nextAction}</li>
                      {item.renderHint && <li>{item.renderHint}</li>}
                      {item.reviewCandidateCount > 0 && (
                        <li>只读依赖候选 {item.reviewCandidateCount} 项，仍需人工评审，不自动放行。</li>
                      )}
                    </ul>
                    {(item.topRequests.length > 0 || item.reviewCandidateRequests.length > 0) && (
                      <details className="inline-disclosure l2-raw-request-drawer">
                        <summary>查看原始请求诊断</summary>
                        {item.topRequests.length > 0 && (
                          <div className="l2-review-candidates" aria-label={`${item.targetLabel} 拦截请求诊断清单`}>
                            <strong>拦截请求诊断清单</strong>
                            <span>仅用于开发排查，不自动放行真实保存</span>
                            <ul>
                              {item.topRequests.map((request) => (
                                <li key={request}>{request}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {item.reviewCandidateRequests.length > 0 && (
                          <div className="l2-review-candidates" aria-label={`${item.targetLabel} 只读依赖人工评审清单`}>
                            <strong>只读依赖人工评审清单</strong>
                            <span>仅人工评审，不自动放行真实保存</span>
                            <ul>
                              {item.reviewCandidateRequests.map((request) => (
                                <li key={request}>{request}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </details>
                    )}
                  </article>
                ))}
                </div>
              )}
              {l2Gate?.status !== 'passed' && l2DiagnosticSummaries.length === 0 && (
                <div className="l2-diagnostics" aria-label="L2 失败诊断">
                  <div className="l2-diagnostics__head">
                    <strong>只读失败诊断</strong>
                    <span>未收到明细，不放行真实保存</span>
                  </div>
                  <article className="l2-diagnostic-card">
                    <div className="l2-diagnostic-card__title">
                      <strong>真实只读检查未通过</strong>
                      <span>{l2Gate?.status ?? 'not_run'}</span>
                    </div>
                    <ul>
                      <li>{l2Gate?.detail ?? '缺少真实只读检查证据。'}</li>
                      <li>需要商品采集页与草稿箱页双目标真实通过后，才可进入保存判断。</li>
                    </ul>
                  </article>
                </div>
              )}
              <DecisionRow
                label="单商品只保存"
                status={l3Gate?.status ?? 'not_run'}
                detail={l3Gate?.status === 'blocked'
                  ? '真实只读检查通过后才启动采集认领；人工确认未完成前不启动单商品只保存；批量保存当前未开放。'
                  : '真实写操作仍需要人工批准令牌；待批准不等于已通过。'}
              />
              <div className="gate-note">
                当前按钮策略：真实只读检查未通过时保持阻断；采集认领可启动第一段流程；单商品只保存仍需后端人工批准；批量保存当前未开放。
              </div>
            </div>
          </details>
        </div>
      </details>
    </section>
  )
}

export function ExecutionConsole({
  workspace,
  selectedTask,
  agentConsole,
  agentConsoleError,
  configPreview,
  configPreviewError,
  configPreviewLoading,
  runtimeStatus,
  runtimeStatusError,
  desktopRuntime,
  runtimeLogs,
  runtimeLogSource,
  runtimeLogError,
  runtimeLogLevel,
  runtimeLogQuery,
  l2RunnerState,
  lastRuntimeControlResult,
  busy,
  dxmLoginDraft,
  dxmCredentialState,
  onDxmLoginDraftChange,
  onClearSavedDxmCredential,
  onRuntimeLogSourceChange,
  onRuntimeLogLevelChange,
  onRuntimeLogQueryChange,
  onStartAgentConsole,
  onContinueDxmLogin,
  onNavigateDxmTarget,
  onStopAgentConsole,
  onSnapshotAgentConsole,
  onRequestAgentConsoleTakeover,
  onReleaseAgentConsoleTakeover,
  onControlAgentConsoleBrowser,
  onRuntimeControl,
  onShowTasks,
  onShowConfig,
  onShowEvidence,
  onShowReports,
  onOpenDxmLogin,
}: ExecutionConsoleProps) {
  const taskLogs = selectedTask ? workspace.logs.filter((item) => item.task_id === selectedTask.id) : workspace.logs
  const steps = workspace.deliverySteps.length
    ? workspace.deliverySteps.map((step) => {
      const stepLabel = humanConsoleCodeLabel(step.state)
      return {
        title: displaySafeStepLabel(step.label),
        code: displaySafeStepCode(step.state),
        detail: `${stepLabel}${step.evidence_count ? ` / 证据 ${step.evidence_count}` : ''}${step.workflow_actions?.length ? ` / ${step.workflow_actions.map(displaySafeWorkflowAction).join(', ')}` : ''}`,
        state: step.status === 'completed' ? 'done' : step.status === 'running' ? 'current' : step.status === 'failed' ? 'blocked' : 'pending',
      }
    })
    : buildConsoleSteps(selectedTask, workspace.logs)
  const activeStep = steps.find((step) => step.state === 'current' || step.state === 'blocked') ?? steps.find((step) => step.state === 'pending') ?? steps[0]
  const browserFrame = getBrowserFrame(workspace, selectedTask, agentConsole)
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')
  const consolePrimaryPath = buildConsolePrimaryPath({ selectedTask, reports: workspace.reports, configPreview, configPreviewError, configPreviewLoading, l2Gate, l3Gate, runtimeStatus, busy })
  const realSaveBlocked = consolePrimaryPath.saveBlocked
  const realSaveBlockReason = consolePrimaryPath.detail
  const browserStartBlocked = consolePrimaryPath.blocksBrowserStart
  const browserStartBlockReason = consolePrimaryPath.detail
  const runtimeLogCount = runtimeLogs[runtimeLogSource]?.items?.length
    ?? runtimeLogs[runtimeLogSource]?.lines.length
    ?? 0
  const actionTimelineCount = agentConsole?.action_events?.length ?? agentConsole?.step_history?.length ?? 0
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const compactCompletedReview = selectedTaskCompleted && !agentConsole?.active
  const consoleFocusPanel = (
    <ConsoleFocusPanel
      selectedTask={selectedTask}
      activeStep={activeStep}
      agentConsole={agentConsole}
      primaryPath={consolePrimaryPath}
      l2Gate={l2Gate}
      l3Gate={l3Gate}
      runtimeStatus={runtimeStatus}
      runtimeStatusError={runtimeStatusError}
      runtimeLogSource={runtimeLogSource}
      runtimeLogCount={runtimeLogCount}
      runtimeLogs={runtimeLogs}
      runtimeLogError={runtimeLogError}
      onStartAgentConsole={onStartAgentConsole}
      onShowTasks={onShowTasks}
      onShowConfig={onShowConfig}
      onShowReports={onShowReports}
      onRuntimeControl={onRuntimeControl}
      onRuntimeLogSourceChange={onRuntimeLogSourceChange}
      onOpenDxmLogin={onOpenDxmLogin}
      onContinueDxmLogin={onContinueDxmLogin}
    />
  )

  return (
    <section className="agent-console-layout" aria-label="开始只保存">
      {runtimeStatusError && (
        <ServiceRecoveryPanel
          runtimeStatusError={runtimeStatusError}
          desktopRuntime={desktopRuntime}
          onRuntimeLogSourceChange={onRuntimeLogSourceChange}
        />
      )}

      {!compactCompletedReview && consoleFocusPanel}

      {compactCompletedReview ? (
        <ConsoleCompletedReviewPanel
          selectedTask={selectedTask}
          runtimeLogSource={runtimeLogSource}
          runtimeLogCount={runtimeLogCount}
          runtimeLogs={runtimeLogs}
          runtimeLogError={runtimeLogError}
          onRuntimeLogSourceChange={onRuntimeLogSourceChange}
          onShowReports={onShowReports}
          onShowEvidence={onShowEvidence}
          onShowTasks={onShowTasks}
        >
          <AgentStagePanel
            embedded
            workspace={workspace}
            selectedTask={selectedTask}
            activeStep={activeStep}
            browserFrame={browserFrame}
            agentConsole={agentConsole}
            agentConsoleError={agentConsoleError}
            runtimeStatus={runtimeStatus}
            runtimeStatusError={runtimeStatusError}
            busy={busy}
            realSaveBlocked={realSaveBlocked}
            realSaveBlockReason={realSaveBlockReason}
            primaryPath={consolePrimaryPath}
            browserStartBlocked={browserStartBlocked}
            browserStartBlockReason={browserStartBlockReason}
            dxmLoginDraft={dxmLoginDraft}
            dxmCredentialState={dxmCredentialState}
            onStartAgentConsole={onStartAgentConsole}
            onDxmLoginDraftChange={onDxmLoginDraftChange}
            onClearSavedDxmCredential={onClearSavedDxmCredential}
            onOpenDxmLogin={onOpenDxmLogin}
            onContinueDxmLogin={onContinueDxmLogin}
            onNavigateDxmTarget={onNavigateDxmTarget}
            onStopAgentConsole={onStopAgentConsole}
            onSnapshotAgentConsole={onSnapshotAgentConsole}
            onRequestAgentConsoleTakeover={onRequestAgentConsoleTakeover}
            onReleaseAgentConsoleTakeover={onReleaseAgentConsoleTakeover}
            onControlAgentConsoleBrowser={onControlAgentConsoleBrowser}
            onRuntimeControl={onRuntimeControl}
            onShowTasks={onShowTasks}
            onShowEvidence={onShowEvidence}
            onShowReports={onShowReports}
          />
        </ConsoleCompletedReviewPanel>
      ) : (
        <AgentStagePanel
          workspace={workspace}
          selectedTask={selectedTask}
          activeStep={activeStep}
          browserFrame={browserFrame}
          agentConsole={agentConsole}
          agentConsoleError={agentConsoleError}
          runtimeStatus={runtimeStatus}
          runtimeStatusError={runtimeStatusError}
          busy={busy}
          realSaveBlocked={realSaveBlocked}
          realSaveBlockReason={realSaveBlockReason}
          primaryPath={consolePrimaryPath}
          browserStartBlocked={browserStartBlocked}
          browserStartBlockReason={browserStartBlockReason}
          dxmLoginDraft={dxmLoginDraft}
          dxmCredentialState={dxmCredentialState}
          onStartAgentConsole={onStartAgentConsole}
          onDxmLoginDraftChange={onDxmLoginDraftChange}
          onClearSavedDxmCredential={onClearSavedDxmCredential}
          onOpenDxmLogin={onOpenDxmLogin}
          onContinueDxmLogin={onContinueDxmLogin}
          onNavigateDxmTarget={onNavigateDxmTarget}
          onStopAgentConsole={onStopAgentConsole}
          onSnapshotAgentConsole={onSnapshotAgentConsole}
          onRequestAgentConsoleTakeover={onRequestAgentConsoleTakeover}
          onReleaseAgentConsoleTakeover={onReleaseAgentConsoleTakeover}
          onControlAgentConsoleBrowser={onControlAgentConsoleBrowser}
          onRuntimeControl={onRuntimeControl}
          onShowTasks={onShowTasks}
          onShowEvidence={onShowEvidence}
          onShowReports={onShowReports}
        />
      )}

      {!compactCompletedReview && (
        <L2RunnerStatePanel
          state={l2RunnerState}
          l2Gate={l2Gate}
          runtimeStatus={runtimeStatus}
          busy={busy}
          onRunPrecheck={() => onRuntimeControl('run_l2_readonly_probe')}
          onLogSourceChange={onRuntimeLogSourceChange}
          onShowReports={onShowReports}
        />
      )}

      <details className="module-card span-3 disclosure-card console-advanced console-diagnostics-drawer">
        <summary>更多诊断与维护</summary>
        <div className="console-diagnostics-grid">
          <section className="console-diagnostics-panel console-diagnostics-panel--wide" aria-label="完整日志与维护诊断">
            <ModuleHead title="完整日志与维护诊断" meta="按需展开查看" />
            <RuntimeLogPanel
              logs={runtimeLogs}
              source={runtimeLogSource}
              error={runtimeLogError}
              level={runtimeLogLevel}
              query={runtimeLogQuery}
              onSourceChange={onRuntimeLogSourceChange}
              onLevelChange={onRuntimeLogLevelChange}
              onQueryChange={onRuntimeLogQueryChange}
            />
          </section>
          <section className="console-diagnostics-panel" aria-label="运行时维护">
            <ModuleHead title="运行时维护" meta="安全动作" />
          <RuntimeControlPanel
            busy={busy}
            selectedTask={selectedTask}
            agentConsole={agentConsole}
            runtimeStatus={runtimeStatus}
            lastRuntimeControlResult={lastRuntimeControlResult}
            onRuntimeControl={onRuntimeControl}
          />
          </section>
          <section className="console-diagnostics-panel" aria-label="自动操作轨迹">
            <ModuleHead title="自动操作轨迹" meta={`${actionTimelineCount} 条`} />
            <AgentActionTimeline agentConsole={agentConsole} />
          </section>
          <section className="console-diagnostics-panel console-diagnostics-panel--wide" aria-label="状态机步骤">
            <ModuleHead title="状态机步骤" meta={selectedTask ? `任务 #${selectedTask.id}` : '未选择任务'} />
            <div className="stepper">
              {steps.map((step, index) => (
                <div key={step.title} className={`step ${step.state}`}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>{step.title}</strong>
                    <small>{step.detail}</small>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <section className="console-diagnostics-panel console-diagnostics-panel--wide" aria-label="任务执行日志">
            <ModuleHead title="任务执行日志" meta={`${taskLogs.length} 条`} />
            <div className="timeline-list">
              {taskLogs.map((log) => (
                <LogRow key={log.id} log={log} />
              ))}
              {!taskLogs.length && (
                <EmptyState title="暂无执行日志" detail="当前仅可查看真实只读诊断与证据；真实只读检查未通过时禁止启动真实保存。" />
              )}
            </div>
          </section>
        </div>
      </details>
    </section>
  )
}

function AgentStagePanel({
  embedded = false,
  workspace,
  selectedTask,
  activeStep,
  browserFrame,
  agentConsole,
  agentConsoleError,
  runtimeStatus,
  runtimeStatusError,
  busy,
  realSaveBlocked,
  realSaveBlockReason,
  primaryPath,
  browserStartBlocked,
  browserStartBlockReason,
  dxmLoginDraft,
  dxmCredentialState,
  onStartAgentConsole,
  onDxmLoginDraftChange,
  onClearSavedDxmCredential,
  onOpenDxmLogin,
  onContinueDxmLogin,
  onNavigateDxmTarget,
  onStopAgentConsole,
  onSnapshotAgentConsole,
  onRequestAgentConsoleTakeover,
  onReleaseAgentConsoleTakeover,
  onControlAgentConsoleBrowser,
  onRuntimeControl,
  onShowTasks,
  onShowEvidence,
  onShowReports,
}: {
  embedded?: boolean
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  activeStep?: { title: string; code?: string; detail: string; state: string }
  browserFrame: { url: string; evidencePath: string; source: string }
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  busy: boolean
  realSaveBlocked: boolean
  realSaveBlockReason: string
  primaryPath: ConsolePrimaryPath
  browserStartBlocked: boolean
  browserStartBlockReason: string
  dxmLoginDraft: DxmLoginDraft
  dxmCredentialState: DxmCredentialState
  onStartAgentConsole: () => void
  onDxmLoginDraftChange: (draft: DxmLoginDraft) => void
  onClearSavedDxmCredential: () => void
  onOpenDxmLogin: () => void
  onContinueDxmLogin: () => void
  onNavigateDxmTarget: (target: 'data_acquisition' | 'draft_box') => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
  onRequestAgentConsoleTakeover: () => void
  onReleaseAgentConsoleTakeover: () => void
  onControlAgentConsoleBrowser: (command: AgentConsoleControlCommand) => void
  onRuntimeControl: (action: RuntimeControlAction) => void
  onShowTasks: () => void
  onShowEvidence: () => void
  onShowReports: () => void
}) {
  return (
    <div className={embedded ? 'agent-console-stage agent-console-stage--embedded' : 'module-card agent-console-stage'}>
      <ModuleHead
        title="店小秘操作窗口"
        meta={agentConsole?.active ? '真实浏览器运行中' : '先登录，再检查，最后只保存'}
      />
      <AgentLoginPanel
        dxmLoginDraft={dxmLoginDraft}
        dxmCredentialState={dxmCredentialState}
        runtimeStatus={runtimeStatus}
        runtimeStatusError={runtimeStatusError}
        busy={busy}
        onDxmLoginDraftChange={onDxmLoginDraftChange}
        onClearSavedDxmCredential={onClearSavedDxmCredential}
        onOpenDxmLogin={onOpenDxmLogin}
        onContinueDxmLogin={onContinueDxmLogin}
      />
      <p className="agent-stage-control-summary">
        Agent 控制真实浏览器；独立真实店小秘窗口会显式打开，自动填写和点击保存只来自当前任务，发布和批量无人值守保持关闭，截图只作为报告证据。
      </p>
      <AgentConsoleControls
        agentConsole={agentConsole}
        agentConsoleError={agentConsoleError}
        runtimeStatus={runtimeStatus}
        runtimeStatusError={runtimeStatusError}
        selectedTask={selectedTask}
        busy={busy}
        realSaveBlocked={realSaveBlocked}
        realSaveBlockReason={realSaveBlockReason}
        primaryPath={primaryPath}
        browserStartBlocked={browserStartBlocked}
        browserStartBlockReason={browserStartBlockReason}
        onStartAgentConsole={onStartAgentConsole}
        onNavigateDxmTarget={onNavigateDxmTarget}
        onStopAgentConsole={onStopAgentConsole}
        onSnapshotAgentConsole={onSnapshotAgentConsole}
        onRequestAgentConsoleTakeover={onRequestAgentConsoleTakeover}
        onReleaseAgentConsoleTakeover={onReleaseAgentConsoleTakeover}
        onControlAgentConsoleBrowser={onControlAgentConsoleBrowser}
        onRuntimeControl={onRuntimeControl}
      />
      <details className="agent-stage-support-drawer inline-disclosure">
        <summary>更多浏览器状态与证据</summary>
        {realSaveBlocked && (
          <details className="gate-note gate-note--danger inline-disclosure">
            <summary>查看阻断详情</summary>
            <span>{realSaveBlockReason}</span>
            <div className="next-step-actions">
              <button className="button button--secondary" type="button" onClick={onShowTasks}>回到选择商品</button>
              <button className="button button--secondary" type="button" onClick={onShowReports} data-section="reports">查看只读评审与检查计划</button>
              <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看证据缺口</button>
            </div>
          </details>
        )}
        <details className="agent-browser-drawer inline-disclosure">
          <summary>浏览器状态与证据路径</summary>
          <small>外部真实浏览器窗口由 Agent 控制；控制台默认不内嵌浏览器画面，避免把状态面板误当成实时页面。</small>
          <AgentBrowserFrame
            workspace={workspace}
            selectedTask={selectedTask}
            activeStep={activeStep}
            browserFrame={browserFrame}
            agentConsole={agentConsole}
          />
        </details>
      </details>
    </div>
  )
}

function ConsoleCompletedReviewPanel({
  selectedTask,
  runtimeLogSource,
  runtimeLogCount,
  runtimeLogs,
  runtimeLogError,
  onRuntimeLogSourceChange,
  onShowReports,
  onShowEvidence,
  onShowTasks,
  children,
}: {
  selectedTask: Task | null
  runtimeLogSource: RuntimeLogSource
  runtimeLogCount: number
  runtimeLogs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  runtimeLogError: string | null
  onRuntimeLogSourceChange: (source: RuntimeLogSource) => void
  onShowReports: () => void
  onShowEvidence: () => void
  onShowTasks: () => void
  children: ReactNode
}) {
  const sourceLabel = runtimeLogSourceLabels()[runtimeLogSource]
  return (
    <div className="module-card span-2 console-review-panel">
      <ModuleHead title="任务已完成" meta={selectedTask ? `任务 #${selectedTask.id}` : '等待任务'} />
      <div className="console-review-panel__body">
        <div>
          <strong>下一步只复核结果</strong>
          <span>查看保存结果、未发布证明和真实浏览器记录；如要处理新商品，回到选择商品创建新任务。</span>
        </div>
        <div className="console-review-panel__facts">
          <span><b>结果</b><strong>优先查看</strong></span>
          <span><b>保存证据</b><strong>核对未发布</strong></span>
          <span><b>日志</b><strong>{sourceLabel} {runtimeLogCount} 条</strong></span>
        </div>
      </div>
      <div className="console-review-panel__actions">
        <button className="button button--secondary" type="button" onClick={onShowReports} data-section="reports">查看保存结果</button>
        <button className="button button--quiet" type="button" onClick={onShowEvidence}>查看保存证据</button>
        <button className="button button--quiet" type="button" onClick={onShowTasks}>创建/选择任务</button>
      </div>
      <div className="console-review-panel__log" aria-label="最近日志">
        <RuntimeLogPreview
          logs={runtimeLogs}
          source={runtimeLogSource}
          error={runtimeLogError}
          onSourceChange={onRuntimeLogSourceChange}
        />
        <small>完整日志在下方“更多诊断与维护”。</small>
      </div>
      <details className="inline-disclosure console-review-panel__browser">
        <summary>继续操作真实浏览器</summary>
        <small>仅在需要重新登录、补做真实只读检查或人工排查时展开；完成态默认不展示浏览器操控细节。</small>
        {children}
      </details>
    </div>
  )
}

function RuntimeControlPanel({
  busy,
  selectedTask,
  agentConsole,
  runtimeStatus,
  lastRuntimeControlResult,
  onRuntimeControl,
}: {
  busy: boolean
  selectedTask: Task | null
  agentConsole: AgentConsoleSession | null
  runtimeStatus: RuntimeStatus | null
  lastRuntimeControlResult: RuntimeControlResponse | null
  onRuntimeControl: (action: RuntimeControlAction) => void
}) {
  const agentActive = Boolean(agentConsole?.active)
  const canMarkManualReview = canMarkRealTaskForManualReview(selectedTask)
  const launcherManaged = Boolean(runtimeStatus?.runtimeControl?.managedByLauncher)
  const restartAvailable = Boolean(runtimeStatus?.runtimeControl?.restartAvailable)
  const restartDisabled = busy || !restartAvailable
  const runtimeOwnerText = runtimeControlOwnerText(runtimeStatus?.runtimeControl?.owner ?? 'direct', Boolean(runtimeStatus?.runtimeControl?.managedByDesktop))
  const runtimeControlDetail = runtimeStatus?.runtimeControl?.detail
    ?? '未读取到启动来源；请关闭并重新打开免安装版 exe，或使用 scripts/start-mvp.bat 启动后再重试。'
  const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)
  const l2ProbeDisabled = busy || l2ProbeResourceState.blocked
  return (
    <div className="runtime-control-panel">
      <button
        className="button button--secondary"
        type="button"
        disabled={busy || !agentActive}
        onClick={() => onRuntimeControl('stop_agent_console')}
      >
        停止浏览器 Agent
      </button>
      <button
        className="button button--quiet"
        type="button"
        disabled={busy}
        onClick={() => onRuntimeControl('clear_stuck_tasks')}
      >
        清理卡住任务
      </button>
      <button
        className="button button--quiet"
        type="button"
        disabled={busy || !canMarkManualReview}
        onClick={() => onRuntimeControl('mark_real_task_manual_review')}
      >
        转人工复核
      </button>
      <button
        className="button button--quiet"
        type="button"
        disabled={l2ProbeDisabled}
        title={l2ProbeResourceState.title}
        onClick={() => onRuntimeControl('run_l2_readonly_probe')}
      >
        {READONLY_PRECHECK_CTA}
      </button>
      {l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}
      <details className="inline-disclosure">
        <summary>服务重启</summary>
        <div className="runtime-control-panel__restart">
          <button className="button button--quiet" type="button" disabled={restartDisabled} onClick={() => onRuntimeControl('restart_backend')}>
            重启后端
          </button>
          <button className="button button--quiet" type="button" disabled={restartDisabled} onClick={() => onRuntimeControl('restart_frontend')}>
            重启前端
          </button>
          <small>
            启动来源：{runtimeOwnerText}。启动器托管：{launcherManaged ? '已接管' : '未接管'}。{runtimeControlDetail}
          </small>
        </div>
      </details>
      <RuntimeControlResultSummary result={lastRuntimeControlResult} />
      <small>维护动作会写入启动器日志；真实保存任务不会被“清理卡住任务”取消；转人工复核不会取消真实浏览器进程。</small>
    </div>
  )
}

function runtimeControlOwnerText(owner: string, managedByDesktop: boolean) {
  if (owner === 'desktop' || managedByDesktop) return 'DXM Agent Console 免安装版'
  if (owner === 'start_mvp') return 'start-mvp.bat'
  return '旧进程/直接 Python，关闭并重新打开免安装版 exe'
}

function getL2ProbeResourceState(runtimeStatus: RuntimeStatus | null) {
  if (!runtimeStatus || !runtimeStatus.dependencies) {
    return {
      blocked: true,
      title: '真实只读检查依赖状态未知，请先刷新运行状态或重新打开免安装版。',
      detail: '真实只读检查依赖状态未知，请先刷新运行状态或重新打开免安装版。',
      repairSteps: [
        '刷新运行状态，确认后端已经由免安装版接管。',
        '如果仍未知，关闭旧的 DXM Agent Console 或后台旧进程。',
        '打开桌面免安装目录里的 DXM-Agent-Console.exe。',
        '不要只复制 exe，必须保留 resources 文件夹。',
      ],
      checkedPathPreview: [],
    }
  }
  if (runtimeStatus.l2ReadonlyProbe?.running) {
    const runId = runtimeStatus.l2ReadonlyProbe.runId ?? '未知 runId'
    const taskId = runtimeStatus.l2ReadonlyProbe.taskId ? ` / 任务 #${runtimeStatus.l2ReadonlyProbe.taskId}` : ''
    return {
      blocked: true,
      title: `真实只读检查正在运行：${runId}${taskId}`,
      detail: `真实只读检查正在运行，请等待完成。当前检查：${runId}${taskId}。请等待完成或查看实时日志；完成前不会启动第二个检查。关闭旧窗口或后台旧进程后，再重新打开免安装版。`,
      repairSteps: [],
      checkedPathPreview: [],
    }
  }
  const dependencies = runtimeStatus?.dependencies ?? {}
  const required = [
    ['真实只读检查启动器', dependencies.l2_readonly_probe_runner],
    ['真实只读检查脚本', dependencies.l2_readonly_probe_script],
    ['只读异常候选规则', dependencies.l2_readonly_probe_allowlist],
  ] as const
  const missing = required.filter(([, item]) => item?.status === 'missing')
  if (!missing.length) {
    return {
      blocked: false,
      title: '运行双目标真实只读检查；不会保存、不会发布。',
      detail: '',
      repairSteps: [],
      checkedPathPreview: [],
    }
  }
  const detail = missing
    .map(([label, item]) => `${item?.userMessage || `真实只读检查组件未安装完整：缺少${item?.label || label}。`}`)
    .join('；')
  const checkedPaths = missing
    .flatMap(([, item]) => item?.checkedPaths ?? [])
    .slice(0, 4)
  const checkedText = checkedPaths.length ? `已检查：${checkedPaths.join('；')}` : '已检查路径：暂无'
  const backendRepairSteps = Array.from(new Set(missing.flatMap(([, item]) => item?.repairSteps ?? [])))
  const repairSteps = backendRepairSteps.length
    ? backendRepairSteps
    : [
    '关闭旧的 DXM Agent Console 或后台旧进程。',
    '打开桌面免安装目录里的 DXM-Agent-Console.exe。',
    '不要只复制 exe，必须保留 resources 文件夹。',
    ]
  return {
    blocked: true,
    title: `真实只读检查组件未安装完整：${detail}。${checkedText}`,
    detail: `真实只读检查组件未安装完整，请关闭旧进程并重新打开完整免安装目录版。${detail}。${checkedText}`,
    repairSteps,
    checkedPathPreview: checkedPaths,
  }
}

function RuntimeControlResultSummary({ result }: { result: RuntimeControlResponse | null }) {
  if (!result || (result.action !== 'clear_stuck_tasks' && result.action !== 'mark_real_task_manual_review' && result.action !== 'run_l2_readonly_probe')) {
    return null
  }
  if (result.action === 'run_l2_readonly_probe') {
    return (
      <div className="runtime-control-result" aria-label="真实只读检查启动结果">
        <strong>真实只读检查已启动</strong>
        <span>检查目标：{formatL2ProbeTargets(result.targets)}</span>
        <span>完成后会自动刷新结果。</span>
        <small>不会保存、不会发布；请保持真实店小秘登录窗口可用。</small>
        <details className="inline-disclosure">
          <summary>技术日志</summary>
          <small>run-id：{result.runId ?? '等待返回'}</small>
          <small>日志：{result.logPath ?? '启动器日志'}</small>
        </details>
      </div>
    )
  }
  if (result.action === 'mark_real_task_manual_review') {
    const marked = result.markedTasks ?? []
    const markedText = marked.length ? marked.map(manualReviewTaskLabel).join('、') : '0 个'
    return (
      <div className="runtime-control-result" aria-label="人工复核结果">
        <strong>人工复核结果</strong>
        <span>已转人工复核：{markedText}</span>
        <span>状态标记：needs_manual_review</span>
        {result.message && <small>{result.message}</small>}
      </div>
    )
  }
  const cleared = result.clearedTasks ?? []
  const skipped = result.skippedTasks ?? []
  const clearedText = cleared.length ? cleared.map(runtimeTaskLabel).join('、') : '0 个'
  const protectedText = skipped.length ? skipped.map(protectedRuntimeTaskLabel).join('、') : '0 个'
  return (
    <div className="runtime-control-result" aria-label="清理结果">
      <strong>清理结果</strong>
      <span>已取消非真实写入任务：{clearedText}</span>
      <span>真实写入任务已保护，未自动取消：{protectedText}</span>
      {result.message && <small>{result.message}</small>}
    </div>
  )
}

function formatL2ProbeTargets(targets?: string[]) {
  const labels = {
    data_acquisition: '商品采集页',
    draft_box: '采集箱/草稿箱',
  } as Record<string, string>
  const values = (targets?.length ? targets : ['data_acquisition', 'draft_box'])
    .map((target) => labels[target] ?? target)
  return values.join('、')
}

function runtimeTaskLabel(item: Record<string, unknown>) {
  return `#${String(item.id ?? '?')}`
}

function protectedRuntimeTaskLabel(item: Record<string, unknown>) {
  const parts = [
    runtimeTaskLabel(item),
    typeof item.mode === 'string' ? item.mode : '',
    typeof item.status === 'string' ? item.status : '',
    item.reason === 'real_write_protected' ? 'real_write_protected' : typeof item.reason === 'string' ? item.reason : '',
  ].filter(Boolean)
  return parts.join(' ')
}

function manualReviewTaskLabel(item: Record<string, unknown>) {
  const parts = [
    runtimeTaskLabel(item),
    typeof item.mode === 'string' ? item.mode : '',
    typeof item.previousStatus === 'string' ? `${item.previousStatus} -> needs_manual_review` : 'needs_manual_review',
  ].filter(Boolean)
  return parts.join(' ')
}

function canMarkRealTaskForManualReview(task: Task | null) {
  if (!task) return false
  const mode = String(task.mode || task.payload?.execution_mode || '')
  if (!['claim_only', 'single_save', 'batch_save'].includes(mode)) return false
  return ['running', 'paused', 'failed', 'partial_success'].includes(String(task.status || ''))
}

function AgentActionTimeline({ agentConsole }: { agentConsole: AgentConsoleSession | null }) {
  const events = getAgentActionTimelineEvents(agentConsole)
  if (!events.length) {
    return <EmptyState title="暂无动作轨迹" detail="任务运行时，点击、填写、保存等待步骤会从后端自动浏览器同步到这里。" />
  }
  return (
    <div className="agent-action-timeline">
      {events.map((event, index) => {
        const typeLabel = getAgentActionTypeLabel(event.type)
        const title = event.label ?? event.action ?? event.target ?? event.step_code ?? typeLabel
        const stepCode = displaySafeStepCode(event.step_code ?? event.state ?? event.type ?? 'WAITING')
        const fieldDomain = event.field_domain ?? '自动化'
        const detail = getAgentActionDetail(event)
        const status = getAgentActionStatus(event.status)
        return (
          <article key={`${event.timestamp ?? event.step_code ?? event.action ?? event.type}-${index}`} className="agent-action-row">
            <span>{events.length - index}</span>
            <div>
              <div className="agent-action-row__head">
                <span className="agent-action-row__type">{typeLabel}</span>
                {status && <span className={`status-pill ${status.tone}`}>{status.label}</span>}
              </div>
              <strong>{displaySafeStepLabel(title)}</strong>
              <small>{[
                stepCode,
                fieldDomain,
                event.task_id ? `task #${event.task_id}` : '',
                event.job_id ? `job #${event.job_id}` : '',
                event.product_id ? `product #${event.product_id}` : '',
              ].filter(Boolean).join(' / ')}</small>
              {detail && <code>{detail}</code>}
            </div>
          </article>
        )
      })}
    </div>
  )
}

function getAgentActionTimelineEvents(agentConsole: AgentConsoleSession | null): AgentConsoleActionEvent[] {
  const actionEvents = agentConsole?.action_events ?? []
  if (actionEvents.length) return [...actionEvents].reverse().slice(0, 12)

  return [...(agentConsole?.step_history ?? [])].reverse().slice(0, 12).map((event) => {
    const stepCode = String(event.step_code ?? event.state ?? event.code ?? 'WAITING')
    return {
      type: 'workflow_action',
      action: String(event.step_name ?? event.title ?? stepCode),
      label: String(event.step_name ?? event.title ?? stepCode),
      state: typeof event.state === 'string' ? event.state : undefined,
      step_code: stepCode,
      task_id: typeof event.task_id === 'number' ? event.task_id : undefined,
      job_id: typeof event.job_id === 'number' ? event.job_id : undefined,
      product_id: typeof event.product_id === 'number' ? event.product_id : undefined,
      field_domain: event.field_domain ? String(event.field_domain) : '状态机',
      status: typeof event.status === 'string' ? event.status : undefined,
      page_url: typeof event.page_url === 'string' ? event.page_url : undefined,
      screenshot_url: typeof event.screenshot_url === 'string' ? event.screenshot_url : typeof event.screenshot_path === 'string' ? event.screenshot_path : undefined,
      timestamp: typeof event.updated_at === 'string' ? event.updated_at : typeof event.timestamp === 'string' ? event.timestamp : undefined,
    }
  })
}

function getAgentActionTypeLabel(type?: string) {
  const labels: Record<string, string> = {
    workflow_action: '流程',
    click: '点击',
    fill: '填写',
    select: '选择',
    upload: '上传',
    wait: '等待',
    save: '保存',
    browser_control: '控制',
  }
  return labels[type ?? ''] ?? (type ? type.slice(0, 12) : '动作')
}

function getAgentActionStatus(status?: string) {
  if (!status) return null
  if (status === 'ok') return { label: 'ok', tone: 'ok' }
  if (status === 'failed' || status === 'error') return { label: status, tone: 'danger' }
  return { label: status.slice(0, 16), tone: 'muted' }
}

function getAgentActionDetail(event: AgentConsoleActionEvent) {
  if (event.save_result) return summarizeAgentSaveResult(event.save_result)
  if (event.page_url) return `URL ${shortUrl(event.page_url)}`
  if (event.target && event.value) return `${event.target}: ${event.value}`.slice(0, 120)
  if (event.target) return event.target.slice(0, 120)
  if (event.value) return event.value.slice(0, 120)
  if (event.screenshot_url) return event.screenshot_url.slice(0, 120)
  return ''
}

function summarizeAgentSaveResult(saveResult: Record<string, unknown>) {
  const entries = Object.entries(saveResult)
    .filter(([, value]) => value !== null && value !== undefined)
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${summarizeAgentActionValue(value)}`)
  return entries.length ? entries.join(' / ') : '保存结果已返回'
}

function summarizeAgentActionValue(value: unknown) {
  if (typeof value === 'string') return value.slice(0, 48)
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value).slice(0, 48)
  } catch {
    return String(value).slice(0, 48)
  }
}

function ConsoleFocusPanel({
  selectedTask,
  activeStep,
  agentConsole,
  primaryPath,
  l2Gate,
  l3Gate,
  runtimeStatus,
  runtimeStatusError,
  runtimeLogSource,
  runtimeLogCount,
  runtimeLogs,
  runtimeLogError,
  onStartAgentConsole,
  onShowTasks,
  onShowConfig,
  onShowReports,
  onRuntimeControl,
  onRuntimeLogSourceChange,
  onOpenDxmLogin,
  onContinueDxmLogin,
}: {
  selectedTask: Task | null
  activeStep?: { title: string; code?: string; detail: string; state: string }
  agentConsole: AgentConsoleSession | null
  primaryPath: ConsolePrimaryPath
  l2Gate?: RegressionGate
  l3Gate?: RegressionGate
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError?: string | null
  runtimeLogSource: RuntimeLogSource
  runtimeLogCount: number
  runtimeLogs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  runtimeLogError: string | null
  onStartAgentConsole: () => void
  onShowTasks: () => void
  onShowConfig: () => void
  onShowReports: () => void
  onRuntimeControl: (action: RuntimeControlAction) => void
  onRuntimeLogSourceChange: (source: RuntimeLogSource) => void
  onOpenDxmLogin: () => void
  onContinueDxmLogin: () => void
}) {
  const active = Boolean(agentConsole?.active)
  const hasBrowserSession = Boolean(agentConsole?.active || agentConsole?.updated_at)
  const browserLaunching = Boolean(agentConsole?.browser_launching)
  const browserVisible = Boolean(agentConsole?.browser_visible)
  const manualTakeover = Boolean(agentConsole?.manual_takeover)
  const currentUrl = agentConsole?.current_url ?? agentConsole?.target_url
  const selectedTaskCompleted = selectedTask?.status === 'completed'
  const guardLabel = selectedTaskCompleted
    ? '任务已完成'
    : primaryPath.saveBlocked
      ? '保存前置条件未完成'
      : '可申请只保存'
  const browserLabel = active
    ? browserLaunching
      ? '正在启动'
      : browserVisible
      ? '窗口可见'
      : '会话中，窗口未显示'
    : '待启动'
  const controlLabel = manualTakeover
    ? '人工接管中'
    : active && browserVisible
      ? 'Agent 可控'
      : active
        ? browserLaunching ? '启动中' : '等待窗口可见'
        : '启动后可控'
  const takeoverLabel = active
    ? manualTakeover
      ? '接管中，可交还 Agent'
      : '可在生命周期区接管'
    : '启动浏览器后可接管'
  const consoleNext = selectedTaskCompleted
    ? '查看报告与未发布证明'
      : active
        ? browserLaunching
          ? '等待独立真实浏览器启动完成'
          : humanConsoleText(agentConsole?.hud?.next_step ?? '按当前步骤继续操作真实浏览器')
      : primaryPath.next
  const primaryActionLabel = primaryPath.ctaLabel
  const loginState = humanDxmLoginState(runtimeStatus, runtimeStatusError)
  const primaryAction = () => {
    if (primaryPath.action === 'dxm_login') return onOpenDxmLogin()
    if (primaryPath.action === 'reports') return onShowReports()
    if (primaryPath.action === 'config') return onShowConfig()
    if (primaryPath.action === 'current_execution') return onRuntimeLogSourceChange('agent')
    if (primaryPath.action === 'launcher_logs') return onRuntimeLogSourceChange('launcher')
    if (primaryPath.action === 'run_l2') return onRuntimeControl('run_l2_readonly_probe')
    if (primaryPath.action === 'start_browser') return onStartAgentConsole()
    return onShowTasks()
  }
  const sourceLabel = ({
    backend: '后端',
    frontend: '前端',
    launcher: '启动器',
    npm: '依赖安装',
    task: '任务',
    agent: '浏览器 Agent',
  } as Record<RuntimeLogSource, string>)[runtimeLogSource]
  const l2StatusLabel = selectedTaskCompleted ? '已完成' : humanGateStateLabel(l2Gate?.status ?? 'not_run')
  const l3StatusLabel = selectedTaskCompleted ? '已完成' : humanGateStateLabel(l3Gate?.status ?? 'blocked')
  return (
    <div className="module-card span-2 console-focus-panel">
      <div className="console-focus-panel__main">
        <span className={`console-focus-panel__dot ${primaryPath.saveBlocked ? 'is-warn' : active ? 'is-live' : ''}`} aria-hidden="true" />
        <div>
          <ModuleHead title="现在只做哪一步" meta={selectedTask ? `任务 #${selectedTask.id}` : '未选择任务'} />
          <h1>{active ? activeStep?.title ?? primaryPath.title : primaryPath.title}</h1>
          <p>{active ? activeStep?.detail ?? primaryPath.detail : primaryPath.detail}</p>
          {primaryPath.action === 'run_l2' && !active && (
            <div className="console-precheck-explainer" role="note">
              <strong>发生了什么</strong>
              <span>{READONLY_PRECHECK_PURPOSE}</span>
            </div>
          )}
        </div>
      </div>
      <div className="console-focus-panel__decision-grid" aria-label="控制台当前决策">
        <span><strong>当前动作</strong><b>{active ? activeStep?.title ?? primaryPath.title : primaryPath.title}</b></span>
        <span><strong>为什么不能继续</strong><b>{primaryPath.saveBlocked ? primaryPath.reason : '当前未发现保存阻断'}</b></span>
        <span><strong>下一步</strong><b>{consoleNext}</b></span>
      </div>
      <ConsolePrimaryBlockerCard
        primaryPath={primaryPath}
        consoleNext={consoleNext}
        primaryActionLabel={primaryActionLabel}
        onPrimaryAction={primaryAction}
        primaryActionDisabled={false}
        primaryActionDisabledTitle={undefined}
        onShowReports={onShowReports}
        onRuntimeLogSourceChange={onRuntimeLogSourceChange}
        loginState={loginState}
        onOpenDxmLogin={onOpenDxmLogin}
        onContinueDxmLogin={onContinueDxmLogin}
      />
      <div className="console-focus-panel__status-strip" aria-label="执行浏览器首屏状态">
        <span>
          <strong>DXM 登录</strong>
          <b>{loginState?.label ?? '未检测'}</b>
        </span>
        <span>
          <strong>真实只读检查</strong>
          <b>{l2StatusLabel}</b>
        </span>
        <span>
          <strong>人工确认</strong>
          <b>{l3StatusLabel}</b>
        </span>
        <span>
          <strong>执行浏览器</strong>
          <b>{browserLabel}</b>
        </span>
      </div>
      <div className="console-focus-panel__log" aria-label="最近日志">
        <RuntimeLogPreview
          logs={runtimeLogs}
          source={runtimeLogSource}
          error={runtimeLogError}
          onSourceChange={onRuntimeLogSourceChange}
        />
        <small>完整日志在下方“更多诊断与维护”。</small>
      </div>
      <details className="console-focus-panel__details inline-disclosure">
        <summary>维护人员查看技术状态</summary>
        <div className="console-focus-panel__facts">
          <span><strong>任务</strong><b>{selectedTask ? `${displayTaskName(selectedTask)} / ${humanTaskStatus(selectedTask.status)}` : '待选择'}</b></span>
          <span><strong>当前步骤</strong><b>{activeStep?.title ?? '等待任务'}</b></span>
          <span><strong>当前页面</strong><b>{hasBrowserSession && currentUrl ? shortUrl(currentUrl) : '等待启动执行浏览器'}</b></span>
          <span><strong>操控状态</strong><b>{controlLabel}</b></span>
          <span><strong>人工接管</strong><b>{takeoverLabel}</b></span>
          <span><strong>日志</strong><b>{sourceLabel} {runtimeLogCount} 条</b></span>
          <span><strong>门禁</strong><b>{guardLabel}</b></span>
        </div>
      </details>
      <div className="console-focus-panel__actions">
        {selectedTaskCompleted ? (
          <small>任务已完成，下面复核报告、证据和日志。</small>
        ) : (
          <>
            {primaryPath.saveBlocked && <small>{primaryPath.reason}</small>}
            <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">查看检查计划</button>
          </>
        )}
      </div>
    </div>
  )
}

function ConsolePrimaryBlockerCard({
  primaryPath,
  consoleNext,
  primaryActionLabel,
  onPrimaryAction,
  primaryActionDisabled,
  primaryActionDisabledTitle,
  onShowReports,
  onRuntimeLogSourceChange,
  loginState,
  onOpenDxmLogin,
  onContinueDxmLogin,
}: {
  primaryPath: ConsolePrimaryPath
  consoleNext: string
  primaryActionLabel: string
  onPrimaryAction: () => void
  primaryActionDisabled: boolean
  primaryActionDisabledTitle?: string
  onShowReports: () => void
  onRuntimeLogSourceChange: (source: RuntimeLogSource) => void
  loginState: ReturnType<typeof humanDxmLoginState>
  onOpenDxmLogin: () => void
  onContinueDxmLogin: () => void
}) {
  const tone = primaryPath.saveBlocked ? 'is-blocked' : primaryPath.code === 'ready' ? 'is-ready' : 'is-neutral'
  const showLoginRecovery = loginState?.label === '登录还没完成，不是系统故障' || loginState?.label === '登录未通过'
  return (
    <div className={`console-primary-blocker-card ${tone}`} aria-label="当前只处理这一项" data-console-primary-code={primaryPath.code}>
      <strong>当前只处理这一项</strong>
      <p className="console-primary-blocker-card__summary">
        <b>{primaryPath.reason}</b>
        <small>{primaryPath.next || consoleNext}</small>
      </p>
      <button
        className="button button--primary console-primary-blocker-card__action"
        type="button"
        onClick={onPrimaryAction}
        disabled={primaryActionDisabled}
        title={primaryActionDisabledTitle}
      >
        {primaryActionLabel}
      </button>
      <details className="console-primary-blocker-card__details inline-disclosure">
        <summary>查看原因与下一步</summary>
        <div className="console-primary-blocker-card__facts">
          <span>
            <b>发生了什么</b>
            <small>{primaryPath.reason}</small>
          </span>
          <span>
            <b>为什么不能继续</b>
            <small>{primaryPath.detail}</small>
          </span>
          <span>
            <b>下一步</b>
            <small>{primaryPath.next || consoleNext}</small>
          </span>
        </div>
        {primaryPath.action === 'run_l2' && (
          <p className="console-primary-blocker-card__explain">
            <b>{READONLY_PRECHECK_CTA}</b>
            <span>{READONLY_PRECHECK_PURPOSE}</span>
          </p>
        )}
        {primaryPath.action === 'run_l2' && (
          <div className="console-primary-blocker-card__recovery" aria-label="真实只读检查失败恢复路径">
            <span><b>1 确认登录</b><small>真实浏览器已登录，验证码或账号密码错误先在登录窗口修正。</small></span>
            <span><b>2 打开目标页</b><small>能打开商品采集页和采集箱；打不开先处理页面权限或网络。</small></span>
            <span><b>3 重新检查</b><small>无写入风险后，再点击运行真实只读检查。</small></span>
            <button className="button button--quiet" type="button" onClick={() => onRuntimeLogSourceChange('launcher')}>
              查看启动器日志
            </button>
            <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">
              查看检查计划
            </button>
          </div>
        )}
        {primaryPath.code === 'select_task' && (
          <div className="console-primary-blocker-card__task-path" aria-label="任务准备路径">
            <span><b>1 创建或选择任务</b><small>只处理单商品只保存任务；批量和发布入口保持关闭。</small></span>
            <span><b>2 确认店铺和商品</b><small>至少有真实店铺和 1 个商品，编辑页配置才知道本次取值。</small></span>
            <span><b>3 回到配置和检查</b><small>任务选中后再补配置、运行真实只读检查、人工确认保存。</small></span>
          </div>
        )}
        {showLoginRecovery && (
          <div className="console-primary-blocker-card__login-recovery" aria-label="登录恢复路径">
            <strong>{loginState.label}</strong>
            <small>{loginState.next}</small>
            <span><b>1 保持真实浏览器</b><small>真实店小秘窗口不要关闭，先看验证码、账号或密码提示。</small></span>
            <span><b>2 修正验证码或账号密码</b><small>登录未通过时先在可见浏览器里处理，再回控制台检测。</small></span>
            <span><b>3 检测登录状态</b><small>完成验证码后点击检测；仍失败再重新打开登录页。</small></span>
            <button className="button button--quiet" type="button" onClick={onContinueDxmLogin}>
              验证码完成后检测登录状态
            </button>
            <button className="button button--quiet" type="button" onClick={onOpenDxmLogin}>
              重新打开登录页
            </button>
          </div>
        )}
      </details>
    </div>
  )
}

function AgentLoginPanel({
  dxmLoginDraft,
  dxmCredentialState,
  runtimeStatus,
  runtimeStatusError,
  busy,
  onDxmLoginDraftChange,
  onClearSavedDxmCredential,
  onOpenDxmLogin,
  onContinueDxmLogin,
}: {
  dxmLoginDraft: DxmLoginDraft
  dxmCredentialState: DxmCredentialState
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  busy: boolean
  onDxmLoginDraftChange: (draft: DxmLoginDraft) => void
  onClearSavedDxmCredential: () => void
  onOpenDxmLogin: () => void
  onContinueDxmLogin: () => void
}) {
  return (
    <div className="agent-login-panel" aria-label="登录真实店小秘首步操作">
      <div className="agent-login-panel__copy">
        <strong>1 登录真实店小秘</strong>
        <span>先打开可见浏览器完成人工登录和验证码；这里只做登录，不保存、不发布。</span>
      </div>
      <DxmLoginInlineForm
        draft={dxmLoginDraft}
        credentialState={dxmCredentialState}
        runtimeStatus={runtimeStatus}
        runtimeStatusError={runtimeStatusError}
        busy={busy}
        onDraftChange={onDxmLoginDraftChange}
        onClearSavedCredential={onClearSavedDxmCredential}
        onSubmit={onOpenDxmLogin}
        onContinue={onContinueDxmLogin}
        compact
      />
    </div>
  )
}

function AgentBrowserFrame({
  workspace,
  selectedTask,
  activeStep,
  browserFrame,
  agentConsole,
}: {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  activeStep?: { title: string; code?: string; detail: string; state: string }
  browserFrame: { url: string; evidencePath: string; source: string }
  agentConsole: AgentConsoleSession | null
}) {
  const nextStep = nextPendingStep(workspace.deliverySteps, activeStep?.code)
  const hasConsoleHud = Boolean(agentConsole?.active || agentConsole?.updated_at)
  const hud = agentConsole?.hud
  const storeName = (hasConsoleHud ? hud?.store_name : null) ?? selectedTask?.payload.store_name ?? workspace.stores[0]?.name ?? '等待真实店铺'
  const hudTitle = (hasConsoleHud ? hud?.title ?? hud?.label : null) ?? activeStep?.title ?? '等待任务'
  const hudState = humanConsoleCodeLabel((hasConsoleHud ? hud?.state ?? hud?.code : null) ?? activeStep?.code ?? 'WAITING')
  const hudAction = humanConsoleText((hasConsoleHud ? hud?.action ?? hud?.detail : null) ?? activeStep?.detail ?? '等待后端推送步骤')
  const hudNext = humanConsoleText((hasConsoleHud ? hud?.next_step : null) ?? nextStep?.label ?? '等待状态机推进')
  const hudGuard = (hasConsoleHud ? hud?.guard : null) ?? (workspace.publishGuardState?.safe ? '通过' : '等待证明')
  const hudDotState = agentConsole?.last_error ? 'blocked' : agentConsole?.active ? 'current' : activeStep?.state ?? 'pending'
  const recentNetworkEvents = getRecentNetworkEvents(agentConsole)
  const browserLaunching = Boolean(agentConsole?.browser_launching)
  const canControl = Boolean(agentConsole?.active && agentConsole?.browser_visible && !agentConsole?.manual_takeover)
  const browserLaunchFailure = Boolean(agentConsole?.last_error && !browserLaunching && !agentConsole?.browser_visible)

  return (
    <div className="agent-browser agent-browser-shell is-diagnostic">
      <div className="agent-browser__chrome">
        <div className="traffic-lights" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="browser-tab">店小秘自动浏览器</div>
        <div className="browser-url">{browserFrame.url}</div>
        <span className={`status-pill ${agentConsole?.browser_visible ? 'ok' : browserLaunching ? 'warn' : 'muted'}`}>
          {agentConsole?.browser_visible ? '可见浏览器' : browserLaunching ? '正在启动' : '独立浏览器待命'}
        </span>
      </div>
      <div className="agent-browser__viewport">
        <div className="browser-live-surface">
          <div>
            <strong>{agentConsole?.active || agentConsole?.updated_at ? '店小秘真实浏览器正在执行' : '尚未打开店小秘真实浏览器'}</strong>
            <span>
              {agentConsole?.active || agentConsole?.updated_at
                ? browserLaunching
                  ? '正在启动独立真实浏览器；状态会自动刷新，期间不会触发保存或发布。'
                  : canControl
                  ? '可通过下方控制面板滚动或导航当前独立浏览器窗口。'
                  : '浏览器状态已连接；人工接管或窗口未显示时，控制面板会保持只读/禁用。'
                : '点击上方按钮后，会使用独立 Profile 打开真实 dianxiaomi.com。'}
            </span>
            <small>独立浏览器窗口才是真实操作现场；这里仅显示状态和下一步，不在网页内发布。</small>
          </div>
          <dl>
            <div>
              <dt>当前页面</dt>
              <dd>{browserFrame.url}</dd>
            </div>
            <div>
              <dt>控制状态</dt>
              <dd>{canControl ? 'Agent 可控' : agentConsole?.manual_takeover ? '人工接管中' : browserLaunching ? '浏览器启动中' : '等待可见窗口'}</dd>
            </div>
            <div>
              <dt>下一步</dt>
              <dd>{agentConsole?.active ? hudNext : '启动真实浏览器后在独立窗口操作店小秘'}</dd>
            </div>
          </dl>
          <small className="browser-live-surface__control-note">
            页面内操控仅控制当前独立浏览器窗口：支持受限导航和滚动；填写、点击和保存动作必须来自任务流或人工接管。
          </small>
          {browserLaunchFailure && (
            <div className="browser-launch-diagnostic" role="alert" aria-label="真实浏览器启动失败诊断">
              <strong>真实浏览器启动失败</strong>
              <span>{agentConsole?.last_error}</span>
              <small>处理：关闭旧的 DXM Agent Console 或旧浏览器进程后重试；浏览器 Profile：{agentConsole?.profile_dir || '等待后端返回 Profile 目录'}。</small>
            </div>
          )}
        </div>

        <div className="agent-hud" aria-label="浏览器内执行步骤框">
          <div className="agent-hud__head">
            <span className={`hud-dot ${hudDotState}`} />
            <strong>{hudTitle}</strong>
          </div>
          <dl>
            <div>
              <dt>店铺</dt>
              <dd>{storeName}</dd>
            </div>
            <div>
              <dt>当前状态</dt>
              <dd>{hudState}</dd>
            </div>
            <div>
              <dt>正在执行</dt>
              <dd>{hudAction}</dd>
            </div>
            <div>
              <dt>下一步</dt>
              <dd>{hudNext}</dd>
            </div>
          </dl>
          <div className="agent-hud__guard">
            <span>发布隔离</span>
            <strong>{hudGuard}</strong>
          </div>
        </div>
      </div>
      <details className="agent-browser__details inline-disclosure">
        <summary>技术证据路径与网络响应</summary>
        <div className="agent-browser__footer">
          <div className="agent-browser__source">
            <span>{browserFrame.source}</span>
            <div className="agent-network-events" aria-label="网络响应">
              <strong>网络响应</strong>
              {recentNetworkEvents.length > 0 ? (
                recentNetworkEvents.map((event, index) => (
                  <span key={`${event.timestamp ?? event.url ?? 'network'}-${index}`}>
                    <b>{event.status ?? event.type ?? 'event'}</b>
                    <em>{event.method ?? '-'}</em>
                    <code>{shortUrl(event.url)}</code>
                  </span>
                ))
              ) : (
                <span>
                  <b>待命</b>
                  <em>-</em>
                  <code>等待网络响应</code>
                </span>
              )}
            </div>
          </div>
          <span>{agentConsole?.profile_dir ? `浏览器数据目录: ${agentConsole.profile_dir}` : '等待启动独立浏览器'}</span>
        </div>
      </details>
    </div>
  )
}

function AgentConsoleControls({
  agentConsole,
  agentConsoleError,
  runtimeStatus,
  runtimeStatusError,
  selectedTask,
  busy,
  realSaveBlocked,
  realSaveBlockReason,
  primaryPath,
  browserStartBlocked,
  browserStartBlockReason,
  onStartAgentConsole,
  onNavigateDxmTarget,
  onStopAgentConsole,
  onSnapshotAgentConsole,
  onRequestAgentConsoleTakeover,
  onReleaseAgentConsoleTakeover,
  onControlAgentConsoleBrowser,
  onRuntimeControl,
}: {
  agentConsole: AgentConsoleSession | null
  agentConsoleError: string | null
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  selectedTask: Task | null
  busy: boolean
  realSaveBlocked: boolean
  realSaveBlockReason: string
  primaryPath: ConsolePrimaryPath
  browserStartBlocked: boolean
  browserStartBlockReason: string
  onStartAgentConsole: () => void
  onNavigateDxmTarget: (target: 'data_acquisition' | 'draft_box') => void
  onStopAgentConsole: () => void
  onSnapshotAgentConsole: () => void
  onRequestAgentConsoleTakeover: () => void
  onReleaseAgentConsoleTakeover: () => void
  onControlAgentConsoleBrowser: (command: AgentConsoleControlCommand) => void
  onRuntimeControl: (action: RuntimeControlAction) => void
}) {
  const active = Boolean(agentConsole?.active)
  const manualTakeover = Boolean(agentConsole?.manual_takeover)
  const screenshot = agentConsole?.screenshot_url ?? agentConsole?.screenshot ?? ''
  const launching = Boolean(agentConsole?.browser_launching)
  const visible = Boolean(agentConsole?.browser_visible)
  const takeoverStateLabel = !active
    ? '启动后可接管'
    : manualTakeover
      ? '用户正在真实浏览器中接管'
      : launching
        ? '浏览器启动中'
      : visible
        ? 'Agent 可接管'
        : '等待窗口可见'
  const lifecycleStatus = !active
    ? browserStartBlocked
      ? primaryPath.browserStatus
      : '执行浏览器待启动'
    : manualTakeover
      ? '人工正在接管执行浏览器'
      : launching
        ? '正在启动执行浏览器'
      : visible
        ? '执行浏览器已启动，可控'
        : '浏览器会话已创建，等待窗口可见'
  const lifecycleNext = !active
    ? browserStartBlocked
      ? primaryPath.next
      : '点击打开执行浏览器（不保存），进入独立 Profile 浏览器。'
    : manualTakeover
      ? '完成人工处理后点击交还 Agent。'
      : launching
        ? '正在打开独立 Profile 浏览器；控制台会自动刷新状态。'
      : visible
        ? '可刷新画面、人工接管，或使用高级浏览器控制。'
        : '等待窗口显示；如长时间无响应，可关闭后重试。'
  const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)
  const l2ProbeDisabled = busy || l2ProbeResourceState.blocked
  const sessionDisabledReason = busy
    ? '正在处理当前操作，请等待完成后再操作执行浏览器。'
    : !active
      ? '先打开执行浏览器，才能刷新、接管、交还或关闭。'
      : manualTakeover
        ? '当前已人工接管，处理完成后点击交还 Agent。'
        : ''
  const snapshotDisabledReason = busy
    ? '正在处理当前操作，请等待完成后再刷新当前画面。'
    : !active
      ? '先打开执行浏览器，才能刷新当前画面。'
      : ''
  const takeoverDisabledReason = busy
    ? '正在处理当前操作，请等待完成后再人工接管。'
    : !active
      ? '先打开执行浏览器，才能人工接管真实浏览器。'
      : manualTakeover
        ? '当前已人工接管，处理完成后点击交还 Agent。'
        : ''
  const releaseDisabledReason = busy
    ? '正在处理当前操作，请等待完成后再交还 Agent。'
    : !active
      ? '先打开执行浏览器，才需要交还 Agent。'
      : !manualTakeover
        ? '当前未处于人工接管状态，无需交还 Agent。'
        : ''
  const stopDisabledReason = busy
    ? '正在处理当前操作，请等待完成后再关闭浏览器。'
    : !active
      ? '执行浏览器尚未打开，无需关闭。'
      : ''
  return (
    <div className="agent-console-controls">
      <div className="agent-console-controls__status">
        <span className={`status-pill ${active ? 'ok' : 'muted'}`}>{active ? '浏览器会话中' : '未打开浏览器'}</span>
        <span className={`status-pill ${visible ? 'ok' : launching ? 'warn' : active ? 'warn' : 'muted'}`}>
          {visible ? '窗口可见' : launching ? '正在启动' : '窗口未显示'}
        </span>
        <span className={`status-pill ${manualTakeover ? 'warn' : 'muted'}`}>
          {takeoverStateLabel}
        </span>
        <span className="status-pill warn">不会发布</span>
      </div>
      <div className={`agent-console-lifecycle ${browserStartBlocked && !active ? 'is-blocked' : active ? 'is-active' : ''}`} aria-label="执行浏览器会话生命周期">
        <strong>{lifecycleStatus}</strong>
        <span>{lifecycleNext}</span>
        {browserStartBlocked && !active && <small>{browserStartBlockReason}</small>}
        {!browserStartBlocked && realSaveBlocked && !active && <small>{realSaveBlockReason}</small>}
        {sessionDisabledReason && <small className="agent-console-controls__session-reason" aria-label="执行浏览器会话按钮不可用原因">会话按钮不可用原因：{sessionDisabledReason}</small>}
        {primaryPath.code === 'l2' && !active && (
          <div className="agent-console-lifecycle__actions">
            <button className="button button--secondary" type="button" disabled={l2ProbeDisabled} title={l2ProbeResourceState.title} onClick={() => onRuntimeControl('run_l2_readonly_probe')}>
              {READONLY_PRECHECK_CTA}
            </button>
            {l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}
            <L2ProbeResourceRepairPanel l2ProbeResourceState={l2ProbeResourceState} />
          </div>
        )}
      </div>
      {l2ProbeResourceState.blocked && (
        <div className="agent-console-resource-alert" role="alert" aria-label="真实只读检查资源缺失">
          <strong>真实只读检查暂不可运行</strong>
          <span>{l2ProbeResourceState.detail}</span>
          <small>处理：关闭当前旧窗口或后台旧进程，重新打开桌面上的 DXM-Agent-Console-免安装版\\DXM-Agent-Console.exe；完整目录必须保留 resources 文件夹。</small>
          <L2ProbeResourceRepairPanel l2ProbeResourceState={l2ProbeResourceState} />
        </div>
      )}
      <div className="agent-console-controls__actions">
        {primaryPath.code !== 'l2' && (
          <button
            className="button button--secondary"
            type="button"
            disabled={l2ProbeDisabled}
            title={l2ProbeResourceState.title}
            onClick={() => onRuntimeControl('run_l2_readonly_probe')}
          >
            {READONLY_PRECHECK_CTA}
          </button>
        )}
        <button
          className="button button--quiet"
          type="button"
          onClick={() => onNavigateDxmTarget('draft_box')}
          disabled={busy}
          title="登录成功后进入真实店小秘采集箱；该动作只导航，不保存、不发布。"
        >
          进入采集箱
        </button>
        <button
          className="button button--quiet"
          type="button"
          onClick={onStartAgentConsole}
          disabled={busy || !selectedTask || browserStartBlocked || active || launching}
          title={active ? '当前执行浏览器会话正在运行。' : browserStartBlocked ? browserStartBlockReason : realSaveBlocked ? realSaveBlockReason : '打开执行浏览器（不保存）；保存前仍需人工确认'}
        >
          {launching
            ? '执行浏览器启动中'
            : active
              ? '执行浏览器已打开'
              : primaryPath.code === 'l3'
                ? '人工确认后打开执行浏览器'
            : '打开执行浏览器（不保存）'}
        </button>
      </div>
      <details className="agent-console-controls__mission-drawer inline-disclosure">
        <summary>模式说明与安全边界</summary>
        <div className="agent-console-controls__mission">
          <strong>控制台 Agent 模式</strong>
          <span>登录浏览器用于人工登录和验证码。执行浏览器在配置、真实只读检查和人工确认通过后由 Agent 操作。控制台操控独立真实浏览器；截图仅用于报告证据。</span>
          <div>
            <b>1 登录/接入</b>
            <b>2 只读定位</b>
            <b>3 人工放行后只保存</b>
          </div>
        </div>
      </details>
      <details className="agent-console-controls__advanced agent-console-controls__operator-drawer inline-disclosure">
        <summary>执行浏览器操作细节</summary>
        <div className="agent-console-controls__operator-grid">
          <details className="agent-console-controls__advanced inline-disclosure">
            <summary>执行浏览器会话生命周期</summary>
            <div className="agent-console-controls__session">
              <button className="button button--quiet" type="button" onClick={onSnapshotAgentConsole} disabled={busy || !active} title={snapshotDisabledReason || undefined}>
                刷新当前画面
              </button>
              <button className="button button--quiet" type="button" onClick={onRequestAgentConsoleTakeover} disabled={busy || !active || manualTakeover} title={takeoverDisabledReason || undefined}>
                人工接管真实浏览器
              </button>
              <button className="button button--quiet" type="button" onClick={onReleaseAgentConsoleTakeover} disabled={busy || !active || !manualTakeover} title={releaseDisabledReason || undefined}>
                交还 Agent
              </button>
              <button className="button button--secondary" type="button" onClick={onStopAgentConsole} disabled={busy || !active} title={stopDisabledReason || undefined}>
                关闭浏览器
              </button>
              {sessionDisabledReason && <small className="agent-console-controls__session-reason" aria-label="会话按钮不可用原因">会话按钮不可用原因：{sessionDisabledReason}</small>}
              <small>启动、接管、交还和关闭的对象都是独立真实浏览器窗口；控制台只控制真实浏览器，不会启动保存或发布。</small>
            </div>
          </details>
          <details className="agent-console-controls__advanced inline-disclosure">
            <summary>高级浏览器控制</summary>
            <BrowserControlPad
              agentConsole={agentConsole}
              busy={busy}
              onControlAgentConsoleBrowser={onControlAgentConsoleBrowser}
            />
          </details>
          <details className="agent-console-controls__fields inline-disclosure">
            <summary>技术详情</summary>
            <div className="agent-console-controls__field-grid">
              <StatusField label="session_id" value={agentConsole?.session_id} />
              <StatusField label="last_step" value={agentConsole?.last_step_code ?? agentConsole?.hud?.state} />
              <StatusField label="profile_dir" value={agentConsole?.profile_dir} />
              <StatusField label="current_url" value={agentConsole?.current_url ?? agentConsole?.target_url} />
              <StatusField label="screenshot" value={screenshot} />
            </div>
          </details>
        </div>
      </details>
      {agentConsoleError && <div className="agent-console-controls__error console-error">{agentConsoleError}</div>}
    </div>
  )
}

function BrowserControlPad({
  agentConsole,
  busy,
  onControlAgentConsoleBrowser,
}: {
  agentConsole: AgentConsoleSession | null
  busy: boolean
  onControlAgentConsoleBrowser: (command: AgentConsoleControlCommand) => void
}) {
  const [url, setUrl] = useState(agentConsole?.current_url ?? agentConsole?.target_url ?? 'https://www.dianxiaomi.com/')
  const active = Boolean(agentConsole?.active && agentConsole?.browser_visible)
  const disabled = busy || !active || Boolean(agentConsole?.manual_takeover)
  const disabledReason = agentConsole?.manual_takeover
    ? '人工接管中，先交还 Agent。'
    : active
      ? '仅控制当前独立浏览器窗口。'
      : '启动真实浏览器后才能页面内操控。'

  useEffect(() => {
    const nextUrl = agentConsole?.current_url ?? agentConsole?.target_url
    if (nextUrl) setUrl(nextUrl)
  }, [agentConsole?.current_url, agentConsole?.target_url])

  return (
    <div className="browser-control-pad" aria-label="页面内操控">
      <div className="browser-control-pad__head">
        <strong>页面内操控</strong>
        <span>{disabledReason}</span>
      </div>
      <small>仅开放受限导航和滚动；填写、点击和保存必须走任务流或人工接管。</small>
      <div className="browser-control-pad__row browser-control-pad__row--wide">
        <label className="browser-control-pad__selector-field">
          <span>目标 URL</span>
          <input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://www.dianxiaomi.com/"
            aria-label="导航 URL"
            disabled={busy}
          />
        </label>
        <button
          className="button button--quiet"
          type="button"
          disabled={disabled || !url.trim()}
          onClick={() => onControlAgentConsoleBrowser({ action: 'goto', url: url.trim() })}
        >
          导航
        </button>
      </div>
      <div className="browser-control-pad__row">
        <button className="button button--quiet" type="button" disabled={disabled} onClick={() => onControlAgentConsoleBrowser({ action: 'scroll', delta_y: -420 })}>
          向上滚动
        </button>
        <button className="button button--quiet" type="button" disabled={disabled} onClick={() => onControlAgentConsoleBrowser({ action: 'scroll', delta_y: 420 })}>
          滚动页面
        </button>
      </div>
      <div className="browser-control-pad__row browser-control-pad__row--wide">
        <span>页面点击、选择器填写、焦点输入和按键已关闭；需要直接操作时请在真实浏览器窗口中人工接管。</span>
      </div>
    </div>
  )
}

function StatusField({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="agent-console-field">
      <span>{label}</span>
      <code>{value ? String(value) : '暂无'}</code>
    </div>
  )
}

function getRecentNetworkEvents(agentConsole: AgentConsoleSession | null) {
  const networkEvents = agentConsole?.network_events ?? []
  const responseEvents = networkEvents.filter((event) => {
    const type = event.type?.toLowerCase() ?? ''
    return type.includes('response') || typeof event.status === 'number'
  })
  return (responseEvents.length ? responseEvents : networkEvents).slice(-3).reverse()
}

function shortUrl(url?: string) {
  if (!url) return '暂无 URL'
  try {
    const parsed = new URL(url)
    const path = `${parsed.pathname}${parsed.search}`
    return `${parsed.host}${path}`.slice(0, 84)
  } catch {
    return url.slice(0, 84)
  }
}

function L2RunnerStatePanel({
  state,
  l2Gate,
  runtimeStatus,
  busy,
  onRunPrecheck,
  onLogSourceChange,
  onShowReports,
}: {
  state: L2RunnerState
  l2Gate?: RegressionGate
  runtimeStatus: RuntimeStatus | null
  busy: boolean
  onRunPrecheck: () => void
  onLogSourceChange: (source: RuntimeLogSource) => void
  onShowReports: () => void
}) {
  const gateLabel = humanGateStateLabel(l2Gate?.status ?? 'not_run')
  const diagnosticSummaries = summarizeL2Diagnostics(l2Gate)
  const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)
  const tone = state.status === 'passed' ? 'ok' : state.status === 'failed' ? 'danger' : state.status === 'running' ? 'warn' : 'pending'
  const precheckDisabled = busy || state.status === 'running' || l2ProbeResourceState.blocked
  const title = state.status === 'passed'
      ? '真实只读检查通过，已刷新门禁'
    : state.status === 'failed'
      ? '真实只读检查失败，真实保存仍阻断'
      : state.status === 'running'
        ? '正在运行双目标真实只读检查'
        : '等待运行真实只读检查'
  const stateLine = state.line ? humanL2PrecheckError(state.line) : null

  return (
    <div className={`module-card span-1 l2-runner-state l2-runner-state--${state.status}`} aria-live="polite">
      <ModuleHead title="保存前安全检查" meta={`状态：${gateLabel}`} />
      <div className="l2-runner-state__body">
        <span className={`status-pill ${tone}`}>{state.status === 'idle' ? '待运行' : state.status === 'running' ? '运行中' : state.status === 'passed' ? '通过' : '失败'}</span>
        <strong>{title}</strong>
        <small>{state.status === 'passed'
          ? '可以继续人工确认只保存。'
          : state.status === 'failed'
            ? '请确认已登录并能打开商品采集页、草稿箱页后重试。'
            : state.status === 'running'
              ? '请等待检查完成，完成后自动刷新。'
              : '点击下方按钮开始检查。'}</small>
        {(state.runId || state.exitCode !== null || stateLine) && (
          <details className="inline-disclosure">
            <summary>排障日志</summary>
            {state.runId && <small>run-id：{state.runId}</small>}
            {state.exitCode !== null && <small>退出码：{state.exitCode}</small>}
            {stateLine && <code>{stateLine}</code>}
          </details>
        )}
      </div>
      <div className="l2-runner-state__primary-action" aria-label="运行真实只读检查主操作">
        <button
          className="button"
          type="button"
          disabled={precheckDisabled}
          title={l2ProbeResourceState.title}
          onClick={() => {
            onLogSourceChange('launcher')
            onRunPrecheck()
          }}
        >
          {state.status === 'running' ? '安全检查运行中' : READONLY_PRECHECK_CTA}
        </button>
        {l2ProbeResourceState.blocked && <small>{l2ProbeResourceState.detail}</small>}
      </div>
      <L2PrecheckFailureAdvice summaries={diagnosticSummaries} state={state} gateStatus={l2Gate?.status} />
      <L2PrecheckRunbook
        state={state}
        onLogSourceChange={onLogSourceChange}
        onShowReports={onShowReports}
      />
    </div>
  )
}

function L2PrecheckFailureAdvice({
  summaries,
  state,
  gateStatus,
}: {
  summaries: L2DiagnosticSummary[]
  state: L2RunnerState
  gateStatus?: RegressionGate['status']
}) {
  if (state.status !== 'failed' && gateStatus !== 'blocked') return null
  const visibleSummaries = summaries.slice(0, 2)

  return (
    <div className="l2-precheck-failure-advice" aria-label="真实只读检查失败处理建议">
      <strong>真实只读检查失败处理建议</strong>
      {visibleSummaries.length ? (
        visibleSummaries.map((item) => (
          <article key={item.target}>
            <span><b>失败页面</b><small>{item.targetLabel} / {humanDiagnosticNavigation(item.navigation)}</small></span>
            <span><b>失败检查</b><small>{item.failedChecks.slice(0, 2).map(humanFailedCheckLabel).join(' / ') || '页面检查未满足'}</small></span>
            <span><b>下一步处理</b><small>{item.nextAction}</small></span>
          </article>
        ))
      ) : (
        <article>
          <span><b>失败页面</b><small>等待诊断明细</small></span>
          <span><b>失败检查</b><small>未收到页面诊断，请先查看启动器日志。</small></span>
          <span><b>下一步处理</b><small>确认真实浏览器已登录并能打开目标页，再重新运行真实只读检查。</small></span>
        </article>
      )}
    </div>
  )
}

function L2PrecheckRunbook({
  state,
  onLogSourceChange,
  onShowReports,
}: {
  state: L2RunnerState
  onLogSourceChange: (source: RuntimeLogSource) => void
  onShowReports: () => void
}) {
  const nextAction = state.status === 'passed'
    ? '真实只读检查通过后，继续人工确认单商品只保存。'
    : state.status === 'running'
      ? '真实只读检查运行中，请查看启动器日志等待完成结果。'
      : state.status === 'failed'
        ? '真实只读检查失败后怎么办：查看启动器日志和检查计划，先处理登录、页面打不开或写请求风险，再重新运行。'
        : `点击“${READONLY_PRECHECK_CTA}”后，系统只检查页面可达和写入风险。`

  return (
    <details className="l2-precheck-runbook inline-disclosure" aria-label="真实只读检查操作引导">
      <summary>安全检查说明</summary>
      <div className="l2-precheck-runbook__steps">
        <span><b>1 打开真实店小秘页面</b><small>确认已登录，能访问商品采集页。</small></span>
        <span><b>2 检查两个页面</b><small>商品采集页 + 采集箱/草稿箱；不会领取、不会保存、不会发布。</small></span>
        <span><b>3 通过后人工确认保存</b><small>只读通过不等于保存，仍需人工确认单商品只保存。</small></span>
      </div>
      <small>{nextAction}</small>
      <div className="l2-precheck-runbook__actions">
        <button className="button button--quiet" type="button" onClick={() => onLogSourceChange('launcher')}>
          查看排障日志
        </button>
        <button className="button button--quiet" type="button" onClick={onShowReports} data-section="reports">
          查看检查计划
        </button>
      </div>
    </details>
  )
}

function ServiceRecoveryPanel({
  runtimeStatusError,
  desktopRuntime,
  onRuntimeLogSourceChange,
}: {
  runtimeStatusError: string
  desktopRuntime: DesktopRuntimeInfo | null
  onRuntimeLogSourceChange: (source: RuntimeLogSource) => void
}) {
  const desktopLogPath = desktopRuntime?.desktopLogPath ?? '免安装版启动后显示 desktop-main.log 路径'
  const backendLogPath = desktopRuntime?.backendLogPath ?? '免安装版启动后显示 backend.log 路径'

  return (
    <section className="service-recovery-panel span-3" aria-label="工作台服务恢复">
      <div className="service-recovery-panel__main">
        <span className="status-dot status-dot--danger" aria-hidden="true" />
        <div>
          <strong>工作台服务连接异常</strong>
          <small>不是店小秘账号、配置或页面问题；先恢复本机后端，再重新运行真实只读检查和真实浏览器流程。</small>
        </div>
      </div>
      <div className="service-recovery-panel__paths">
        <span><b>桌面日志</b><code>{desktopLogPath}</code></span>
        <span><b>后端日志</b><code>{backendLogPath}</code></span>
      </div>
      <div className="service-recovery-panel__actions">
        <small>{runtimeStatusError}</small>
        <button type="button" className="secondary-button" onClick={() => onRuntimeLogSourceChange('launcher')}>
          查看启动器日志
        </button>
      </div>
    </section>
  )
}

function RuntimeLogPreview({
  logs,
  source,
  error,
  onSourceChange,
}: {
  logs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  source: RuntimeLogSource
  error: string | null
  onSourceChange: (source: RuntimeLogSource) => void
}) {
  const current = logs[source]
  const items = normalizeRuntimeLogItems(current)
  const visibleItems = businessRuntimeLogItems(items).slice(-5)
  const labels = runtimeLogSourceLabels()
  const refreshMeta = runtimeLogRefreshMeta(current, items.length)

  return (
    <div className="runtime-log-preview" aria-live="polite">
      <div className="runtime-log-preview__head">
        <strong>最近日志</strong>
        <span className={`runtime-log-refresh runtime-log-refresh--${refreshMeta.tone}`}>
          {refreshMeta.status}
        </span>
      </div>
      <div className="runtime-log-tabs runtime-log-tabs--compact" role="tablist" aria-label="运行日志来源">
        {(Object.keys(labels) as RuntimeLogSource[]).map((item) => (
          <button
            key={item}
            type="button"
            className={item === source ? 'is-active' : ''}
            onClick={() => onSourceChange(item)}
          >
            {labels[item]}
          </button>
        ))}
      </div>
      <div className={`runtime-log-refresh runtime-log-refresh--${refreshMeta.tone}`}>
        <small>{refreshMeta.detail}</small>
      </div>
      {error && <div className="console-error">{error}</div>}
      <div className="runtime-log-preview__body">
        {visibleItems.length ? (
          visibleItems.map((item, index) => (
            <RuntimeLogSummaryLine key={`${source}-preview-${index}`} item={item} compact />
          ))
        ) : (
          <span>{current?.exists === false ? '日志文件尚未生成。' : '暂无关键业务日志，完整日志在维护诊断中查看。'}</span>
        )}
      </div>
      <small>正在实时刷新；切换来源只影响当前预览。</small>
    </div>
  )
}

function RuntimeLogPanel({
  logs,
  source,
  error,
  level,
  query,
  onSourceChange,
  onLevelChange,
  onQueryChange,
}: {
  logs: Record<RuntimeLogSource, RuntimeLogResponse | null>
  source: RuntimeLogSource
  error: string | null
  level: 'all' | 'info' | 'warning' | 'error'
  query: string
  onSourceChange: (source: RuntimeLogSource) => void
  onLevelChange: (level: 'all' | 'info' | 'warning' | 'error') => void
  onQueryChange: (query: string) => void
}) {
  const current = logs[source]
  const logViewRef = useRef<HTMLDivElement | null>(null)
  const [autoFollow, setAutoFollow] = useState(true)
  const labels = runtimeLogSourceLabels()

  const items = normalizeRuntimeLogItems(current)
  const filteredRuntimeLogItems = filterRuntimeLogItems(items, level, query)
  const visibleRuntimeLogItems = businessRuntimeLogItems(filteredRuntimeLogItems).slice(-6)
  const refreshMeta = runtimeLogRefreshMeta(current, items.length)

  useEffect(() => {
    if (!autoFollow || !logViewRef.current) return
    logViewRef.current.scrollTop = logViewRef.current.scrollHeight
  }, [autoFollow, items.length, source])

  function handleLogScroll() {
    const node = logViewRef.current
    if (!node || !autoFollow) return
    const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight
    if (distanceToBottom > 48) setAutoFollow(false)
  }

  function resumeAutoFollow() {
    setAutoFollow(true)
    window.requestAnimationFrame(() => {
      if (logViewRef.current) logViewRef.current.scrollTop = logViewRef.current.scrollHeight
    })
  }

  return (
    <div className="runtime-log-panel">
      <div className="runtime-log-toolbar">
        <strong>完整日志与维护诊断</strong>
        <span>后端、前端、启动器、任务和浏览器 Agent 日志会自动增量刷新。</span>
        <span className={`runtime-log-toolbar__refresh runtime-log-toolbar__refresh--${refreshMeta.tone}`}>
          {refreshMeta.status} · {refreshMeta.detail}
        </span>
        <label>
          <input
            type="checkbox"
            checked={autoFollow}
            onChange={(event) => {
              if (event.target.checked) {
                resumeAutoFollow()
              } else {
                setAutoFollow(false)
              }
            }}
          />
          自动跟随最新日志
        </label>
      </div>
      <div className="runtime-log-tabs" role="tablist" aria-label="运行日志来源">
        {(Object.keys(labels) as RuntimeLogSource[]).map((item) => (
          <button
            key={item}
            type="button"
            className={item === source ? 'is-active' : ''}
            onClick={() => onSourceChange(item)}
          >
            {labels[item]}
          </button>
        ))}
      </div>
      <div className="runtime-log-filters">
        <label>
          <span>级别</span>
          <select value={level} onChange={(event) => onLevelChange(event.target.value as 'all' | 'info' | 'warning' | 'error')}>
            <option value="all">全部</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>
        </label>
        <label>
          <span>搜索</span>
          <input value={query} placeholder="保存 / error / add.json" onChange={(event) => onQueryChange(event.target.value)} />
        </label>
      </div>
      {error && <div className="console-error">{error}</div>}
      <div ref={logViewRef} className="runtime-log-view" aria-live="polite" data-testid="runtime-log-view" onScroll={handleLogScroll}>
        {visibleRuntimeLogItems.length
          ? visibleRuntimeLogItems.map((item, index) => <RuntimeLogSummaryLine key={`${source}-${index}`} item={item} />)
          : <span>{current?.exists === false ? '日志文件尚未生成，启动服务后会自动出现。' : '暂无关键业务日志，完整原始日志在下方展开。'}</span>}
      </div>
      <small>最近日志：默认只显示关键业务进度；完整原始日志在下方维护诊断区展开查看。</small>
      <details className="inline-disclosure runtime-log-full-drawer">
        <summary>查看完整日志与维护诊断</summary>
        <div className="runtime-log-view runtime-log-view--full">
          {filteredRuntimeLogItems.length
            ? filteredRuntimeLogItems.map((item, index) => <RuntimeLogLine key={`${source}-full-${index}`} item={item} />)
            : <span>暂无完整日志。</span>}
        </div>
      </details>
      <small>维护诊断：日志来源 {labels[source]}，当前筛选后 {filteredRuntimeLogItems.length} 条；原始技术细节只在展开区显示。</small>
    </div>
  )
}

function normalizeRuntimeLogItems(current: RuntimeLogResponse | null | undefined): RuntimeLogItem[] {
  return current?.items ?? current?.lines.map((line) => ({ line, level: 'info', tags: [] })) ?? []
}

function filterRuntimeLogItems(items: RuntimeLogItem[], level: 'all' | 'info' | 'warning' | 'error', query: string) {
  const normalizedQuery = query.trim().toLowerCase()
  return items.filter((item) => {
    const normalizedLevel = String(item.level || 'info').toLowerCase()
    if (level !== 'all' && normalizedLevel !== level) return false
    if (!normalizedQuery) return true
    const haystack = `${item.line} ${item.tags.join(' ')}`.toLowerCase()
    return haystack.includes(normalizedQuery)
  })
}

function businessRuntimeLogItems(items: RuntimeLogItem[]) {
  const selected: RuntimeLogItem[] = []
  const seen = new Set<string>()

  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]
    const summary = humanRuntimeLogLine(item)
    if (!isBusinessRuntimeLogItem(item, summary)) continue
    const key = `${String(item.level || 'info').toLowerCase()}::${summary}`
    if (seen.has(key)) continue
    selected.push(item)
    seen.add(key)
    if (selected.length >= 12) break
  }

  return selected.reverse()
}

function isBusinessRuntimeLogItem(item: RuntimeLogItem, summary: string) {
  const raw = `${item.line} ${item.tags.join(' ')}`.toLowerCase()
  const level = String(item.level || 'info').toLowerCase()
  if (level === 'warning' || level === 'error') return true
  if (summary.includes('诊断证据已记录')) return false
  if (summary.includes('技术路径和接口细节')) return false
  return [
    '执行步骤',
    '店小秘',
    '登录',
    '真实只读检查',
    '采集页',
    '采集箱',
    '认领',
    '编辑页',
    '填写',
    '图片',
    '物流',
    '保存',
    '未发布',
    '浏览器',
    '任务',
    '失败',
    '阻断',
  ].some((keyword) => summary.includes(keyword))
    || [
      'step=',
      'task#',
      'open_data_acquisition',
      'claim_to_draft_box',
      'verify_draft_box_claim',
      'open_edit_page',
      'open_editor',
      'fill_base_info',
      'fill_title',
      'fill_media',
      'fill_images',
      'fill_logistics',
      'save_only',
      'verify_not_published',
      'browser_closed',
      'live_browser',
      'target page',
      'greenlet',
      'cannot switch',
      'failed',
      'error',
    ].some((keyword) => raw.includes(keyword))
}

function runtimeLogRefreshMeta(current: RuntimeLogResponse | null | undefined, itemCount: number) {
  if (!current) {
    return { status: '等待首次刷新', detail: '正在连接日志接口', tone: 'pending' }
  }
  if (current.exists === false) {
    return { status: '日志未生成', detail: '服务启动后会自动出现', tone: 'pending' }
  }
  const refreshedAt = current.fetchedAt ? formatTime(current.fetchedAt) : '刚刚'
  if (current.stale) {
    const writtenAt = current.modifiedAt ? formatTime(current.modifiedAt) : '未知时间'
    const ageText = formatLogAge(current.ageSeconds)
    return { status: '日志源久未写入', detail: `最后写入 ${writtenAt}${ageText ? ` · ${ageText}` : ''} · 界面刷新 ${refreshedAt} · 当前 ${itemCount} 条`, tone: 'warn' }
  }
  return { status: '正在实时刷新', detail: `界面刷新 ${refreshedAt} · 当前 ${itemCount} 条`, tone: 'ok' }
}

function runtimeLogSourceLabels(): Record<RuntimeLogSource, string> {
  return {
    backend: '后端',
    frontend: '前端',
    launcher: '启动器',
    npm: '依赖安装',
    task: '任务',
    agent: '浏览器 Agent',
  }
}

function RuntimeLogSummaryLine({ item, compact = false }: { item: RuntimeLogItem; compact?: boolean }) {
  const hint = technicalRuntimeLogHint(item.line)
  return (
    <div className={`runtime-log-summary-line runtime-log-summary-line--${item.level} ${compact ? 'runtime-log-preview__line' : ''}`}>
      <span>{runtimeLogLevelLabel(item.level)}</span>
      <strong>{humanRuntimeLogLine(item)}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function runtimeLogLevelLabel(level: string) {
  const normalized = String(level || 'info').toLowerCase()
  if (normalized === 'error') return '失败'
  if (normalized === 'warning' || normalized === 'warn') return '注意'
  return '提示'
}

function humanRuntimeLogLine(item: RuntimeLogItem) {
  const line = item.line.trim()
  const normalized = line.toLowerCase()
  const operatorMessage = humanOperatorMessage(line)
  if (operatorMessage !== line) return operatorMessage
  if (normalized.includes('browser_closed') || normalized.includes('browser_window_not_visible') || line.includes('真实浏览器窗口已关闭')) {
    return '真实浏览器窗口已关闭，请重新打开执行浏览器。'
  }
  if (normalized.includes('target page, context or browser has been closed') || normalized.includes('live_browser_page_missing')) {
    return '真实浏览器窗口不可用：请保持执行浏览器打开，再重新启动当前步骤。'
  }
  if (normalized.includes('live_browser_hud_apply_failed')) {
    return '浏览器进度浮窗暂未挂上：请保持真实浏览器打开，系统会继续保护性暂停。'
  }
  if (line.includes('Cannot switch to a different thread') || normalized.includes('greenlet') || line.includes('Playwright Sync API') || line.includes('Playwright')) {
    return '浏览器会话异常：当前浏览器自动化会话已经失效，系统没有继续保存。请关闭当前执行浏览器，重新打开真实浏览器后再运行任务。'
  }
  if (normalized.includes('open_data_acquisition')) {
    return '正在打开店小秘数据采集页。'
  }
  if (normalized.includes('claim_to_draft_box')) {
    return '正在把选中的商品认领到采集箱。'
  }
  if (normalized.includes('verify_draft_box_claim')) {
    return '正在确认商品已经进入采集箱。'
  }
  if (normalized.includes('open_edit_page') || normalized.includes('open_editor')) {
    return '正在打开店小秘商品编辑页。'
  }
  if (normalized.includes('fill_base_info') || normalized.includes('fill_title')) {
    return '正在填写标题、类目和基础信息。'
  }
  if (normalized.includes('fill_media') || normalized.includes('fill_images')) {
    return '正在处理商品图片和素材。'
  }
  if (normalized.includes('fill_logistics')) {
    return '正在填写物流与包裹信息。'
  }
  if (normalized.includes('save_only')) {
    return '正在点击店小秘“保存”，不会发布。'
  }
  if (normalized.includes('verify_not_published')) {
    return '正在确认商品保存后没有发布。'
  }
  if (normalized.includes('release_lock')) {
    return '本次任务已结束，正在释放任务占用。'
  }
  if (normalized.includes('internal server error') || normalized.includes('traceback')) {
    return '系统执行失败：请确认本机服务和真实浏览器正常后重试。'
  }
  if (normalized.includes('login_success') || normalized.includes('dxm login') || line.includes('登录成功')) {
    return '店小秘登录状态已确认。'
  }
  if (normalized.includes('[l2-readonly-runner] finished') || normalized.includes('readonly') && normalized.includes('exit_code=0')) {
    return '真实只读检查已完成。'
  }
  if (normalized.includes('target=draft_box') || normalized.includes('draft_box')) {
    return '正在检查店小秘采集箱页。'
  }
  if (normalized.includes('target=data_acquisition') || normalized.includes('data_acquisition')) {
    return '正在检查店小秘商品采集页。'
  }
  if (normalized.includes('add.json') || line.includes('保存成功') || line.includes('编辑成功')) {
    return '店小秘保存接口返回成功。'
  }
  if (normalized.includes('json_path') || normalized.includes('markdown_path') || normalized.includes('screenshot') || normalized.includes('dom_sha256')) {
    return '诊断证据已记录。'
  }
  if (normalized.includes('failed') || normalized.includes('error') || item.level === 'error') {
    return '当前步骤失败，请展开完整原始日志查看细节。'
  }
  return stripRuntimeLogPrefix(line)
}

function technicalRuntimeLogHint(line: string) {
  const normalized = line.toLowerCase()
  if (line.includes('Cannot switch to a different thread') || normalized.includes('greenlet') || line.includes('Playwright Sync API') || line.includes('Playwright')) {
    return '原始浏览器线程细节已收进完整原始日志。'
  }
  if (normalized.includes('c:\\') || normalized.includes('d:\\') || normalized.includes('/api/') || normalized.includes('.py')) {
    return '技术路径和接口细节已收进完整原始日志。'
  }
  if (normalized.includes('json_path') || normalized.includes('markdown_path') || normalized.includes('dom_sha256')) {
    return '证据文件路径可在完整原始日志中查看。'
  }
  return null
}

function stripRuntimeLogPrefix(line: string) {
  return line
    .replace(/^\[[^\]]+\]\s*/, '')
    .replace(/^(INFO|WARNING|ERROR)\s+(INFO|WARNING|ERROR)\s+/i, '$2 ')
    .replace(/^(INFO|WARNING|ERROR)\s+task#\d+(?:\s+job#\d+)?:\s*/i, '')
    .replace(/^(INFO|WARNING|ERROR)\s+/i, '')
    .replace(/^\d{8,}[\w-]*\s+/, '')
    .slice(0, 180)
}

function RuntimeLogLine({ item }: { item: RuntimeLogItem }) {
  return (
    <div className={`runtime-log-line runtime-log-line--${item.level}`}>
      <span>{item.level.toUpperCase()}</span>
      <code>{item.line}</code>
      {item.tags.length > 0 && (
        <small>{item.tags.slice(0, 3).map((tag) => <b key={tag}>{tag}</b>)}</small>
      )}
    </div>
  )
}

export function EvidenceTimeline({
  workspace,
  selectedTask,
  onShowTasks,
  onShowConsole,
}: CommonProps & { onShowTasks: () => void; onShowConsole: () => void }) {
  const evidences = selectedTask ? workspace.evidences.filter((item) => item.task_id === selectedTask.id) : workspace.evidences
  const reports = selectedTask ? workspace.reports.filter((item) => item.task_id === selectedTask.id) : workspace.reports
  const evidencePoints = filterEvidencePointsForTask(workspace.evidencePoints, evidences, reports, selectedTask)

  return (
    <section className="module-layout" aria-label="保存证据">
      <div className="module-card span-3">
        <ModuleHead title="交付证据摘要" meta={`等级 ${workspace.evidenceGrade?.grade ?? 'C'}`} />
        <div className="evidence-point-grid">
          {evidencePoints.slice(0, 8).map((point, index) => (
            <EvidencePointCard key={`${point.kind}-${point.id ?? index}`} point={point} />
          ))}
          {!evidencePoints.length && (
            <EmptyState
              title="暂无可验收证据"
              detail="当前真实保存未放行时，保存结果、未发布证明和保存回包为 0 条是预期阻断；只有单商品只保存完成后才生成可验收证据等级。"
              actions={(
                <>
                  <button className="button button--secondary" type="button" onClick={onShowTasks}>查看选择商品门禁</button>
                  <button className="button button--quiet" type="button" onClick={onShowConsole}>查看真实只读证据</button>
                </>
              )}
            />
          )}
        </div>
      </div>
      <details className="module-card span-3 disclosure-card evidence-raw-disclosure">
        <summary>
          原始证据明细
          <span>{evidences.length} 条，按需展开</span>
        </summary>
        <div className="evidence-timeline">
          {evidences.map((evidence) => (
            <EvidenceRow key={evidence.id} evidence={evidence} />
          ))}
          {!evidences.length && (
            <EmptyState
              title="暂无原始证据"
              detail="未执行不代表通过；真实截图、DOM、报告和网络摘要会在执行后出现。"
              actions={<button className="button button--secondary" type="button" onClick={onShowTasks}>查看阻断原因</button>}
            />
          )}
        </div>
      </details>
      <details className="module-card span-3 disclosure-card evidence-grade-disclosure">
        <summary>
          证据等级说明
          <span>验收口径</span>
        </summary>
        <div className="grade-grid">
          <GradeCard grade="A" title="可直接验收" detail="同屏绑定任务、账号、商品、保存结果，并可回溯文件。" />
          <GradeCard grade="B" title="可辅助验收" detail="有截图或结构化记录，但缺少部分上下文绑定。" />
          <GradeCard grade="C" title="只能提示风险" detail="前端或日志提示，不能单独作为交付验收证据。" />
        </div>
      </details>
    </section>
  )
}

function humanPublishGuardStatus(status?: string | null) {
  return ({
    safe_unpublished: '保存后未发布',
    unsafe_publish_risk: '发现发布风险',
    blocked: '已暂停',
    waiting: '等待执行',
    empty: '等待执行',
    unknown: '等待执行',
  } as Record<string, string>)[status ?? 'unknown'] ?? status ?? '等待执行'
}

function buildConsolePrimaryPath({
  selectedTask,
  reports,
  configPreview,
  configPreviewError,
  configPreviewLoading,
  l2Gate,
  l3Gate,
  runtimeStatus,
  busy,
}: {
  selectedTask: Task | null
  reports: Report[]
  configPreview: ConfigPreview | null
  configPreviewError: string | null
  configPreviewLoading: boolean
  l2Gate?: RegressionGate
  l3Gate?: RegressionGate
  runtimeStatus: RuntimeStatus | null
  busy: boolean
}): ConsolePrimaryPath {
  const configOk = configPreview?.ok === true
  const l2Ready = l2Gate?.status === 'passed'
  const l3Ready = l3Gate?.status === 'passed'
  const dxmLoggedIn = DXM_LOGGED_IN_STATUSES.has(runtimeStatus?.dxmLogin?.status ?? '')
  const l2ProbeResourceState = getL2ProbeResourceState(runtimeStatus)
  const l2Detail = humanGateDetail(l2Gate?.detail)
  const l3Detail = humanGateDetail(l3Gate?.detail)

  if (!selectedTask) {
    return {
      code: 'select_task',
      title: '需要选择任务',
      reason: '当前没有选中的单商品只保存任务。',
      detail: '先在选择商品页创建或选择一个单商品只保存任务，再进入填写编辑页、真实只读检查和执行浏览器。',
      next: '去选择商品页选择任务',
      ctaLabel: '去选择商品',
      action: 'tasks',
      browserStatus: '未选择任务，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (selectedTask.status === 'completed') {
    return {
      code: 'completed',
      title: '保存成功',
      reason: '当前任务已完成。',
      detail: '继续复核保存结果、未发布证明、日志和证据。',
      next: '查看保存结果与未发布证明',
      ctaLabel: '查看保存结果',
      action: 'reports',
      browserStatus: '任务已完成',
      blocksBrowserStart: true,
      saveBlocked: false,
    }
  }
  if (selectedTask.status === 'running') {
    return {
      code: 'running',
      title: '正在执行',
      reason: '任务已经启动，避免重复启动执行浏览器。',
      detail: '查看当前执行浏览器、运行日志和自动操作轨迹。',
      next: '等待当前任务完成',
      ctaLabel: '查看当前执行',
      action: 'current_execution',
      browserStatus: '任务运行中',
      blocksBrowserStart: true,
      saveBlocked: false,
    }
  }
  if (selectedTask.status === 'failed') {
    const failure = humanTaskFailureMessage(selectedTask, reports)
    return {
      code: 'not_draft',
      title: '保存失败，需处理',
      reason: failure.reason,
      detail: failure.detail,
      next: '重新创建单商品只保存任务',
      ctaLabel: '重新创建单商品只保存任务',
      action: 'tasks',
      browserStatus: '上次执行失败，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (isRealDxmMutationTask(selectedTask) && !dxmLoggedIn) {
    return {
      code: 'login',
      title: '需要登录店小秘',
      reason: `DXM 登录状态：${runtimeStatus?.dxmLogin?.status ?? '未检测'}。`,
      detail: '先打开可见的真实店小秘登录浏览器，完成账号、验证码或二次确认后再继续。',
      next: '打开真实登录页并完成登录',
      ctaLabel: '打开真实登录页',
      action: 'dxm_login',
      browserStatus: '店小秘未登录，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (selectedTask.status !== 'draft') {
    return {
      code: 'not_draft',
      title: '需要选择任务',
      reason: '当前任务不是草稿状态。',
      detail: '请选择草稿任务，或重新创建单商品只保存任务。',
      next: '回到选择商品页选择草稿任务',
      ctaLabel: '选择草稿任务',
      action: 'tasks',
      browserStatus: '任务状态不可启动，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (isUnreleasedRealDxmMutationTask(selectedTask)) {
    return {
      code: 'unreleased',
      title: '当前模式未放行',
      reason: `${humanTaskModeLabel(selectedTask.mode)} 当前未放行。`,
      detail: '批量保存和无人值守仍需单独验收；当前开放采集认领和单商品只保存路径。',
      next: '回到选择商品页创建单商品只保存任务',
      ctaLabel: '创建单商品只保存任务',
      action: 'tasks',
      browserStatus: '当前模式未放行，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (isRealDxmMutationTask(selectedTask) && configPreviewError) {
    return {
      code: 'config',
      title: '需要补配置',
      reason: '配置检查接口不可用，不能判断当前任务字段是否完整。',
      detail: humanConfigError(configPreviewError),
      next: '去填写编辑页重新检查',
      ctaLabel: '去填写编辑页重新检查',
      action: 'config',
      browserStatus: '配置检查接口异常，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (isRealDxmMutationTask(selectedTask) && (configPreviewLoading || configPreview?.taskId !== selectedTask.id)) {
    return {
      code: 'config',
      title: '需要补配置',
      reason: '正在读取编辑页配置保存的本次任务取值。',
      detail: '系统正在确认店铺、类目、图片、物流和半托管字段；校验完成前不会启动真实保存。',
      next: '等待配置校验完成',
      ctaLabel: '查看填写编辑页',
      action: 'config',
      browserStatus: '配置校验中，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (isRealDxmMutationTask(selectedTask) && !configOk) {
    return {
      code: 'config',
      title: '需要补配置',
      reason: configPreview ? '当前任务配置检查未通过。' : '尚未完成本次任务配置检查。',
      detail: configPreview?.missing.length
        ? `请先补齐：${configPreview.missing.slice(0, 4).join('、')}`
        : '请先到填写编辑页检查本次任务配置，确认店铺、类目、图片、物流和半托管字段。',
      next: '去填写编辑页补齐配置',
      ctaLabel: '去填写编辑页补齐配置',
      action: 'config',
      browserStatus: '配置未完成，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (requiresRealL2(selectedTask) && !l2Ready && l2ProbeResourceState.blocked) {
    return {
      code: 'l2_resource',
      title: '需要运行真实只读检查',
      reason: '真实只读检查暂不可运行。',
      detail: l2ProbeResourceState.detail,
      next: '查看启动器日志，按提示恢复完整免安装目录后再运行真实只读检查。',
      ctaLabel: '查看启动器日志',
      action: 'launcher_logs',
      browserStatus: '真实只读检查组件未就绪，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (requiresRealL2(selectedTask) && !l2Ready) {
    return {
      code: 'l2',
      title: '需要运行真实只读检查',
      reason: `真实只读检查：${humanGateStateLabel(l2Gate?.status ?? 'not_run')}。${READONLY_PRECHECK_PURPOSE}`,
      detail: l2Detail ?? '需要商品采集页和草稿箱页两个真实页面只读检查均通过。',
      next: READONLY_PRECHECK_CTA,
      ctaLabel: READONLY_PRECHECK_CTA,
      action: 'run_l2',
      browserStatus: '真实只读检查未通过，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (requiresRealL2(selectedTask) && !l3Ready) {
    return {
      code: 'l3',
      title: '需要人工确认只保存',
      reason: '真实保存前还没有完成人工批准。',
      detail: l3Detail ?? '真实只读检查通过后，仍需要人工确认批准，只启动单商品只保存。',
      next: '去选择商品页填写批准人并启动',
      ctaLabel: '去选择商品页人工确认',
      action: 'tasks',
      browserStatus: '等待人工确认，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  if (busy) {
    return {
      code: 'busy',
      title: '正在处理当前操作',
      reason: '工作台正在处理上一个请求。',
      detail: '请等待当前请求完成后再启动执行浏览器。',
      next: '等待当前操作完成',
      ctaLabel: '查看检查计划',
      action: 'reports',
      browserStatus: '当前操作未完成，执行浏览器暂不启动',
      blocksBrowserStart: true,
      saveBlocked: true,
    }
  }
  return {
    code: 'ready',
    title: '可以启动执行浏览器',
    reason: '配置、真实只读检查和人工确认当前未阻断。',
    detail: '将打开独立执行浏览器窗口；保存前仍需确认，不会发布。',
    next: '打开执行浏览器（不保存）',
    ctaLabel: '打开执行浏览器（不保存）',
    action: 'start_browser',
    browserStatus: '执行浏览器待启动',
    blocksBrowserStart: false,
    saveBlocked: false,
  }
}

function humanTaskFailureMessage(selectedTask: Task, reports: Report[]) {
  const failedJob = selectedTask.jobs?.find((job) => job.status === 'failed' && job.error_message)
  const taskReport = reports.find((report) => Number(report.task_id) === selectedTask.id)
  const reportSummary = taskReport?.summary && typeof taskReport.summary === 'object' ? taskReport.summary as Record<string, unknown> : {}
  const saveResult = taskReport?.save_result && typeof taskReport.save_result === 'object' ? taskReport.save_result as Record<string, unknown> : {}
  const raw = failedJob?.error_message
    ?? reportSummary.blocked_reason
    ?? saveResult.message
    ?? saveResult.msg
    ?? '上次保存结果证据不完整，系统没有拿到保存成功证明。'
  const reason = humanOperatorMessage(String(raw))
  return {
    reason,
    detail: reason.includes('浏览器会话异常')
      ? '系统没有执行保存。请保持真实店小秘登录窗口可用，关闭旧执行浏览器或重启控制台后重新创建单商品只保存任务。'
      : '请先查看报告里的失败原因；确认店小秘浏览器可用后，重新创建单商品只保存任务再执行。',
  }
}

function FinalCheckFreshnessRow({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const matches = finalCheck?.final_check_matches_current_worktree === true
  const freshness = finalCheck?.final_check_freshness ?? 'unknown'
  const label = matches ? '自检覆盖当前代码' : '自检未覆盖当前代码'
  const detail = matches
    ? '报告 Git 与当前工作区一致。'
    : freshness === 'dirty_worktree'
      ? '当前有未提交改动，报告不能作为源码包证明。'
      : freshness === 'stale_head'
        ? '报告 Git 与当前代码不一致。'
        : '尚无法确认报告与当前代码一致。'

  return (
    <div className={`final-check-freshness-row ${matches ? 'is-current' : 'is-stale'}`}>
      <span>{matches ? 'OK' : '!'}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  )
}

function RuntimeGateFreshnessRow({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const freshness = finalCheck?.final_check_runtime_gate_freshness ?? 'unknown'
  const matches = finalCheck?.final_check_runtime_gate_matches_report === true
  const staleGate = freshness === 'stale_gate'
  const label = matches ? '运行门禁仍支持自检结论' : staleGate ? '运行门禁已使自检过期' : '运行门禁待复核'
  const detail = matches
    ? '当前真实只读检查和人工确认与最近自检结论一致。'
    : staleGate
      ? '真实检查证据有时效；历史验收不能作为当前启动依据。'
      : '尚无法确认当前真实检查结果是否仍支持最近自检。'

  return (
    <div className={`final-check-freshness-row ${matches ? 'is-current' : 'is-stale'}`}>
      <span>{matches ? 'OK' : '!'}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  )
}

function DeliveryReadinessRow({ readiness }: { readiness: string }) {
  const isBlocked = isBlockedReadiness(readiness)
  const isReady = isReadyReadiness(readiness)
  const tone = isReady ? 'is-ready' : isBlocked ? 'is-blocked' : 'is-unknown'
  const label = isReady ? '真实店小秘单商品只保存可申请' : isBlocked ? '真实店小秘保存暂不启动' : `真实店小秘保存${humanReadinessLabel(readiness)}`
  const detail = isReady
    ? '仅代表受控单品保存；批量、无人值守和发布仍需单独放行。'
    : isBlocked
      ? '预期阻断，不可执行真实写入。'
      : '状态未知，不可执行真实写入。'

  return (
    <div className={`delivery-readiness-row ${tone}`}>
      <span>{isReady ? 'OK' : isBlocked ? '暂停' : '!'}</span>
      <strong>{label}</strong>
      <small>{detail}</small>
    </div>
  )
}

export function MetricCard({ label, value, detail, tone }: { label: string; value: number | string; detail: string; tone: string }) {
  return (
    <div className={`metric-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  )
}

export function ModuleHead({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="module-head">
      <h2>{title}</h2>
      <span>{meta}</span>
    </div>
  )
}

function EmptyState({ title, detail, actions }: { title: string; detail: string; actions?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{detail}</span>
      {actions && <div className="next-step-actions">{actions}</div>}
    </div>
  )
}

function ConfigItem({ label, value, hint, empty = false }: { label: string; value: string; hint: string; empty?: boolean }) {
  return (
    <div className={`config-item ${empty ? 'is-empty' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  )
}

function ReferenceTemplateMap({ sections }: { sections: DxmReferenceTemplateSection[] }) {
  return (
    <div className="reference-grid">
      {sections.map((section) => (
        <div key={section.section} className={`reference-cell ${section.templateNames.length ? 'is-ready' : 'is-missing'}`}>
          <div className="reference-cell__head">
            <strong>{referenceSectionLabels[section.section]}</strong>
            <span>{section.required ? '必填' : '可选'}</span>
          </div>
          <code>{section.section}</code>
          <div className="pill-list">
            {section.templateNames.length
              ? section.templateNames.map((name) => <span key={name}>{name}</span>)
              : <span className="is-muted">待后端返回命中模板</span>}
          </div>
          <small>来源：{section.source === 'new' ? 'dxm_reference_templates' : section.source === 'legacy' ? '旧字段兼容' : '默认规则'}</small>
        </div>
      ))}
    </div>
  )
}

function TemplateRow({ template }: { template: Template }) {
  return (
    <tr>
      <td><code>{template.template_type}</code></td>
      <td>{template.template_name}</td>
      <td>{template.binding_scope}</td>
      <td><span className={`status-pill ${template.is_enabled ? 'ok' : 'muted'}`}>{template.is_enabled ? '启用' : '停用'}</span></td>
    </tr>
  )
}

function ProductCard({ product }: { product: Product }) {
  return (
    <article className="product-card">
      <strong>{product.title}</strong>
      <span>{product.category_name} / {product.currency} {product.price}</span>
      <small>SKU {product.sku_count}，图片 {product.image_count}，状态 {product.status}</small>
    </article>
  )
}

function LogRow({ log }: { log: LogItem }) {
  return (
    <article className="timeline-row">
      <span className={`status-pill ${log.level === 'error' ? 'danger' : log.level === 'warning' ? 'warn' : 'ok'}`}>{humanLevel(log.level)}</span>
      <div>
        <strong>{displaySafeLogMessage(log.message)}</strong>
        <small>{formatTime(log.created_at)} / task #{log.task_id}{log.job_id ? ` / job #${log.job_id}` : ''}</small>
      </div>
    </article>
  )
}

function EvidenceRow({ evidence }: { evidence: Evidence }) {
  const grade = evidenceGrade(evidence)
  const url = toArtifactUrl((evidence as Evidence & { file_path_url?: string }).file_path_url ?? evidence.file_path)
  const title = String(evidence.meta?.title ?? evidence.evidence_type)
  const acceptance = String(evidence.meta?.acceptance ?? '等待补齐验收说明')

  return (
    <article className={`evidence-row grade-${grade}`}>
      <div className="grade-badge">{grade}</div>
      <div>
        <strong>{title}</strong>
        <span>{acceptance}</span>
        <small>{formatTime(evidence.created_at)} / {evidence.evidence_type}</small>
      </div>
      {url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`查看证据：${title}`}>查看证据</a> : <span className="status-pill muted">无文件</span>}
    </article>
  )
}

function EvidencePointCard({ point }: { point: EvidencePoint }) {
  const title = humanEvidencePointTitle(point)
  const kindLabel = humanEvidencePointKind(point.kind)
  const ok = point.ok === undefined ? true : point.ok
  const url = toArtifactUrl(point.file_path_url ?? point.file_path)

  return (
    <article className={`evidence-point-card ${ok ? 'ok' : 'warn'}`}>
      <span className="status-pill muted">{kindLabel}</span>
      <strong>{title}</strong>
      <small>{point.created_at ? formatTime(point.created_at) : '结构化报告项'}</small>
      {url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`查看证据项：${title}`}>查看</a> : <span>无文件</span>}
    </article>
  )
}

function humanEvidencePointKind(kind: string) {
  const normalized = String(kind ?? '').toLowerCase()
  if (normalized === 'state_snapshot') return '步骤快照'
  if (normalized === 'workflow_action') return '执行证据'
  if (normalized.includes('report')) return '报告证据'
  if (normalized.includes('summary')) return '汇总证据'
  if (normalized.includes('publish_guard')) return '发布隔离'
  return kind || '证据'
}

function humanEvidencePointTitle(point: EvidencePoint) {
  const raw = String(point.action ?? point.state ?? point.kind ?? '')
  const normalized = raw.toUpperCase()
  const labels: Record<string, string> = {
    RELEASE_LOCK: '完成任务',
    WRITE_REPORT: '生成结果报告',
    VERIFY_NOT_PUBLISHED: '确认未发布',
    VERIFY_SAVE_RESULT: '确认保存成功',
    SAVE_ONLY: '点击保存',
    PRE_SAVE_GUARD_CHECK: '复核保存安全',
    FILL_SEMI_VARIANTS: '填写半托管 SKU 信息',
    FILL_SEMI_GOODS: '填写半托管信息',
    OPEN_SEMI_MANAGED_PAGE: '打开半托管页',
    ENABLE_SEMI_MANAGED: '开启半托管服务',
    FILL_COMPLIANCE: '填写合规 / 海关',
    FILL_MEDIA: '处理图片素材',
    FILL_VARIANTS: '填写 SKU / 价格 / 库存',
    FILL_BASE_INFO: '填写标题和基础信息',
    VERIFY_EDIT_OWNERSHIP: '确认编辑页归属',
    OPEN_EDIT_PAGE: '打开编辑页',
    VERIFY_LIST_OWNERSHIP: '确认采集箱归属',
    CLAIM_PRODUCT: '写入领取备注',
    ITEM_LOCKING: '锁定任务商品',
    FIND_PRODUCT: '定位目标商品',
    OPEN_DRAFT_LIST: '打开采集箱',
    PRECHECK_PUBLISH_GUARD: '确认只保存不发布',
    PRECHECK_SESSION: '检查店小秘登录',
    PRECHECK_CONFIG: '检查任务配置',
  }
  return labels[normalized] ?? raw.replace(/_/g, ' ').toLowerCase()
}

function ExceptionCard({ item }: { item: ExceptionItem }) {
  const problem = buildProblemCardCopy(item)
  return (
    <article className="exception-card">
      <div className="exception-card__head">
        <strong>{problem.title}</strong>
        <span className="status-pill danger">需处理</span>
      </div>
      <div className="exception-card__problem-grid" aria-label="默认问题恢复卡">
        <span>
          <strong>发生了什么</strong>
          <small>{problem.what}</small>
        </span>
        <span>
          <strong>为什么不能继续</strong>
          <small>{problem.why}</small>
        </span>
        <span>
          <strong>下一步</strong>
          <small>{problem.next}</small>
        </span>
      </div>
      <details className="inline-disclosure">
        <summary>维护人员查看技术细节</summary>
        <small>错误码：{item.error_code}</small>
        <small>领域：{item.field_domain}</small>
        <small>诊断摘要：{humanOperatorMessage(item.title || item.detail || item.error_code)}</small>
        <small>处理建议：{humanOperatorMessage(item.suggestion || '请查看实时日志或诊断文件后重试。')}</small>
        <pre>{item.detail || item.title || item.error_code}</pre>
        <small>完整原始信息请查看实时日志或诊断文件。</small>
      </details>
    </article>
  )
}

function buildProblemCardCopy(item: ExceptionItem) {
  const raw = `${item.error_code} ${item.title} ${item.detail} ${item.suggestion}`
  const message = humanOperatorMessage(item.detail || item.title || item.error_code)
  const suggestion = humanOperatorMessage(item.suggestion || '请按页面提示处理后重试。')
  const title = humanOperatorTitle(item.title || item.error_code, '问题需要处理')

  if (raw.includes('login') || raw.includes('登录')) {
    return {
      title: '店小秘还没登录',
      what: '系统还没有确认真实店小秘浏览器处于已登录状态。',
      why: '没有登录态时不会打开执行浏览器，也不会保存或发布。',
      next: '点“登录店小秘”，打开真实登录页，完成验证码后再点“检测登录状态”。',
    }
  }
  if (raw.includes('L2') || raw.toLowerCase().includes('probe') || raw.includes('真实只读检查')) {
    return {
      title: '真实只读检查没有通过',
      what: message,
      why: '商品采集页和草稿箱页没有完成只读验证前，系统不会启动真实保存。',
      next: `点“${READONLY_PRECHECK_CTA}”；如果提示正在运行，就等待完成后刷新。`,
    }
  }
  if (raw.includes('当前任务不是草稿状态') || raw.includes('not draft') || raw.includes('failed')) {
    return {
      title: '这条任务已经执行过或失败',
      what: message,
      why: '已经执行过的任务不能直接重复启动，避免重复操作真实店小秘。',
      next: '点“选择商品”，重新创建单商品只保存任务。',
    }
  }
  if (message.includes('保存结果证据不完整') || raw.includes('save_result')) {
    return {
      title: '保存结果证据不完整',
      what: message,
      why: '系统没有拿到保存成功、未发布证明和保存接口回包。',
      next: '先查看保存结果；确认真实浏览器可用后，重新创建单商品只保存任务。',
    }
  }
  if (message.includes('浏览器会话异常')) {
    return {
      title: '浏览器会话异常',
      what: message,
      why: '当前执行浏览器会话不可用，继续执行可能无法确认真实页面状态。',
      next: '关闭旧浏览器窗口或后台旧进程，重新打开免安装版，再启动真实浏览器。',
    }
  }
  return {
    title,
    what: message,
    why: '系统为了避免误保存或误发布，已暂停当前步骤。',
    next: suggestion,
  }
}

function isReadyReadiness(readiness: string) {
  return readiness === 'READY'
}

function isBlockedReadiness(readiness: string) {
  return readiness === 'BLOCKED'
}

function humanReadinessLabel(readiness: string) {
  if (isReadyReadiness(readiness)) return '可申请单商品只保存'
  if (isBlockedReadiness(readiness)) return '暂不启动真实保存'
  if (readiness === '未检查') return '待验收'
  return '待确认'
}

function ReportCard({ report }: { report: Report }) {
  const url = toArtifactUrl(report.file_path_url ?? report.file_path)
  const title = humanReportTitle(report)
  return (
    <article className="report-card">
      <div className="report-card__head">
        <strong>{title}</strong>
        <span className={`status-pill ${reportStatusTone(report.status)}`}>{humanReportStatus(report.status)}</span>
      </div>
      <p>{humanReportSummary(report)}</p>
      <div className="report-card__footer">
        <small>{report.created_at ? formatTime(report.created_at) : '待生成时间'}</small>
        {url ? <a href={url} target="_blank" rel="noreferrer" aria-label={`打开报告：${title}`}>打开报告</a> : <span>等待文件</span>}
      </div>
    </article>
  )
}

function GradeCard({ grade, title, detail }: { grade: 'A' | 'B' | 'C'; title: string; detail: string }) {
  return (
    <article className={`grade-card grade-${grade}`}>
      <span>{grade}</span>
      <strong>{title}</strong>
      <small>{detail}</small>
    </article>
  )
}

export function GapList({ gaps }: { gaps: AcceptanceGap[] }) {
  return (
    <div className="gap-list">
      {gaps.map((gap) => (
        <article key={gap.id} className={`gap-row severity-${gap.severity}`} data-gap-id={gap.id} data-severity={gap.severity}>
          <div>
            <strong>{gap.title}</strong>
            <span>{humanGateDetail(gap.detail) ?? gap.detail}</span>
          </div>
          <small>负责处理：{humanAcceptanceGapOwner(gap.owner)} / 证明强度：{gap.evidenceLevel}</small>
        </article>
      ))}
    </div>
  )
}

function humanAcceptanceGapOwner(owner: string) {
  const labels: Record<string, string> = {
    evidence: '保存证据',
    report: '保存结果',
    'ops-review': '人工复核',
    qa: '验收检查',
    runtime: '执行过程',
  }
  return labels[owner] ?? owner
}

export function isRealWriteExpectedBlocked(workspace: DeliveryWorkspace) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')

  return l2Gate?.status !== 'passed' || l3Gate?.status !== 'passed'
}

export function presentAcceptanceGaps(gaps: AcceptanceGap[], realWriteExpectedBlocked: boolean): AcceptanceGap[] {
  if (!realWriteExpectedBlocked) return gaps

  return gaps.map((gap) => {
    if (!l3PostEvidenceGapIds.has(gap.id)) return gap

    return {
      ...gap,
      title: `真实保存后补齐：${gap.title}`,
      severity: 'watch',
      detail: `${gap.detail}（预期阻断，真实写入放行后再补齐）`,
    }
  })
}

export function CheckRow({ label, ok, testId, state }: { label: string; ok: boolean; testId?: string; state?: string }) {
  const tone = state === 'locked' ? 'locked' : ok ? 'ok' : 'warn'
  const marker = state === 'locked' ? '暂停' : ok ? '✓' : '!'

  return (
    <div className={`check-row ${tone}`} data-testid={testId} data-state={state}>
      <span aria-hidden="true">{marker}</span>
      <strong>{label}</strong>
    </div>
  )
}

function BusinessReportCheckRow({ count, realWriteExpectedBlocked }: { count: number; realWriteExpectedBlocked: boolean }) {
  if (count === 0 && realWriteExpectedBlocked) {
    return <CheckRow label="业务保存报告 0 份（真实保存后，预期阻断）" ok={false} state={'locked'} />
  }

  return <CheckRow label={`业务保存报告 ${count} 份`} ok={count > 0} state={count > 0 ? 'present' : 'missing'} />
}

function EvidenceCheckRow({ label, count, realWriteExpectedBlocked }: { label: string; count: number; realWriteExpectedBlocked: boolean }) {
  if (count === 0 && realWriteExpectedBlocked) {
    return <CheckRow label={`${label} 0 条（预期阻断）`} ok={false} state={'locked'} />
  }

  return <CheckRow label={`${label} ${count} 条`} ok={count > 0} state={count > 0 ? 'present' : 'missing'} />
}

function PostL3ReportCheckRow({ label, ok, realWriteExpectedBlocked }: { label: string; ok: boolean; realWriteExpectedBlocked: boolean }) {
  if (realWriteExpectedBlocked) {
    return <CheckRow label={`${label}（真实保存后要求）`} ok={false} state={'locked'} />
  }

  return <CheckRow label={label} ok={ok} state={ok ? 'present' : 'missing'} />
}

function DecisionRow({ label, status, detail }: { label: string; status: string; detail: string }) {
  const ok = status === 'passed'
  return (
    <article className={`decision-row ${ok ? 'is-ok' : 'is-blocked'}`}>
      <div>
        <strong>{label}</strong>
        <span>{detail}</span>
      </div>
      <span className={`status-pill ${gateStatusPill(status)}`}>{humanGateStatus(status)}</span>
    </article>
  )
}

type L2DiagnosticSummary = {
  target: string
  targetLabel: string
  navigation: string
  failedChecks: string[]
  requestSummary: string
  topRequests: string[]
  renderHint: string | null
  reviewCandidateCount: number
  reviewCandidateRequests: string[]
  nextAction: string
}

function summarizeL2Diagnostics(gate?: RegressionGate): L2DiagnosticSummary[] {
  const latest = asRecord(gate?.latest)
  const targets = asRecord(latest?.realTargets) ?? asRecord(latest?.mockTargets)
  if (!targets) return []
  return Object.entries(targets).map(([target, raw]) => {
    const targetData = asRecord(raw)
    const diagnostics = asRecord(targetData?.diagnostics)
    const navigation = asRecord(diagnostics?.navigation)
    const renderState = asRecord(diagnostics?.render_state)
    const checks = asRecord(diagnostics?.strict_pass_checks)
    const groups = Array.isArray(diagnostics?.blocked_request_groups) ? diagnostics.blocked_request_groups : []
    const reviewCandidates = Array.isArray(diagnostics?.allowlist_review_candidates) ? diagnostics.allowlist_review_candidates : []
    const failedCheckKeys = Object.entries(checks ?? {})
      .filter(([, value]) => value === false)
      .map(([key]) => key)
    const failedChecks = failedCheckKeys.map((key) => l2CheckLabel(key))
    const finalPath = stringValue(navigation?.final_path, '未知路径')
    const finalClass = stringValue(navigation?.final_path_class, 'unknown')
    const topRequests = groups.slice(0, 3).map((group) => {
      const item = asRecord(group)
      const count = numberValue(item?.count)
      const method = stringValue(item?.method, 'GET')
      const path = stringValue(item?.path, '未知请求')
      const reason = Array.isArray(item?.reasons) ? item.reasons.join(', ') : 'blocked'
      return `${method} ${path} x${count} / ${reason}`
    })
    const reviewCandidateRequests = reviewCandidates.slice(0, 4).map((candidate) => {
      const item = asRecord(candidate)
      const count = numberValue(item?.count)
      const method = stringValue(item?.method, 'GET')
      const host = stringValue(item?.host, '')
      const path = stringValue(item?.path, '未知请求')
      const reason = Array.isArray(item?.reasons) ? item.reasons.join(', ') : '待人工评审'
      return `${method} ${host}${path} x${count} / ${reason}`
    })
    return {
      target,
      targetLabel: humanL2TargetLabel(target),
      navigation: `最终 ${finalPath}（${l2FinalPathLabel(finalClass)}）`,
      failedChecks,
      requestSummary: humanBlockedRequestSummary(groups.length, reviewCandidates.length),
      topRequests,
      renderHint: renderState?.app_shell_only === true ? '页面疑似停留在 app shell/loading，未证明目标模块可达。' : null,
      reviewCandidateCount: reviewCandidates.length,
      reviewCandidateRequests,
      nextAction: l2DiagnosticNextAction({
        failedCheckKeys,
        finalClass,
        reviewCandidateCount: reviewCandidates.length,
        appShellOnly: renderState?.app_shell_only === true,
      }),
    }
  })
}

function humanL2TargetLabel(target: string) {
  return ({
    data_acquisition: '商品采集页',
    draft_box: '采集箱/草稿箱',
  } as Record<string, string>)[target] ?? target
}

function l2DiagnosticNextAction({
  failedCheckKeys,
  finalClass,
  reviewCandidateCount,
  appShellOnly,
}: {
  failedCheckKeys: string[]
  finalClass: string
  reviewCandidateCount: number
  appShellOnly: boolean
}) {
  if (failedCheckKeys.includes('cookies_loaded') || failedCheckKeys.includes('not_login_page') || finalClass === 'login') {
    return '先在真实登录浏览器完成登录，再重新运行真实只读检查。'
  }
  if (failedCheckKeys.includes('final_url_matches') || failedCheckKeys.includes('target_url_matches') || finalClass === 'home' || finalClass === 'other') {
    return '检查目标页面是否跳到首页/登录页，必要时重新进入采集页或草稿箱后复跑。'
  }
  if (reviewCandidateCount > 0) {
    return '把只读依赖候选交给人工评审；未评审前不要放行真实保存。'
  }
  if (appShellOnly) {
    return '页面停留在加载壳，等待真实页面加载完成或重开浏览器后复跑。'
  }
  return '查看启动器日志中的请求拦截记录，修正页面阻断后复跑真实只读检查。'
}

function humanBlockedRequestSummary(blockedGroupCount: number, reviewCandidateCount: number) {
  if (blockedGroupCount > 0 && reviewCandidateCount > 0) {
    return `发现 ${blockedGroupCount} 类请求被拦截，另有 ${reviewCandidateCount} 个只读依赖需要人工评审。`
  }
  if (blockedGroupCount > 0) {
    return `发现 ${blockedGroupCount} 类请求被拦截；先处理页面加载或网络阻断后复跑。`
  }
  if (reviewCandidateCount > 0) {
    return `发现 ${reviewCandidateCount} 个只读依赖候选；人工评审前不放行真实保存。`
  }
  return '未发现请求阻断明细，优先检查登录状态、目标页面和页面加载。'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function stringValue(value: unknown, fallback: string) {
  return typeof value === 'string' && value ? value : fallback
}

function numberValue(value: unknown) {
  return typeof value === 'number' ? value : Number(value) || 0
}

function l2CheckLabel(key: string) {
  return ({
    ok: '真实只读检查未通过',
    safety_ok: '安全断言失败',
    target_url_matches: '目标 URL 不匹配',
    final_url_matches: '最终路径偏离',
    cookies_loaded: 'cookie 未加载',
    not_login_page: '疑似登录页',
    zero_write: '存在写请求',
    zero_non_read: '存在非只读请求',
    zero_blocked: '存在拦截请求',
    zero_forbidden: '命中禁词 URL',
    zero_websocket: '存在 WebSocket',
  } as Record<string, string>)[key] ?? key
}

function l2FinalPathLabel(value: string) {
  return ({
    home: '回到今天做什么',
    login: '登录页',
    target: '目标页',
    other: '其他路径',
    mock_or_external: '离线/外部',
    unknown: '未知',
  } as Record<string, string>)[value] ?? value
}

function humanGateStatus(status: string) {
  return ({
    ready: '已就绪',
    not_run: '未运行',
    mock_passed: '离线证据',
    partial: '部分完成',
    passed: '通过',
    failed: '失败',
    blocked: '已阻断',
    approval_required: '需批准',
  } as Record<string, string>)[status] ?? status
}

function gateStatusPill(status: string) {
  if (status === 'passed' || status === 'ready') return 'ok'
  if (status === 'failed' || status === 'blocked') return 'danger'
  return 'warn'
}

function gateStatusTone(status: string) {
  if (status === 'passed' || status === 'ready') return 'is-ok'
  if (status === 'failed' || status === 'blocked') return 'is-danger'
  return 'is-warn'
}

function buildConsoleSteps(selectedTask: Task | null, logs: LogItem[]) {
  const active = selectedTask?.status === 'running'
  const completed = selectedTask?.status === 'completed'
  const hasLogs = logs.length > 0
  return [
    { title: '配置检查', detail: '店铺、商品、模板、图片与隔离口径', state: hasLogs ? 'done' : 'current' },
    { title: '任务锁定', detail: '绑定商品与批次，不触碰上架入口', state: active || completed ? 'done' : 'pending' },
    { title: '只读页面核验', detail: '核对真实页面、字段和证据路径', state: active ? 'current' : completed ? 'done' : 'pending' },
    { title: '只读复核', detail: '确认双目标同轮次只读证据', state: completed ? 'done' : 'pending' },
    { title: '真实保存确认', detail: '需要人工批准与明确保存回包证据', state: completed ? 'done' : 'pending' },
    { title: '保存复盘', detail: '证明强度、问题处理、验收缺口归档', state: completed ? 'done' : 'pending' },
  ]
}

function getBrowserFrame(workspace: DeliveryWorkspace, selectedTask: Task | null, agentConsole?: AgentConsoleSession | null) {
  if (agentConsole?.active) {
    return {
      url: agentConsole.current_url || agentConsole.target_url || 'https://www.dianxiaomi.com/',
      evidencePath: agentConsole.screenshot_url ?? agentConsole.screenshot ?? '',
      source: agentConsole.browser_visible ? '来自可见独立 Profile 浏览器会话' : '浏览器会话已创建，等待窗口可见',
    }
  }
  const taskEvidence = selectedTask
    ? workspace.evidences.filter((item) => item.task_id === selectedTask.id)
    : workspace.evidences
  const screenshot = [...taskEvidence]
    .reverse()
    .find((item) => {
      const path = item.file_path ?? ''
      return /\.(png|jpg|jpeg|webp)$/i.test(path)
    })
  const pageUrl = String(screenshot?.meta?.page_url ?? workspace.evidencePoints.find((point) => point.state)?.page_url ?? '')

  return {
    url: agentConsole?.target_url || '等待启动真实浏览器',
    evidencePath: screenshot?.file_path ?? '',
    source: screenshot || pageUrl ? '截图仅用于报告证据，实时操作请启动真实浏览器' : '等待真实浏览器会话，当前无页面可达证据',
  }
}

function nextPendingStep(steps: RunStep[], currentCode?: string) {
  if (!steps.length) return null
  const currentIndex = currentCode ? steps.findIndex((step) => step.state === currentCode) : -1
  return steps.slice(Math.max(currentIndex + 1, 0)).find((step) => step.status === 'pending') ?? null
}

function filterEvidencePointsForTask(
  points: EvidencePoint[],
  evidences: Evidence[],
  reports: Report[],
  selectedTask: Task | null,
) {
  if (!selectedTask) return points

  const evidenceIds = new Set(evidences.map((item) => String(item.id)))
  const jobIds = new Set(evidences.map((item) => item.job_id).filter((value): value is number => typeof value === 'number').map(String))
  const reportIds = new Set(reports.map((item) => String(item.id)))

  return points.filter((point) => {
    const explicitTaskId = numberFromUnknown(point.task_id ?? point.taskId)
    if (explicitTaskId !== null) return explicitTaskId === selectedTask.id

    const evidenceId = point.evidence_id ?? point.evidenceId ?? point.id
    if (evidenceId !== undefined && evidenceIds.has(String(evidenceId))) return true

    const jobId = point.job_id ?? point.jobId
    if (jobId !== null && jobId !== undefined && jobIds.has(String(jobId))) return true

    const reportId = point.report_id ?? point.reportId
    if (reportId !== undefined && reportIds.has(String(reportId))) return true

    if (point.kind === 'state_snapshot') return false
    return isStructuredReportPoint(point)
  })
}

function isStructuredReportPoint(point: EvidencePoint) {
  const kind = String(point.kind ?? '').toLowerCase()
  return kind.includes('report') || kind.includes('summary') || kind.includes('publish_guard')
}

function numberFromUnknown(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

export function requiresManualApproval(task: Task) {
  return task.mode === 'single_save'
}

function requiresRealL2(task: Task) {
  return isRealDxmMutationTask(task)
}

function getTaskDisplayKey(task: Task) {
  const productIds = Array.isArray(task.payload.product_ids) ? task.payload.product_ids.join(',') : ''
  return [
    displayTaskName(task),
    task.mode,
    task.payload.store_name ?? task.store_id ?? '',
    task.payload.category_name ?? '',
    productIds,
  ].join('|')
}

export function displayTaskName(task: Pick<Task, 'name' | 'mode'>) {
  if (task.mode === 'single_save' && task.name === LEGACY_QA_REAL_MUTATION_TASK_NAME) {
    return 'QA local gated single_save fixture'
  }
  if (task.mode === 'single_save' && task.name.toLowerCase().includes('l3 canary save-only')) {
    return '单商品只保存核验任务'
  }
  return task.name
}

function isAuxiliaryTask(task: Pick<Task, 'name' | 'mode'>) {
  return task.mode === 'dry_run' || task.name.startsWith('QA ')
}

function isStartableSingleSaveTask(task: Task) {
  const storeName = String(task.payload.store_name ?? '')
  return task.mode === 'single_save'
    && task.status === 'draft'
    && !isAuxiliaryTask(task)
    && RELEASED_SINGLE_SAVE_STORE_NAMES.has(storeName)
}

function isReleasedRealDxmMutationTask(task: Task) {
  return task.mode === 'claim_only' || task.mode === 'single_save'
}

function isUnreleasedRealDxmMutationTask(task: Task) {
  return task.mode === 'batch_save'
}

function isRealDxmMutationTask(task: Task) {
  return isReleasedRealDxmMutationTask(task) || isUnreleasedRealDxmMutationTask(task)
}

function humanTaskModeLabel(mode?: string | null) {
  const labels: Record<string, string> = {
    probe: '真实只读检查',
    single_save: '单商品只保存',
    claim_only: '采集认领',
    batch_save: '批量保存未开放',
    dry_run: '开发自检',
  }
  return mode ? labels[mode] ?? mode : '等待任务'
}

function humanGateStateLabel(status: string) {
  const labels: Record<string, string> = {
    passed: '通过',
    failed: '失败',
    blocked: '已阻断',
    approval_required: '待人工确认',
    not_run: '未运行',
    partial: '部分完成',
    mock_passed: '离线证据',
    ready: '已就绪',
  }
  return labels[status] ?? status
}

function humanGateDetail(detail?: string | null) {
  if (!detail) return null
  const operatorMessage = humanOperatorMessage(detail)
  if (operatorMessage !== detail) return operatorMessage
  const resourceMessage = humanL2PrecheckError(detail)
  if (resourceMessage !== detail) return resourceMessage
  if (
    detail.includes('时效')
    || detail.includes('过期')
    || detail.includes('最新证据年龄')
    || detail.includes('证据年龄')
    || detail.includes('age')
    || detail.includes('expired')
  ) {
    return `真实只读检查证据已过期，请点击“${READONLY_PRECHECK_CTA}”刷新后再继续。`
  }
  if (detail.includes('data_acquisition') || detail.includes('draft_box')) {
    return detail
      .split('data_acquisition').join('商品采集页')
      .split('draft_box').join('草稿箱页')
      .split('L2').join('真实只读检查')
      .split('L3').join('真实保存')
      .split('passed').join('通过')
      .split('probe').join('真实只读检查')
  }
  return detail
    .split('L2').join('真实只读检查')
    .split('L3').join('真实保存')
    .split('passed').join('通过')
    .split('probe').join('真实只读检查')
}

function humanConfigError(message: string | null | undefined) {
  if (!message) return '配置检查失败：请确认本机工作台服务正在运行，然后重新检查本次配置。'
  const operatorMessage = humanOperatorMessage(message)
  if (operatorMessage !== message) return `配置检查失败：${operatorMessage}`
  const normalized = message.toLowerCase()
  if (
    normalized.includes('failed to fetch')
    || normalized.includes('networkerror')
    || normalized.includes('load failed')
  ) {
    return '配置检查失败：本机工作台服务暂时不可用，请重新打开免安装版或确认后端服务正在运行。'
  }
  return message
}

function humanL2PrecheckError(message: string) {
  if (message.includes('L2 readonly probe resources are missing')) {
    return '真实只读检查组件未安装完整：请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  if (message.includes('L2 readonly probe runner is missing')) {
    return '真实只读检查组件未安装完整：缺少真实只读检查启动器。请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  if (message.includes('L2 readonly probe script is missing')) {
    return '真实只读检查组件未安装完整：缺少真实只读检查脚本。请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  return message
}

function humanDiagnosticNavigation(value: string) {
  return value
    .split('data_acquisition').join('商品采集页')
    .split('draft_box').join('草稿箱页')
    .replace(/\/web\/productCrawl\/dataAcquisition/g, '商品采集页')
    .replace(/\/web\/smt\/smtProductList\/draft/g, '草稿箱页')
}

function humanFailedCheckLabel(value: string) {
  if (value.includes('strict_pass_checks')) return '页面检查未满足'
  if (value.includes('network')) return '网络检查未满足'
  if (value.includes('render')) return '页面渲染未满足'
  return value
    .split('strict_pass_checks').join('页面检查')
    .split('passed').join('通过')
}

function l2StartLabel(status?: string) {
  if (status === 'partial') return '真实只读检查缺目标，禁止启动'
  if (status === 'failed') return '真实只读检查失败，禁止启动'
  if (status === 'mock_passed') return '等待真实只读检查，禁止启动'
  return '真实只读检查未通过，禁止启动'
}

function displaySafeStepLabel(label: string) {
  return label.includes('只点击保存') ? '真实保存待批准' : label
}

function displaySafeStepCode(code: string) {
  return code === 'SAVE_ONLY' ? 'SAVE_GATE' : code
}

function displaySafeWorkflowAction(action: string) {
  return action === 'save_only' || action === 'SAVE_ONLY' ? 'l3_save_gate' : action
}

function humanConsoleCodeLabel(code?: string | null) {
  if (!code) return '等待状态'
  const normalized = String(code).toUpperCase()
  const labels: Record<string, string> = {
    PRECHECK_CONFIG: '启动前配置校验',
    PRECHECK_SESSION: '检查登录态',
    PRECHECK_PUBLISH_GUARD: '发布隔离检查',
    OPEN_DRAFT_LIST: '进入采集箱',
    OPEN_EDIT_PAGE: '打开编辑页',
    SAVE_ONLY: '只保存',
    SAVE_GATE: '只保存',
    VERIFY_SAVE_RESULT: '校验保存成功',
    VERIFY_NOT_PUBLISHED: '确认未发布',
    WRITE_REPORT: '生成报告',
    RELEASE_LOCK: '释放任务锁',
    WAITING: '等待状态',
  }
  return labels[normalized] ?? String(code).replace(/_/g, ' ').toLowerCase()
}

function humanConsoleText(value?: string | null) {
  if (!value) return ''
  return String(value)
    .split('PRECHECK_CONFIG').join('启动前配置校验')
    .split('SAVE_ONLY').join('只保存')
    .split('L3_SAVE_GATE').join('只保存')
    .split('SAVE_GATE').join('只保存')
    .split('L2').join('真实只读检查')
    .split('L3').join('真实保存')
}

function displaySafeLogMessage(message: string) {
  return message
    .split('只点击保存').join('真实保存待批准')
    .split('SAVE_ONLY').join('SAVE_GATE')
}

function humanReportTitle(report: Report) {
  const raw = String(report.title ?? report.report_type ?? `报告 #${report.id}`)
  return humanOperatorTitle(raw, report.status === 'failed' ? '保存任务未完成' : `报告 #${report.id}`)
}

function humanReportSummary(report: Report) {
  if (typeof report.summary === 'string') return humanOperatorMessage(report.summary)
  const summary = report.summary && typeof report.summary === 'object' ? report.summary as Record<string, unknown> : {}
  const saveResult = report.save_result && typeof report.save_result === 'object' ? report.save_result as Record<string, unknown> : {}
  const message = summary.blocked_reason ?? summary.status ?? saveResult.message ?? saveResult.msg ?? '等待执行结果补齐'
  return humanOperatorMessage(String(message))
}

function humanReportStatus(status?: string | null) {
  const labels: Record<string, string> = {
    success: '成功',
    failed: '失败',
    partial_success: '部分成功',
    running: '运行中',
    draft: '待执行',
  }
  return labels[String(status || 'draft')] ?? String(status || '待执行')
}

function reportStatusTone(status?: string | null) {
  if (status === 'success') return 'ok'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warn'
  return 'muted'
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatLogAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds < 0) return ''
  if (seconds < 60) return `${seconds} 秒未写入`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟未写入`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时未写入`
}
