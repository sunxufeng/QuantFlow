import { useCallback, useEffect, useState } from 'react'
import { backtestStrategies, runWalkForward } from './api.js'

function fmtPct(v, d = 2) {
  if (v == null) return '—'
  return `${(v * 100).toFixed(d)}%`
}
function fmtNum(v, d = 2) {
  if (v == null) return '—'
  return Number(v).toFixed(d)
}

function StatCard({ label, value, color, sub }) {
  return (
    <div style={{ flex: '1 1 160px', minWidth: 160, background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: '10px 12px' }}>
      <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color: color || '#e2e8f0' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// 分组柱状图：每折 IS vs OOS 收益
function FoldBars({ folds }) {
  if (!folds || folds.length === 0) return null
  const W = 760
  const H = 240
  const pad = 44
  const vals = []
  folds.forEach((f) => vals.push(f.is_metrics?.total_return, f.oos_metrics?.total_return))
  const valid = vals.filter((v) => v != null)
  if (!valid.length) return null
  const lo = Math.min(0, ...valid)
  const hi = Math.max(...valid)
  const yspan = hi - lo || 1
  const y = (v) => H - pad - ((v - lo) / yspan) * (H - pad * 2)
  const n = folds.length
  const groupW = (W - pad * 2) / n
  const bw = Math.min(28, groupW / 2 - 4)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 240 }}>
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" />
      <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="#94a3b8" strokeDasharray="3 3" />
      {folds.map((f, i) => {
        const cx = pad + groupW * (i + 0.5)
        const isV = f.is_metrics?.total_return
        const oosV = f.oos_metrics?.total_return
        const xIs = cx - bw - 2
        const xOos = cx + 2
        return (
          <g key={i}>
            {isV != null && <rect x={xIs} y={y(isV)} width={bw} height={H - pad - y(isV)} fill="#2563eb" opacity={0.85} />}
            {oosV != null && <rect x={xOos} y={y(oosV)} width={bw} height={H - pad - y(oosV)} fill="#f97316" opacity={0.85} />}
            <text x={cx} y={H - pad + 14} fill="#64748b" fontSize="9" textAnchor="middle">
              {String(f.test_period?.start || '').slice(5)}
            </text>
          </g>
        )
      })}
      <text x={W - pad} y={pad - 8} fill="#64748b" fontSize="9" textAnchor="end">蓝=样本内 · 橙=样本外</text>
    </svg>
  )
}

export default function WalkForward() {
  const [strategies, setStrategies] = useState([])
  const [strategy, setStrategy] = useState('ma_cross')
  const [paramsText, setParamsText] = useState('{"fast":5,"slow":20}')
  const [symbols, setSymbols] = useState('TEST.STOCK')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [nFolds, setNFolds] = useState(5)
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
    let params = {}
    if (paramsText && paramsText.trim()) {
      try { params = JSON.parse(paramsText) } catch { setError('参数需为合法 JSON'); setBusy(false); return }
    }
    try {
      const res = await runWalkForward({
        strategy,
        params,
        symbols: symbols.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
        start,
        end,
        n_folds: Number(nFolds) || 5,
      })
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [strategy, paramsText, symbols, start, end, nFolds])

  const s = result?.summary || {}

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>Walk-forward 样本外验证（V16 · 扩张窗口训练/测试，检验策略在 unseen 数据上的稳健性）</h3>
      </div>
      <form className="qf-prop-form" onSubmit={run} style={{ maxWidth: 920 }}>
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          将区间切分为 N 折：每折用「起点→折起点」作样本内训练、用该折作样本外测试，评估样本外收益/夏普相对样本内的衰减与一致性。
          样本外胜率（OOS 收益&gt;0 的折占比）与跑赢样本内比率越高，策略越稳健。
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="qf-prop-field" style={{ width: 170 }}>
            <label className="qf-prop-label">策略</label>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.length === 0 && <option value={strategy}>{strategy}</option>}
              {strategies.map((x) => (<option key={x.name} value={x.name}>{x.name}</option>))}
            </select>
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 220 }}>
            <label className="qf-prop-label">参数 JSON</label>
            <input value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 180 }}>
            <label className="qf-prop-label">标的（逗号分隔）</label>
            <input value={symbols} onChange={(e) => setSymbols(e.target.value)} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
          <div className="qf-prop-field" style={{ width: 140 }}>
            <label className="qf-prop-label">开始</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ width: 140 }}>
            <label className="qf-prop-label">结束</label>
            <input value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="qf-prop-field" style={{ width: 110 }}>
            <label className="qf-prop-label">折数</label>
            <input type="number" min="2" max="20" value={nFolds} onChange={(e) => setNFolds(e.target.value)} />
          </div>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '验证中…' : '运行样本外验证'}
          </button>
        </div>
      </form>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="qf-hint">策略 {result.strategy} · 共 {result.n_folds} 折 · 样本外折 {s.n_oos_folds}</div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
            <StatCard label="样本内平均收益" value={fmtPct(s.mean_is_return)} color="#2563eb" />
            <StatCard label="样本外平均收益" value={fmtPct(s.mean_oos_return)} color="#f97316"
              sub={`衰减 ${fmtPct((s.mean_oos_return ?? 0) - (s.mean_is_return ?? 0))}`} />
            <StatCard label="样本内/外夏普" value={`${fmtNum(s.mean_is_sharpe)} / ${fmtNum(s.mean_oos_sharpe)}`} />
            <StatCard label="样本外胜率" value={fmtPct(s.oos_positive_rate, 0)} color="#15803d" />
            <StatCard label="跑赢样本内比率" value={fmtPct(s.oos_beats_is_rate, 0)} color="#a855f7" />
          </div>

          <div className="qf-an-block" style={{ marginTop: 14, background: '#1e293b', borderRadius: 10, padding: 12 }}>
            <div style={{ fontSize: 13, color: '#e2e8f0', marginBottom: 6 }}>逐折样本内 vs 样本外收益</div>
            <FoldBars folds={result.folds} />
          </div>

          <table className="qf-state-table" style={{ marginTop: 14 }}>
            <thead>
              <tr>
                <th>测试区间</th>
                <th>样本内收益</th>
                <th>样本外收益</th>
                <th>收益衰减</th>
                <th>样本内夏普</th>
                <th>样本外夏普</th>
              </tr>
            </thead>
            <tbody>
              {result.folds.map((f, i) => (
                <tr key={i}>
                  <td>{f.test_period?.start} ~ {f.test_period?.end}</td>
                  <td style={{ color: (f.is_metrics?.total_return || 0) >= 0 ? '#15803d' : '#dc2626' }}>{fmtPct(f.is_metrics?.total_return)}</td>
                  <td style={{ color: (f.oos_metrics?.total_return || 0) >= 0 ? '#15803d' : '#dc2626' }}>{fmtPct(f.oos_metrics?.total_return)}</td>
                  <td style={{ color: (f.degradation_total_return || 0) >= 0 ? '#15803d' : '#dc2626' }}>{fmtPct(f.degradation_total_return)}</td>
                  <td>{fmtNum(f.is_metrics?.sharpe)}</td>
                  <td>{fmtNum(f.oos_metrics?.sharpe)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
