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
      { id: 'home', label: '操作首页', short: '首', hint: '查看当前步骤和下一步操作' },
      { id: 'dxm_access', label: '店小秘登录', short: '登', hint: '记住账号并打开真实店小秘浏览器' },
    ],
  },
  {
    id: 'claim',
    label: '采集',
    short: '1',
    items: [
      { id: 'acquisition_claim', label: '采集认领', short: '采', hint: '从数据采集认领到采集箱' },
      { id: 'draft_edit_save', label: '采集箱商品', short: '箱', hint: '查看已经认领到采集箱的商品' },
    ],
  },
  {
    id: 'config',
    label: '配置',
    short: '2',
    items: [
      { id: 'template_center', label: '编辑页模板', short: '模', hint: '按店小秘编辑页分区管理多套模板' },
      { id: 'template_management', label: '模板管理', short: '管', hint: '管理店铺、类目和本次任务模板' },
    ],
  },
  {
    id: 'save',
    label: '保存',
    short: '3',
    items: [
      { id: 'product_tasks', label: '编辑保存', short: '存', hint: '创建采集箱商品只保存任务并完成人工确认' },
      { id: 'start_save', label: '真实浏览器', short: '览', hint: '查看真实浏览器、中文进度窗和人工接管' },
    ],
  },
  {
    id: 'review',
    label: '复盘',
    short: '4',
    items: [
      { id: 'results', label: '保存结果', short: '果', hint: '查看保存结果和未发布证明' },
      { id: 'issues', label: '问题与证据', short: '证', hint: '查看阻断原因、恢复建议和证据' },
    ],
  },
  {
    id: 'system',
    label: '系统',
    short: '5',
    items: [
      { id: 'settings', label: '设置与日志', short: '系', hint: '查看运行环境、日志路径和维护设置' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '操作首页',
  dxm_access: '店小秘登录',
  acquisition_claim: '采集认领',
  draft_edit_save: '采集箱商品',
  template_center: '编辑页模板',
  product_tasks: '编辑保存',
  current_task: '编辑保存',
  task_history: '编辑保存',
  edit_config: '编辑页模板',
  config_basic: '基础信息',
  config_category_title: '类目与标题',
  config_price_stock: '价格库存',
  config_images: '图片素材',
  config_logistics: '包装物流',
  config_compliance: '合规海关',
  template_management: '模板管理',
  start_save: '真实浏览器',
  preflight: '真实浏览器',
  real_browser: '真实浏览器',
  manual_takeover: '人工接管',
  results: '保存结果',
  issues: '问题与证据',
  evidence: '保存结果',
  help: '使用帮助',
  settings: '设置与日志',
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
              <span>先采集认领，再编辑只保存</span>
              <span className="sr-only">操作首页 / 店小秘登录 / 采集认领 / 采集箱商品 / 编辑页模板 / 模板管理 / 编辑保存 / 真实浏览器 / 保存结果 / 问题与证据 / 设置与日志</span>
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
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作分为采集认领和编辑只保存。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
