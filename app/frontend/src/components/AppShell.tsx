import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type PrimaryNavigationItem = {
  id: WorkbenchSection
  label: string
  short: string
  hint: string
}

const primaryNavigation: PrimaryNavigationItem[] = [
  { id: 'home', label: '编辑工作台', short: '编', hint: '查看当前状态和唯一下一步' },
  { id: 'template_center', label: '模板中心', short: '模', hint: '管理编辑使用的模板' },
  { id: 'start_save', label: '浏览器现场', short: '览', hint: '查看真实浏览器和当前执行' },
  { id: 'task_history', label: '批次记录', short: '记', hint: '查看历史任务、结果和异常' },
  { id: 'settings', label: '系统设置', short: '设', hint: '查看运行环境与系统设置' },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '编辑工作台',
  dxm_access: '账号与浏览器',
  acquisition_claim: '待认领入箱',
  draft_edit_save: '商品箱编辑保存',
  template_center: '模板中心',
  product_tasks: '当前保存任务',
  current_task: '当前保存任务',
  task_history: '批次记录',
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
  settings: '系统设置',
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
              <strong>DXM 编辑工作台</strong>
              <span>受控编辑 · 只保存不发布</span>
              <span className="sr-only">编辑工作台 / 模板中心 / 浏览器现场 / 批次记录 / 系统设置</span>
            </div>
          )}
          <button className="icon-button" type="button" onClick={onToggleSidebar} aria-label="切换侧边栏">
            {sidebarCollapsed ? '>' : '<'}
          </button>
        </div>
        <nav className="nav-list">
          {primaryNavigation.map((item) => (
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
        </nav>
        <span className="sr-only">数据连接状态：{sourceLabel}。所有真实操作以当前后端能力和人工批准为准。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
