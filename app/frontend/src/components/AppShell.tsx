import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type PrimaryNavigationItem = {
  id: WorkbenchSection
  label: string
  short: string
  hint: string
}

const primaryNavigation: PrimaryNavigationItem[] = [
  { id: 'home', label: '工作台', short: '工', hint: '查看当前状态和唯一下一步' },
  { id: 'dxm_access', label: '连接店小秘', short: '连', hint: '打开真实可见浏览器并确认当前登录会话' },
  { id: 'draft_selection', label: '采集箱选品', short: '选', hint: '从实时 API 草稿列表选择至少三件商品' },
  { id: 'dxm_templates', label: '店小秘模板', short: '模', hint: '同步并查看店小秘后台已配置的模板' },
  { id: 'template_center', label: '普货方案', short: '案', hint: '新建、查看、改版本、归档本地方案' },
  { id: 'start_save', label: '开始批量保存', short: '存', hint: '后续阶段：复核后串行执行只保存' },
  { id: 'results', label: '保存结果', short: '果', hint: '查看回包、页面成功态与未发布证据' },
  { id: 'settings', label: '设置', short: '设', hint: '查看运行环境与系统设置' },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '工作台',
  dxm_access: '账号与浏览器',
  acquisition_claim: '待认领入箱',
  draft_selection: '采集箱选品',
  draft_edit_save: '商品箱批量编辑',
  dxm_templates: '店小秘模板',
  template_center: '普货方案',
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
  start_save: '开始批量保存',
  preflight: '浏览器诊断',
  real_browser: '浏览器诊断',
  manual_takeover: '人工接管',
  results: '保存结果',
  issues: '问题与证据',
  evidence: '保存证据',
  help: '使用帮助',
  settings: '设置',
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
  const [theme, setTheme] = useState<'light' | 'dark'>('light')
  const activeLabel = useMemo(
    () => sectionLabels[activeSection] ?? '工作台',
    [activeSection],
  )

  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true })
  }, [activeSection])

  return (
    <div className={`app-shell theme-${theme} ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
      <aside className="sidebar" aria-label={`运营工作台导航，${sourceLabel}`}>
        <div className="sidebar__brand">
          <div className="brand-mark" aria-hidden="true">DX</div>
          {!sidebarCollapsed && (
            <div>
              <strong>DXM 编辑工作台</strong>
              <span>受控编辑 · 只保存不发布</span>
              <span className="sr-only">工作台 / 连接店小秘 / 采集箱选品 / 店小秘模板 / 普货方案 / 开始批量保存 / 保存结果 / 设置</span>
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
              <span className="nav-subitem__label">{item.label}</span>
              <span className="nav-subitem__short" aria-hidden="true">{item.short}</span>
              <small className="sr-only">{item.hint}</small>
            </button>
          ))}
        </nav>
        <span className="sr-only">数据连接状态：{sourceLabel}。所有真实操作以当前后端能力和人工批准为准。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        <header className="workspace-topbar">
          <div>
            <span>当前页面</span>
            <strong>{activeLabel}</strong>
          </div>
          <div className="workspace-topbar__actions">
            <span className="workspace-topbar__source">{sourceLabel}</span>
            <button
              className="workspace-topbar__theme"
              type="button"
              onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')}
              aria-label={`切换到${theme === 'light' ? '深色' : '浅色'}主题`}
            >
              {theme === 'light' ? '深色' : '浅色'}
            </button>
          </div>
        </header>
        <div className="workspace-body">{children}</div>
      </main>
    </div>
  )
}
