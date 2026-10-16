import { useRef } from 'react'
import { createManualLoginController, manualLoginDisabledReason } from './dxmManualLogin'
import type { ManualLoginState } from './dxmManualLogin'

type Effects = Omit<Parameters<typeof createManualLoginController>[0], 'getState'>

export function useDxmManualLogin(state: ManualLoginState, effects: Effects) {
  const current = useRef({ state, effects })
  current.current = { state, effects }
  const action = useRef<ReturnType<typeof createManualLoginController>>()
  if (!action.current) {
    action.current = createManualLoginController({
      getState: () => current.current.state,
      pending: (value) => current.current.effects.pending(value),
      error: (message) => current.current.effects.error(message),
      notice: (message) => current.current.effects.notice(message),
      invalidate: () => current.current.effects.invalidate(),
      handoff: () => current.current.effects.handoff(),
      refresh: () => current.current.effects.refresh(),
    })
  }
  return { open: action.current, disabledReason: manualLoginDisabledReason(state) }
}
