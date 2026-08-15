import { useCallback, useEffect, useState } from 'react'
import { backtestStrategies, runSensitivity } from './api.js'

const METRICS = [
  { v: 'total_return', label: '总收益' },
  { v: 'annual_return', label: '年化收益' },
  { v: 'sharpe', label: '夏普比率' },
  { v: 'max_drawdown', label: '最大回撤' },
  { v: 'win_rate', label: '胜率' },
]

const DEFAULT_STRATEGY_PARAMS = {
  ma_cross: { param: 'fast', values: '3,5,8,10,15,20' },
  buy_hold: { param: 'hold_days', values: '20,40,60,120,180' },
  fund_dingtou: { param: 'amount', values: '500,1000,2000,5000,10000' },
  fund_value_avg: { param: 'target_growth', values: '0.01,0.02,0.03,0.05' },
  futures_ma_cross: { param: 'fast', values: '3,5,8,10,15,20' },
}

function SensitChart({ data }) {
  if (!data || data.length < 2) return null
  const W = 720
  const H = 240
  const pad = 44
  const xs = data.map((p) => p.param_value)
  const ys = data.map((p) => p.value)
  const lo = Math.min(...ys)
  const hi = Math.max(...ys)
  const xlo = Math.min(...xs)
  const xhi = Math.max(...xs)
  const xspan = xhi - xlo || 1
  const yspan = hi - lo || 1
  const x = (v) => pad + ((v - xlo) / xspan) * (W - pad * 2)
  const y = (v) => H - pad - ((v - lo) / yspan) * (H - pad * 2)
  const line = data.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.param_value).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  return (
    <div className="qf-an-block" style={{ marginTop: 12 }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 240 }}>
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="#94a3b8" strokeDasharray="3 3" />
        <path d={line} fill="none" stroke="#2563eb" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        {data.map((p, i) => (
          <circle key={i} cx={x(p.param_value)} cy={y(p.value)} r="3" fill="#2563eb" />
        ))}
        <text x={pad} y={pad - 8} fill="#64748b" fontSize="10">{hi.toFixed(4)}</text>
        <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="10">{lo.toFixed(4)}</text>
        <text x={W - pad} y={H - pad + 14} fill="#64748b" fontSize="9" textAnchor="end">{xhi}</text>
        <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="9">{xlo}</text>
      </svg>
    </div>
  )
}

export default function Sensitivity() {
  const [strategies, setStrategies] = useState([])
  const [strategy, setStrategy] = useState('ma_cross')
  const [param, setParam] = useState('fast')
  const [valuesText, setValuesText] = useState('3,5,8,10,15,20')
  const [symbols, setSymbols] = useState('TEST.STOCK')
  const [metric, setMetric] = useState('total_return')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    backtestStrategies()
      .then((r) => setStrategies(r.items || []))
      .catch(() => setStrategies([]))
  }, [])

  const onStrategy = useCallback((name) => {
    setStrategy(name)
    const d = DEFAULT_STRATEGY_PARAMS[name]
    if (d) {
      setParam(d.param)
      setValuesText(d.values)
    }
  }, [])

  const run = useCallback(async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    const values = valuesText.split(/[,\s]+/).map((s) => Number(s.trim())).filter((v) => !Number.isNaN(v))
    if (values.length < 2) {
      setError('请至少给出 2 个待扫描的参数取值（逗号分隔）')
      setBusy(false)
      return
    }
    try {
      const res = await runSensitivity({
        strategy,
        params: {},
        param,
        values,
        symbols: symbols.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
        start,
        end,
        metric,
      })
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [strategy, param, valuesText, symbols, start, end, metric])

  const metricLabel = (METRICS.find((m) => m.v === metric) || {}).label || metric
  const data = result?.points || []

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>参数敏感性分析（V14 · 固定其余参数，扫描单参数对绩效的影响）</h3>
      </div>
      <form className="qf-prop-form" onSubmit={run} style={{ maxWidth: 860 }}>
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          选择一个策略，固定其它参数，扫描某个参数的一组取值，逐次回测并绘制指标曲线，快速定位参数的敏感区间。
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="qf-prop-field" style={{ width: 180 }}>
            <label className="qf-prop-label">策略</label>
            <select value={strategy} onChange={(e) => onStrategy(e.target.value)}>
              {strategies.length === 0 && <option value={strategy}>{strategy}</option>}
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>
          </div>
          <div className="qf-prop-field" style={{ width: 160 }}>
            <label className="qf-prop-label">扫描参数</label>
            <input value={param} onChange={(e) => setParam(e.target.value)} placeholder="如 fast / amount" />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 220 }}>
            <label className="qf-prop-label">取值列表（逗号分隔）</label>
            <input value={valuesText} onChange={(e) => setValuesText(e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 200 }}>
            <label className="qf-prop-label">标的（逗号分隔）</label>
            <input value={symbols} onChange={(e) => setSymbols(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ width: 150 }}>
            <label className="qf-prop-label">指标</label>
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => (
                <option key={m.v} value={m.v}>{m.label}</option>
              ))}
            </select>
          </div>
          <div className="qf-prop-field" style={{ width: 140 }}>
            <label className="qf-prop-label">开始</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ width: 140 }}>
            <label className="qf-prop-label">结束</label>
            <input value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '分析中…' : '运行敏感性分析'}
          </button>
        </div>
      </form>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="qf-hint">
            策略 {result.strategy} · 参数 <b>{result.param}</b> · 指标 <b>{metricLabel}</b>
            （{result.metric}）· 样本 {data.length} 组
          </div>
          <SensitChart data={data} />
          <table className="qf-state-table" style={{ marginTop: 10 }}>
            <thead>
              <tr><th>{result.param} 取值</th><th>{metricLabel}</th></tr>
            </thead>
            <tbody>
              {data.map((p, i) => (
                <tr key={i}>
                  <td>{p.param_value}</td>
                  <td style={{ color: (p.value || 0) >= 0 ? '#15803d' : '#dc2626' }}>
                    {p.value == null ? '—' : p.value.toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
