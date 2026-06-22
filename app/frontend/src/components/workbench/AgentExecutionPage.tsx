import type { ComponentProps } from 'react'
import { ExecutionConsoleView } from '../WorkbenchModules'

type AgentExecutionPageProps = ComponentProps<typeof ExecutionConsoleView>

export function AgentExecutionPage(props: AgentExecutionPageProps) {
  return <ExecutionConsoleView {...props} />
}
