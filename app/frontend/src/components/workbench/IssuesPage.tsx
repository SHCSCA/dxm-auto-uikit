import type { ReactNode } from 'react'
import type { AcceptanceGap, DeliveryWorkspace, ExceptionItem, Task } from '../../types'
import { humanOperatorMessage, humanOperatorTitle } from './workbenchCopy'

type IssuesPageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
}

const READONLY_PRECHECK_CTA = '运行保存前安全检查'
const l3PostEvidenceGapIds = new Set(['gap-save-result', 'gap-unpublished-proof', 'gap-network-save-response'])

export function IssuesPage({ workspace, selectedTask }: IssuesPageProps) {
  const exceptions = selectedTask ? workspace.exceptions.filter((item) => item.task_id === selectedTask.id) : workspace.exceptions
  const presentedAcceptanceGaps = presentAcceptanceGaps(workspace.acceptanceGaps, isRealWriteExpectedBlocked(workspace))
  const defaultProblemRecoveryCards = [
    {
      title: '店小秘还没登录',
      what: '真实店小秘浏览器还没有确认登录成功。',
      why: '没有登录态时，浏览器现场不会启动保存动作，也不会保存或发布。',
      next: '去“登录店小秘”，打开真实登录页，完成验证码后检测登录状态。',
    },
    {
      title: '保存前安全检查没有通过',
      what: '商品采集页和采集箱页还没有完成安全检查。',
      why: '安全检查未通过前，系统不能确认页面安全，所以不会启动真实保存。',
      next: `去“浏览器现场”，点击“${READONLY_PRECHECK_CTA}”。`,
    },
    {
      title: '这条任务已经执行过或失败',
      what: '当前任务不是可启动的草稿任务。',
      why: '已经执行过的任务不能重复启动，避免重复操作真实店小秘。',
      next: '去“采集箱编辑保存”，重新创建单商品只保存任务。',
    },
    {
      title: '保存结果证据不完整',
      what: '系统没有拿到保存成功、未发布证明和保存接口回包。',
      why: '证据不完整时不能当作交付成功。',
      next: '去“保存结果”查看失败原因，再重新创建单商品只保存任务。',
    },
    {
      title: '浏览器会话异常',
      what: '真实浏览器会话不可用或旧进程仍占用。',
      why: '系统无法确认当前页面状态时，会暂停真实保存。',
      next: '关闭旧窗口或后台旧进程后，再重新打开免安装版。',
    },
  ]
  const emptyExceptionDetail = selectedTask?.status === 'completed'
    ? '当前任务暂无问题记录；如需复核保存链路，请查看保存结果。'
    : '未执行不代表通过；执行失败、字段缺失和保存阻断会进入结果与问题。'

  return (
    <section className="module-layout" aria-label="结果与问题">
      <div className="module-card span-2">
        <ModuleHead title="结果与问题" meta={`${exceptions.length} 条待处理`} />
        <div className="exception-list">
          {exceptions.map((item) => (
            <ExceptionCard key={item.id} item={item} />
          ))}
          {!exceptions.length && (
            <>
              <EmptyState title="暂无待处理问题" detail={emptyExceptionDetail} />
              <div className="default-problem-cards" aria-label="默认问题恢复卡">
                {defaultProblemRecoveryCards.map((card) => (
                  <article key={card.title} className="exception-card">
                    <div className="exception-card__head">
                      <strong>{card.title}</strong>
                      <span className="status-pill warn">可自查</span>
                    </div>
                    <div className="exception-card__problem-grid">
                      <span>
                        <strong>发生了什么</strong>
                        <small>{card.what}</small>
                      </span>
                      <span>
                        <strong>为什么不能继续</strong>
                        <small>{card.why}</small>
                      </span>
                      <span>
                        <strong>下一步</strong>
                        <small>{card.next}</small>
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="module-card">
        <ModuleHead title="还缺哪些证明" meta={`${presentedAcceptanceGaps.length} 项`} />
        <GapList gaps={presentedAcceptanceGaps} />
      </div>
    </section>
  )
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
      why: '没有登录态时不会打开浏览器现场执行保存，也不会保存或发布。',
      next: '点“登录店小秘”，打开真实登录页，完成验证码后再点“检测登录状态”。',
    }
  }
  if (raw.includes('L2') || raw.toLowerCase().includes('probe') || raw.includes('真实只读检查') || raw.includes('保存前安全检查')) {
    return {
      title: '保存前安全检查没有通过',
      what: message,
      why: '商品采集页和采集箱页没有完成安全检查前，系统不会启动真实保存。',
      next: `点“${READONLY_PRECHECK_CTA}”；如果提示正在运行，就等待完成后刷新。`,
    }
  }
  if (raw.includes('当前任务不是草稿状态') || raw.includes('not draft') || raw.includes('failed')) {
    return {
      title: '这条任务已经执行过或失败',
      what: message,
      why: '已经执行过的任务不能直接重复启动，避免重复操作真实店小秘。',
      next: '点“采集箱编辑保存”，重新创建单商品只保存任务。',
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
      why: '当前浏览器现场会话不可用，继续执行可能无法确认真实页面状态。',
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

function GapList({ gaps }: { gaps: AcceptanceGap[] }) {
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

function presentAcceptanceGaps(gaps: AcceptanceGap[], realWriteExpectedBlocked: boolean): AcceptanceGap[] {
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

function isRealWriteExpectedBlocked(workspace: DeliveryWorkspace) {
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const l3Gate = workspace.regressionGates.find((gate) => gate.level === 'L3')

  return l2Gate?.status !== 'passed' || l3Gate?.status !== 'passed'
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

function humanGateDetail(detail?: string | null) {
  if (!detail) return null
  const operatorMessage = humanOperatorMessage(detail)
  if (operatorMessage !== detail) return operatorMessage
  const resourceMessage = humanL2PrecheckError(detail)
  if (resourceMessage !== detail) return resourceMessage
  const safeDetail = safeGateDetailFallback(detail)
  if (safeDetail !== detail) return safeDetail
  if (
    detail.includes('时效')
    || detail.includes('过期')
    || detail.includes('最新证据年龄')
    || detail.includes('证据年龄')
    || detail.includes('age')
    || detail.includes('expired')
  ) {
    return `保存前安全检查证据已过期，请点击“${READONLY_PRECHECK_CTA}”刷新后再继续。`
  }
  if (detail.includes('data_acquisition') || detail.includes('draft_box')) {
    return safeDetail
      .split('data_acquisition').join('商品采集页')
      .split('draft_box').join('采集箱页')
      .split('L2').join('保存前安全检查')
      .split('L3').join('真实保存')
      .split('passed').join('通过')
      .split('probe').join('保存前安全检查')
  }
  return safeDetail
    .split('L2').join('保存前安全检查')
    .split('L3').join('真实保存')
    .split('passed').join('通过')
    .split('probe').join('保存前安全检查')
}

function safeGateDetailFallback(detail: string) {
  const normalized = detail.toLowerCase()
  if (
    normalized.includes('/api/')
    || normalized.includes(' get ')
    || normalized.includes(' post ')
    || normalized.includes(' x')
    || normalized.includes('blocked requests')
    || normalized.includes('traceback')
    || normalized.includes('greenlet')
    || normalized.includes('playwright')
    || normalized.includes('internal server error')
  ) {
    return '保存前安全检查未通过；原始诊断已收进维护详情，请按页面提示处理后重新检查。'
  }
  return String(detail)
}

function humanL2PrecheckError(message: string) {
  if (message.includes('L2 readonly probe resources are missing')) {
    return '保存前安全检查组件未安装完整：请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  if (message.includes('L2 readonly probe runner is missing')) {
    return '保存前安全检查组件未安装完整：缺少安全检查启动器。请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  if (message.includes('L2 readonly probe script is missing')) {
    return '保存前安全检查组件未安装完整：缺少安全检查脚本。请关闭旧进程并重新打开完整免安装目录版；系统已阻止真实保存，不会发布。'
  }
  return message
}

function ModuleHead({ title, meta }: { title: string; meta: string }) {
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
      <p>{detail}</p>
      {actions && <div className="toolbar">{actions}</div>}
    </div>
  )
}
