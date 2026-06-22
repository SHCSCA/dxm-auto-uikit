import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'start' | 'task' | 'run' | 'review' | 'system'
  label: string
  short: string
  items: Array<{ id: WorkbenchSection; label: string; short: string; hint: string }>
}

const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'start',
    label: '准备',
    short: '1',
    items: [
      { id: 'home', label: '今日操作', short: '首', hint: '查看当前进度和下一步' },
      { id: 'dxm_access', label: '账号登录', short: '登', hint: '打开真实店小秘并检测登录状态' },
    ],
  },
  {
    id: 'task',
    label: '配置',
    short: '2',
    items: [
      { id: 'product_tasks', label: '商品任务', short: '任', hint: '选择商品并创建单商品只保存任务' },
      { id: 'edit_config', label: '编辑配置', short: '配', hint: '按店小秘编辑页分区填写本次任务取值和模板' },
    ],
  },
  {
    id: 'run',
    label: '执行',
    short: '3',
    items: [
      { id: 'agent_execution', label: '真实浏览器', short: '览', hint: '登录、只读检查、执行浏览器' },
    ],
  },
  {
    id: 'review',
    label: '复盘',
    short: '4',
    items: [
      { id: 'results', label: '结果报告', short: '报', hint: '查看保存结果、未发布证明和验收报告' },
      { id: 'evidence', label: '证据中心', short: '证', hint: '核对只保存、未发布和浏览器证据' },
      { id: 'issues', label: '问题处理', short: '问', hint: '查看失败原因、阻断说明和处理建议' },
    ],
  },
  {
    id: 'system',
    label: '系统',
    short: '5',
    items: [
      { id: 'settings', label: '帮助设置', short: '设', hint: '查看运行范围、服务状态和高级诊断入口' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '今日操作',
  dxm_access: '账号登录',
  product_tasks: '商品任务',
  edit_config: '编辑配置',
  agent_execution: '真实浏览器',
  results: '结果报告',
  issues: '问题处理',
  settings: '帮助设置',
  guide: '操作引导',
  dashboard: '状态',
  config: '编辑配置',
  tasks: '当前任务',
  console: '浏览器执行',
  evidence: '证据中心',
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
              <span className="sr-only">今日操作 / 账号登录 / 商品任务 / 编辑配置 / 真实浏览器 / 结果报告 / 证据中心 / 问题处理 / 帮助设置</span>
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
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作在账号登录和真实浏览器中完成。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
