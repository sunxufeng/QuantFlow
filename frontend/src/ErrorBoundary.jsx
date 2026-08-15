import { Component } from 'react'

// 带「缓存破坏」整页刷新的错误边界。
// 捕获到渲染错误时，直接强制刷新当前路径（追加 _cb 时间戳，确保拉到最新 index.html + bundle）。
// 现已不再使用「构建号路径隔离」：index.html 走 no-store、bundle 文件名带内容哈希，天然防陈旧缓存。
// 防死循环：同一构建号只自动刷新一次（用 sessionStorage 记录），若仍报错说明是新代码真实 bug。

async function goFreshEntry() {
  try {
    const url = new URL(window.location.href)
    url.searchParams.set('_cb', String(Date.now()))
    window.location.replace(url.pathname + url.search + url.hash)
  } catch {
    window.location.reload(true)
  }
}

function alreadyFixedFor(build) {
  try {
    return sessionStorage.getItem('qf_last_fix') === build
  } catch {
    return false
  }
}
function markFixedFor(build) {
  try {
    sessionStorage.setItem('qf_last_fix', build || '')
  } catch { /* ignore */ }
}

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
    try {
      fetch('/version.json', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .then((v) => {
          const build = v && v.build
          if (build && !alreadyFixedFor(build)) {
            markFixedFor(build)
            // 延迟一点，确保用户能看到「正在修复」提示
            setTimeout(goFreshEntry, 700)
          }
        })
        .catch(() => {})
    } catch {
      /* ignore */
    }
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
            <div className="qf-hint" style={{ marginBottom: 12 }}>
              检测到可能是「陈旧缓存的旧代码」导致，可点击下方按钮强制跳转到最新版本。
            </div>
            <button className="qf-btn qf-btn-primary" onClick={goFreshEntry}>
              立即强制刷新
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
