import type { ComponentProps } from 'react'
import { TaskCenterView } from '../WorkbenchModules'

type ProductTasksPageProps = ComponentProps<typeof TaskCenterView>

export function ProductTasksPage(props: ProductTasksPageProps) {
  return <TaskCenterView {...props} />
}
