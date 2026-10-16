import { postJson } from './api.ts'
import { recordFrontendError } from './diagnostics/frontendErrors.ts'
import type { RuntimeStatus } from './types.ts'

export type ManualLoginState = {
  runtimeStatus: RuntimeStatus | null
  runtimeStatusError: string | null
  busy: boolean
  requestPending: boolean
  hasActiveTask: boolean
  hasActiveBatch: boolean
  batchStateAvailable: boolean
  agentConsoleActive: boolean
}

export function manualLoginDisabledReason(state: ManualLoginState): string {
  if (state.busy || state.requestPending) return '正在处理当前操作，请稍候再手动登录。'
  if (state.runtimeStatus?.dxmLogin?.status === 'manual_login_required') return '手动登录窗口已打开，请在窗口完成登录后检测登录状态。'
  if (state.hasActiveTask || state.hasActiveBatch) return '任务或批次正在占用浏览器，请先等待完成或停止。'
  if (state.agentConsoleActive || state.runtimeStatus?.agentConsole?.active) return '浏览器现场仍在使用，请先关闭该现场。'
  const agent = state.runtimeStatus?.browserAgent
  if (state.runtimeStatusError || !state.batchStateAvailable || !agent) return '当前浏览器占用状态未确认，请刷新工作台后重试。'
  if (agent.manualTakeover === true) return '浏览器正在人工接管中，请先交还自动浏览器。'
  if (!['idle', 'stopped'].includes(agent.status)
      || agent.active !== false || agent.manualTakeover !== false || agent.needsRestart !== false
      || agent.executionLeaseActive !== false || agent.sessionOperationActive !== false
      || !Number.isInteger(agent.reservedCommandCount) || agent.reservedCommandCount !== 0) {
    return '浏览器仍被执行、预约或会话操作占用，暂时不能手动登录。'
  }
  return ''
}

export function manualLoginRuntimeView(current: RuntimeStatus | null, opened: boolean): RuntimeStatus | null {
  if (!current) return null
  return { ...current, dxmLogin: { status: opened ? 'manual_login_required' : 'manual_login_opening',
    reasonCode: opened ? 'MANAGED_MANUAL_LOGIN_REQUIRED' : undefined,
    loggedIn: false, readerReady: false, browserVisible: opened, currentUrl: null } }
}

type ManualLoginEffects = {
  getState: () => ManualLoginState
  pending: (value: boolean) => void
  error: (message: string | null) => void
  notice: (message: string | null) => void
  invalidate: () => void
  handoff: () => void
  refresh: () => Promise<unknown>
}

export function createManualLoginController(effects: ManualLoginEffects) {
  let pending = false
  return async () => {
    if (pending) return false
    const reason = manualLoginDisabledReason(effects.getState())
    if (reason) { effects.error(reason); return false }
    pending = true
    effects.pending(true)
    effects.error(null)
    effects.notice(null)
    try {
      effects.invalidate()
      // 手动入口不读取凭据；窗口打开也不能签发登录或执行资格。
      const result = await postJson<Record<string, unknown>>('/api/dxm/workflow/manual-login', {})
      if (result.ok !== true || result.stage !== 'manual_login_required'
          || result.reason_code !== 'MANAGED_MANUAL_LOGIN_REQUIRED' || result.logged_in !== false
          || result.reader_ready !== false || result.browser_visible !== true) {
        throw new Error('手动登录窗口状态未能确认，请查看真实浏览器并重新检测登录状态。')
      }
      effects.handoff()
      effects.notice('手动登录窗口已打开。请在真实店小秘窗口输入账号密码并完成验证码，再点击“验证码完成后检测登录状态”。')
      return true
    } catch (error) {
      recordFrontendError(error, { component: 'dxm_access', action: 'manual_login' })
      effects.error(`手动登录未完成：${error instanceof Error ? error.message : '窗口未能打开，请查看实时日志后重试。'}`)
      return false
    } finally {
      pending = false
      effects.pending(false)
      try { await effects.refresh() } catch (error) {
        recordFrontendError(error, { component: 'dxm_access', action: 'manual_login_refresh' })
        effects.error('登录窗口状态刷新失败，请查看实时日志后重新检测登录状态。')
      }
    }
  }
}
