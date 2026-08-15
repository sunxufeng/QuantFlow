import { useCallback, useEffect, useState } from 'react'
import { backtestStrategies, runSensitivityGrid } from './api.js'

const METRICS = [
  { v: 'total_return', label: '总收益' },
  { v: 'annual_return', label: '年化收益' },
  { v: 'sharpe', label: '夏普比率' },
  { v: 'max_drawdown', label: '最大回撤' },
  { v: 'win_rate', label: '胜率' },
  { v: 'final_value', label: '终值' },
]

function colorFor(v, lo, hi) {
  if (v == null) return '#334155'
  if (hi <= lo) return '#6366f1'
  const t = (v - lo) / (hi - lo)
  const hue = Math.round(t * 120) // 0=红(低) -> 120=绿(高)
  return `hsl(${hue}, 68%, 45%)`
}

function Heatmap({ result }) {
  const { param_a, param_a_values, param_b, param_b_values, grid, best } = result
  const vals = grid.flat().filter((v) => v != null)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const cell = 56
  const labelW = 70
  const labelH = 56
  const W = labelW + param_b_values.length * cell
  const H = labelH + param_a_values.length * cell
  const bestA = best?.param_a
  const bestB = best?.param_b
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, height: 'auto', background: '#1e293b', borderRadius: 10 }}>
      {/* 列标题（param_b） */}
      {param_b_values.map((vb, j) => (
        <text key={`c${j}`} x={labelW + j * cell + cell / 2} y={labelH - 8} fill="#cbd5e1" fontSize="11"
          textAnchor="middle">{String(vb)}</text>
      ))}
      {/* 行标题（param_a） */}
      {param_a_values.map((va, i) => (
        <text key={`r${i}`} x={labelW - 8} y={labelH + i * cell + cell / 2 + 4} fill="#cbd5e1" fontSize="11"
          textAnchor="end">{String(va)}</text>
      ))}
      {/* 单元格 */}
      {grid.map((row, i) => row.map((v, j) => {
        const isBest = va_eq(param_a_values[i], bestA) && vb_eq(param_b_values[j], bestB)
        return (
          <g key={`${i}-${j}`}>
            <rect x={labelW + j * cell} y={labelH + i * cell} width={cell - 2} height={cell - 2}
              rx={4} fill={colorFor(v, lo, hi)}
              stroke={isBest ? '#fbbf24' : '#0f172a'} strokeWidth={isBest ? 3 : 1} />
            <text x={labelW + j * cell + cell / 2} y={labelH + i * cell + cell / 2 + 4}
              fill={v == null ? '#94a3b8' : '#fff'} fontSize="10" textAnchor="middle">
              {v == null ? '—' : (Math.abs(v) >= 1 ? v.toFixed(0) : v.toFixed(3))}
            </text>
          </g>
        )
      }))}
      {/* 轴标题 */}
      <text x={W / 2} y={H + 2} fill="#64748b" fontSize="10" textAnchor="middle">{param_b}</text>
      <text x={10} y={H / 2} fill="#64748b" fontSize="10" textAnchor="middle"
        transform={`rotate(-90 10 ${H / 2})`}>{param_a}</text>
    </svg>
  )
}
function va_eq(a, b) { return String(a) === String(b) }
function vb_eq(a, b) { return String(a) === String(b) }

export default function ParamGrid() {
  const [strategies, setStrategies] = useState([])
  const [strategy, setStrategy] = useState('ma_cross')
  const [paramA, setParamA] = useState('fast')
  const [valuesA, setValuesA] = useState('3,5,8,10,15,20')
  const [paramB, setParamB] = useState('slow')
  const [valuesB, setValuesB] = useState('15,20,30,40,60')
  const [symbols, setSymbols] = useState('TEST.STOCK')
  const [metric, setMetric] = useState('total_return')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    backtestStrategies().then((r) => setStrategies(r.items || [])).catch(() => setStrategies([]))
  }, [])

  const run = useCallback(async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    const parse = (t) => t.split(/[,\s]+/).map((s) => Number(s.trim())).filter((v) => !Number.isNaN(v))
    const va = parse(valuesA)
    const vb = parse(valuesB)
    if (va.length < 2 || vb.length < 2) {
      setError('两个参数都至少给出 2 个取值（逗号分隔）')
      setBusy(false)
      return
    }
    if (paramA.trim() === paramB.trim()) {
      setError('两个扫描参数不能相同')
      setBusy(false)
      return
    }
    try {
      const res = await runSensitivityGrid({
        strategy,
        params: {},
        grid: { [paramA.trim()]: va, [paramB.trim()]: vb },
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
  }, [strategy, paramA, valuesA, paramB, valuesB, symbols, start, end, metric])

  const metricLabel = (METRICS.find((m) => m.v === metric) || {}).label || metric

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>多参数敏感性网格（V16 · 双参数笛卡尔积扫描，热力图定位最优区间）</h3>
      </div>
      <form className="qf-prop-form" onSubmit={run} style={{ maxWidth: 920 }}>
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          固定其余参数，同时扫描两个参数的取值组合，逐格回测并绘制指标热力图（红=低，绿=高，金框=全局最优），快速识别参数的协同效应。
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="qf-prop-field" style={{ width: 170 }}>
            <label className="qf-prop-label">策略</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.length === 0 && <option value={strategy}>{strategy}</option>}
              {strategies.map((s) => (<option key={s.name} value={s.name}>{s.name}</option>))}
            </select>
          </div>
          <div className="qf-prop-field" style={{ width: 130 }}>
            <label className="qf-prop-label">参数 A</label>
            <input value={paramA} onChange={(e) => setParamA(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 200 }}>
            <label className="qf-prop-label">A 取值（逗号分隔）</label>
            <input value={valuesA} onChange={(e) => setValuesA(e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
          <div className="qf-prop-field" style={{ width: 130 }}>
            <label className="qf-prop-label">参数 B</label>
            <input value={paramB} onChange={(e) => setParamB(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 200 }}>
            <label className="qf-prop-label">B 取值（逗号分隔）</label>
            <input value={valuesB} onChange={(e) => setValuesB(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 180 }}>
            <label className="qf-prop-label">标的（逗号分隔）</label>
            <input value={symbols} onChange={(e) => setSymbols(e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
          <div className="qf-prop-field" style={{ width: 150 }}>
            <label className="qf-prop-label">指标</label>
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => (<option key={m.v} value={m.v}>{m.label}</option>))}
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
            {busy ? '扫描中…' : '运行网格扫描'}
          </button>
        </div>
      </form>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="qf-hint">
            策略 {result.strategy} · 指标 <b>{metricLabel}</b>（{result.metric}）· 网格 {result.param_a_values.length}×{result.param_b_values.length}
            {result.best?.value != null && <> · 最优 {result.param_a}={result.best.param_a} / {result.param_b}={result.best.param_b} → <b>{result.best.value.toFixed(4)}</b></>}
          </div>
          <div className="qf-an-block" style={{ marginTop: 12, overflowX: 'auto' }}>
            <Heatmap result={result} />
          </div>
          <table className="qf-state-table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>{result.param_a} \ {result.param_b}</th>
                {result.param_b_values.map((vb, j) => (<th key={j}>{vb}</th>))}
              </tr>
            </thead>
            <tbody>
              {result.grid.map((row, i) => (
                <tr key={i}>
                  <td>{result.param_a_values[i]}</td>
                  {row.map((v, j) => (
                    <td key={j} style={{ color: v == null ? '#64748b' : (v >= 0 ? '#15803d' : '#dc2626') }}>
                      {v == null ? '—' : v.toFixed(4)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
