import type { FormEvent } from 'react'
import type { RuntimeStatus } from '../../types'
import { humanOperatorMessage } from './workbenchCopy'

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

const DXM_LOGGED_IN_STATUSES = new Set(['login_success', 'logged_in', 'not_published_verified', 'workflow_navigation'])

export function DxmAccessPage({
  runtimeStatus,
  runtimeStatusError,
  dxmLoginDraft,
  dxmCredentialState,
  busy,
  onDxmLoginDraftChange,
  onClearSavedDxmCredential,
  onOpenDxmLogin,
  onContinueDxmLogin,
  onNavigateDxmTarget,
  onShowConsole,
}: DxmAccessPageProps) {
  const dxmLoggedIn = !runtimeStatusError && DXM_LOGGED_IN_STATUSES.has(runtimeStatus?.dxmLogin?.status ?? '')
  const loginLocation = compactDxmLoginUrl(runtimeStatus?.dxmLogin?.currentUrl) || '等待打开真实登录页'
  const loginPhase = humanDxmLoginPhase(runtimeStatus, runtimeStatusError)
  const loginState = humanDxmLoginState(runtimeStatus, runtimeStatusError) ?? {
    tone: 'warn',
    label: '等待登录状态',
    detail: '还没有拿到店小秘登录检测结果。',
    next: '先打开真实登录页，完成验证码后再检测登录状态。',
  }
  return (
    <section className="module-layout dxm-access-layout" aria-label="登录店小秘">
      <div className="module-card span-2 dxm-access-card">
        <ModuleHead title="登录真实店小秘" meta="只做登录，不保存、不发布" />
        <div className="dxm-access-steps" aria-label="登录步骤">
          <span className={dxmLoginDraft.username && dxmLoginDraft.password ? 'is-done' : 'is-current'}>
            <b>1 填写店小秘账号和店小秘密码</b>
            <small>可勾选记住账号密码；凭据只做本机加密保存。</small>
          </span>
          <span className={dxmLoggedIn ? 'is-done' : 'is-current'}>
            <b>2 打开真实登录页</b>
            <small>系统会打开可见的独立店小秘浏览器窗口。</small>
          </span>
          <span className={dxmLoggedIn ? 'is-done' : 'is-current'}>
            <b>3 验证码完成后检测登录状态</b>
            <small>验证码、二次确认和账号选择都在真实浏览器内处理。</small>
          </span>
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
        />
      </div>

      <div className="module-card dxm-access-status-card">
        <ModuleHead title="登录状态" meta={dxmLoggedIn ? 'DXM 已登录' : '等待真实登录'} />
        <div className="dxm-access-status-card__body">
          <span className={`status-pill ${loginState.tone}`}>{loginState.label}</span>
          <strong>{dxmLoggedIn ? '已登录，继续下一步' : '先完成真实店小秘登录'}</strong>
          <small>{loginState.detail}</small>
          <div className="dxm-access-status-card__facts" aria-label="登录状态摘要">
            <span><b>当前状态</b><small>{loginPhase}</small></span>
            <span><b>真实浏览器停留位置</b><small>{loginLocation}</small></span>
            <span><b>下一步</b><small>{loginState.next}</small></span>
          </div>
        </div>
        <div className="dxm-access-status-card__actions">
          <button className="button button--secondary" type="button" onClick={dxmLoggedIn ? onShowConsole : onOpenDxmLogin} disabled={busy}>
            {dxmLoggedIn ? '继续到浏览器现场' : '打开真实登录页'}
          </button>
        </div>
        <details className="inline-disclosure">
          <summary>可选：打开店小秘页面或日志</summary>
          <small>登录浏览器只用于人工登录和验证码处理；浏览器现场只在配置、保存前安全检查和人工确认通过后由 Agent 操控。</small>
          <div className="dxm-access-status-card__actions">
            <button className="button button--quiet" type="button" onClick={() => onNavigateDxmTarget('draft_box')} disabled={!dxmLoggedIn || busy}>
              进入商品箱
            </button>
            <button className="button button--quiet" type="button" onClick={() => onNavigateDxmTarget('data_acquisition')} disabled={!dxmLoggedIn || busy}>
              进入待认领列表
            </button>
            <button className="button button--quiet" type="button" onClick={onShowConsole}>
              查看登录日志
            </button>
          </div>
        </details>
      </div>
    </section>
  )
}

function DxmLoginInlineForm({
  draft,
  credentialState,
  runtimeStatus,
  runtimeStatusError,
  busy,
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
    <form className="operator-inline-form" onSubmit={submit}>
      <div className="operator-inline-form__head">
        <strong>登录/人工处理真实浏览器</strong>
        <span>这里只打开真实店小秘窗口，不启动保存；窗口会显式可见，用户可输入验证码、查看错误并手动调整。</span>
      </div>
      {accountFields}
      {loginStateBlock}
      {actions}
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
      next: '下一步：进入待认领列表、商品箱，或运行保存前安全检查。',
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
      detail: runtimeStatus?.dxmLogin?.lastError
        ? humanOperatorMessage(runtimeStatus?.dxmLogin?.lastError)
        : (currentUrl ? `真实浏览器停留位置：${currentUrl}` : '未检测到有效登录态。'),
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

function humanDxmLoginPhase(runtimeStatus?: RuntimeStatus | null, runtimeStatusError?: string | null) {
  if (runtimeStatusError) return '未登录'
  const status = runtimeStatus?.dxmLogin?.status
  if (!status) return '未登录'
  if (DXM_LOGGED_IN_STATUSES.has(status) || status === 'workflow_navigation') return '已登录'
  if (status === 'waiting_captcha') return '等待验证码'
  if (status === 'login_failed' || status.includes('failed')) return '登录失败'
  return '未登录'
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

function ModuleHead({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="module-head">
      <h2>{title}</h2>
      <span>{meta}</span>
    </div>
  )
}
