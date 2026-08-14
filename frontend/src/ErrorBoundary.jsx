import { Component } from 'react'

// 带「缓存破坏」整页刷新的错误边界。
// 根因：前端由 node server.mjs 托管，域名前还有阿里云 CDN，会缓存 index.html 与带 hash 的 bundle。
// 一旦浏览器/CDN 保留了「发版前的旧 bundle」，点击某些视图就会执行旧代码（如历史 setView is not defined），
// 且普通刷新仍请求同一个被缓存的 index.html，导致错误复发。
// 解决：捕获到渲染错误时，做一次「带缓存破坏参数」的整页刷新（?_cb=<时间戳>），
// 让 CDN/浏览器无法命中被缓存的 index.html，从而拉取到最新 index.html + 最新 bundle。
// 若已带 _cb 仍报错，说明是新代码真实 bug，停止自动刷新以免死循环，改为展示错误 + 手动按钮。

function cacheBustReload() {
  try {
    const url = new URL(window.location.href)
    url.searchParams.set('_cb', String(Date.now()))
    window.location.replace(url.pathname + url.search + url.hash)
  } catch {
    window.location.reload(true)
  }
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
      const alreadyBusted = new URL(window.location.href).searchParams.has('_cb')
      if (!alreadyBusted) {
        // 延迟一点，确保用户能看到「正在修复」提示；旧 bundle 引发的错误会被这次刷新彻底解决
        setTimeout(cacheBustReload, 700)
      }
    } catch {
      /* ignore */
    }
  }

  render() {
    if (this.state.error) {
      const alreadyBusted = (() => {
        try {
          return new URL(window.location.href).searchParams.has('_cb')
        } catch {
          return false
        }
      })()
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
            {alreadyBusted ? (
              <div className="qf-hint" style={{ marginBottom: 12 }}>
                已尝试刷新到最新版本仍报错，可能是新代码的真实异常。请检查网络或联系管理员。
              </div>
            ) : (
              <div className="qf-hint" style={{ marginBottom: 12 }}>
                检测到可能是「陈旧缓存的旧代码」导致，正在自动刷新到最新版本…
              </div>
            )}
            <button className="qf-btn qf-btn-primary" onClick={cacheBustReload}>
              立即强制刷新
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
