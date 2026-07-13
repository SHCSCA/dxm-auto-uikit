import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'prepare' | 'claim' | 'config' | 'save' | 'review' | 'system'
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
      { id: 'home', label: '首页', short: '首', hint: '查看当前步骤和下一步操作' },
      { id: 'dxm_access', label: '账号与浏览器', short: '登', hint: '记住账号并打开真实店小秘浏览器' },
    ],
  },
  {
    id: 'claim',
    label: '第一段：待认领商品',
    short: '1',
    items: [
      { id: 'acquisition_claim', label: '待认领入箱', short: '箱', hint: '把店小秘里已经存在的待认领商品放进商品箱' },
    ],
  },
  {
    id: 'config',
    label: '配置',
    short: '2',
    items: [
      { id: 'template_center', label: '模板中心', short: '模', hint: '按店小秘编辑页分区管理多套模板' },
      { id: 'template_management', label: '模板管理', short: '管', hint: '管理店铺、类目和本次任务模板' },
    ],
  },
  {
    id: 'save',
    label: '第二段：编辑只保存',
    short: '3',
    items: [
      { id: 'draft_edit_save', label: '商品箱编辑保存', short: '箱', hint: '从已认领商品箱开始编辑并只保存' },
      { id: 'product_tasks', label: '当前保存任务', short: '任', hint: '查看当前只保存任务、人工确认和恢复动作' },
      { id: 'start_save', label: '浏览器现场', short: '览', hint: '查看真实浏览器、中文进度窗和人工接管' },
      { id: 'task_history', label: '任务记录', short: '记', hint: '查看历史任务、失败原因和恢复入口' },
    ],
  },
  {
    id: 'review',
    label: '复盘',
    short: '4',
    items: [
      { id: 'results', label: '结果报告', short: '报', hint: '查看保存结果、失败原因和下一步' },
      { id: 'evidence', label: '报告与证据', short: '据', hint: '查看未发布证明、页面记录和保存回包' },
      { id: 'issues', label: '问题与证据', short: '证', hint: '查看阻断原因、恢复建议和证据' },
    ],
  },
  {
    id: 'system',
    label: '维护',
    short: '5',
    items: [
      { id: 'settings', label: '系统维护', short: '系', hint: '查看运行环境、服务状态和维护设置' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '首页',
  dxm_access: '账号与浏览器',
  acquisition_claim: '待认领入箱',
  draft_edit_save: '商品箱编辑保存',
  template_center: '模板中心',
  product_tasks: '当前保存任务',
  current_task: '当前保存任务',
  task_history: '任务记录',
  edit_config: '编辑页模板',
  config_basic: '基础信息',
  config_category_title: '类目与标题',
  config_price_stock: '价格库存',
  config_images: '图片素材',
  config_logistics: '包装物流',
  config_compliance: '合规海关',
  template_management: '模板管理',
  start_save: '浏览器现场',
  preflight: '浏览器现场',
  real_browser: '浏览器现场',
  manual_takeover: '人工接管',
  results: '结果报告',
  issues: '问题与证据',
  evidence: '保存证据',
  help: '使用帮助',
  settings: '系统维护',
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
              <span>先认领已有商品，再编辑只保存</span>
              <span className="sr-only">首页 / 账号与浏览器 / 待认领入箱 / 模板中心 / 模板管理 / 商品箱编辑保存 / 当前保存任务 / 浏览器现场 / 任务记录 / 结果报告 / 保存证据 / 问题与证据 / 系统维护</span>
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
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作分为待认领入箱和商品箱编辑只保存。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
