import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'prepare' | 'configure' | 'execute' | 'review'
  label: string
  short: string
  items: Array<{ id: WorkbenchSection; label: string; short: string; hint: string }>
}

const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'prepare',
    label: '准备',
    short: '1',
    items: [
      { id: 'guide', label: '操作引导与账号登录', short: '导', hint: '登录店小秘、查看当前下一步' },
    ],
  },
  {
    id: 'configure',
    label: '配置',
    short: '2',
    items: [
      { id: 'config', label: '编辑页配置与模板', short: '配', hint: '按 DXM 编辑页分区填写本次任务取值' },
    ],
  },
  {
    id: 'execute',
    label: '执行',
    short: '3',
    items: [
      { id: 'tasks', label: '当前任务', short: '任', hint: '选择商品、确认单商品只保存、填写人工批准' },
      { id: 'console', label: '真实浏览器', short: '览', hint: '登录、只读检查、Agent 执行浏览器' },
    ],
  },
  {
    id: 'review',
    label: '复盘',
    short: '4',
    items: [
      { id: 'reports', label: '结果报告', short: '报', hint: '保存结果、未发布证明与最终验收' },
      { id: 'evidence', label: '证据与问题', short: '证', hint: '保存证据、网络证据和异常处理入口' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  guide: '操作引导',
  dashboard: '状态',
  config: '编辑页配置',
  tasks: '当前任务',
  console: '真实浏览器',
  evidence: '证据与问题',
  exceptions: '问题处理',
  reports: '结果报告',
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
              <strong>DXM 只保存自动化</strong>
              <span>真实浏览器执行</span>
              <span className="sr-only">准备 / 配置 / 执行 / 复盘</span>
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
