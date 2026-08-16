import { useCallback, useEffect, useState } from 'react'
import { brokerGetConfig, getToken, getLivePositions, getLiveFills, verifyOrder, marketSession } from './api.js'

const SYMBOL_HINT = '示例：600519（贵州茅台）、000001（平安银行）、AAPL'

function authHeaders() {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

export default function Trading({ onNavigate }) {
  const [summary, setSummary] = useState(null)
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [tab, setTab] = useState('trade')           // trade | analytics
  const [mode, setMode] = useState('paper')        // paper | live
  const [liveCapable, setLiveCapable] = useState(false)
  const [liveStatus, setLiveStatus] = useState(null)
  const [broker, setBroker] = useState(null)
  const [form, setForm] = useState({ symbol: '', side: 'buy', type: 'market', qty: '', price: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [account, setAccount] = useState(null)
  const [resetCash, setResetCash] = useState('')
  const [resetMsg, setResetMsg] = useState('')
  const [livePositions, setLivePositions] = useState([])
  const [liveFills, setLiveFills] = useState([])
  const [session, setSession] = useState(null)          // V104 市场时段
  const [verifyRes, setVerifyRes] = useState(null)        // V104 合规预检结果
  const [verifyBusy, setVerifyBusy] = useState(false)

  const load = useCallback(() => {
    return Promise.all([
      fetch('/api/trading/summary', { headers: authHeaders() }).then(r => r.json()).catch(() => null),
      fetch('/api/trading/positions', { headers: authHeaders() }).then(r => r.json()).catch(() => []),
      fetch('/api/trading/orders', { headers: authHeaders() }).then(r => r.json()).catch(() => []),
      fetch('/api/trading/analytics', { headers: authHeaders() }).then(r => r.json()).catch(() => null),
      fetch('/api/trading/account', { headers: authHeaders() }).then(r => r.json()).catch(() => null),
    ]).then(([s, p, o, a, acct]) => {
      setSummary(s)
      setPositions(p || [])
      setOrders(o || [])
      setAnalytics(a)
      if (acct) {
        setAccount(acct)
        if (!resetCash) setResetCash(String(acct.initial_cash))
      }
    })
  }, [])

  useEffect(() => {
    load()
    brokerGetConfig().then(setBroker).catch(() => {})
    fetch('/api/trading/mode', { headers: authHeaders() })
      .then(r => r.json())
      .then(d => setLiveCapable(!!d.live_capable))
      .catch(() => {})
    fetch('/api/trading/live/status', { headers: authHeaders() })
      .then(r => r.json())
      .then(setLiveStatus)
      .catch(() => {})
    if (liveCapable) {
      getLivePositions().then(setLivePositions).catch(() => setLivePositions([]))
      getLiveFills().then(setLiveFills).catch(() => setLiveFills([]))
    }
    marketSession('stock').then(setSession).catch(() => {})
  }, [load])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    const path = mode === 'live' ? '/api/trading/live/orders' : '/api/trading/orders'
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          symbol: form.symbol,
          side: form.side,
          type: form.type,
          qty: Number(form.qty),
          price: form.type === 'limit' ? Number(form.price) : null,
        }),
      })
      if (!res.ok) {
        const er = await res.json().catch(() => ({}))
        throw new Error(er.detail || `下单失败(${res.status})`)
      }
      setForm({ symbol: '', side: 'buy', type: 'market', qty: '', price: '' })
      if (mode === 'paper') await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const verify = async () => {
    if (!form.symbol || !form.qty) {
      setError('请先填写标的与数量再做合规预检')
      return
    }
    setVerifyBusy(true)
    setVerifyRes(null)
    try {
      const res = await verifyOrder({
        symbol: form.symbol,
        side: form.side,
        type: form.type,
        qty: Number(form.qty),
        price: form.type === 'limit' && form.price ? Number(form.price) : null,
      })
      setVerifyRes(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setVerifyBusy(false)
    }
  }

  const cancel = async (id) => {
    setBusy(true)
    try {
      await fetch(`/api/trading/orders/${id}/cancel`, { method: 'POST', headers: authHeaders() })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const simulate = async () => {
    setBusy(true)
    try {
      await fetch('/api/trading/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: '{}',
      })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    if (!window.confirm('确认重置模拟账户？现金/持仓/委托/成交将清空（初始资金保持当前值）。')) return
    setBusy(true)
    try {
      await fetch('/api/trading/reset', { method: 'DELETE', headers: authHeaders() })
      setResetMsg('')
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const resetToCash = async () => {
    const cash = Number(resetCash)
    if (!cash || cash <= 0) {
      setError('请输入有效的初始资金（正数）')
      return
    }
    if (!window.confirm(`确认将模拟账户重置为初始资金 ${cash.toLocaleString()}？所有现金/持仓/委托/成交将清空。`)) return
    setBusy(true)
    setResetMsg('')
    try {
      const res = await fetch('/api/trading/reset', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ initial_cash: cash }),
      })
      if (!res.ok) {
        const er = await res.json().catch(() => ({}))
        throw new Error(er.detail || `重置失败(${res.status})`)
      }
      const data = await res.json().catch(() => ({}))
      setResetMsg(`账户已重置，初始资金 ${Number(data.initial_cash).toLocaleString()}`)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const liveDisabled = mode === 'live' && !liveCapable

  return (
    <div className="qf-templates" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="qf-templates-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2>交易</h2>
        {/* 面板 / 分析 切换 */}
        <div style={{ display: 'inline-flex', borderRadius: 8, overflow: 'hidden', border: '1px solid #cbd5e1' }}>
          <button type="button" onClick={() => setTab('trade')}
            style={toggleStyle(tab === 'trade', '#6366f1')}>面板</button>
          <button type="button" onClick={() => setTab('analytics')}
            style={toggleStyle(tab === 'analytics', '#0ea5e9')}>分析</button>
        </div>
        {/* 模拟 / 实盘 切换 */}
        <div style={{ display: 'inline-flex', borderRadius: 8, overflow: 'hidden', border: '1px solid #cbd5e1' }}>
          <button type="button" onClick={() => setMode('paper')}
            style={toggleStyle(mode === 'paper', '#6366f1')}>模拟</button>
          <button type="button" onClick={() => setMode('live')}
            style={toggleStyle(mode === 'live', liveCapable ? '#16a34a' : '#94a3b8')}>实盘</button>
        </div>
        <span className="qf-hint">
          券商：{broker?.broker || 'none'}
          {mode === 'live' && (liveCapable ? ' · 已具备实盘条件' : ' · 未配置（请在券商设置填写真实凭证）')}
        </span>
        {mode === 'paper' && (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="qf-btn qf-btn-sm" onClick={simulate} disabled={busy}>模拟行情推进</button>
            <button className="qf-btn qf-btn-sm" onClick={reset} disabled={busy}>重置账户</button>
          </span>
        )}
      </div>

      {error && <div className="qf-error">{error}</div>}

      {/* V6.0 模拟账户：可配置初始资金（纯本地，持久化） */}
      {mode === 'paper' && account && (
        <div style={{ marginTop: 12, border: '1px solid #6366f1', borderRadius: 10, padding: 14, background: '#fafaff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#4338ca', marginBottom: 8 }}>
            模拟账户（V6.0）· 初始资金可配置
          </div>
          <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', marginBottom: 10 }}>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#4338ca' }}>{account.initial_cash.toLocaleString()}</div><div className="qf-mcard-label">初始资金</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{account.cash.toLocaleString()}</div><div className="qf-mcard-label">当前现金</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#6366f1' }}>{account.equity.toLocaleString()}</div><div className="qf-mcard-label">当前权益</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{account.position_count}</div><div className="qf-mcard-label">持仓数</div></div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="qf-prop-field" style={{ margin: 0 }}>
              <span className="qf-prop-label">重置初始资金</span>
              <input className="qf-name-input" type="number" min="1" step="10000" value={resetCash}
                onChange={(e) => setResetCash(e.target.value)} style={{ width: 180 }} />
            </label>
            <button className="qf-btn qf-btn-primary qf-btn-sm" onClick={resetToCash} disabled={busy}>重置为自定义初始资金</button>
            <button className="qf-btn qf-btn-sm" onClick={reset} disabled={busy}>仅清空（保持初始资金）</button>
          </div>
          {resetMsg && <div className="qf-success">{resetMsg}</div>}
          <div className="qf-hint" style={{ marginTop: 6 }}>
            重置后所有现金/持仓/委托/成交清空，权益曲线从指定初始资金重新开始。账户数据按用户隔离、纯本地存储。
          </div>
        </div>
      )}

      {liveDisabled && (
        <div className="qf-hint" style={{ background: '#fff7ed', border: '1px solid #fed7aa', padding: 10, borderRadius: 8, marginBottom: 12 }}>
          实盘模式尚未配置（{liveStatus?.message || '缺少券商凭证'}）。
          请在「券商设置」中选择 universal / easytrade / xuntou 并填写 api_key 等凭证；
          凭证就绪后这里即可切换到真实下单。
          <button className="qf-btn qf-btn-sm" style={{ marginLeft: 8 }} onClick={() => onNavigate && onNavigate('broker')}>去券商设置</button>
        </div>
      )}

      {mode === 'live' && liveCapable && (
        <div className="qf-hint" style={{ background: '#ecfdf5', border: '1px solid #a7f3d0', padding: 10, borderRadius: 8, marginBottom: 12 }}>
          实盘已具备条件（券商：{liveStatus?.broker}）。真实下单/查询已接入 {liveStatus?.broker?.toUpperCase()} 连接器，凭证就绪后直接连线真实柜台。
        </div>
      )}

      {mode === 'live' && liveCapable && (
        <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 320px', minWidth: 300, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>实盘持仓（{liveStatus?.broker?.toUpperCase()} 柜台）</div>
            {livePositions.length === 0 && <div className="qf-prop-hint">暂无实盘持仓</div>}
            {livePositions.length > 0 && (
              <table className="qf-state-table">
                <thead><tr><th>标的</th><th>数量</th><th>均价</th><th>市值</th></tr></thead>
                <tbody>
                  {livePositions.map((p, i) => (
                    <tr key={p.symbol || i}>
                      <td>{p.symbol}</td>
                      <td style={{ color: Number(p.quantity) >= 0 ? '#16a34a' : '#e11d48' }}>{Number(p.quantity).toLocaleString()}</td>
                      <td>{Number(p.avg_cost).toFixed(2)}</td>
                      <td>{p.market_value != null ? Number(p.market_value).toLocaleString() : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div style={{ flex: '1 1 320px', minWidth: 300, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>实盘成交</div>
            {liveFills.length === 0 && <div className="qf-prop-hint">暂无实盘成交</div>}
            {liveFills.length > 0 && (
              <table className="qf-state-table">
                <thead><tr><th>标的</th><th>方向</th><th>数量</th><th>价格</th></tr></thead>
                <tbody>
                  {liveFills.map((f, i) => (
                    <tr key={i}>
                      <td>{f.symbol}</td>
                      <td style={{ color: f.side === 'buy' ? '#16a34a' : '#e11d48' }}>{f.side === 'buy' ? '买' : '卖'}</td>
                      <td>{Number(f.quantity).toLocaleString()}</td>
                      <td>{Number(f.price).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', marginTop: 12 }}>
        <div className="qf-mcard"><div className="qf-mcard-value">{summary ? summary.cash.toLocaleString() : '-'}</div><div className="qf-mcard-label">现金</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{summary ? summary.market_value.toLocaleString() : '-'}</div><div className="qf-mcard-label">持仓市值</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#6366f1' }}>{summary ? summary.equity.toLocaleString() : '-'}</div><div className="qf-mcard-label">总资产</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: summary && summary.realized_pnl >= 0 ? '#e11d48' : '#0891b2' }}>{summary ? summary.realized_pnl.toLocaleString() : '-'}</div><div className="qf-mcard-label">已实现盈亏</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{summary ? summary.position_count : '-'}</div><div className="qf-mcard-label">持仓数</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{summary ? summary.open_orders : '-'}</div><div className="qf-mcard-label">挂单</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#0891b2' }}>{summary ? summary.total_fees.toLocaleString() : '-'}</div><div className="qf-mcard-label">累计手续费</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{summary ? (summary.win_rate * 100).toFixed(0) + '%' : '-'}</div><div className="qf-mcard-label">胜率</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{summary ? (summary.exposure * 100).toFixed(0) + '%' : '-'}</div><div className="qf-mcard-label">持仓敞口</div></div>
      </div>

      {summary && summary.equity_curve && summary.equity_curve.length > 1 && (
        <div style={{ marginTop: 14, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>权益曲线（模拟账户）</div>
          <EquitySparkline data={summary.equity_curve} initial={summary.initial_cash} />
        </div>
      )}

      {tab === 'trade' && (<>
      <div style={{ display: 'flex', gap: 16, marginTop: 18, flexWrap: 'wrap' }}>
        {/* 下单 */}
        <form onSubmit={submit} style={{ flex: '1 1 300px', minWidth: 280, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            下单（{mode === 'live' ? '实盘' : '模拟'}）
            {session && (
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 500,
                background: session.open ? '#dcfce7' : '#fee2e2', color: session.open ? '#166534' : '#991b1b' }}>
                市场{session.open ? '开市' : '休市'}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <button type="button" onClick={() => setForm(f => ({ ...f, side: 'buy' }))}
              style={btnStyle(form.side === 'buy', '#16a34a')}>买入</button>
            <button type="button" onClick={() => setForm(f => ({ ...f, side: 'sell' }))}
              style={btnStyle(form.side === 'sell', '#e11d48')}>卖出</button>
          </div>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">标的代码</span>
            <input className="qf-name-input" value={form.symbol} onChange={(e) => setForm(f => ({ ...f, symbol: e.target.value }))}
              placeholder={SYMBOL_HINT} required />
          </label>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">委托类型</span>
            <select className="qf-name-input" value={form.type} onChange={(e) => setForm(f => ({ ...f, type: e.target.value }))}>
              <option value="market">市价</option>
              <option value="limit">限价</option>
            </select>
          </label>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">数量（股）</span>
            <input className="qf-name-input" type="number" min="1" value={form.qty} onChange={(e) => setForm(f => ({ ...f, qty: e.target.value }))} required />
          </label>
          {form.type === 'limit' && (
            <label className="qf-prop-field" style={{ marginBottom: 10 }}>
              <span className="qf-prop-label">限价</span>
              <input className="qf-name-input" type="number" min="0" step="0.01" value={form.price} onChange={(e) => setForm(f => ({ ...f, price: e.target.value }))} required />
            </label>
          )}
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy || liveDisabled} style={{ width: '100%' }}>
            {busy ? '提交中…' : mode === 'live' ? '实盘委托' : '提交委托'}
          </button>
          <button type="button" onClick={verify} disabled={verifyBusy} className="qf-btn" style={{ width: '100%', marginTop: 8 }}>
            {verifyBusy ? '校验中…' : '交易合规预检'}
          </button>
          {verifyRes && (
            <div style={{ marginTop: 10, fontSize: 12 }}>
              {verifyRes.violations.length === 0 && (
                <div style={{ color: '#166534', background: '#dcfce7', padding: '8px 10px', borderRadius: 8 }}>✓ 合规检查通过，无拦截项</div>
              )}
              {verifyRes.violations.map((v, i) => (
                <div key={i} style={{ color: v.level === 'error' ? '#991b1b' : '#92400e',
                  background: v.level === 'error' ? '#fee2e2' : '#fef3c7', padding: '6px 10px', borderRadius: 8, marginBottom: 6 }}>
                  {v.level === 'error' ? '✕ ' : '⚠ '}{v.message}
                </div>
              ))}
              {verifyRes.suggestions.map((s, i) => (
                <div key={`s${i}`} style={{ color: '#1e40af', background: '#dbeafe', padding: '6px 10px', borderRadius: 8, marginBottom: 6 }}>💡 {s}</div>
              ))}
            </div>
          )}
        </form>

        {/* 持仓 */}
        <div style={{ flex: '2 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>持仓</div>
          {positions.length === 0 && <div className="qf-prop-hint">暂无持仓</div>}
          {positions.length > 0 && (
            <table className="qf-state-table">
              <thead><tr><th>标的</th><th>数量</th><th>均价</th><th>已实现盈亏</th></tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.symbol}>
                    <td>{p.symbol}</td>
                    <td style={{ color: Number(p.qty) >= 0 ? '#16a34a' : '#e11d48' }}>{Number(p.qty).toLocaleString()}</td>
                    <td>{Number(p.avg_cost).toFixed(2)}</td>
                    <td style={{ color: Number(p.realized_pnl) >= 0 ? '#e11d48' : '#0891b2' }}>{Number(p.realized_pnl).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* 委托（仅模拟模式维护挂单/成交流水） */}
      {mode === 'paper' && (
        <div style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>委托记录</div>
          {orders.length === 0 && <div className="qf-prop-hint">暂无委托</div>}
          {orders.length > 0 && (
            <table className="qf-state-table">
              <thead><tr><th>时间</th><th>标的</th><th>方向</th><th>类型</th><th>数量</th><th>价格</th><th>状态</th><th>操作</th></tr></thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td className="qf-hint">{o.created_at}</td>
                    <td>{o.symbol}</td>
                    <td style={{ color: o.side === 'buy' ? '#16a34a' : '#e11d48' }}>{o.side === 'buy' ? '买入' : '卖出'}</td>
                    <td>{o.type === 'market' ? '市价' : '限价'}</td>
                    <td>{Number(o.qty).toLocaleString()}</td>
                    <td>{o.price != null ? Number(o.price).toFixed(2) : '市价'}</td>
                    <td>{statusLabel(o.status)}</td>
                    <td>
                      {o.status === 'open' && (
                        <button className="qf-btn qf-btn-sm" onClick={() => cancel(o.id)} disabled={busy}>撤单</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      </>
      )}

      {tab === 'analytics' && analytics && (
        <AnalyticsPanel data={analytics} initial={analytics.equity_curve?.[0]?.equity || summary?.initial_cash || 1_000_000} />
      )}
    </div>
  )
}

function AnalyticsPanel({ data, initial }) {
  const pct = (v) => (v * 100).toFixed(1) + '%'
  return (
    <div style={{ marginTop: 18 }}>
      <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: data.max_drawdown < 0 ? '#e11d48' : '#16a34a' }}>{pct(data.max_drawdown)}</div><div className="qf-mcard-label">最大回撤</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{data.total_trades}</div><div className="qf-mcard-label">交易笔数</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value">{pct(data.win_rate)}</div><div className="qf-mcard-label">胜率</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#0891b2' }}>{data.profit_factor}</div><div className="qf-mcard-label">盈利因子</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#16a34a' }}>{data.avg_win.toLocaleString()}</div><div className="qf-mcard-label">平均盈利</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#e11d48' }}>{data.avg_loss.toLocaleString()}</div><div className="qf-mcard-label">平均亏损</div></div>
      </div>

      {data.equity_curve && data.equity_curve.length > 1 && (
        <div style={{ marginTop: 14, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 8 }}>权益曲线</div>
          <EquitySparkline data={data.equity_curve} initial={initial} />
        </div>
      )}

      <div style={{ marginTop: 14, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>逐标的盈亏（已实现）</div>
        {(!data.trades || data.trades.length === 0) && <div className="qf-prop-hint">暂无已平仓交易</div>}
        {data.trades && data.trades.length > 0 && (
          <table className="qf-state-table">
            <thead><tr><th>标的</th><th>已实现盈亏</th><th>结果</th></tr></thead>
            <tbody>
              {data.trades.map((t) => (
                <tr key={t.symbol}>
                  <td>{t.symbol}</td>
                  <td style={{ color: Number(t.realized_pnl) >= 0 ? '#16a34a' : '#e11d48' }}>{Number(t.realized_pnl).toLocaleString()}</td>
                  <td>{Number(t.realized_pnl) >= 0 ? '盈利' : '亏损'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

function toggleStyle(active, color) {
  return {
    padding: '6px 16px',
    border: 'none',
    background: active ? color : '#fff',
    color: active ? '#fff' : 'var(--text)',
    cursor: 'pointer',
    fontSize: 12,
  }
}

function btnStyle(active, color) {
  return {
    flex: 1,
    padding: '8px 0',
    borderRadius: 8,
    border: `1px solid ${active ? color : '#cbd5e1'}`,
    background: active ? color : '#fff',
    color: active ? '#fff' : 'var(--text)',
    cursor: 'pointer',
    fontSize: 12,
  }
}

function statusLabel(s) {
  return { open: '挂单', filled: '已成交', cancelled: '已撤单', rejected: '已拒绝' }[s] || s
}

function EquitySparkline({ data, initial }) {
  const W = 720, H = 120, PAD = 8
  const pts = data.map(d => d.equity)
  const min = Math.min(initial, ...pts)
  const max = Math.max(initial, ...pts)
  const span = (max - min) || 1
  const stepX = data.length > 1 ? (W - PAD * 2) / (data.length - 1) : 0
  const coords = data.map((d, i) => {
    const x = PAD + (data.length > 1 ? i * stepX : W / 2)
    const y = PAD + (1 - (d.equity - min) / span) * (H - PAD * 2)
    return [x, y]
  })
  const path = coords.map((c, i) => (i === 0 ? 'M' : 'L') + c[0].toFixed(1) + ' ' + c[1].toFixed(1)).join(' ')
  const last = coords[coords.length - 1]
  const up = pts[pts.length - 1] >= initial
  const color = up ? '#16a34a' : '#e11d48'
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img" aria-label="权益曲线">
      <line x1={PAD} y1={PAD + (1 - (initial - min) / span) * (H - PAD * 2)} x2={W - PAD} y2={PAD + (1 - (initial - min) / span) * (H - PAD * 2)}
        stroke="#cbd5e1" strokeDasharray="4 4" strokeWidth="1" />
      <path d={path} fill="none" stroke={color} strokeWidth="2" />
      <circle cx={last[0]} cy={last[1]} r="3" fill={color} />
      <text x={PAD} y={PAD + 10} fontSize="10" fill="#94a3b8">高 {max.toLocaleString()}</text>
      <text x={PAD} y={H - PAD} fontSize="10" fill="#94a3b8">低 {min.toLocaleString()}</text>
    </svg>
  )
}
