import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

const navItems: Array<{ id: WorkbenchSection; label: string; short: string }> = [
  { id: 'dashboard', label: '总览', short: '览' },
  { id: 'config', label: '配置中心', short: '配' },
  { id: 'tasks', label: '任务中心', short: '任' },
  { id: 'console', label: '执行控制台', short: '控' },
  { id: 'evidence', label: '证据中心', short: '证' },
  { id: 'exceptions', label: '异常池', short: '异' },
  { id: 'reports', label: '报告中心', short: '报' },
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
              <strong>交付工作台</strong>
              <span>保存核验 / 证据复盘</span>
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
            <small>后端工作台接口未就绪时，前端会显示安全空态或本地演示数据。</small>
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
