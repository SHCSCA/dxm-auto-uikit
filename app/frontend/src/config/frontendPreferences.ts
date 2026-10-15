import { recordFrontendError } from '../diagnostics/frontendErrors'
import { frontendConfig } from './frontendConfig'

export function readWorkbenchTheme(): 'light' | 'dark' {
  try {
    return window.localStorage.getItem(frontendConfig.storage.themeKey) === 'dark' ? 'dark' : 'light'
  } catch (caught) {
    recordFrontendError(caught, { component: 'preferences', action: 'read_theme' })
    return 'light'
  }
}

export function saveWorkbenchTheme(theme: 'light' | 'dark') {
  try {
    window.localStorage.setItem(frontendConfig.storage.themeKey, theme)
  } catch (caught) {
    recordFrontendError(caught, { component: 'preferences', action: 'save_theme' })
  }
}
