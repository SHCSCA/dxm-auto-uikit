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
    message.includes('save_result')
    || message.includes('published=false')
    || message.includes('network/HAR')
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
