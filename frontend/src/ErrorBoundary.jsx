import { Component } from 'react'

// 带「缓存破坏」整页刷新的错误边界。
// 根因：前端由 node server.mjs 托管，域名前还有阿里云 CDN，会把 index.html 与 bundle 缓存起来。
// 一旦浏览器/CDN 保留了「发版前的旧 bundle」，点击某些视图就会执行旧代码（如历史 setView is not defined），
// 且普通刷新仍请求同一个被缓存的 index.html，导致错误复发。
// 解决：捕获到渲染错误时，直接跳转到「最新构建号专属入口 /<build>/」（每次发版路径都不同，
// 浏览器/CDN 永远无法命中旧缓存），从而彻底拉取最新 index.html + 最新 bundle。
// 防死循环：同一构建号只自动跳转一次（用 sessionStorage 记录），若仍报错说明是新代码真实 bug。

async function goFreshEntry() {
  try {
    const res = await fetch('/version.json', { cache: 'no-store' })
    const v = await res.json()
    if (v && v.build) {
      window.location.replace('/' + v.build + '/')
      return
    }
  } catch { /* ignore，落到下面的兜底 */ }
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
