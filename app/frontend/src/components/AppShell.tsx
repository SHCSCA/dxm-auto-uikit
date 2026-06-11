import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'execute' | 'prepare' | 'review' | 'system'
  label: string
  short: string
  summary: string
  items: Array<{ id: WorkbenchSection; label: string; short: string; hint: string }>
}

const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'prepare',
    label: '准备',
    short: '1',
    summary: '操作引导与编辑页配置',
    items: [
      { id: 'guide', label: '操作引导', short: '导', hint: '下一步' },
      { id: 'config', label: '编辑页配置', short: '配', hint: '按店小秘分区填写' },
    ],
  },
  {
    id: 'execute',
    label: '执行',
    short: '2',
    summary: 'Agent 控制台与真实浏览器',
    items: [
      { id: 'console', label: 'Agent 控制台', short: '控', hint: '真实浏览器' },
      { id: 'tasks', label: '当前任务', short: '任', hint: '启动与审批' },
    ],
  },
  {
    id: 'review',
    label: '复核',
    short: '3',
    summary: '证据、报告、异常',
    items: [
      { id: 'evidence', label: '证据中心', short: '证', hint: '保存证据' },
      { id: 'reports', label: '报告中心', short: '报', hint: '复验结论' },
      { id: 'exceptions', label: '异常池', short: '异', hint: '待处理问题' },
    ],
  },
  {
    id: 'system',
    label: '系统',
    short: '4',
    summary: '状态与诊断',
    items: [
      { id: 'dashboard', label: '系统总览', short: '览', hint: '连接与门禁' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  guide: '操作引导',
  dashboard: '总览',
  config: '配置中心',
  tasks: '任务中心',
  console: '执行控制台',
  evidence: '证据中心',
  exceptions: '异常池',
  reports: '报告中心',
}

type AppShellProps = {
  activeSection: WorkbenchSection
  onSectionChange: (section: WorkbenchSection) => void
  children: ReactNode
  sidebarCollapsed: boolean
  onToggleSidebar: () => void
  sourceLabel: string
}

export function AppShell({
  activeSection,
  onSectionChange,
  children,
  sidebarCollapsed,
  onToggleSidebar,
  sourceLabel,
}: AppShellProps) {
  const mainRef = useRef<HTMLElement | null>(null)
  const activeLabel = useMemo(
    () => sectionLabels[activeSection] ?? '工作台',
    [activeSection],
  )

  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true })
  }, [activeSection])

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
      <aside className="sidebar" aria-label="运营工作台导航">
        <div className="sidebar__brand">
          <div className="brand-mark" aria-hidden="true">DX</div>
          {!sidebarCollapsed && (
            <div>
              <strong>DXM Agent</strong>
              <span>真实浏览器自动化</span>
              <span className="sr-only">配置 / 任务 / 真实浏览器执行</span>
            </div>
          )}
          <button className="icon-button" type="button" onClick={onToggleSidebar} aria-label="切换侧边栏">
            {sidebarCollapsed ? '>' : '<'}
          </button>
        </div>
        <nav className="nav-list">
          {primaryAreas.map((area) => (
            <section
              key={area.id}
              className={`nav-section ${area.items.some((item) => item.id === activeSection) ? 'is-active' : ''}`}
              aria-label={area.label}
            >
              <div className="nav-section__head">
                <span className="nav-section__index" aria-hidden="true">{area.short}</span>
                {!sidebarCollapsed && (
                  <span>
                    <strong>{area.label}</strong>
                    <small>{area.summary}</small>
                  </span>
                )}
              </div>
              <div className="nav-section__items">
                {area.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`nav-item nav-subitem ${activeSection === item.id ? 'is-active' : ''}`}
                    onClick={() => onSectionChange(item.id)}
                    title={`${area.label} / ${item.label}：${item.hint}`}
                    aria-current={activeSection === item.id ? 'page' : undefined}
                    data-section={item.id}
                  >
                    {!sidebarCollapsed && (
                      <>
                        <span className="nav-subitem__mark" aria-hidden="true">{item.short}</span>
                        <span className="nav-subitem__label">{item.label}</span>
                        <small>{item.hint}</small>
                      </>
                    )}
                    {sidebarCollapsed && <span>{item.short}</span>}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </nav>
        {!sidebarCollapsed && (
          <div className="sidebar__note">
            <span>状态</span>
            <span className="sr-only">连接状态</span>
            <span className="sr-only">真实店小秘操作在执行控制台的独立浏览器窗口中完成。</span>
            <strong>{sourceLabel}</strong>
          </div>
        )}
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
