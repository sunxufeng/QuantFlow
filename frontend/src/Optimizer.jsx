import { useState } from 'react'
import { optimizeBacktest, backtestStrategies } from './api.js'

const OBJECTIVES = [
  ['sharpe', '夏普比率'],
  ['total_return', '总收益'],
  ['annual_return', '年化收益'],
  ['max_drawdown', '最大回撤（越接近 0 越好）'],
  ['win_rate', '胜率'],
]

const PRESET_STRATEGIES = {
  ma_cross: { fast: [2, 3, 5], slow: [6, 8, 10, 12] },
  futures_ma_cross: { fast: [2, 3, 5], slow: [6, 8, 10, 12] },
}

function fmtPct(v) {
  if (v == null) return '-'
  return `${(Number(v) * 100).toFixed(2)}%`
}
function fmtNum(v, d = 3) {
  if (v == null) return '-'
  return Number(v).toFixed(d)
}

export default function Optimizer() {
  const [strategies, setStrategies] = useState([])
  const [strategy, setStrategy] = useState('ma_cross')
  const [symbol, setSymbol] = useState('TEST.STOCK')
  const [start, setStart] = useState('2024-01-02')
  const [end, setEnd] = useState('2024-02-01')
  const [objective, setObjective] = useState('sharpe')
  const [topN, setTopN] = useState(10)
  const [gridText, setGridText] = useState(
    JSON.stringify({ fast: [2, 3, 5], slow: [6, 8, 10, 12] }, null, 2)
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  const loadStrategies = () => {
    backtestStrategies()
      .then((r) => setStrategies(r.items || []))
      .catch(() => setStrategies([]))
  }
  if (strategies.length === 0) loadStrategies()

  const applyPreset = () => {
    const preset = PRESET_STRATEGIES[strategy]
    if (preset) setGridText(JSON.stringify(preset, null, 2))
  }

  const run = () => {
    setError('')
    let grid
    try {
      grid = JSON.parse(gridText)
    } catch (e) {
      setError('参数网格不是合法 JSON（示例：{"fast":[3,5],"slow":[15,20]}）')
      return
    }
    setLoading(true)
    setResult(null)
    optimizeBacktest({
      strategy,
      symbols: symbol.split(',').map((s) => s.trim()).filter(Boolean),
      start,
      end,
      objective,
      top_n: topN,
      grid,
    })
      .then(setResult)
      .catch((e) => setError(`优化失败: ${e.message}`))
      .finally(() => setLoading(false))
  }

  const num = (v) => fmtNum(v)

  return (
    <div style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>回测参数优化器（V2.1）</h3>
        <button className="qf-btn qf-btn-primary" onClick={run} disabled={loading}>
          {loading ? '优化中…' : '开始优化'}
        </button>
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        在给定参数网格上做笛卡尔积遍历，对每组参数运行回测并按目标指标排序返回 Top-N。纯离线，无需券商凭证。
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12, maxWidth: 720 }}>
        <label className="qf-field">
          <span>策略</span>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
            {strategies.length === 0 && <option value={strategy}>{strategy}</option>}
            {strategies.map((s) => (
              <option key={s.name} value={s.name}>{s.name}</option>
            ))}
          </select>
        </label>
        <label className="qf-field">
          <span>标的（逗号分隔）</span>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label className="qf-field">
          <span>起始日期</span>
          <input value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="qf-field">
          <span>结束日期</span>
          <input value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label className="qf-field">
          <span>优化目标</span>
          <select value={objective} onChange={(e) => setObjective(e.target.value)}>
            {OBJECTIVES.map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </label>
        <label className="qf-field">
          <span>返回 Top-N</span>
          <input type="number" min={1} max={100} value={topN} onChange={(e) => setTopN(Number(e.target.value) || 10)} />
        </label>
      </div>

      <div style={{ marginTop: 12, maxWidth: 720 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="qf-field-label">参数网格（JSON）</span>
          <button className="qf-btn qf-btn-sm" onClick={applyPreset}>套用预设</button>
        </div>
        <textarea
          value={gridText}
          onChange={(e) => setGridText(e.target.value)}
          rows={5}
          style={{ width: '100%', fontFamily: 'monospace', fontSize: 12, padding: 8 }}
        />
      </div>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div className="qf-an-block" style={{ marginTop: 16 }}>
          <div className="qf-an-title">
            优化结果 · 目标={result.objective} · 组合 {result.total_combos} 组
            （成功 {result.completed} / 失败 {result.failed}）· 排序：{result.objective_direction === 'higher' ? '越大越好' : ''}
          </div>
          {result.top.length === 0 ? (
            <div className="qf-hint">无有效结果（可能全部组合运行失败）。</div>
          ) : (
            <div style={{ overflowX: 'auto', marginTop: 10 }}>
              <table className="qf-table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>参数</th>
                    <th>夏普</th>
                    <th>总收益</th>
                    <th>年化</th>
                    <th>最大回撤</th>
                    <th>胜率</th>
                  </tr>
                </thead>
                <tbody>
                  {result.top.map((row) => (
                    <tr key={row.rank}>
                      <td>{row.rank}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                        {Object.entries(row.params)
                          .map(([k, v]) => `${k}=${v}`)
                          .join(' ')}
                      </td>
                      <td>{num(row.metrics.sharpe)}</td>
                      <td className={Number(row.metrics.total_return) >= 0 ? 'qf-up' : 'qf-down'}>{fmtPct(row.metrics.total_return)}</td>
                      <td>{fmtPct(row.metrics.annual_return)}</td>
                      <td>{fmtPct(row.metrics.max_drawdown)}</td>
                      <td>{fmtPct(row.metrics.win_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
