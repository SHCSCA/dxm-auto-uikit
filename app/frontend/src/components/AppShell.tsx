import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import type { WorkbenchSection } from '../types'

type WorkbenchPrimaryArea = {
  id: 'daily_flow' | 'review' | 'system'
  label: string
  short: string
  items: Array<{ id: WorkbenchSection; label: string; short: string; hint: string }>
}

const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'daily_flow',
    label: '日常流程',
    short: '1',
    items: [
      { id: 'home', label: '今日任务', short: '今', hint: '看今天该处理哪一步' },
      { id: 'dxm_access', label: '登录店小秘', short: '登', hint: '打开真实店小秘并确认登录' },
      { id: 'acquisition_claim', label: '采集认领', short: '采', hint: '从数据采集认领到采集箱' },
      { id: 'draft_edit_save', label: '编辑保存', short: '编', hint: '从采集箱打开编辑页并只保存' },
      { id: 'template_center', label: '模板中心', short: '模', hint: '管理店铺和类目模板' },
    ],
  },
  {
    id: 'review',
    label: '结果复盘',
    short: '2',
    items: [
      { id: 'results', label: '保存结果', short: '果', hint: '确认保存成功且未发布' },
      { id: 'issues', label: '问题处理', short: '问', hint: '按失败原因恢复' },
    ],
  },
  {
    id: 'system',
    label: '帮助与系统',
    short: '3',
    items: [
      { id: 'help', label: '使用帮助', short: '帮', hint: '普通用户操作说明' },
      { id: 'settings', label: '系统设置', short: '设', hint: '日志、服务、维护诊断' },
    ],
  },
]

const sectionLabels: Record<WorkbenchSection, string> = {
  home: '今日任务',
  dxm_access: '登录店小秘',
  acquisition_claim: '采集认领',
  draft_edit_save: '编辑保存',
  template_center: '模板中心',
  product_tasks: '商品任务',
  current_task: '当前任务',
  task_history: '历史任务',
  edit_config: '填写编辑页',
  config_basic: '基础信息',
  config_category_title: '类目与标题',
  config_price_stock: '价格库存',
  config_images: '图片素材',
  config_logistics: '包装物流',
  config_compliance: '合规海关',
  template_management: '模板管理',
  start_save: '开始只保存',
  preflight: '运行前检查',
  real_browser: '真实浏览器',
  manual_takeover: '人工接管',
  results: '保存结果',
  issues: '问题处理',
  evidence: '证据归档',
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
              <strong>DXM 只保存自动化</strong>
              <span>采集认领后只保存，不发布</span>
              <span className="sr-only">今日任务 / 登录店小秘 / 采集认领 / 编辑保存 / 模板中心 / 保存结果 / 问题处理 / 使用帮助 / 系统设置</span>
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
        <span className="sr-only">数据连接状态：{sourceLabel}。真实店小秘操作分为采集认领和编辑保存两段完成。</span>
      </aside>
      <main ref={mainRef} className="workspace" tabIndex={-1} aria-label={`${activeLabel}主内容`}>
        <span className="sr-only" aria-live="polite">当前页面：{activeLabel}</span>
        {children}
      </main>
    </div>
  )
}
