import { Component, type ErrorInfo, type ReactNode } from 'react'
import { recordFrontendError } from '../diagnostics/frontendErrors'

export class FrontendErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, _info: ErrorInfo) {
    recordFrontendError(error, { component: 'react', action: 'render_failed' })
  }

  render() {
    if (this.state.failed) {
      return (
        <main role="alert" className="empty-state">
          <h1>工作台界面暂时不可用</h1>
          <p>错误已记录。正在执行的任务结果需先由后端和真实页面核对；刷新不会重新批准或派发任务。</p>
          <button type="button" onClick={() => window.location.reload()}>重新加载工作台</button>
        </main>
      )
    }
    return this.props.children
  }
}
