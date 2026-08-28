import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'
import { useDxmShop } from '../dxmShopContext'
import frontendPackage from '../../package.json'

type PrimaryNavigationItem = {
  id: WorkbenchSection
  label: string
  icon: NavigationIcon
  hint: string
}

type NavigationIcon = 'home' | 'link' | 'box' | 'template' | 'plan' | 'save' | 'result' | 'settings'

const primaryNavigation: PrimaryNavigationItem[] = [
  { id: 'home', label: '工作台', icon: 'home', hint: '查看当前状态和唯一下一步' },
  { id: 'dxm_access', label: '连接店小秘', icon: 'link', hint: '打开真实可见浏览器并确认当前登录会话' },
  { id: 'draft_selection', label: '采集箱选品', icon: 'box', hint: '从实时 API 草稿列表选择商品' },
  { id: 'dxm_templates', label: '店小秘模板', icon: 'template', hint: '同步并查看店小秘后台已配置的模板' },
  { id: 'template_center', label: '普货方案', icon: 'plan', hint: '新建、查看、改版本、归档本地方案' },
  { id: 'start_save', label: '开始批量保存', icon: 'save', hint: '复核后串行执行只保存' },
  { id: 'results', label: '保存结果', icon: 'result', hint: '查看回包、页面成功态与未发布证据' },
  { id: 'settings', label: '设置', icon: 'settings', hint: '查看运行环境与系统设置' },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '工作台',
  dxm_access: '账号与浏览器',
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
  const [theme, setTheme] = useState<'light' | 'dark'>(() => (
    window.localStorage.getItem('dxm-workbench-theme') === 'dark' ? 'dark' : 'light'
  ))
  const dxmShop = useDxmShop()
  const activeLabel = useMemo(
    () => sectionLabels[activeSection] ?? '工作台',
    [activeSection],
  )

  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true })
  }, [activeSection])

  useEffect(() => {
    window.localStorage.setItem('dxm-workbench-theme', theme)
  }, [theme])

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
            <ChevronIcon direction={sidebarCollapsed ? 'right' : 'left'} />
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
              <NavigationGlyph name={item.icon} />
              <span className="nav-subitem__label">{item.label}</span>
              <small className="sr-only">{item.hint}</small>
            </button>
          ))}
        </nav>
        <section className="sidebar-shop-selector" aria-label="当前店铺">
          {!sidebarCollapsed && (
            <>
              <div className="sidebar-shop-selector__head">
                <span>当前店铺</span>
                <button
                  className="sidebar-shop-selector__refresh"
                  type="button"
                  onClick={() => { void dxmShop.refresh(true) }}
                  disabled={dxmShop.loading}
                  title="重新读取真实店铺"
                >
                  {dxmShop.loading ? '…' : '↻'}
                </button>
              </div>
              <select
                value={dxmShop.selectedShopId}
                onChange={(event) => dxmShop.setSelectedShopId(event.target.value)}
                disabled={dxmShop.loading || !dxmShop.shops.length}
                aria-label="选择当前店铺"
              >
                {dxmShop.loading && <option value="">正在读取店铺…</option>}
                {!dxmShop.loading && !dxmShop.shops.length && <option value="">请先登录店小秘</option>}
                {dxmShop.shops.map((shop) => (
                  <option key={shop.id} value={shop.id}>{shop.name}</option>
                ))}
              </select>
              <small>
                {dxmShop.error
                  ? '店铺读取失败，可点击 ↻ 重试。'
                  : dxmShop.selectedShopId
                    ? '模板、草稿与方案按当前店铺隔离。'
                    : '登录后先选择店铺。'}
              </small>
            </>
          )}
          {sidebarCollapsed && (
            <span className="sidebar-shop-selector__collapsed" title={dxmShop.shops.find((shop) => shop.id === dxmShop.selectedShopId)?.name ?? '未选择店铺'}>
              <StoreIcon />
            </span>
          )}
          <span className="sidebar__version" title={`DXM 编辑工作台 ${frontendPackage.version}`}>
            {sidebarCollapsed ? `v${frontendPackage.version}` : `版本 ${frontendPackage.version}`}
          </span>
        </section>
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

function ChevronIcon({ direction }: { direction: 'left' | 'right' }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={direction === 'left' ? 'm14.5 6-6 6 6 6' : 'm9.5 6 6 6-6 6'} />
    </svg>
  )
}

function StoreIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 10h16M6 10v9h12v-9M5 5h14l1 5H4l1-5Zm4 9h6" />
    </svg>
  )
}

function NavigationGlyph({ name }: { name: NavigationIcon }) {
  const paths: Record<NavigationIcon, string> = {
    home: 'M4 11.5 12 5l8 6.5V20h-5v-5H9v5H4v-8.5Z',
    link: 'M9.5 14.5 14.5 9m-8.2 7.7-1 1a3.8 3.8 0 0 0 5.4 0l2.1-2.1m4.9-8.3 1-1a3.8 3.8 0 0 0-5.4 0l-2.1 2.1',
    box: 'm4 8 8 4 8-4M4 8l8-4 8 4v9l-8 4-8-4V8Zm8 4v9',
    template: 'M5 4h14v16H5V4Zm4 0v16M9 9h10M9 14h10',
    plan: 'M7 4h10v3h3v13H4V7h3V4Zm0 3h10M8 12h8m-8 4h5',
    save: 'M5 4h12l2 2v14H5V4Zm3 0v6h8V4m-7 16v-6h6v6',
    result: 'M5 4h14v16H5V4Zm4 5h6m-6 4h6m-6 4h4',
    settings: 'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Zm0-4 1 2.1 2.3.4 1.6-1 2.1 2.1-1 1.6.4 2.3 2.1 1-2.1 1-.4 2.3 1 1.6-2.1 2.1-1.6-1-2.3.4-1 2.1h-3l-1-2.1-2.3-.4-1.6 1-2.1-2.1 1-1.6-.4-2.3-2.1-1 2.1-1 .4-2.3-1-1.6L6.1 6l1.6 1 2.3-.4 1-2.1h1Z',
  }
  return (
    <svg className="nav-item__icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={paths[name]} />
    </svg>
  )
}
