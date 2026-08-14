import { useState } from 'react'
import { runBacktest, backtestReport } from './api.js'

function fmtPct(v) {
  if (v == null) return '-'
  const n = Number(v) * 100
  return `${n.toFixed(2)}%`
}

function fmtNum(v, d = 2) {
  if (v == null) return '-'
  return Number(v).toFixed(d)
}

function EquityChart({ curve }) {
  if (!curve || !curve.length) return null
  const W = 600
  const H = 160
  const pad = 10
  const vals = curve.map((p) => Number(p.total_value) || 0)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const span = hi - lo || 1
  const stepX = curve.length > 1 ? (W - pad * 2) / (curve.length - 1) : 0
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  const path = curve
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * stepX).toFixed(1)},${y(Number(p.total_value) || 0).toFixed(1)}`)
    .join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 160, marginTop: 12 }}>
      <polyline points={path} fill="none" stroke="#15803d" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export default function FuturesBacktest({ onRun }) {
  const [form, setForm] = useState({
    symbol: 'IF2406',
    start: '2024-01-01',
    end: '2024-06-01',
    initial_cash: 1000000,
    multiplier: 10,
    short_window: 5,
    long_window: 20,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState(null)

  const change = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setReport(null)
    try {
      const payload = {
        strategy: 'futures_ma_cross',
        params: {
          short_window: Number(form.short_window),
          long_window: Number(form.long_window),
        },
        symbols: [form.symbol],
        start: form.start,
        end: form.end,
        initial_cash: Number(form.initial_cash),
        asset_types: { [form.symbol]: 'future' },
        multipliers: { [form.symbol]: Number(form.multiplier) },
        strategy_name: '期货均线交叉',
      }
      const r = await runBacktest(payload)
      const detail = await backtestReport(r.run_id)
      setReport(detail)
      if (onRun) onRun(detail)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const m = report?.metrics || {}

  return (
    <div>
      <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginTop: 12 }}>
        <div className="qf-prop-field">
          <label className="qf-prop-label">期货合约代码</label>
          <input value={form.symbol} onChange={(e) => change('symbol', e.target.value)} placeholder="如 IF2406" required />
        </div>
        <div className="qf-prop-field">
          <label className="qf-prop-label">开始日期</label>
          <input type="date" value={form.start} onChange={(e) => change('start', e.target.value)} required />
        </div>
        <div className="qf-prop-field">
          <label className="qf-prop-label">结束日期</label>
          <input type="date" value={form.end} onChange={(e) => change('end', e.target.value)} required />
        </div>
        <div className="qf-prop-field">
          <label className="qf-prop-label">初始资金</label>
          <input type="number" min={1} value={form.initial_cash} onChange={(e) => change('initial_cash', e.target.value)} required />
        </div>
        <div className="qf-prop-field">
          <label className="qf-prop-label">合约乘数</label>
          <input type="number" min={1} value={form.multiplier} onChange={(e) => change('multiplier', e.target.value)} required />
        </div>
        <div className="qf-prop-field">
          <label className="qf-prop-label">短周期</label>
          <input type="number" min={1} value={form.short_window} onChange={(e) => change('short_window', e.target.value)} required />
        </div>
        <div className="qf-prop-field">
          <label className="qf-prop-label">长周期</label>
          <input type="number" min={1} value={form.long_window} onChange={(e) => change('long_window', e.target.value)} required />
        </div>
        <div className="qf-prop-field" style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '运行中…' : '运行期货回测'}
          </button>
        </div>
      </form>
      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}
      {report && (
        <div style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 10 }}>回测报告：{report.strategy} · {report.symbols?.join(', ')}</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
            <div className="qf-mcard"><div className="qf-mcard-label">总收益</div><div className="qf-mcard-value">{fmtPct(m.total_return)}</div></div>
            <div className="qf-mcard"><div className="qf-mcard-label">年化收益</div><div className="qf-mcard-value">{fmtPct(m.annual_return)}</div></div>
            <div className="qf-mcard"><div className="qf-mcard-label">夏普</div><div className="qf-mcard-value">{fmtNum(m.sharpe)}</div></div>
            <div className="qf-mcard"><div className="qf-mcard-label">最大回撤</div><div className="qf-mcard-value">{fmtPct(m.max_drawdown)}</div></div>
            <div className="qf-mcard"><div className="qf-mcard-label">胜率</div><div className="qf-mcard-value">{fmtPct(m.win_rate)}</div></div>
          </div>
          <EquityChart curve={report.equity_curve} />
        </div>
      )}
    </div>
  )
}
