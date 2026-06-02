import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

const navItems: Array<{ id: WorkbenchSection; label: string; short: string }> = [
  { id: 'guide', label: '操作引导', short: '导' },
  { id: 'dashboard', label: '总览', short: '览' },
  { id: 'config', label: '配置中心', short: '配' },
  { id: 'tasks', label: '任务中心', short: '任' },
  { id: 'console', label: '执行控制台', short: '执' },
]

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
    () => navItems.find((item) => item.id === activeSection)?.label ?? '工作台',
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
              <strong>DXM 自动化工作台</strong>
              <span>配置 / 任务 / 真实浏览器执行</span>
            </div>
          )}
          <button className="icon-button" type="button" onClick={onToggleSidebar} aria-label="切换侧边栏">
            {sidebarCollapsed ? '>' : '<'}
          </button>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${activeSection === item.id ? 'is-active' : ''}`}
              onClick={() => onSectionChange(item.id)}
              title={item.label}
              aria-current={activeSection === item.id ? 'page' : undefined}
              data-section={item.id}
            >
              <span className="nav-item__icon" aria-hidden="true">{item.short}</span>
              {!sidebarCollapsed && <span>{item.label}</span>}
            </button>
          ))}
        </nav>
        {!sidebarCollapsed && (
          <div className="sidebar__note">
            <span>数据源</span>
            <strong>{sourceLabel}</strong>
            <small>后端接口未就绪时只显示安全空态；演示数据仅开发模式可用。</small>
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
