import type { WorkbenchSection } from '../types'
import './compactWorkbenchNavigation.css'

type NavigationItem = { id: WorkbenchSection; label: string }

export function CompactWorkbenchNavigation({ items, activeSection, activeLabel, onSectionChange }: {
  items: NavigationItem[]
  activeSection: WorkbenchSection
  activeLabel: string
  onSectionChange: (section: WorkbenchSection) => void
}) {
  return (
    <select className="compact-workbench-navigation" aria-label="切换工作台页面" value={activeSection} onChange={(event) => onSectionChange(event.target.value as WorkbenchSection)}>
      {!items.some((item) => item.id === activeSection) && <option value={activeSection}>{activeLabel}</option>}
      {items.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select>
  )
}
