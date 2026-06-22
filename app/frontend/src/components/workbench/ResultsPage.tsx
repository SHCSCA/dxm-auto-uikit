import type { ReactNode } from 'react'
import type {
  AcceptanceGap,
  DeliveryWorkspace,
  FinalDeliveryCheckSummary,
  RegressionGate,
  Report,
  Task,
} from '../../types'
import { toArtifactUrl } from '../../workspace'
import { humanOperatorMessage, humanOperatorTitle } from './workbenchCopy'

type ResultsPageProps = {
  workspace: DeliveryWorkspace
  selectedTask: Task | null
  finalCheck: FinalDeliveryCheckSummary | null
  onShowEvidence: () => void
  onShowConsole: () => void
  onShowExceptions: () => void
}

const READONLY_PRECHECK_CTA = '运行真实只读检查'

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

type L2DiagnosticSummary = {
  target: string
  targetLabel: string
  navigation: string
  failedChecks: string[]
  topRequests: string[]
  renderHint: string | null
  reviewCandidateCount: number
  reviewCandidateRequests: string[]
  nextAction: string
}

export function ResultsPage({
  workspace,
  selectedTask,
  finalCheck,
  onShowEvidence,
  onShowConsole,
  onShowExceptions,
}: ResultsPageProps) {
  const reports = selectedTask ? workspace.reports.filter((item) => item.task_id === selectedTask.id) : workspace.reports
  const reportSummary = workspace.reportSummary
  const l2ProbePlan = workspace.l2ProbePlan
  const l2Gate = workspace.regressionGates.find((gate) => gate.level === 'L2')
  const effectiveReadiness = finalCheck?.effective_real_dxm_write_readiness ?? finalCheck?.real_dxm_write_readiness
  const realWriteExpectedBlocked = effectiveReadiness === 'BLOCKED'
  const businessReportCount = reportSummary?.total_reports ?? reports.length
  const saveResultCount = reportSummary?.save_results?.length ?? 0
  const unpublishedProofCount = reportSummary?.published_proofs?.length ?? 0
  const networkHarCount = (reportSummary?.network_save_results?.length ?? 0) + (reportSummary?.har_summaries?.length ?? 0)
  const l2AllowlistReviewItems = summarizeL2Diagnostics(l2Gate).flatMap((item) =>
    item.reviewCandidateRequests.map((request) => ({ target: item.targetLabel, request })),
  )

  return (
    <section className="module-layout" aria-label="保存结果" data-testid="report-center-section">
      <BusinessResultSummaryCard
        selectedTask={selectedTask}
        latestReport={reportSummary?.latest_report ?? reports[0] ?? null}
        saveResultCount={saveResultCount}
        unpublishedProofCount={unpublishedProofCount}
        networkHarCount={networkHarCount}
        publishGuardStatus={workspace.publishGuardState?.status}
        realWriteExpectedBlocked={realWriteExpectedBlocked}
        onShowEvidence={onShowEvidence}
        onShowConsole={onShowConsole}
      />
      <div className="module-card span-3">
        <ModuleHead title="保存后核对" meta={humanPublishGuardStatus(workspace.publishGuardState?.status)} />
        <div className="report-check-grid">
          <BusinessReportCheckRow count={businessReportCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <EvidenceCheckRow label="保存结果" count={saveResultCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <EvidenceCheckRow label="未发布证明" count={unpublishedProofCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <EvidenceCheckRow label="保存回包" count={networkHarCount} realWriteExpectedBlocked={realWriteExpectedBlocked} />
        </div>
        {realWriteExpectedBlocked && (
          <p className="delivery-check-card__warning">人工确认前不要求生成新的真实保存证据；0 条代表当前自动化真实保存按规则暂停。</p>
        )}
      </div>
      <div className="module-card span-3 report-followup-actions" aria-label="复核与后续处理">
        <div>
          <strong>复核与后续处理</strong>
          <span>任务结束后优先看保存证据；有阻断再处理问题；需要继续执行回“开始只保存”。</span>
        </div>
        <div className="toolbar">
          <button className="button button--secondary" type="button" data-section="evidence" onClick={onShowEvidence}>查看保存证据</button>
          <button className="button button--quiet" type="button" data-section="exceptions" onClick={onShowExceptions}>处理问题</button>
          <button className="button button--quiet" type="button" data-section="console" onClick={onShowConsole}>回到开始只保存</button>
        </div>
      </div>
      <div className="module-card span-3">
        <ModuleHead title="保存结果" meta={`${reports.length} 份报告`} />
        <div className="report-grid">
          {reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
          {!reports.length && (
            <EmptyState
              title={realWriteExpectedBlocked ? '真实保存报告待人工确认' : '暂无报告'}
              detail={realWriteExpectedBlocked
                ? '真实写入未确认前不要求生成业务保存报告；自动化工作台验收摘要见上方。'
                : '单商品只保存完成并生成未发布证明后，这里会展示报告和证据路径。当前可先查看真实只读诊断和证据缺口。'}
              actions={(
                <>
                  <button className="button button--secondary" type="button" onClick={onShowEvidence}>查看证据缺口</button>
                  <button className="button button--quiet" type="button" onClick={onShowConsole}>查看真实只读证据</button>
                </>
              )}
            />
          )}
        </div>
      </div>
      <FinalDeliveryCheckCard finalCheck={finalCheck} />
      <details className="module-card span-3 disclosure-card l2-next-step-card">
        <summary>
          重新验证真实只读检查
          <span>高级复核，需人工批准</span>
        </summary>
        <div className="l2-allowlist-review">
          <div className="l2-allowlist-review__head">
            <strong>真实只读异常候选处理</strong>
            <span>先评审，再重新检查</span>
          </div>
          <p>当前只生成候选清单，不自动放行。未完成人工评审前，不运行下方真实只读检查命令。</p>
          {l2AllowlistReviewItems.length > 0 ? (
            <ul>
              {l2AllowlistReviewItems.slice(0, 8).map((item) => (
                <li key={`${item.target}:${item.request}`}>{item.target}：{item.request}</li>
              ))}
            </ul>
          ) : (
            <p>当前工作区没有可展示的异常候选；仍需按最终报告和真实只读检查证据复核后再决定是否重跑。</p>
          )}
        </div>
        <p>{l2ProbePlan.purpose || '真实保存保持暂停；仅在操作者确认可进行只读检查时，才重新运行采集页和采集箱检查。'}</p>
        <p>采集页和采集箱必须使用同一次检查记录复验，确保双目标证据绑定到同一次人工批准的真实只读检查。</p>
        <div className="l2-next-step-card__commands">
          {l2ProbePlan.commands.map((command) => (
            <code key={command}>{command}</code>
          ))}
        </div>
        <p>证据目录：{l2ProbePlan.outputDir}。{l2ProbePlan.acceptanceCriteria.join(' ')}</p>
        <p>{l2ProbePlan.safetyNotes.join(' ')}</p>
      </details>
      <details className="module-card span-3 disclosure-card">
        <summary>
          {realWriteExpectedBlocked ? '真实保存后报告必须覆盖' : '报告必须覆盖'}
          <span>{realWriteExpectedBlocked ? '真实写入放行后' : '交付检查表'}</span>
        </summary>
        <div className="report-check-grid">
          <PostL3ReportCheckRow label="配置模板命中" ok={workspace.dxmReferenceTemplates.some((item) => item.templateNames.length)} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <PostL3ReportCheckRow label="执行步骤与结果" ok={workspace.logs.length > 0} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <PostL3ReportCheckRow label="证明强度 A/B/C" ok={workspace.evidences.length > 0} realWriteExpectedBlocked={realWriteExpectedBlocked} />
          <PostL3ReportCheckRow label="验收缺口已列明" ok={workspace.acceptanceGaps.length > 0} realWriteExpectedBlocked={realWriteExpectedBlocked} />
        </div>
      </details>
    </section>
  )
}

function FinalDeliveryCheckCard({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const available = finalCheck?.status === 'available'
  const checkedAt = finalCheck?.checked_at ? new Date(finalCheck.checked_at).toLocaleString() : '尚无记录'
  const reportPath = finalCheck?.summary_path ?? 'outputs/final-delivery-check/final-delivery-check.md'
  const jsonPath = finalCheck?.json_path ?? 'outputs/final-delivery-check/final-delivery-check.json'
  const gitHead = finalCheck?.git_head ? finalCheck.git_head.slice(0, 8) : '未记录'
  const currentGitHead = finalCheck?.current_git_head ? finalCheck.current_git_head.slice(0, 8) : '未记录'
  const browserQaGitHead = finalCheck?.browser_qa_git_head ? finalCheck.browser_qa_git_head.slice(0, 8) : '未记录'
  const finalCheckMatchesCurrent = finalCheck?.final_check_matches_current_worktree === true
  const localWorkbenchOk = finalCheck?.local_workbench_check === 'PASS'
  const postFinalReportQaState = finalCheck?.post_final_report_qa_ok === true
    ? 'PASS'
    : finalCheck?.post_final_report_qa_ok === false
      ? 'FAIL'
      : '待刷新/未运行'
  const readiness = finalCheck?.effective_real_dxm_write_readiness ?? finalCheck?.real_dxm_write_readiness ?? '未检查'
  const reportReadiness = finalCheck?.real_dxm_write_readiness ?? '未检查'
  const runtimeGateFreshness = finalCheck?.final_check_runtime_gate_freshness ?? 'unknown'
  const runtimeGateStale = runtimeGateFreshness === 'stale_gate'
  const realDxmMutationAllowed = finalCheck?.effective_real_dxm_mutation_allowed ?? (isReadyReadiness(readiness) && finalCheck?.real_dxm_mutation_allowed === true)
  const realDxmMutationScope = finalCheck?.effective_real_dxm_mutation_scope ?? (realDxmMutationAllowed ? finalCheck?.real_dxm_mutation_scope ?? 'controlled_single_save_only' : 'none')
  const reportWriteExpectedBlocked = isBlockedReadiness(finalCheck?.real_dxm_write_readiness ?? '') && finalCheck?.real_dxm_mutation_allowed !== true
  const realDxmMutationAllowedLabel = realDxmMutationAllowed
    ? `真实写入允许 true / ${realDxmMutationScope}`
    : '真实写入允许 false / none'
  const blockedReason = finalCheck?.effective_real_dxm_write_blocked_reason ?? finalCheck?.real_dxm_write_blocked_reason
  const readinessDetail = !available
    ? '还没有读取到最近验收结果；请先运行本地验收。'
    : runtimeGateStale && isReadyReadiness(readiness)
      ? '最终验收报告待刷新；当前运行门禁已按最新真实检查结果覆盖为可申请单商品只保存，源码包交付前仍需重新运行最终验收。'
      : runtimeGateStale
        ? '最终验收报告待刷新；请先重新运行真实只读检查和本地验收。'
      : isReadyReadiness(readiness)
      ? '单商品只保存路径已有验收记录；执行前仍需人工确认，批量、无人值守和发布仍保持关闭。'
      : isBlockedReadiness(readiness)
        ? '自动化工作台可继续查看和检查；真实保存暂不启动。'
        : '当前真实写入状态未知，不可执行真实写入；请先重新运行本地验收并复核真实只读检查。'
  const nextStepText = isReadyReadiness(readiness)
    ? '复核当前任务、批准人和报告链路后，再启动单商品只保存。'
    : `先在当前任务点击“${READONLY_PRECHECK_CTA}”，通过后再进行人工确认保存。`
  const browserQaScreenshotCount = finalCheck?.browser_qa_screenshot_hashes
    ? Object.keys(finalCheck.browser_qa_screenshot_hashes).length
    : 0
  const freshnessLabel = finalCheckMatchesCurrent ? '自检覆盖当前代码' : '自检未覆盖当前代码'
  const browserQaLabel = `浏览器 QA ${finalCheck?.browser_qa_ok === true ? 'PASS' : finalCheck?.browser_qa_ok === false ? 'FAIL' : '待刷新/未运行'}`
  const localWorkbenchLabel = `自动化工作台 ${finalCheck?.local_workbench_check ?? '未检查'}`
  const readinessBoundaryCopy = isReadyReadiness(readiness)
    ? '真实店小秘单商品只保存可申请；单商品只保存路径已有验收记录；批量、无人值守和发布仍保持关闭。'
    : '预期阻断：不可执行真实写入；真实保存暂不启动。'

  return (
    <div className="module-card span-3 delivery-check-card">
      <ModuleHead title="维护人员验收信息" meta={available ? checkedAt : '尚未运行'} />
      <div className="report-check-grid">
        <CheckRow
          label={`最终验收报告${localWorkbenchOk ? '通过' : '待刷新'}`}
          ok={localWorkbenchOk}
        />
        <CheckRow
          label={`真实保存状态：${humanReadinessLabel(readiness)}`}
          ok={isReadyReadiness(readiness)}
          state={isBlockedReadiness(readiness) ? 'locked' : undefined}
        />
      </div>
      <div className="delivery-check-card__body">
        <p>{readinessDetail}</p>
        {blockedReason && (
          <div className="delivery-check-card__decision" aria-label="验收阻断说明">
            <span>
              <strong>发生了什么</strong>
              <small>真实保存暂时不能启动。</small>
            </span>
            <span>
              <strong>为什么不能继续</strong>
              <small>{humanGateDetail(blockedReason)}</small>
            </span>
            <span>
              <strong>下一步</strong>
              <small>{nextStepText}</small>
            </span>
          </div>
        )}
        <div className="delivery-check-card__next-step">
          <strong>下一步</strong>
          <span>{nextStepText}</span>
        </div>
        <div className="delivery-check-card__visible-qa" aria-label="交付验收摘要">
          <span>{localWorkbenchLabel}</span>
          <span>{browserQaLabel}</span>
          <span>最终报告与证据 QA {postFinalReportQaState}</span>
          <span>{freshnessLabel}</span>
          <span>浏览器 QA Git {browserQaGitHead} / 截图哈希 {browserQaScreenshotCount} 项</span>
          <span>{readinessBoundaryCopy}</span>
        </div>
        {reportWriteExpectedBlocked && (
          <div className="report-check-grid delivery-check-card__expected-locks" aria-label="真实保存暂停时的预期证据状态">
            <BusinessReportCheckRow count={0} realWriteExpectedBlocked={true} />
            <EvidenceCheckRow label="保存结果" count={0} realWriteExpectedBlocked={true} />
            <EvidenceCheckRow label="未发布证明" count={0} realWriteExpectedBlocked={true} />
            <EvidenceCheckRow label="保存回包" count={0} realWriteExpectedBlocked={true} />
          </div>
        )}
        <div className="delivery-check-card__release-gates" aria-label="真实写入放行前置">
          <strong>真实写入放行前置</strong>
          <ol>
            {realWriteReleasePrerequisites.map((item) => (
              <li key={item.title}>
                <span>{item.title}</span>
                <small>{item.detail}</small>
              </li>
            ))}
          </ol>
        </div>
        <details className="disclosure-card delivery-check-card__appendix">
          <summary>
            技术验收信息
            <span className="delivery-check-card__qa-summary">
              维护人员使用
            </span>
          </summary>
          <div className="report-check-grid">
            <CheckRow label={`自动化工作台 ${finalCheck?.local_workbench_check ?? '未检查'}`} ok={finalCheck?.local_workbench_check === 'PASS'} />
            <DeliveryReadinessRow readiness={readiness} />
            <FinalCheckFreshnessRow finalCheck={finalCheck} />
            <RuntimeGateFreshnessRow finalCheck={finalCheck} />
            <SourcePackageCheckRow finalCheck={finalCheck} />
            <CheckRow label={`浏览器 QA ${finalCheck?.browser_qa_ok === true ? 'PASS' : finalCheck?.browser_qa_ok === false ? 'FAIL' : '待刷新/未运行'}`} ok={finalCheck?.browser_qa_ok === true} />
            <CheckRow
              label={`最终报告与证据 QA ${postFinalReportQaState}`}
              ok={finalCheck?.post_final_report_qa_ok === true}
              testId="final-report-center-qa"
              state={postFinalReportQaState}
            />
          </div>
          {runtimeGateStale && (
            <p className="delivery-check-card__warning">
              运行门禁已覆盖历史自检：报告记录 {humanReadinessLabel(reportReadiness)}，当前真实只读检查={humanGateStatus(finalCheck?.current_l2_gate_status ?? 'unknown')} / 人工确认={humanGateStatus(finalCheck?.current_l3_gate_status ?? 'unknown')}，有效状态为 {humanReadinessLabel(readiness)}。
            </p>
          )}
        {available && !finalCheckMatchesCurrent && (
          <p className="delivery-check-card__warning">
            自检未覆盖当前代码：请重新运行本地验收命令；源码包交付前运行源码包验收命令。
          </p>
        )}
        <details className="disclosure-card delivery-check-card__technical">
          <summary>
            技术路径和验收命令
            <span>仅排查问题时展开</span>
          </summary>
          <div className="delivery-check-card__paths">
            <code>{reportPath}</code>
            <code>{jsonPath}</code>
            {finalCheck?.l2_allowlist_review_template_markdown_path && (
              <code>{finalCheck.l2_allowlist_review_template_markdown_path}</code>
            )}
            {finalCheck?.l2_allowlist_review_template_json_path && (
              <code>{finalCheck.l2_allowlist_review_template_json_path}</code>
            )}
            {finalCheck?.final_report_center_screenshot_path && (
              <code data-testid="final-report-center-screenshot-path">{finalCheck.final_report_center_screenshot_path}</code>
            )}
            <span>自检 Git {gitHead} / 当前 Git {currentGitHead}</span>
            <span>OK 范围 {finalCheck?.ok_scope ?? '未记录'} / {realDxmMutationAllowedLabel}</span>
            <span>有效真实保存 {humanReadinessLabel(readiness)} / 报告记录 {humanReadinessLabel(reportReadiness)} / 运行门禁 {runtimeGateFreshness}</span>
            <span>受控单商品只保存 {finalCheck?.controlled_single_save_ready === true ? '可申请' : '未放行'} / 批量无人值守发布 {finalCheck?.batch_unattended_publish_allowed === true ? '允许' : '阻断'}</span>
            <span>预期真实写入 {finalCheck?.expected_real_dxm_write_readiness ?? '未记录'} / 有效预期匹配 {finalCheck?.effective_real_dxm_write_readiness_matches_expected === true ? 'true' : 'false'} / 报告记录匹配 {finalCheck?.real_dxm_write_readiness_matches_expected === true ? 'true' : 'false'}</span>
            <span>真实只读异常候选评审模板 {finalCheck?.l2_allowlist_review_template_state ?? '未生成'} / 候选 {finalCheck?.l2_allowlist_review_template_candidate_count ?? 0} 项</span>
            <span>模板哈希 MD {shortHash(finalCheck?.l2_allowlist_review_template_markdown_sha256)} / JSON {shortHash(finalCheck?.l2_allowlist_review_template_json_sha256)}</span>
            <span>浏览器 QA Git {browserQaGitHead} / 截图哈希 {finalCheck?.browser_qa_screenshot_hashes ? Object.keys(finalCheck.browser_qa_screenshot_hashes).length : 0} 项</span>
            <span>最终报告页截图 qa-report-center-final.png / 截图哈希 {finalCheck?.post_final_report_qa_screenshot_hashes ? Object.keys(finalCheck.post_final_report_qa_screenshot_hashes).length : 0} 项</span>
          </div>
          <div className="delivery-check-card__commands">
            <div>
              <span>本地验收命令</span>
              <code className="delivery-check-card__command">scripts\final-delivery-check.bat</code>
            </div>
            <div>
              <span>源码包验收命令</span>
              <code className="delivery-check-card__command">scripts\final-delivery-check.bat -RequireCleanWorktree</code>
            </div>
          </div>
        </details>
        </details>
      </div>
    </div>
  )
}

function ModuleHead({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="module-head">
      <h2>{title}</h2>
      <span>{meta}</span>
    </div>
  )
}

function BusinessResultSummaryCard({
  selectedTask,
  latestReport,
  saveResultCount,
  unpublishedProofCount,
  networkHarCount,
  publishGuardStatus,
  realWriteExpectedBlocked,
  onShowEvidence,
  onShowConsole,
}: {
  selectedTask: Task | null
  latestReport: Report | null
  saveResultCount: number
  unpublishedProofCount: number
  networkHarCount: number
  publishGuardStatus?: string | null
  realWriteExpectedBlocked: boolean
  onShowEvidence: () => void
  onShowConsole: () => void
}) {
  const taskDone = selectedTask?.status === 'completed'
  const reportSuccess = latestReport?.status === 'success'
  const hasSaveProof = saveResultCount > 0 && unpublishedProofCount > 0 && networkHarCount > 0
  const ok = taskDone && reportSuccess && hasSaveProof && publishGuardStatus === 'safe_unpublished'
  const saveQuestion = ok
    ? '已保存'
    : taskDone && reportSuccess
      ? '保存已返回，证据待补齐'
      : '等待保存'
  const publishQuestion = publishGuardStatus === 'safe_unpublished' || unpublishedProofCount > 0
    ? '没有发布'
    : ok
      ? '没有发布'
      : '等待未发布证明'
  const productLabel = taskProductLabel(selectedTask)
  const completedAt = latestReport?.created_at
    ? formatTime(latestReport.created_at)
    : taskDone
      ? '等待报告时间'
      : '等待完成'
  const nextStep = ok
    ? '查看保存证据，确认未发布。'
    : realWriteExpectedBlocked
      ? '回到开始只保存，完成安全检查和人工确认。'
      : '处理问题或回到开始只保存重试。'
  const title = ok
    ? '本次只保存已完成'
    : realWriteExpectedBlocked
      ? '等待人工确认后保存'
      : taskDone
        ? '本次结果需要复核'
        : '还没有完成保存'
  const detail = ok
    ? '系统已拿到保存成功、未发布证明和保存接口回包。'
    : realWriteExpectedBlocked
      ? '真实保存不会自动启动；完成登录、配置、安全检查和人工确认后再执行。'
      : '请先查看保存证据或回到开始只保存页处理当前阻断。'

  return (
    <div className={`module-card span-3 business-result-summary ${ok ? 'is-ok' : realWriteExpectedBlocked ? 'is-waiting' : 'is-warn'}`} aria-label="本次保存结果">
      <ModuleHead title="本次保存结果" meta={selectedTask ? `任务 #${selectedTask.id}` : '未选择任务'} />
      <div className="business-result-summary__main">
        <div>
          <strong>{title}</strong>
          <span>{detail}</span>
          {latestReport && <small>最新报告：{humanReportTitle(latestReport)} / {humanReportStatus(latestReport.status)}</small>}
        </div>
        <div className="business-result-summary__facts">
          <span className={saveResultCount > 0 || ok ? 'is-ok' : 'is-warn'}><b>保存成功了吗</b><strong>{saveQuestion}</strong></span>
          <span className={publishGuardStatus === 'safe_unpublished' || unpublishedProofCount > 0 ? 'is-ok' : 'is-warn'}><b>有没有发布</b><strong>{publishQuestion}</strong></span>
          <span><b>商品</b><strong>{productLabel}</strong></span>
          <span><b>完成时间</b><strong>{completedAt}</strong></span>
          <span><b>下一步</b><strong>{nextStep}</strong></span>
        </div>
      </div>
      <div className="report-followup-actions business-result-summary__actions" aria-label="本次结果后续动作">
        <button className="button button--secondary" type="button" onClick={onShowEvidence}>查看保存证据</button>
        <button className="button button--quiet" type="button" onClick={onShowConsole}>回到开始只保存</button>
      </div>
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

function taskProductLabel(task: Task | null) {
  if (!task) return '等待选择商品'
  const payload = task.payload ?? {}
  const directTitle = textValue(payload.product_title)
    || textValue(payload.product_name)
    || textValue(payload.title)
    || textValue(payload.name)
  if (directTitle) return directTitle
  const titles = Array.isArray(payload.product_titles)
    ? payload.product_titles.map(textValue).filter(Boolean)
    : []
  if (titles.length > 0) return titles.slice(0, 2).join(' / ')
  const productIds = Array.isArray(payload.product_ids) ? payload.product_ids : []
  const count = productIds.length || task.total_jobs || 0
  if (count > 0) return `${task.name} / ${count} 件商品`
  return task.name || '当前任务商品'
}

function textValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function CheckRow({ label, ok, testId, state }: { label: string; ok: boolean; testId?: string; state?: string }) {
  const tone = state === 'locked' ? 'locked' : ok ? 'ok' : 'warn'
  const marker = state === 'locked' ? '暂停' : ok ? '✓' : '!'

  return (
    <div className={`check-row ${tone}`} data-testid={testId} data-state={state}>
      <span aria-hidden="true">{marker}</span>
      <strong>{label}</strong>
    </div>
  )
}

function SourcePackageCheckRow({ finalCheck }: { finalCheck: FinalDeliveryCheckSummary | null }) {
  const sourcePackageCheck = finalCheck?.source_package_check ?? '未检查'
  const ok = sourcePackageCheck === 'PASS' || finalCheck?.source_package_check === 'NOT_REQUIRED'
  const label = sourcePackageSummaryLabel(finalCheck)

  return <CheckRow label={label} ok={ok} />
}

function sourcePackageSummaryLabel(finalCheck: FinalDeliveryCheckSummary | null) {
  const sourcePackageCheck = finalCheck?.source_package_check ?? '未检查'
  const sourcePackageReadiness = finalCheck?.source_package_readiness ?? '未检查'
  if (finalCheck?.source_package_check === 'NOT_REQUIRED') {
    return '源码包验收 NOT_REQUIRED（默认本地验收不要求源码包 clean）'
  }
  return `源码包验收 ${sourcePackageCheck} / 工作区 ${sourcePackageReadiness}`
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
      topRequests: groups.slice(0, 3).map((group) => {
        const item = asRecord(group)
        const count = numberValue(item?.count)
        const method = stringValue(item?.method, 'GET')
        const path = stringValue(item?.path, '未知请求')
        const reason = Array.isArray(item?.reasons) ? item.reasons.join(', ') : 'blocked'
        return `${method} ${path} x${count} / ${reason}`
      }),
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

function shortHash(value?: string | null) {
  return value ? value.slice(0, 12) : '未记录'
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
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
    return `真实只读检查证据已过期，请点击“${READONLY_PRECHECK_CTA}”刷新后再继续。`
  }
  if (detail.includes('data_acquisition') || detail.includes('draft_box')) {
    return safeDetail
      .split('data_acquisition').join('商品采集页')
      .split('draft_box').join('草稿箱页')
      .split('L2').join('真实只读检查')
      .split('L3').join('真实保存')
      .split('passed').join('通过')
      .split('probe').join('真实只读检查')
  }
  return safeDetail
    .split('L2').join('真实只读检查')
    .split('L3').join('真实保存')
    .split('passed').join('通过')
    .split('probe').join('真实只读检查')
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
    return '真实只读检查未通过；原始诊断已收进技术详情，请按页面提示处理后重新检查。'
  }
  return String(detail)
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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function stringValue(value: unknown, fallback: string) {
  return typeof value === 'string' && value ? value : fallback
}

function numberValue(value: unknown) {
  return typeof value === 'number' ? value : Number(value) || 0
}
