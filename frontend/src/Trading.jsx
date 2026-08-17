import { useCallback, useEffect, useState } from 'react'
import { brokerGetConfig, brokerSaveConfig, getToken, getLivePositions, getLiveFills, getLiveAccount, verifyOrder, marketSession, hedgeCalc, getAdapters, futuresSpecs, futuresCalc, optionsCalc } from './api.js'

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
  const [tab, setTab] = useState('trade')           // trade | analytics | hedge | adapters | futures | options
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
  const [adapters, setAdapters] = useState(null)          // V106 适配器目录
  const [liveAccount, setLiveAccount] = useState(null)     // V107 实盘账户/盈亏监控
  const [enablingVirtual, setEnablingVirtual] = useState(false)  // V107 启用虚拟券商

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
      refreshLive()
    }
    marketSession('stock').then(setSession).catch(() => {})
    getAdapters().then(setAdapters).catch(() => setAdapters(null))
  }, [load])

  const refreshLive = useCallback(() => {
    if (!liveCapable) return
    getLivePositions().then(setLivePositions).catch(() => setLivePositions([]))
    getLiveFills().then(setLiveFills).catch(() => setLiveFills([]))
    getLiveAccount().then(setLiveAccount).catch(() => setLiveAccount(null))
  }, [liveCapable])

  const enableVirtual = async () => {
    setEnablingVirtual(true)
    setError('')
    try {
      await brokerSaveConfig({ broker: 'virtual' })
      const [brk, mode, status] = await Promise.all([
        brokerGetConfig().catch(() => null),
        fetch('/api/trading/mode', { headers: authHeaders() }).then(r => r.json()).catch(() => null),
        fetch('/api/trading/live/status', { headers: authHeaders() }).then(r => r.json()).catch(() => null),
      ])
      if (brk) setBroker(brk)
      if (mode) setLiveCapable(!!mode.live_capable)
      if (status) setLiveStatus(status)
      setMode('live')
      refreshLive()
    } catch (err) {
      setError(err.message)
    } finally {
      setEnablingVirtual(false)
    }
  }

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
      else if (mode === 'live') refreshLive()
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
          <button type="button" onClick={() => setTab('hedge')}
            style={toggleStyle(tab === 'hedge', '#f59e0b')}>对冲</button>
          <button type="button" onClick={() => setTab('adapters')}
            style={toggleStyle(tab === 'adapters', '#10b981')}>连接</button>
          <button type="button" onClick={() => setTab('futures')}
            style={toggleStyle(tab === 'futures', '#ef4444')}>期货</button>
          <button type="button" onClick={() => setTab('options')}
            style={toggleStyle(tab === 'options', '#8b5cf6')}>期权</button>
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
          可先启用<b>虚拟券商</b>（等价 CTP/QMT 接口，本地账本撮合，无需任何凭证），体验完整实盘下单/持仓/盈亏监控流程：
          <button className="qf-btn qf-btn-primary qf-btn-sm" style={{ marginLeft: 8 }} onClick={enableVirtual} disabled={enablingVirtual}>
            {enablingVirtual ? '启用中…' : '启用虚拟券商（无需凭证）'}
          </button>
          <button className="qf-btn qf-btn-sm" style={{ marginLeft: 4 }} onClick={() => onNavigate && onNavigate('broker')}>去券商设置</button>
        </div>
      )}

      {mode === 'live' && liveCapable && (
        <div className="qf-hint" style={{ background: '#ecfdf5', border: '1px solid #a7f3d0', padding: 10, borderRadius: 8, marginBottom: 12 }}>
          {liveStatus?.broker === 'virtual'
            ? '虚拟券商已就绪：等价 CTP/QMT 接口，本地账本撮合，无需凭证/SDK（用于前向测试与演示）。'
            : `实盘已具备条件（券商：${liveStatus?.broker}）。真实下单/查询已接入 ${liveStatus?.broker?.toUpperCase()} 连接器，凭证就绪后直接连线真实柜台。`}
        </div>
      )}

      {mode === 'live' && liveCapable && liveAccount && (
        <div style={{ marginTop: 12, border: '1px solid #16a34a', borderRadius: 10, padding: 14, background: '#f0fdf4' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#15803d', marginBottom: 8 }}>
            实盘账户监控（V107 · 权益 / 盈亏）
          </div>
          <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(liveAccount.equity).toLocaleString()}</div><div className="qf-mcard-label">账户权益</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(liveAccount.cash).toLocaleString()}</div><div className="qf-mcard-label">可用现金</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(liveAccount.market_value).toLocaleString()}</div><div className="qf-mcard-label">持仓市值</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: Number(liveAccount.pnl) >= 0 ? '#e11d48' : '#0891b2' }}>{Number(liveAccount.pnl).toLocaleString()}</div><div className="qf-mcard-label">累计盈亏</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: Number(liveAccount.pnl_pct) >= 0 ? '#e11d48' : '#0891b2' }}>{Number(liveAccount.pnl_pct).toFixed(2)}%</div><div className="qf-mcard-label">收益率</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(liveAccount.initial_cash).toLocaleString()}</div><div className="qf-mcard-label">初始资金</div></div>
          </div>
          <div className="qf-hint" style={{ marginTop: 6 }}>对手方来源：{liveAccount.mode} · 实时刷新请点击下方「刷新实盘」。</div>
        </div>
      )}

      {mode === 'live' && liveCapable && (
        <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 320px', minWidth: 300, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)' }}>实盘持仓（{liveStatus?.broker?.toUpperCase()} 柜台）</div>
              <button type="button" className="qf-btn qf-btn-sm" style={{ marginLeft: 'auto' }} onClick={refreshLive}>刷新实盘</button>
            </div>
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

      {tab === 'hedge' && <HedgeCalculator />}

      {tab === 'adapters' && <AdaptersPanel data={adapters} onNavigate={onNavigate} onRefresh={load} />}

      {tab === 'futures' && <FuturesCalculator />}
      {tab === 'options' && <OptionsCalculator />}
    </div>
  )
}

function HedgeCalculator() {
  const [kind, setKind] = useState('beta')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [res, setRes] = useState(null)

  // beta 对冲
  const [portfolioText, setPortfolioText] = useState(
    '[\n  {"symbol":"600519.SH","market_value":300000,"beta":1.05},\n  {"symbol":"000001.SZ","market_value":200000,"beta":1.20}\n]'
  )
  const [futurePrice, setFuturePrice] = useState('3800')
  const [multiplier, setMultiplier] = useState('300')
  const [targetBeta, setTargetBeta] = useState('0')
  const [futureBeta, setFutureBeta] = useState('1')

  // reverse 反向
  const [currentQty, setCurrentQty] = useState('100')
  const [mode, setMode] = useState('close')

  // group 篮子
  const [longText, setLongText] = useState('{"AG2110.SHF":15}')
  const [shortText, setShortText] = useState('{}')
  const [pricesText, setPricesText] = useState('{}')

  const parse = (txt, fallback) => {
    try { return JSON.parse(txt) } catch (e) { throw new Error('JSON 解析失败：' + e.message) }
  }

  const calc = async () => {
    setBusy(true)
    setError('')
    setRes(null)
    try {
      let payload
      if (kind === 'beta') {
        payload = {
          kind: 'beta',
          portfolio: parse(portfolioText),
          future_price: Number(futurePrice),
          multiplier: Number(multiplier),
          target_beta: Number(targetBeta),
          future_beta: Number(futureBeta),
        }
      } else if (kind === 'reverse') {
        payload = { kind: 'reverse', current_qty: Number(currentQty), mode }
      } else {
        payload = {
          kind: 'group',
          long_dict: parse(longText),
          short_dict: parse(shortText),
          prices: parse(pricesText),
        }
      }
      const data = await hedgeCalc(payload)
      setRes(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const card = { flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>
        对冲 / 反向交易计算器（V105 · 移植自 panda reverse_operation 计算内核）
      </div>
      {error && <div className="qf-error">{error}</div>}

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <button type="button" onClick={() => setKind('beta')} style={toggleStyle(kind === 'beta', '#f59e0b')}>Beta 中性对冲</button>
        <button type="button" onClick={() => setKind('reverse')} style={toggleStyle(kind === 'reverse', '#f59e0b')}>反向平仓 / 反手</button>
        <button type="button" onClick={() => setKind('group')} style={toggleStyle(kind === 'group', '#f59e0b')}>多空篮子组单</button>
      </div>

      {kind === 'beta' && (
        <div style={{ ...card }}>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">股票组合（JSON：[{'{'}"symbol, market_value, beta{'}'}]）</span>
            <textarea className="qf-name-input" rows={5} value={portfolioText}
              onChange={(e) => setPortfolioText(e.target.value)} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </label>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">期货点位</span>
              <input className="qf-name-input" type="number" value={futurePrice} onChange={(e) => setFuturePrice(e.target.value)} />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">合约乘数</span>
              <input className="qf-name-input" type="number" value={multiplier} onChange={(e) => setMultiplier(e.target.value)} />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">目标β</span>
              <input className="qf-name-input" type="number" step="0.1" value={targetBeta} onChange={(e) => setTargetBeta(e.target.value)} />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">合约β</span>
              <input className="qf-name-input" type="number" step="0.1" value={futureBeta} onChange={(e) => setFutureBeta(e.target.value)} />
            </label>
          </div>
        </div>
      )}

      {kind === 'reverse' && (
        <div style={{ ...card }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <button type="button" onClick={() => setMode('close')} style={btnStyle(mode === 'close', '#f59e0b')}>平仓至 0</button>
            <button type="button" onClick={() => setMode('flip')} style={btnStyle(mode === 'flip', '#f59e0b')}>反手</button>
          </div>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">当前持仓数量（正=多 / 负=空）</span>
            <input className="qf-name-input" type="number" value={currentQty} onChange={(e) => setCurrentQty(e.target.value)} />
          </label>
          <div className="qf-hint">例如当前多仓 100 → 平仓需卖出 100；反手需卖出 200（平多+开空）。</div>
        </div>
      )}

      {kind === 'group' && (
        <div style={{ ...card }}>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">多头篮子 long_dict（JSON：{'{'}"SYM":qty{'}'}）</span>
            <textarea className="qf-name-input" rows={3} value={longText}
              onChange={(e) => setLongText(e.target.value)} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </label>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">空头篮子 short_dict（JSON：{'{'}"SYM":qty{'}'}）</span>
            <textarea className="qf-name-input" rows={3} value={shortText}
              onChange={(e) => setShortText(e.target.value)} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </label>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">价格 prices（可选，用于名义金额：{'{'}"SYM":price{'}'}）</span>
            <textarea className="qf-name-input" rows={2} value={pricesText}
              onChange={(e) => setPricesText(e.target.value)} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          </label>
          <div className="qf-hint">对应 panda insert_future_group_order / insert_stock_group_order 的篮子组单。</div>
        </div>
      )}

      <button className="qf-btn qf-btn-primary" onClick={calc} disabled={busy} style={{ marginTop: 12 }}>
        {busy ? '计算中…' : '计算'}
      </button>

      {res && (
        <div style={{ marginTop: 14, border: '1px solid #f59e0b', borderRadius: 10, padding: 14, background: '#fffbeb' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#b45309', marginBottom: 8 }}>
            计算结果（{res.kind}）
          </div>
          {res.kind === 'beta' && (
            <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.portfolio_beta}</div><div className="qf-mcard-label">组合贝塔</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.portfolio_value.toLocaleString()}</div><div className="qf-mcard-label">组合市值</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#b45309' }}>{res.contracts}</div><div className="qf-mcard-label">对冲手数</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.side_label}</div><div className="qf-mcard-label">方向</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.hedge_notional.toLocaleString()}</div><div className="qf-mcard-label">对冲名义</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.residual_beta}</div><div className="qf-mcard-label">残差贝塔</div></div>
            </div>
          )}
          {res.kind === 'reverse' && (
            <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.current_qty}</div><div className="qf-mcard-label">当前持仓</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.order_side_label}</div><div className="qf-mcard-label">下单方向</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#b45309' }}>{res.order_qty}</div><div className="qf-mcard-label">下单数量</div></div>
              <div className="qf-mcard"><div className="qf-mcard-value">{res.mode}</div><div className="qf-mcard-label">模式</div></div>
            </div>
          )}
          {res.kind === 'group' && (
            <>
              <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', marginBottom: 10 }}>
                <div className="qf-mcard"><div className="qf-mcard-value">{res.long_count}</div><div className="qf-mcard-label">多头只数</div></div>
                <div className="qf-mcard"><div className="qf-mcard-value">{res.short_count}</div><div className="qf-mcard-label">空头只数</div></div>
                <div className="qf-mcard"><div className="qf-mcard-value">{res.net_notional.toLocaleString()}</div><div className="qf-mcard-label">净敞口</div></div>
              </div>
              <table className="qf-state-table">
                <thead><tr><th>标的</th><th>方向</th><th>数量</th></tr></thead>
                <tbody>
                  {res.orders.map((o, i) => (
                    <tr key={i}>
                      <td>{o.symbol}</td>
                      <td style={{ color: o.side === 'buy' ? '#16a34a' : '#e11d48' }}>{o.side === 'buy' ? '买入' : '卖出'}</td>
                      <td>{o.qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div className="qf-success" style={{ marginTop: 10 }}>{res.note}</div>
        </div>
      )}
    </div>
  )
}

function AdaptersPanel({ data, onNavigate, onRefresh }) {
  if (!data) {
    return (
      <div style={{ marginTop: 18, color: '#64748b', fontSize: 13 }}>加载适配器目录中…</div>
    )
  }
  const badge = (ok) => (
    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, fontWeight: 600,
      background: ok ? '#dcfce7' : '#fee2e2', color: ok ? '#166534' : '#991b1b' }}>
      {ok ? '已就绪' : '未配置'}
    </span>
  )
  const Section = ({ title, items, accent }) => (
    <div style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: accent, marginBottom: 10 }}>{title}</div>
      {items.length === 0 && <div className="qf-prop-hint">暂无</div>}
      {items.map((a, i) => (
        <div key={a.id || i} style={{ border: '1px solid #eef2f7', borderRadius: 8, padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 13 }}>{a.name}</span>
            {badge(!!a.configured)}
            <span className="qf-hint" style={{ marginLeft: 'auto' }}>{a.mode}</span>
          </div>
          <div className="qf-hint" style={{ marginTop: 4 }}>{a.note}</div>
          {a.required_env && a.required_env.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: '#64748b' }}>
              所需：{a.required_env.join('、')}{a.required_sdk ? ` + ${a.required_sdk}` : ''}
            </div>
          )}
        </div>
      ))}
    </div>
  )
  const s = data.summary || {}
  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>
        适配器与连接（V106 · panda 多源接口缝）
      </div>
      <div className="qf-hint" style={{ marginBottom: 8 }}>
        覆盖 panda_quantflow 的 Tushare / CTP / QMT / 数字货币 等多源行情与实盘柜台。
        已就绪项可直接使用；未配置项为接口缝，配齐凭证/SDK 后即接入真实连接，无需改动上层。
      </div>
      <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#10b981' }}>{s.configured_market || 0}/{s.total_market || 0}</div><div className="qf-mcard-label">市场源就绪</div></div>
        <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#6366f1' }}>{s.configured_brokers || 0}/{s.total_brokers || 0}</div><div className="qf-mcard-label">券商就绪</div></div>
      </div>

      <Section title="市场数据源" items={data.market_sources || []} accent="#10b981" />
      <Section title="券商连接器" items={data.brokers || []} accent="#6366f1" />

      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="qf-btn qf-btn-sm" onClick={() => onRefresh && onRefresh()}>刷新</button>
        <button className="qf-btn qf-btn-sm" onClick={() => onNavigate && onNavigate('broker')}>去券商设置</button>
      </div>
    </div>
  )
}

function FuturesCalculator() {
  const [specs, setSpecs] = useState([])
  const [symbol, setSymbol] = useState('IF2409')
  const [price, setPrice] = useState('3800')
  const [qty, setQty] = useState('1')
  const [prevClose, setPrevClose] = useState('')
  const [marginRate, setMarginRate] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    futuresSpecs().then(setSpecs).catch(() => setSpecs([]))
  }, [])

  const calc = async () => {
    setBusy(true)
    setError('')
    setRes(null)
    try {
      const data = await futuresCalc({
        symbol,
        price: Number(price),
        qty: Number(qty),
        prev_close: prevClose ? Number(prevClose) : undefined,
        margin_rate: marginRate ? Number(marginRate) : undefined,
      })
      setRes(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const selected = specs.find(s => symbol && s.code.toLowerCase() === symbol.replace(/\d|\..*/g, '').toLowerCase())
  const card = { flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>
        期货品种规格与计算器（V108 · 移植自 panda FutureInfoMap 品种元数据）
      </div>
      {error && <div className="qf-error">{error}</div>}

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ ...card }}>
          <label className="qf-prop-field" style={{ marginBottom: 10 }}>
            <span className="qf-prop-label">品种（输入合约或选择）</span>
            <input className="qf-name-input" list="futures-specs" value={symbol}
              onChange={(e) => setSymbol(e.target.value)} placeholder="如 IF2409 / cu2501 / sc2501" />
            <datalist id="futures-specs">
              {specs.map((s) => (
                <option key={s.code} value={s.code}>{s.name}（{s.exchange_name}）</option>
              ))}
            </datalist>
          </label>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">价格</span>
              <input className="qf-name-input" type="number" value={price} onChange={(e) => setPrice(e.target.value)} />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">手数</span>
              <input className="qf-name-input" type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">昨结算价（算涨跌停）</span>
              <input className="qf-name-input" type="number" value={prevClose} onChange={(e) => setPrevClose(e.target.value)} placeholder="可选" />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">保证金率覆盖</span>
              <input className="qf-name-input" type="number" step="0.01" value={marginRate} onChange={(e) => setMarginRate(e.target.value)} placeholder="默认见规格" />
            </label>
          </div>
          <button className="qf-btn qf-btn-primary" onClick={calc} disabled={busy} style={{ marginTop: 12, width: '100%' }}>
            {busy ? '计算中…' : '计算'}
          </button>
          {selected && (
            <div className="qf-hint" style={{ marginTop: 10 }}>
              规格：{selected.name}（{selected.exchange_name}）· 乘数 {selected.multiplier} · 保证金率 {(selected.margin_rate * 100).toFixed(1)}% · 涨跌停 ±{(selected.price_limit * 100).toFixed(1)}% · 最小价位 {selected.min_tick}
            </div>
          )}
        </div>

        <div style={{ ...card, flex: '1 1 320px' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>全部品种（参考）</div>
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            <table className="qf-state-table">
              <thead><tr><th>品种</th><th>名称</th><th>交易所</th><th>乘数</th><th>保证金</th><th>涨跌停</th></tr></thead>
              <tbody>
                {specs.map((s) => (
                  <tr key={s.code} onClick={() => setSymbol(s.code)} style={{ cursor: 'pointer' }}>
                    <td>{s.code}</td>
                    <td>{s.name}</td>
                    <td>{s.exchange_name}</td>
                    <td>{s.multiplier}</td>
                    <td>{(s.margin_rate * 100).toFixed(1)}%</td>
                    <td>±{(s.price_limit * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="qf-hint" style={{ marginTop: 8 }}>点击行可快速填入品种。保证金率/涨跌停为常用参考值，实盘以交易所与券商为准。</div>
        </div>
      </div>

      {res && (
        <div style={{ marginTop: 14, border: '1px solid #ef4444', borderRadius: 10, padding: 14, background: '#fef2f2' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#b91c1c', marginBottom: 8 }}>
            {res.symbol} 计算结果
          </div>
          <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(res.contract_value_per_lot).toLocaleString()}</div><div className="qf-mcard-label">单手持仓价值</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(res.total_contract_value).toLocaleString()}</div><div className="qf-mcard-label">总持仓价值</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#b91c1c' }}>{Number(res.margin_required).toLocaleString()}</div><div className="qf-mcard-label">保证金占用</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(res.commission).toLocaleString()}</div><div className="qf-mcard-label">手续费</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{res.limit_up != null ? Number(res.limit_up).toLocaleString() : '-'}</div><div className="qf-mcard-label">涨停价</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{res.limit_down != null ? Number(res.limit_down).toLocaleString() : '-'}</div><div className="qf-mcard-label">跌停价</div></div>
          </div>
        </div>
      )}
    </div>
  )
}

function OptionsCalculator() {
  const [spot, setSpot] = useState('100')
  const [strike, setStrike] = useState('100')
  const [maturity, setMaturity] = useState('0.25')
  const [rate, setRate] = useState('0.03')
  const [volatility, setVolatility] = useState('0.2')
  const [optionType, setOptionType] = useState('call')
  const [marketPrice, setMarketPrice] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const calc = async () => {
    setBusy(true)
    setError('')
    setRes(null)
    try {
      const data = await optionsCalc({
        spot: Number(spot),
        strike: Number(strike),
        maturity: Number(maturity),
        rate: Number(rate),
        volatility: Number(volatility),
        option_type: optionType,
        market_price: marketPrice ? Number(marketPrice) : undefined,
      })
      setRes(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const card = { flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }
  const g = res?.greeks || {}

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>
        期权定价与希腊值计算器（V109 · Black-Scholes 欧式期权，纯数学零依赖）
      </div>
      {error && <div className="qf-error">{error}</div>}

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ ...card }}>
          <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
            <button type="button" onClick={() => setOptionType('call')} style={btnStyle(optionType === 'call', '#8b5cf6')}>看涨 Call</button>
            <button type="button" onClick={() => setOptionType('put')} style={btnStyle(optionType === 'put', '#8b5cf6')}>看跌 Put</button>
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">标的现价 S</span>
              <input className="qf-name-input" type="number" value={spot} onChange={(e) => setSpot(e.target.value)} />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">行权价 K</span>
              <input className="qf-name-input" type="number" value={strike} onChange={(e) => setStrike(e.target.value)} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">到期（年）</span>
              <input className="qf-name-input" type="number" step="0.01" value={maturity} onChange={(e) => setMaturity(e.target.value)} placeholder="0.25=3个月" />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">无风险利率 r</span>
              <input className="qf-name-input" type="number" step="0.001" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0.03=3%" />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">波动率 σ</span>
              <input className="qf-name-input" type="number" step="0.01" value={volatility} onChange={(e) => setVolatility(e.target.value)} placeholder="0.2=20%" />
            </label>
            <label className="qf-prop-field" style={{ flex: 1, minWidth: 120 }}>
              <span className="qf-prop-label">市价（反解 IV）</span>
              <input className="qf-name-input" type="number" value={marketPrice} onChange={(e) => setMarketPrice(e.target.value)} placeholder="可选" />
            </label>
          </div>

          <button className="qf-btn qf-btn-primary" onClick={calc} disabled={busy} style={{ marginTop: 12, width: '100%' }}>
            {busy ? '计算中…' : '计算'}
          </button>
          <div className="qf-hint" style={{ marginTop: 8 }}>
            填入「市价」可按 Black-Scholes 反解隐含波动率（二分法）；若市价低于内在价值则无解。单位：Vega 每波动率 +100%，Theta 每年，均附友好单位。
          </div>
        </div>

        <div style={{ ...card, flex: '1 1 320px' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>公式与约定</div>
          <div className="qf-hint" style={{ lineHeight: 1.7 }}>
            d1 = [ln(S/K) + (r + σ²/2)·T] / (σ·√T)<br />
            d2 = d1 − σ·√T<br />
            Call = S·N(d1) − K·e^(−rT)·N(d2)<br />
            Put = K·e^(−rT)·N(−d2) − S·N(−d1)<br />
            <br />
            Δ = N(d1) / N(d1)−1<br />
            Γ = N'(d1) / (S·σ·√T)<br />
            Vega = S·N'(d1)·√T<br />
            Θ、Rho 按连续复利推导。
          </div>
        </div>
      </div>

      {res && (
        <div style={{ marginTop: 14, border: '1px solid #8b5cf6', borderRadius: 10, padding: 14, background: '#faf5ff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#6d28d9', marginBottom: 8 }}>
            理论价与希腊值（{res.option_type === 'call' ? '看涨 Call' : '看跌 Put'}）
          </div>
          <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#6d28d9' }}>{Number(res.price).toLocaleString()}</div><div className="qf-mcard-label">理论期权价</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.delta).toLocaleString()}</div><div className="qf-mcard-label">Delta Δ</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.gamma).toLocaleString()}</div><div className="qf-mcard-label">Gamma Γ</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.vega).toLocaleString()}</div><div className="qf-mcard-label">Vega（每100%）</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.vega_per_1pct).toLocaleString()}</div><div className="qf-mcard-label">Vega（每1%）</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.theta).toLocaleString()}</div><div className="qf-mcard-label">Theta（每年）</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.theta_per_day).toLocaleString()}</div><div className="qf-mcard-label">Theta（每天）</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value">{Number(g.rho).toLocaleString()}</div><div className="qf-mcard-label">Rho（每100%）</div></div>
            <div className="qf-mcard"><div className="qf-mcard-value" style={{ color: '#6d28d9' }}>{res.implied_volatility != null ? (Number(res.implied_volatility) * 100).toFixed(2) + '%' : '—'}</div><div className="qf-mcard-label">隐含波动率</div></div>
          </div>
        </div>
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
