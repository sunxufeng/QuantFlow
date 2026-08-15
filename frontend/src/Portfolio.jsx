import { useCallback, useEffect, useMemo, useState } from 'react'
import { backtestStrategies, runPortfolioBacktest } from './api.js'

const REBALANCE_OPTS = [
  { v: 'none', label: '买入持有（不再平衡）' },
  { v: 'D', label: '每日' },
  { v: 'W', label: '每周' },
  { v: 'M', label: '每月' },
  { v: 'Q', label: '每季' },
  { v: 'Y', label: '每年' },
]

const DEFAULT_LEG = { strategy: 'ma_cross', symbols: 'TEST.STOCK', weight: 1 }

function NavChart({ curve, benchmark }) {
  if (!curve || curve.length < 2) return null
  const W = 720
  const H = 220
  const pad = 36
  const vals = curve.map((p) => p.total_value)
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  const benchVals = benchmark && benchmark.length >= 2 ? benchmark.map((p) => p.value) : null
  if (benchVals) {
    lo = Math.min(lo, ...benchVals)
    hi = Math.max(hi, ...benchVals)
  }
  const span = hi - lo || 1
  const x = (i) => pad + (i / (curve.length - 1)) * (W - pad * 2)
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  const path = curve.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.total_value).toFixed(1)}`).join(' ')
  const first = vals[0]
  const last = vals[vals.length - 1]
  const up = last >= first
  const color = up ? '#15803d' : '#dc2626'
  const benchPath = benchVals
    ? benchVals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
    : null
  return (
    <div className="qf-an-block">
      <div className="qf-an-title">组合净值曲线（{curve.length} 个交易日）</div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 220 }}>
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" strokeWidth="1" />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" strokeWidth="1" />
        {benchPath && (
          <path d={benchPath} fill="none" stroke="#94a3b8" strokeWidth="1.4" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
        )}
        <path d={path} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <text x={pad} y={pad - 8} fill="#64748b" fontSize="10">{hi.toFixed(0)}</text>
        <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="10">{lo.toFixed(0)}</text>
        <text x={W - pad} y={H - pad + 14} fill="#64748b" fontSize="9" textAnchor="end">
          {curve[curve.length - 1].date}
        </text>
        <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="9">{curve[0].date}</text>
      </svg>
      {benchPath && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 4, fontSize: 11 }}>
          <span style={{ color: '#15803d', fontWeight: 600 }}>— 组合净值</span>
          <span style={{ color: '#94a3b8' }}>-- 等权基准（{benchmark && benchmark.length ? benchmark[0].date : ''} 起）</span>
        </div>
      )}
    </div>
  )
}

const LEG_COLORS = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2', '#db2777', '#65a30d']

function AttributionChart({ attribution }) {
  if (!attribution || !attribution.by_leg || attribution.by_leg.length === 0) return null
  const dates = attribution.dates || []
  const legs = attribution.by_leg
  const n = dates.length
  if (n < 2) return null
  const W = 720
  const H = 240
  const pad = 40
  const step = Math.max(1, Math.floor(n / 320))
  const idxs = []
  for (let i = 0; i < n; i += step) idxs.push(i)
  if (idxs[idxs.length - 1] !== n - 1) idxs.push(n - 1)
  // 组合总贡献 = 各腿贡献逐日求和
  const totalSeries = dates.map((_, i) => legs.reduce((s, l) => s + (l.cumulative_return_contrib[i] || 0), 0))
  let lo = 0
  let hi = 0
  for (const l of legs) for (const v of l.cumulative_return_contrib) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
  for (const v of totalSeries) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
  const span = hi - lo || 1
  const x = (k) => pad + (k / (idxs.length - 1)) * (W - pad * 2)
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  const line = (series) => idxs.map((i, k) => `${k === 0 ? 'M' : 'L'}${x(k).toFixed(1)},${y(series[i]).toFixed(1)}`).join(' ')
  return (
    <div className="qf-an-block">
      <div className="qf-an-title">
        绩效归因：各腿累计收益贡献（再平衡后真实权重，求和 = 组合总收益）
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 240 }}>
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#cbd5e1" />
        <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="#94a3b8" strokeDasharray="3 3" />
        {legs.map((l, li) => (
          <path
            key={li}
            d={line(l.cumulative_return_contrib)}
            fill="none"
            stroke={LEG_COLORS[li % LEG_COLORS.length]}
            strokeWidth="1.6"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <path d={line(totalSeries)} fill="none" stroke="#0f172a" strokeWidth="2.2" strokeDasharray="6 3" vectorEffect="non-scaling-stroke" />
        <text x={pad} y={pad - 8} fill="#64748b" fontSize="10">{(hi * 100).toFixed(1)}%</text>
        <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="10">{(lo * 100).toFixed(1)}%</text>
        <text x={W - pad} y={H - pad + 14} fill="#64748b" fontSize="9" textAnchor="end">{dates[n - 1]}</text>
        <text x={pad} y={H - pad + 14} fill="#64748b" fontSize="9">{dates[0]}</text>
      </svg>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 6, fontSize: 11 }}>
        <span style={{ color: '#0f172a', fontWeight: 600 }}>— 组合总收益</span>
        {legs.map((l, li) => (
          <span key={li} style={{ color: LEG_COLORS[li % LEG_COLORS.length] }}>
            ■ {l.strategy}（{((l.final_contrib || 0) * 100).toFixed(2)}%）
          </span>
        ))}
      </div>
    </div>
  )
}

function AttributionTable({ legs, attribution }) {
  if (!attribution || !attribution.by_leg) return null
  const total = attribution.total_return || 0
  return (
    <table className="qf-state-table" style={{ marginTop: 6 }}>
      <thead>
        <tr>
          <th>腿</th><th>策略</th><th>权重</th><th>腿收益</th>
          <th>对组合收益贡献</th><th>贡献占比</th>
        </tr>
      </thead>
      <tbody>
        {attribution.by_leg.map((b) => {
          const lg = (legs || []).find((l) => l.index === b.index) || {}
          const share = total !== 0 ? b.final_contrib / total : 0
          return (
            <tr key={b.index}>
              <td>{b.index}</td>
              <td>{b.strategy}</td>
              <td>{(b.weight * 100).toFixed(1)}%</td>
              <td>{((lg.total_return || 0) * 100).toFixed(2)}%</td>
              <td style={{ color: b.final_contrib >= 0 ? '#15803d' : '#dc2626' }}>
                {(b.final_contrib * 100).toFixed(2)}%
              </td>
              <td>{(share * 100).toFixed(1)}%</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function RiskDecomp({ risk, legs }) {
  if (!risk) return null
  const n = (risk.risk_contrib_pct || []).length
  if (n === 0) return null
  const maxPct = Math.max(1e-6, ...risk.risk_contrib_pct.map((v) => Math.abs(v)))
  return (
    <div className="qf-an-block">
      <div className="qf-an-title">
        风险分解（V13 · 欧拉波动率分解，各腿风险贡献之和 = 组合波动）
      </div>
      <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 6 }}>
        组合年化波动率：<b style={{ color: '#0f172a' }}>{(risk.portfolio_vol_annual * 100).toFixed(2)}%</b>
      </div>
      <table className="qf-state-table" style={{ marginTop: 6 }}>
        <thead>
          <tr>
            <th>腿</th><th>策略</th><th>权重</th><th>腿年化波动</th>
            <th>风险贡献(年化)</th><th>风险贡献占比</th>
          </tr>
        </thead>
        <tbody>
          {risk.risk_contrib_pct.map((pct, k) => {
            const lg = (legs || []).find((l) => l.index === k) || {}
            return (
              <tr key={k}>
                <td>{k}</td>
                <td>{lg.strategy || ''}</td>
                <td>{((risk.weights?.[k] || 0) * 100).toFixed(1)}%</td>
                <td>{((risk.per_leg_vol_annual?.[k] || 0) * 100).toFixed(2)}%</td>
                <td>{((risk.risk_contrib_annual?.[k] || 0) * 100).toFixed(2)}%</td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{
                      width: `${Math.max(2, (Math.abs(pct) / maxPct) * 120)}px`,
                      height: 10, borderRadius: 3,
                      background: pct >= 0 ? '#2563eb' : '#dc2626',
                    }} />
                    <span>{(pct * 100).toFixed(1)}%</span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {n > 1 && (
        <div style={{ marginTop: 10 }}>
          <div className="qf-an-title" style={{ fontSize: 12 }}>相关系数矩阵</div>
          <table className="qf-state-table" style={{ marginTop: 4, width: 'auto' }}>
            <thead>
              <tr><th></th>{risk.correlation.map((_, k) => <th key={k}>腿{k}</th>)}</tr>
            </thead>
            <tbody>
              {risk.correlation.map((row, a) => (
                <tr key={a}>
                  <td>腿{a}</td>
                  {row.map((v, b) => (
                    <td key={b} style={{
                      color: a === b ? '#0f172a' : (v >= 0 ? '#15803d' : '#dc2626'),
                      fontWeight: a === b ? 700 : 400,
                    }}>{v.toFixed(2)}</td>
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

function FactorExposure({ exposure }) {
  if (!exposure || !exposure.factors || exposure.factors.length === 0) return null
  const maxW = Math.max(1e-6, ...exposure.factors.map((f) => Math.abs(f.exposure_weight)))
  return (
    <div className="qf-an-block">
      <div className="qf-an-title">
        组合因子暴露（V14 · 按策略关联因子聚合 IC/IR 与暴露占比）
      </div>
      <table className="qf-state-table" style={{ marginTop: 6 }}>
        <thead>
          <tr>
            <th>因子</th><th>加权 IC 均值</th><th>IR</th><th>组合暴露占比</th>
          </tr>
        </thead>
        <tbody>
          {exposure.factors.map((f) => (
            <tr key={f.factor}>
              <td>{f.factor}</td>
              <td style={{ color: f.ic_mean >= 0 ? '#15803d' : '#dc2626' }}>
                {f.ic_mean.toFixed(4)}
              </td>
              <td style={{ color: f.ir >= 0 ? '#15803d' : '#dc2626' }}>
                {f.ir.toFixed(4)}
              </td>
              <td>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{
                    width: `${Math.max(2, (Math.abs(f.exposure_weight) / maxW) * 140)}px`,
                    height: 10, borderRadius: 3,
                    background: '#7c3aed',
                  }} />
                  <span>{(f.exposure_weight * 100).toFixed(1)}%</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="qf-hint" style={{ marginTop: 6 }}>
        暴露占比按「引用该因子的各腿权重」归一，总和 = 100%；IC 均值为该因子在样本内对收益方向预测能力的度量。
      </div>
    </div>
  )
}

export default function Portfolio() {
  const [strategies, setStrategies] = useState([])
  const [legs, setLegs] = useState([{ ...DEFAULT_LEG }])
  const [rebalance, setRebalance] = useState('M')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [initialCash, setInitialCash] = useState(1000000)
  const [benchmarkSymbol, setBenchmarkSymbol] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    backtestStrategies()
      .then((r) => setStrategies(r.items || []))
      .catch(() => setStrategies([]))
  }, [])

  const updateLeg = useCallback((idx, patch) => {
    setLegs((ls) => ls.map((l, i) => (i === idx ? { ...l, ...patch } : l)))
  }, [])
  const addLeg = useCallback(() => {
    setLegs((ls) => [...ls, { ...DEFAULT_LEG, symbols: '', weight: 1 }])
  }, [])
  const removeLeg = useCallback((idx) => {
    setLegs((ls) => (ls.length <= 1 ? ls : ls.filter((_, i) => i !== idx)))
  }, [])

  const run = useCallback(async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    const payload = {
      legs: legs.map((l) => ({
        strategy: l.strategy,
        symbols: l.symbols.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
        weight: Number(l.weight) || 1,
        params: l.strategy === 'ma_cross' ? { fast: 5, slow: 20 } : {},
      })),
      initial_cash: Number(initialCash) || 1000000,
      start,
      end,
      rebalance,
      benchmark_symbol: benchmarkSymbol.trim() || undefined,
    }
    if (payload.legs.some((l) => l.symbols.length === 0)) {
      setError('每条腿至少需要一个标的')
      setBusy(false)
      return
    }
    try {
      const res = await runPortfolioBacktest(payload)
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [legs, initialCash, start, end, rebalance])

  const m = result?.metrics || {}
  const lastAlloc = result?.equity_curve?.[result.equity_curve.length - 1]?.allocation || {}

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
        <div className="qf-result-head">
          <h3>组合回测（V14 · 多腿 + 再平衡 + 绩效归因 + 风险分解 + 因子暴露 + 基准对比）</h3>
        </div>
      <form className="qf-prop-form" onSubmit={run} style={{ maxWidth: 860 }}>
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          每条腿 = 一个策略 + 一组标的 + 权重；按权重合并为组合净值，支持周期性再平衡（买入持有 / 日 / 周 / 月 / 季 / 年）。
        </div>
        {legs.map((leg, idx) => (
          <div
            key={idx}
            style={{
              display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8,
              padding: 8, border: '1px solid #1e293b', borderRadius: 8, flexWrap: 'wrap',
            }}
          >
            <select
              className="qf-name-input"
              value={leg.strategy}
              onChange={(e) => updateLeg(idx, { strategy: e.target.value })}
              style={{ width: 150 }}
            >
              {strategies.length === 0 && <option value={leg.strategy}>{leg.strategy}</option>}
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>{s.name}</option>
              ))}
            </select>
            <input
              className="qf-name-input"
              value={leg.symbols}
              onChange={(e) => updateLeg(idx, { symbols: e.target.value })}
              placeholder="标的，逗号分隔"
              style={{ flex: 1, minWidth: 160 }}
            />
            <label style={{ fontSize: 12, color: '#94a3b8' }}>权重</label>
            <input
              className="qf-name-input"
              type="number"
              step="0.1"
              value={leg.weight}
              onChange={(e) => updateLeg(idx, { weight: e.target.value })}
              style={{ width: 80 }}
            />
            <button
              type="button"
              className="qf-btn qf-btn-sm"
              onClick={() => removeLeg(idx)}
              disabled={legs.length <= 1}
            >
              删除
            </button>
          </div>
        ))}
        <button type="button" className="qf-btn" onClick={addLeg} style={{ marginBottom: 8 }}>
          ＋ 添加腿
        </button>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 8 }}>
          <div className="qf-prop-field" style={{ width: 150 }}>
            <label className="qf-prop-label">再平衡频率</label>
            <select value={rebalance} onChange={(e) => setRebalance(e.target.value)}>
              {REBALANCE_OPTS.map((o) => (
                <option key={o.v} value={o.v}>{o.label}</option>
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
          <div className="qf-prop-field" style={{ width: 150 }}>
            <label className="qf-prop-label">初始资金</label>
            <input
              type="number"
              value={initialCash}
              onChange={(e) => setInitialCash(e.target.value)}
            />
          </div>
          <div className="qf-prop-field" style={{ width: 150 }}>
            <label className="qf-prop-label">基准标的（可选）</label>
            <input
              value={benchmarkSymbol}
              onChange={(e) => setBenchmarkSymbol(e.target.value)}
              placeholder="如 TEST.STOCK"
            />
          </div>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '回测中…' : '运行组合回测'}
          </button>
        </div>
      </form>

      {error && <div className="qf-error" style={{ marginTop: 12 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div className="qf-mcards">
            <div className="qf-mcard">
              <div className="qf-mcard-label">总收益</div>
              <div className="qf-mcard-value">{((m.total_return || 0) * 100).toFixed(2)}%</div>
            </div>
            <div className="qf-mcard">
              <div className="qf-mcard-label">年化收益</div>
              <div className="qf-mcard-value">{((m.annual_return || 0) * 100).toFixed(2)}%</div>
            </div>
            <div className="qf-mcard">
              <div className="qf-mcard-label">夏普</div>
              <div className="qf-mcard-value">{(m.sharpe || 0).toFixed(3)}</div>
            </div>
            <div className="qf-mcard">
              <div className="qf-mcard-label">最大回撤</div>
              <div className="qf-mcard-value">{((m.max_drawdown || 0) * 100).toFixed(2)}%</div>
            </div>
          </div>

          <NavChart curve={result.equity_curve} benchmark={result.benchmark_curve} />

          <div className="qf-an-title" style={{ marginTop: 12 }}>
            各腿明细（run_id: {result.run_id} · 再平衡: {result.rebalance}）
          </div>
          <table className="qf-state-table" style={{ marginTop: 6 }}>
            <thead>
              <tr>
                <th>腿</th><th>策略</th><th>权重</th><th>分配资金</th>
                <th>期末市值</th><th>总收益</th><th>夏普</th><th>最大回撤</th><th>交易数</th>
              </tr>
            </thead>
            <tbody>
              {(result.legs || []).map((lg) => (
                <tr key={lg.index}>
                  <td>{lg.index}</td>
                  <td>{lg.strategy}</td>
                  <td>{(lg.weight * 100).toFixed(1)}%</td>
                  <td>{lg.allocated_cash?.toFixed(0)}</td>
                  <td>{lg.final_value?.toFixed(0)}</td>
                  <td>{((lg.total_return || 0) * 100).toFixed(2)}%</td>
                  <td>{(lg.sharpe || 0).toFixed(3)}</td>
                  <td>{((lg.max_drawdown || 0) * 100).toFixed(2)}%</td>
                  <td>{lg.n_trades}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="qf-an-title" style={{ marginTop: 16 }}>
            绩效归因（V12 · 组合总收益按各腿盈亏贡献分解）
          </div>
          <AttributionChart attribution={result.attribution} />
          <AttributionTable legs={result.legs} attribution={result.attribution} />

          <div className="qf-an-title" style={{ marginTop: 16 }}>
            风险分解（V13 · 组合波动按各腿贡献拆解）
          </div>
          <RiskDecomp risk={result.risk_decomposition} legs={result.legs} />

          {result.benchmark_symbol && (
            <div className="qf-hint" style={{ marginTop: 8 }}>
              {result.benchmark_symbol} 等权买入持有基准年化波动：
              {(((result.risk_decomposition?.portfolio_vol_annual) || 0) * 100).toFixed(2)}%（组合 vs 基准对照见上图虚线）
            </div>
          )}

          <div className="qf-an-title" style={{ marginTop: 16 }}>
            组合因子暴露（V14 · 按策略关联因子聚合）
          </div>
          <FactorExposure exposure={result.factor_exposure} />

          <div className="qf-hint" style={{ marginTop: 8 }}>
            期末配置占比：
            {Object.entries(lastAlloc).map(([k, v]) => (
              <span key={k} style={{ marginLeft: 8 }}>
                腿{k}: {((v || 0) * 100).toFixed(1)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
