import { useCallback, useEffect, useState } from 'react'
import { backtestStrategies, runMonteCarlo } from './api.js'

function fmtMoney(v) {
  if (v == null) return '—'
  return Math.round(v).toLocaleString()
}
function fmtPct(v, digits = 2) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(digits)}%`
}
function fmtNum(v, digits = 2) {
  if (v == null) return '—'
  return Number(v).toFixed(digits)
}

// 净值置信带图：P5~P95（浅）/ P25~P75（深）/ 中位 / 实际
function BandChart({ bands, dates, actual }) {
  if (!bands || bands.length < 2) return null
  const W = 760
  const H = 280
  const pad = 50
  const ys = []
  bands.forEach((b) => { ys.push(b.p_low, b.p_high) })
  if (actual) { ys.push(actual.final_value) }
  const lo = Math.min(...ys)
  const hi = Math.max(...ys)
  const yspan = hi - lo || 1
  const y = (v) => H - pad - ((v - lo) / yspan) * (H - pad * 2)
  const n = bands.length
  const x = (i) => pad + (i / (n - 1)) * (W - pad * 2)

  const areaPath = (loKey, hiKey) => {
    const top = bands.map((b, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(b[hiKey]).toFixed(1)}`).join(' ')
    const bottom = bands.slice().reverse().map((b, k) => {
      const i = n - 1 - k
      return `L${x(i).toFixed(1)},${y(b[loKey]).toFixed(1)}`
    }).join(' ')
    return `${top} ${bottom} Z`
  }
  const medianLine = bands.map((b, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(b.p50).toFixed(1)}`).join(' ')
  // 实际路径：用 actual.final_value 作为末点，首点取 bands[0].p50 对齐线（仅作示意）
  const actualLine = [
    `M${x(0).toFixed(1)},${y(bands[0].p50).toFixed(1)}`,
    `L${x(n - 1).toFixed(1)},${y(actual.final_value).toFixed(1)}`,
  ].join(' ')

  const xticks = [0, Math.floor(n / 2), n - 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 280 }}>
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" />
      <path d={areaPath('p_low', 'p_high')} fill="rgba(99,102,241,0.15)" stroke="none" />
      <path d={areaPath('p25', 'p75')} fill="rgba(99,102,241,0.32)" stroke="none" />
      <path d={medianLine} fill="none" stroke="#4f46e5" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      <path d={actualLine} fill="none" stroke="#f97316" strokeWidth="2.5" strokeDasharray="5 3" vectorEffect="non-scaling-stroke" />
      <text x={pad} y={pad - 8} fill="#64748b" fontSize="10">{fmtMoney(hi)}</text>
      <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="10">{fmtMoney(lo)}</text>
      {xticks.map((i) => (
        <text key={i} x={x(i)} y={H - pad + 26} fill="#64748b" fontSize="9" textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>
          {String(dates[i] || '').slice(0, 10)}
        </text>
      ))}
      <text x={W - pad} y={pad - 8} fill="#4f46e5" fontSize="9" textAnchor="end">中位路径</text>
      <text x={W - pad} y={pad + 2} fill="#f97316" fontSize="9" textAnchor="end">实际</text>
    </svg>
  )
}

// 终值直方图
function Histogram({ histogram }) {
  if (!histogram || !histogram.counts || histogram.counts.length === 0) return null
  const { bin_centers, counts, bin_edges } = histogram
  const W = 760
  const H = 200
  const pad = 40
  const maxc = Math.max(...counts) || 1
  const n = counts.length
  const bw = (W - pad * 2) / n
  const y = (c) => H - pad - (c / maxc) * (H - pad * 2)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 200 }}>
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" />
      {counts.map((c, i) => {
        const bx = pad + i * bw
        const by = y(c)
        return (
          <rect key={i} x={bx + 1} y={by} width={Math.max(1, bw - 2)} height={H - pad - by}
            fill="#6366f1" opacity={0.8} />
        )
      })}
      <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="9">{fmtMoney(bin_edges[0])}</text>
      <text x={W - pad} y={H - pad + 14} fill="#64748b" fontSize="9" textAnchor="end">{fmtMoney(bin_edges[bin_edges.length - 1])}</text>
      <text x={W / 2} y={pad - 6} fill="#64748b" fontSize="9" textAnchor="middle">终值分布（{fmtMoney(bin_centers[0])} ~ {fmtMoney(bin_centers[n - 1])}）</text>
    </svg>
  )
}

function StatCard({ label, value, color }) {
  return (
    <div style={{
      flex: '1 1 150px', minWidth: 150, background: '#0f172a', border: '1px solid #1e293b',
      borderRadius: 10, padding: '10px 12px',
    }}>
      <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: color || '#e2e8f0' }}>{value}</div>
    </div>
  )
}

export default function MonteCarlo() {
  const [strategies, setStrategies] = useState([])
  const [strategy, setStrategy] = useState('ma_cross')
  const [symbols, setSymbols] = useState('TEST.STOCK')
  const [paramsText, setParamsText] = useState('{"fast":5,"slow":20}')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [nSims, setNSims] = useState(200)
  const [seed, setSeed] = useState(42)
  const [confidence, setConfidence] = useState(0.9)
  const [runId, setRunId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    backtestStrategies()
      .then((r) => setStrategies(r.items || []))
      .catch(() => setStrategies([]))
  }, [])

  const run = useCallback(async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    let params = {}
    if (paramsText && paramsText.trim()) {
      try {
        params = JSON.parse(paramsText)
      } catch {
        setError('参数需为合法 JSON，如 {"fast":5,"slow":20}')
        setBusy(false)
        return
      }
    }
    const payload = {
      strategy: runId ? undefined : strategy,
      params,
      symbols: runId ? undefined : symbols.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
      start: runId ? undefined : start,
      end: runId ? undefined : end,
      n_sims: Number(nSims) || 200,
      seed: seed === '' ? null : Number(seed),
      confidence: Number(confidence) || 0.9,
      run_id: runId.trim() || null,
    }
    try {
      const res = await runMonteCarlo(payload)
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [strategy, symbols, paramsText, start, end, nSims, seed, confidence, runId])

  const s = result?.summary || {}
  const actual = result?.actual

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>蒙特卡洛鲁棒性模拟（V15 · 自助重采样评估策略表现的统计稳健性）</h3>
      </div>
      <form className="qf-prop-form" onSubmit={run} style={{ maxWidth: 920 }}>
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          对回测的日收益做有放回自助重采样，生成多条等长净值路径，给出终值 / 收益 / 回撤 / 夏普的分布与净值置信带，
          帮助判断策略表现是稳定还是偶然。可填写已存报告 run_id 直接基于其净值曲线模拟。
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="qf-prop-field" style={{ width: 180 }}>
            <label className="qf-prop-label">策略（留空则用 run_id）</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)} disabled={!!runId.trim()}>
              {strategies.length === 0 && <option value={strategy}>{strategy}</option>}
              {strategies.map((x) => (
                <option key={x.name} value={x.name}>{x.name}</option>
              ))}
            </select>
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 220 }}>
            <label className="qf-prop-label">参数 JSON</label>
            <input value={paramsText} onChange={(e) => setParamsText(e.target.value)} disabled={!!runId.trim()} />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 180 }}>
            <label className="qf-prop-label">标的（逗号分隔）</label>
            <input value={symbols} onChange={(e) => setSymbols(e.target.value)} disabled={!!runId.trim()} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
          <div className="qf-prop-field" style={{ width: 140 }}>
            <label className="qf-prop-label">开始</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} disabled={!!runId.trim()} />
          </div>
          <div className="qf-prop-field" style={{ width: 140 }}>
            <label className="qf-prop-label">结束</label>
            <input value={end} onChange={(e) => setEnd(e.target.value)} disabled={!!runId.trim()} />
          </div>
          <div className="qf-prop-field" style={{ width: 110 }}>
            <label className="qf-prop-label">模拟次数</label>
            <input type="number" min="10" max="2000" value={nSims} onChange={(e) => setNSims(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ width: 90 }}>
            <label className="qf-prop-label">随机种子</label>
            <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ width: 110 }}>
            <label className="qf-prop-label">置信水平</label>
            <select value={confidence} onChange={(e) => setConfidence(e.target.value)}>
              <option value={0.8}>80%</option>
              <option value={0.9}>90%</option>
              <option value={0.95}>95%</option>
            </select>
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 160 }}>
            <label className="qf-prop-label">已存报告 run_id（可选）</label>
            <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="留空则按上方运行" />
          </div>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '模拟中…' : '运行鲁棒性模拟'}
          </button>
        </div>
      </form>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="qf-hint">
            策略 {result.strategy}
            {result.run_id ? ` · 报告 ${result.run_id}` : ''}
            · {result.n_sims} 条路径 · 置信 {(result.confidence * 100).toFixed(0)}%
            · 块大小 {result.block_size}
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
            <StatCard label="实际终值" value={fmtMoney(actual?.final_value)} color="#f97316" />
            <StatCard label="模拟中位终值" value={fmtMoney(s.final_equity?.p50)} color="#4f46e5" />
            <StatCard label="终值 P5 / P95" value={`${fmtMoney(s.final_equity?.p5)} / ${fmtMoney(s.final_equity?.p95)}`} />
            <StatCard label="实际 / 模拟中位收益" value={`${fmtPct(actual?.total_return)} / ${fmtPct(s.total_return?.p50)}`} />
            <StatCard label="最大回撤中位" value={fmtPct(s.max_drawdown?.p50)} color="#dc2626" />
            <StatCard label="夏普中位" value={fmtNum(s.sharpe?.p50, 2)} color="#15803d" />
          </div>

          <div className="qf-an-block" style={{ marginTop: 14, background: '#1e293b', borderRadius: 10, padding: 12 }}>
            <div style={{ fontSize: 13, color: '#e2e8f0', marginBottom: 6 }}>净值置信带（浅=P5~P95，深=P25~P75，橙虚线=实际路径）</div>
            <BandChart bands={result.bands} dates={result.dates} actual={actual} />
          </div>

          <div className="qf-an-block" style={{ marginTop: 14, background: '#1e293b', borderRadius: 10, padding: 12 }}>
            <div style={{ fontSize: 13, color: '#e2e8f0', marginBottom: 6 }}>终值分布直方图</div>
            <Histogram histogram={result.histogram} />
          </div>

          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginTop: 14 }}>
            <table className="qf-state-table">
              <thead><tr><th>指标</th><th>P5</th><th>P25</th><th>P50</th><th>P75</th><th>P95</th></tr></thead>
              <tbody>
                {[
                  ['终值', s.final_equity, fmtMoney],
                  ['总收益', s.total_return, (v) => fmtPct(v)],
                  ['最大回撤', s.max_drawdown, (v) => fmtPct(v)],
                  ['夏普', s.sharpe, (v) => fmtNum(v, 2)],
                ].map(([name, row, fmt]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{row ? fmt(row.p5) : '—'}</td>
                    <td>{row ? fmt(row.p25) : '—'}</td>
                    <td style={{ fontWeight: 700 }}>{row ? fmt(row.p50) : '—'}</td>
                    <td>{row ? fmt(row.p75) : '—'}</td>
                    <td>{row ? fmt(row.p95) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
