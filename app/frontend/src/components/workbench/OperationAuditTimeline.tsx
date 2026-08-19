import { useMemo, useState } from 'react'

import { getJson, postJson } from '../../api'
import {
  filterAuditEvents,
  humanAuditAction,
  type OperationAuditEvent,
} from '../../operationAudit'

type TimelineResponse = {
  total: number
  events: OperationAuditEvent[]
  chain?: { ok: boolean; reason_code?: string | null }
}

export function OperationAuditTimeline() {
  const [events, setEvents] = useState<OperationAuditEvent[]>([])
  const [chainOk, setChainOk] = useState<boolean | null>(null)
  const [degraded, setDegraded] = useState(false)
  const [query, setQuery] = useState({ task_id: '', product_id: '', component: '', status: '' })
  const [message, setMessage] = useState<string | null>(null)

  async function refresh() {
    try {
      const listed = await getJson<TimelineResponse>('/api/operation-audit/events?limit=200')
      setEvents(listed.events || [])
      setChainOk(listed.chain?.ok !== false)
      setDegraded(false)
    } catch {
      setDegraded(true)
    }
  }

  async function exportZip() {
    try {
      const result = await postJson<{ path: string; sha256: string }>('/api/operation-audit/export', {})
      setMessage(`已导出诊断包 ${result.sha256.slice(0, 12)}…`)
    } catch {
      setMessage('导出失败')
    }
  }

  const visible = useMemo(
    () => filterAuditEvents(events, {
      task_id: query.task_id || undefined,
      product_id: query.product_id || undefined,
      component: query.component || undefined,
      status: query.status || undefined,
    }),
    [events, query],
  )

  return (
    <article className="module-card span-3" aria-label="操作时间线">
      <div className="module-head">
        <div>
          <span className="eyebrow">operation_audit</span>
          <h2>全链路操作时间线</h2>
          <p>同一相关 ID 串起配置、预览、审批与浏览器动作。不含密码、Cookie 或原始响应。</p>
        </div>
        <div className="e2-ref-sync-actions">
          <button className="button button--secondary" type="button" onClick={() => { void refresh() }}>刷新</button>
          <button className="button button--quiet" type="button" onClick={() => { void exportZip() }}>导出脱敏诊断包</button>
        </div>
      </div>
      {degraded ? <p className="empty-state">AUDIT_DEGRADED：审计时间线暂时不可用，配置操作未静默丢失提示。</p> : null}
      {chainOk === false ? <p className="empty-state">审计哈希链不完整，请导出后交给开发。</p> : null}
      <div className="e2-plan-review" style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8 }}>
        <input className="input" placeholder="任务 ID" value={query.task_id} onChange={(e) => setQuery({ ...query, task_id: e.target.value })} />
        <input className="input" placeholder="商品 ID" value={query.product_id} onChange={(e) => setQuery({ ...query, product_id: e.target.value })} />
        <input className="input" placeholder="组件" value={query.component} onChange={(e) => setQuery({ ...query, component: e.target.value })} />
        <input className="input" placeholder="状态" value={query.status} onChange={(e) => setQuery({ ...query, status: e.target.value })} />
      </div>
      <ol style={{ margin: '12px 0 0', paddingLeft: 18 }}>
        {visible.map((event) => (
          <li key={event.event_id}>
            <strong>{humanAuditAction(event)}</strong>
            {' · '}
            {event.recorded_at}
            {' · '}
            {event.status}
            {event.task_id ? ` · 任务 ${event.task_id}` : ''}
            {event.product_id ? ` · 商品 ${event.product_id}` : ''}
            <div style={{ fontSize: 12, opacity: 0.75 }}>{event.correlation_id}</div>
          </li>
        ))}
      </ol>
      {visible.length === 0 ? <p className="empty-state">还没有可展示的审计事件。点刷新从本机数据库读取。</p> : null}
      {message ? <p>{message}</p> : null}
    </article>
  )
}
