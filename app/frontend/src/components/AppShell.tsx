import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'execute' | 'prepare' | 'review'
  label: string
  short: string
  summary: string
  items: Array<{ id: WorkbenchSection; label: string; short: string; hint: string }>
}

const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'prepare',
    label: '开始',
    short: '1',
    summary: '登录、配置任务',
    items: [
      { id: 'guide', label: '操作引导', short: '导', hint: '登录与下一步' },
      { id: 'config', label: '编辑页配置', short: '配', hint: '模板与本次任务配置' },
    ],
  },
  {
    id: 'execute',
    label: '执行',
    short: '2',
    summary: '任务、只读检查、浏览器',
    items: [
      { id: 'tasks', label: '当前任务', short: '任', hint: '选择商品与批准' },
      { id: 'console', label: '真实浏览器控制台', short: '控', hint: '登录、真实只读检查、真实浏览器' },
    ],
  },
  {
    id: 'review',
    label: '结果',
    short: '3',
    summary: '报告与问题',
    items: [
      { id: 'reports', label: '报告与证据', short: '报', hint: '保存结果与交付验收' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  guide: '操作引导',
  dashboard: '状态',
  config: '编辑页配置',
  tasks: '当前任务',
  console: '真实浏览器控制台',
  evidence: '证据',
  exceptions: '问题处理',
  reports: '报告与证据',
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
      <aside className="sidebar" aria-label={`运营工作台导航，${sourceLabel}`}>
        <div className="sidebar__brand">
          <div className="brand-mark" aria-hidden="true">DX</div>
          {!sidebarCollapsed && (
            <div>
              <strong>DXM Agent</strong>
              <span>只保存自动化</span>
              <span className="sr-only">操作引导 / 编辑页配置 / 当前任务 / 真实浏览器控制台 / 报告与证据</span>
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
                {!sidebarCollapsed && (
                  <span>
                    <strong>{area.label}</strong>
                    <small className="sr-only">{area.summary}</small>
                  </span>
                )}
                {sidebarCollapsed && <span aria-hidden="true">{area.short}</span>}
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
                        <span className="nav-subitem__label">{item.label}</span>
                        <small className="sr-only">{item.hint}</small>
                      </>
                    )}
                    {sidebarCollapsed && <span>{item.short}</span>}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </nav>
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作在登录浏览器和执行浏览器中完成。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
