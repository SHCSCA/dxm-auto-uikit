import type { ComponentProps } from 'react'
import { ConfigCenterView } from '../WorkbenchModules'

type EditConfigPageProps = ComponentProps<typeof ConfigCenterView>

export function EditConfigPage(props: EditConfigPageProps) {
  return <ConfigCenterView {...props} />
}
