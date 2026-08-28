const LOGIN_HANDOFF_STATUSES = new Set([
  'waiting_captcha',
  'login_failed',
  'login_required',
])

/**
 * The login-start request hands control to the operator as soon as the
 * visible browser reaches the captcha/login step.  That handoff is still
 * actionable even when another frontend refresh has not released the global
 * busy flag yet.  Do not use this escape hatch unless the backend reports the
 * visible browser and one of the explicit login-interaction states.
 */
export function canContinueDxmLogin({
  status,
  browserVisible,
  busy,
  requestPending = false,
}: {
  status?: string | null
  browserVisible?: boolean
  busy: boolean
  requestPending?: boolean
}) {
  if (requestPending || !browserVisible || !LOGIN_HANDOFF_STATUSES.has(String(status || ''))) {
    return false
  }
  return true
}

export function dxmLoginContinueDisabledReason({
  status,
  browserVisible,
  busy,
  requestPending = false,
}: {
  status?: string | null
  browserVisible?: boolean
  busy: boolean
  requestPending?: boolean
}) {
  if (requestPending) return '正在检测当前店小秘登录状态，请稍候。'
  if (!browserVisible) return '真实店小秘浏览器尚未打开，请先打开真实登录页。'
  if (!LOGIN_HANDOFF_STATUSES.has(String(status || ''))) return '请先打开真实登录页并完成验证码。'
  return ''
}
