export function humanOperatorTitle(message: string, fallback: string) {
  const safe = humanOperatorMessage(message)
  return safe === message && !looksTechnicalOperatorMessage(message) ? message : fallback
}

export function humanOperatorMessage(message: string) {
  const normalized = message.toLowerCase()
  if (
    message.includes('Cannot switch to a different thread')
    || message.includes('greenlet')
    || message.includes('Playwright Sync API')
  ) {
    return '浏览器连接异常：请关闭旧浏览器窗口，重新打开真实浏览器后再重试当前任务。'
  }
  if (
    message.includes('L2 readonly probe')
    || normalized.includes('l2 readonly')
    || normalized.includes('readonly probe')
    || normalized.includes('probe runner')
    || normalized.includes('probe resources')
  ) {
    return '真实只读检查没有完成：请在“开始只保存”重新运行真实只读检查；通过前系统不会保存或发布。'
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
    return '检查记录没有对齐：请重新运行真实只读检查，让商品采集页和草稿箱页使用同一轮检查记录。'
  }
  if (
    message.includes('save_result')
    || message.includes('published=false')
    || message.includes('network/HAR')
    || normalized.includes('network har')
    || message.includes('save screenshot')
    || message.includes('unpublished screenshot')
  ) {
    return '保存没有完成：系统没有拿到保存成功、未发布证明和网络回包。请确认店小秘页面正常后，重新创建单商品只保存任务。'
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
  return message
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
    || normalized.includes('traceback')
    || normalized.includes('internal server error')
    || normalized.includes('/api/')
    || normalized.includes('.py')
  )
}
