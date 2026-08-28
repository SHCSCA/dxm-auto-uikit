export function humanOperatorTitle(message: string, fallback: string) {
  const sanitized = sanitizeLegacyDxmUserText(message)
  const safe = humanOperatorMessage(message)
  return safe === sanitized && !looksTechnicalOperatorMessage(message) ? safe : fallback
}

type OperatorTaskLike = {
  name?: string | null
  mode?: string | null
  payload?: Record<string, unknown> | null
  total_jobs?: number | null
}

const LEGACY_QA_REAL_MUTATION_TASK_NAME = ['QA guarded', 'real mutation task'].join(' ')

export function humanTaskDisplayName(task: OperatorTaskLike) {
  const mode = String(task.mode || '')
  const rawName = sanitizeLegacyDxmUserText(String(task.name || '')).trim()
  const payload = task.payload && typeof task.payload === 'object' ? task.payload : {}
  const payloadHint = firstTextValue(
    payload.product_title,
    payload.product_name,
    payload.title,
    payload.keyword,
    payload.category_name,
  )
  if (mode === 'single_save' && rawName === LEGACY_QA_REAL_MUTATION_TASK_NAME) {
    return '旧版单商品只保存核验任务'
  }
  if (mode === 'single_save' && rawName.toLowerCase().includes('l3 canary save-only')) {
    return '单商品只保存核验任务'
  }
  if (hasMojibake(rawName) && mode === 'single_save') {
    return `商品箱编辑保存 - ${payloadHint || '当前商品'}`
  }
  if (hasMojibake(rawName)) {
    return payloadHint || humanTaskModeName(mode) || '当前任务'
  }
  return rawName || payloadHint || humanTaskModeName(mode) || '当前任务'
}

export function humanOperatorMessage(message: string) {
  const sanitized = sanitizeLegacyDxmUserText(message)
  const normalized = message.toLowerCase()
  if (
    message.includes('Cannot switch to a different thread')
    || message.includes('greenlet')
    || message.includes('Playwright Sync API')
  ) {
    return '浏览器会话异常：当前浏览器自动化会话已经失效，系统没有继续保存。请关闭当前浏览器现场窗口，重新打开真实浏览器后再运行任务。'
  }
  if (
    normalized.includes('workflow_adapter')
    || normalized.includes('adapter method unavailable')
  ) {
    return '浏览器执行组件未就绪：当前任务没有拿到可用的真实浏览器执行组件。请重新打开免安装版，保持真实浏览器窗口打开后再运行任务；系统没有保存或发布。'
  }
  if (
    message.includes('L2 readonly probe')
    || normalized.includes('l2 readonly')
    || normalized.includes('readonly probe')
    || normalized.includes('probe runner')
    || normalized.includes('probe resources')
  ) {
    return '保存前安全检查未通过：系统还没有确认店小秘页面可以安全读取。请到“浏览器现场”点击“运行保存前安全检查”；通过前系统不会保存或发布。'
  }
  if (
    message.includes('L3')
    || normalized.includes('manual canary')
    || normalized.includes('manual approval')
    || normalized.includes('approval_required')
  ) {
    return '人工确认还没有完成：请确认只保存、不发布，并填写批准人后再继续。'
  }
  if (
    normalized.includes('run_id')
    || normalized.includes('run-id')
    || normalized.includes('run binding')
  ) {
    return '检查记录没有对齐：请重新运行保存前安全检查，让商品箱页面使用同一轮检查记录。'
  }
  if (
    message.includes('save_result')
    || message.includes('published=false')
    || message.includes('network/HAR')
    || normalized.includes('network har')
    || message.includes('save screenshot')
    || message.includes('unpublished screenshot')
  ) {
    return '保存结果证据不完整：系统没有拿到足够证据证明保存成功且未发布。请先查看保存结果；如店小秘页面已保存，请重新创建任务补齐证据。'
  }
  if (message.includes('当前任务不是草稿状态')) {
    return '这条任务已经执行过或失败，不能直接再次启动。请选择草稿任务，或重新创建单商品只保存任务。'
  }
  if (message.includes('Internal Server Error') || normalized.includes('traceback')) {
    return '系统执行失败：请确认本机工作台服务正常、真实店小秘浏览器仍打开，再按页面提示重试。'
  }
  if (looksTechnicalOperatorMessage(message)) {
    return '当前步骤被系统保护性阻断：请按页面提示处理后重试；真实保存不会启动或发布。'
  }
  return sanitized
}

export function sanitizeLegacyDxmUserText(message: string) {
  return String(message)
    .replace(/采集箱编辑保存/g, '商品箱编辑保存')
    .replace(/采集箱商品/g, '商品箱商品')
    .replace(/进入采集箱/g, '进入商品箱')
}

function firstTextValue(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function cleanTaskNameFallback(name: string) {
  if (!name || hasMojibake(name)) return ''
  return name.trim()
}

function hasMojibake(value: string) {
  return value.includes('\uFFFD') || value.includes('Ã') || value.includes('Â')
}

function humanTaskModeName(mode: string) {
  return ({
    single_save: '商品箱编辑保存',
    batch_save: '批量保存未开放',
    probe: '保存前安全检查',
    dry_run: '开发自检',
  } as Record<string, string>)[mode] ?? ''
}

export function looksTechnicalOperatorMessage(message: string) {
  const normalized = message.toLowerCase()
  return Boolean(
    message.includes('L2')
    || message.includes('L3')
    || normalized.includes('probe')
    || normalized.includes('run-id')
    || normalized.includes('run_id')
    || normalized.includes('har')
    || normalized.includes('playwright')
    || normalized.includes('greenlet')
    || normalized.includes('workflow_adapter')
    || normalized.includes('adapter method unavailable')
    || normalized.includes('traceback')
    || normalized.includes('internal server error')
    || normalized.includes('/api/')
    || normalized.includes('.py')
    || normalized.includes('reason_code')
    || normalized.includes('approval_token')
    || normalized.includes('session_id')
    || normalized.includes('browser_session')
    || normalized.includes('fingerprint')
    || normalized.includes('digest')
    || normalized.includes('sha256')
    || /\b[0-9a-f]{64}\b/i.test(message)
  )
}
