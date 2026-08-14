import { Component } from 'react'

// 顶层错误边界：包裹整个 <App />。
// 之前只有内层 ErrorBoundary 包住 <main> 的内容区，一旦 App 自身（外壳 / Sidebar /
// 路由切换等）在渲染期抛错，React 会直接卸载整棵树，表现为「纯白页」且没有任何提示。
// 这里在更外层兜底：任何未被内层边界捕获的错误都会显示可读的错误信息 + 堆栈，
// 不再白屏，也便于定位真实问题。不自动跳转，避免掩盖真实 bug。
export default class AppErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[AppErrorBoundary]', error, info)
    try {
      // 把错误上报到后端日志（best-effort），方便服务端排查
      fetch('/api/client-error', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: String(error?.message || error),
          stack: String(error?.stack || ''),
          phase: 'render',
        }),
      }).catch(() => {})
    } catch {
      /* ignore */
    }
  }

  render() {
    if (this.state.error) {
      const text = String(
        this.state.error?.stack || this.state.error?.message || this.state.error
      )
      return (
        <div
          style={{
            padding: 24,
            fontFamily: 'monospace',
            color: '#b91c1c',
            background: '#fff',
            minHeight: '100vh',
            boxSizing: 'border-box',
          }}
        >
          <h2 style={{ marginTop: 0 }}>应用运行出错（已被顶层错误边界捕获）</h2>
          <p style={{ fontSize: 13, color: '#7f1d1d' }}>
            这不是空白页，而是渲染时抛出的真实错误。请把下方红框里的文字复制发给我，即可定位修复。
          </p>
          <pre
            style={{
              whiteSpace: 'pre-wrap',
              fontSize: 12,
              background: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: 8,
              padding: 12,
              maxHeight: '60vh',
              overflow: 'auto',
            }}
          >
            {text}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 12,
              padding: '8px 16px',
              borderRadius: 6,
              border: 'none',
              background: '#6366f1',
              color: '#fff',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            重新加载
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
