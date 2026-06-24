import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'prepare' | 'claim' | 'save' | 'review' | 'system'
  label: string
  short: string
  items: Array<{ id: WorkbenchSection; label: string; short: string; hint: string }>
}

const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'prepare',
    label: '准备',
    short: '0',
    items: [
      { id: 'home', label: '操作引导', short: '导', hint: '按当前步骤完成真实店小秘只保存' },
      { id: 'dxm_access', label: '登录店小秘', short: '登', hint: '记住账号并打开真实店小秘浏览器' },
    ],
  },
  {
    id: 'claim',
    label: '第一段：采集认领',
    short: '1',
    items: [
      { id: 'acquisition_claim', label: '数据采集认领', short: '采', hint: '从数据采集认领到采集箱' },
    ],
  },
  {
    id: 'save',
    label: '第二段：采集箱只保存',
    short: '2',
    items: [
      { id: 'template_center', label: '编辑页模板', short: '模', hint: '按店小秘编辑页分区管理多套模板' },
      { id: 'draft_edit_save', label: '采集箱只保存', short: '存', hint: '从采集箱商品创建只保存任务' },
      { id: 'start_save', label: '实时浏览器', short: '览', hint: '查看真实浏览器和自动助手执行状态' },
    ],
  },
  {
    id: 'review',
    label: '结果',
    short: '3',
    items: [
      { id: 'task_history', label: '任务与记录', short: '记', hint: '查看历史任务和失败恢复入口' },
      { id: 'results', label: '保存结果', short: '果', hint: '确认保存结果、截图和未发布证明' },
    ],
  },
  {
    id: 'system',
    label: '维护',
    short: '4',
    items: [
      { id: 'settings', label: '系统状态', short: '维', hint: '查看运行环境、日志路径和维护设置' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '操作引导',
  dxm_access: '登录店小秘',
  acquisition_claim: '数据采集认领',
  draft_edit_save: '采集箱只保存',
  template_center: '编辑页模板',
  product_tasks: '任务与记录',
  current_task: '任务与记录',
  task_history: '任务与记录',
  edit_config: '编辑页模板',
  config_basic: '基础信息',
  config_category_title: '类目与标题',
  config_price_stock: '价格库存',
  config_images: '图片素材',
  config_logistics: '包装物流',
  config_compliance: '合规海关',
  template_management: '模板管理',
  start_save: '实时浏览器',
  preflight: '实时浏览器',
  real_browser: '实时浏览器',
  manual_takeover: '人工接管',
  results: '保存结果',
  issues: '保存结果',
  evidence: '保存结果',
  help: '使用帮助',
  settings: '系统状态',
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
              <span>采集认领到采集箱，再只保存</span>
              <span className="sr-only">操作引导 / 登录店小秘 / 数据采集认领 / 编辑页模板 / 采集箱只保存 / 实时浏览器 / 任务与记录 / 保存结果 / 系统状态</span>
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
                    title={`${item.label}：${item.hint}`}
                    aria-label={`${item.label}：${item.hint}`}
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
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作分为第一段数据采集认领和第二段采集箱只保存。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
