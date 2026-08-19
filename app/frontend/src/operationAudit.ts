export type OperationAuditEvent = {
  seq: number
  recorded_at: string
  event_id: string
  correlation_id: string
  root_correlation_id: string
  actor: string
  component: string
  action: string
  phase: string
  status: string
  reason?: string | null
  task_id?: string | null
  product_id?: string | null
  mutation_id?: string | null
}

export type OperationAuditQuery = {
  status?: string
  task_id?: string
  product_id?: string
  component?: string
  phase?: string
  reason?: string
}

export function filterAuditEvents(
  events: OperationAuditEvent[],
  query: OperationAuditQuery,
): OperationAuditEvent[] {
  return events.filter((event) => (
    (!query.status || event.status === query.status)
    && (!query.task_id || event.task_id === query.task_id)
    && (!query.product_id || event.product_id === query.product_id)
    && (!query.component || event.component === query.component)
    && (!query.phase || event.phase === query.phase)
    && (!query.reason || event.reason === query.reason)
  ))
}

export function humanAuditAction(event: Pick<OperationAuditEvent, 'action'>): string {
  const labels: Record<string, string> = {
    login_start: '打开登录',
    login_continue: '确认登录',
    preview: '预览快照',
    freeze: '冻结方案',
    approve_and_start: '批准并开始',
    page_switch: '切换页面',
    save_only_click: '点击保存',
    backend_health: '后端健康',
  }
  return labels[event.action] || event.action
}
