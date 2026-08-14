import { Component } from 'react'

// 防止单个视图渲染异常导致整页白屏：捕获后显示可读错误信息 + 重置按钮。
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary]', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            flex: 1,
            padding: 24,
            overflowY: 'auto',
            color: '#0f172a',
            fontFamily: 'inherit',
          }}
        >
          <div
            style={{
              border: '1px solid #fecaca',
              background: '#fef2f2',
              borderRadius: 8,
              padding: 16,
              maxWidth: 720,
              margin: '0 auto',
            }}
          >
            <div style={{ fontWeight: 700, color: '#b91c1c', marginBottom: 8 }}>
              页面渲染出错
            </div>
            <div style={{ fontSize: 13, color: '#7f1d1d', whiteSpace: 'pre-wrap', marginBottom: 12 }}>
              {String(this.state.error?.message || this.state.error)}
            </div>
            <button
              className="qf-btn qf-btn-primary"
              onClick={() => this.setState({ error: null })}
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
