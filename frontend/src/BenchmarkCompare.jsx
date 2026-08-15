import { useCallback, useEffect, useState } from 'react'
import { runBenchmarkCompare } from './api.js'

const BENCH_COLORS = ['#22d3ee', '#a855f7', '#f59e0b', '#34d399', '#f472b6', '#60a5fa']

function fmtPct(v, d = 2) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(d)}%`
}
function fmtNum(v, d = 2) {
  if (v == null) return '—'
  return Number(v).toFixed(d)
}

function OverlayChart({ strategy, benchmarks }) {
  const all = [strategy, ...benchmarks.map((b) => b.curve)]
  const ys = []
  all.forEach((c) => c.forEach((p) => ys.push(p.value)))
  if (ys.length === 0) return null
  const lo = Math.min(...ys)
  const hi = Math.max(...ys)
  const yspan = hi - lo || 1
  const W = 760
  const H = 300
  const pad = 50
  const n = strategy.length
  const x = (i) => pad + (n <= 1 ? 0 : (i / (n - 1)) * (W - pad * 2))
  const y = (v) => H - pad - ((v - lo) / yspan) * (H - pad * 2)
  const line = (c) => c.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 300 }}>
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" />
      <path d={line(strategy)} fill="none" stroke="#f97316" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
      <text x={pad} y={pad - 8} fill="#f97316" fontSize="10">策略</text>
      {benchmarks.map((b, bi) => (
        <g key={bi}>
          <path d={line(b.curve)} fill="none" stroke={BENCH_COLORS[bi % BENCH_COLORS.length]} strokeWidth="2"
            strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />
          <text x={W - pad} y={pad + 4 + bi * 12} fill={BENCH_COLORS[bi % BENCH_COLORS.length]} fontSize="9" textAnchor="end">{b.name}</text>
        </g>
      ))}
      <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="9">{String(strategy[0]?.date || '').slice(0, 10)}</text>
      <text x={W - pad} y={H - pad + 14} fill="#64748b" fontSize="9" textAnchor="end">{String(strategy[n - 1]?.date || '').slice(0, 10)}</text>
    </svg>
  )
}

export default function BenchmarkCompare() {
  const [runId, setRunId] = useState('')
  const [benches, setBenches] = useState([
    { name: '沪深基准', symbols: 'TEST.STOCK', weights: '', values: '' },
  ])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  const updateBench = (i, key, val) => {
    setBenches((prev) => prev.map((b, k) => (k === i ? { ...b, [key]: val } : b)))
  }
  const addBench = () => setBenches((prev) => [...prev, { name: `基准${prev.length + 1}`, symbols: '', weights: '', values: '' }])
  const removeBench = (i) => setBenches((prev) => prev.filter((_, k) => k !== i))

  const run = useCallback(async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    if (!runId.trim()) {
      setError('请填写已存报告 run_id')
      setBusy(false)
      return
    }
    const benchmarks = benches.map((b) => {
      const symList = (b.symbols || '').split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
      const wList = (b.weights || '').split(/[,\s]+/).map((s) => Number(s.trim())).filter((v) => !Number.isNaN(v))
      const vList = (b.values || '').trim() ? JSON.parse(b.values) : undefined
      const d = { name: b.name || '基准' }
      if (vList) d.values = vList
      else { d.symbols = symList; if (wList.length) d.weights = wList }
      return d
    }).filter((b) => b.symbols?.length || b.values)
    if (!benchmarks.length) {
      setError('请至少配置一个基准（篮子标的或显式序列）')
      setBusy(false)
      return
    }
    try {
      const res = await runBenchmarkCompare({ run_id: runId.trim(), benchmarks })
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [runId, benches])

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>自定义基准对比（V16 · 多基准篮子/显式序列 vs 已存报告，计算相对绩效）</h3>
      </div>
      <form className="qf-prop-form" onSubmit={run} style={{ maxWidth: 960 }}>
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          选择一个已存回测报告（run_id），叠加一个或多个自定义基准（多标的加权篮子或显式序列），计算 beta/alpha/跟踪误差/信息比率等相对绩效。
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 220 }}>
            <label className="qf-prop-label">已存报告 run_id</label>
            <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="从回测报告列表复制" />
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          {benches.map((b, i) => (
            <div key={i} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 10, marginBottom: 8 }}>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <div className="qf-prop-field" style={{ width: 150 }}>
                  <label className="qf-prop-label">基准名称</label>
                  <input value={b.name} onChange={(e) => updateBench(i, 'name', e.target.value)} />
                </div>
                <div className="qf-prop-field" style={{ flex: 1, minWidth: 200 }}>
                  <label className="qf-prop-label">篮子标的（逗号分隔）</label>
                  <input value={b.symbols} onChange={(e) => updateBench(i, 'symbols', e.target.value)} placeholder="留空则用下方显式序列" />
                </div>
                <div className="qf-prop-field" style={{ width: 150 }}>
                  <label className="qf-prop-label">权重（可选，逗号）</label>
                  <input value={b.weights} onChange={(e) => updateBench(i, 'weights', e.target.value)} placeholder="默认等权" />
                </div>
                <button type="button" className="qf-btn qf-btn-sm" onClick={() => removeBench(i)} disabled={benches.length === 1}>删除</button>
              </div>
              <div className="qf-prop-field" style={{ marginTop: 6, width: '100%' }}>
                <label className="qf-prop-label">显式序列（可选，JSON 数组，与报告净值曲线等长）</label>
                <input value={b.values} onChange={(e) => updateBench(i, 'values', e.target.value)} placeholder='如 [100,101,99,...]' />
              </div>
            </div>
          ))}
          <button type="button" className="qf-btn" onClick={addBench} style={{ marginTop: 2 }}>+ 添加基准</button>
        </div>

        <div style={{ marginTop: 12 }}>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '对比中…' : '运行基准对比'}
          </button>
        </div>
      </form>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="qf-hint">
            报告 {result.run_id} · 策略 {result.strategy} · {result.start_date} ~ {result.end_date} · {result.benchmarks.length} 个基准
          </div>
          <div className="qf-an-block" style={{ marginTop: 12, background: '#1e293b', borderRadius: 10, padding: 12 }}>
            <div style={{ fontSize: 13, color: '#e2e8f0', marginBottom: 6 }}>策略 vs 基准净值曲线（橙=策略，彩虚线=基准）</div>
            <OverlayChart strategy={result.strategy_curve} benchmarks={result.benchmarks} />
          </div>

          <table className="qf-state-table" style={{ marginTop: 14 }}>
            <thead>
              <tr>
                <th>基准</th>
                <th>基准收益</th>
                <th>超额收益</th>
                <th>Alpha</th>
                <th>Beta</th>
                <th>跟踪误差</th>
                <th>信息比率</th>
              </tr>
            </thead>
            <tbody>
              {result.benchmarks.map((b, i) => (
                <tr key={i}>
                  <td>
                    <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, marginRight: 6,
                      background: BENCH_COLORS[i % BENCH_COLORS.length] }} />
                    {b.name}
                  </td>
                  <td>{fmtPct(b.relative?.benchmark_return)}</td>
                  <td style={{ color: (b.relative?.excess_return || 0) >= 0 ? '#15803d' : '#dc2626' }}>{fmtPct(b.relative?.excess_return)}</td>
                  <td style={{ color: (b.relative?.alpha || 0) >= 0 ? '#15803d' : '#dc2626' }}>{fmtNum(b.relative?.alpha)}</td>
                  <td>{fmtNum(b.relative?.beta)}</td>
                  <td>{fmtPct(b.relative?.tracking_error)}</td>
                  <td style={{ color: (b.relative?.information_ratio || 0) >= 0 ? '#15803d' : '#dc2626' }}>{fmtNum(b.relative?.information_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
