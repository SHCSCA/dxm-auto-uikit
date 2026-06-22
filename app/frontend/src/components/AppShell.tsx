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
    label: '开始',
    short: '1',
    items: [
      { id: 'home', label: '今天做什么', short: '今', hint: '看当前进度和唯一下一步' },
      { id: 'dxm_access', label: '登录店小秘', short: '登', hint: '打开真实店小秘并检测登录状态' },
    ],
  },
  {
    id: 'task',
    label: '准备商品',
    short: '2',
    items: [
      { id: 'product_tasks', label: '选择商品', short: '选', hint: '选择一个商品并创建单商品只保存任务' },
      { id: 'edit_config', label: '填写编辑页', short: '填', hint: '按店小秘编辑页分区填写本次任务取值' },
    ],
  },
  {
    id: 'run',
    label: '执行保存',
    short: '3',
    items: [
      { id: 'agent_execution', label: '开始只保存', short: '存', hint: '页面检查、人工确认、启动真实浏览器只保存' },
    ],
  },
  {
    id: 'review',
    label: '复盘',
    short: '4',
    items: [
      { id: 'results', label: '保存结果', short: '果', hint: '查看保存成功、未发布证明和验收报告' },
      { id: 'evidence', label: '保存证据', short: '证', hint: '核对只保存、未发布和浏览器证据' },
      { id: 'issues', label: '失败处理', short: '错', hint: '查看失败原因、阻断说明和处理建议' },
    ],
  },
  {
    id: 'system',
    label: '帮助',
    short: '5',
    items: [
      { id: 'settings', label: '帮助与设置', short: '帮', hint: '查看使用范围、服务状态和高级诊断入口' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '今天做什么',
  dxm_access: '登录店小秘',
  product_tasks: '选择商品',
  edit_config: '填写编辑页',
  agent_execution: '开始只保存',
  results: '保存结果',
  issues: '失败处理',
  settings: '帮助与设置',
  guide: '操作引导',
  dashboard: '状态',
  config: '填写编辑页',
  tasks: '当前任务',
  console: '浏览器执行',
  evidence: '保存证据',
  exceptions: '失败处理',
  reports: '保存结果',
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
              <span>真实店小秘只保存</span>
              <span className="sr-only">今天做什么 / 登录店小秘 / 选择商品 / 填写编辑页 / 开始只保存 / 保存结果 / 保存证据 / 失败处理 / 帮助与设置</span>
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
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作在登录店小秘和开始只保存中完成。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
