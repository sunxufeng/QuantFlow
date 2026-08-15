import { useState } from 'react'
import { runMetricsExtended } from './api.js'

function StatCard({ label, value, hint, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 12px', minWidth: 120 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
      {hint ? <div style={{ fontSize: 11, color: '#9ca3af' }}>{hint}</div> : null}
    </div>
  )
}

function UnderwaterChart({ underwater }) {
  const w = 720
  const h = 180
  const pad = 24
  const n = underwater.length
  if (n < 2) return <div style={{ color: '#9ca3af' }}>数据不足</div>
  const minD = Math.min(...underwater)
  const x = (i) => pad + (i / (n - 1)) * (w - 2 * pad)
  const y = (d) => pad + (d / (minD || -1)) * (h - 2 * pad)
  const path = underwater.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(d).toFixed(1)}`).join(' ')
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`}>
      <line x1={pad} y1={pad} x2={w - pad} y2={pad} stroke="#eee" />
      <path d={path} fill="rgba(220,38,38,0.12)" stroke="#dc2626" strokeWidth="1.5" />
      <text x={pad} y={h - 6} fontSize="11" fill="#9ca3af">0%</text>
      <text x={pad} y={y(minD) + 12} fontSize="11" fill="#dc2626">{(minD * 100).toFixed(1)}%</text>
    </svg>
  )
}

export default function RiskReport() {
  const [runId, setRunId] = useState('')
  const [bench, setBench] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    if (!runId.trim()) { setErr('请填写 run_id'); return }
    setLoading(true)
    try {
      const payload = { run_id: runId.trim() }
      if (bench.trim()) payload.benchmark_symbol = bench.trim()
      const res = await runMetricsExtended(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const m = data?.metrics
  const er = m?.extended_risk || {}
  const risk = m?.attribution?.risk || {}
  const periods = m?.attribution?.curve?.drawdown_periods || []

  const fmtPct = (v) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(2)}%`
  const fmtNum = (v, d = 4) => (v === null || v === undefined) ? '—' : Number(v).toFixed(d)

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>扩展风险指标 <span style={{ fontSize: 12, color: '#16a34a' }}>V18</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        基于已存回测报告的净值曲线与成交记录，计算 CVaR / Calmar / Omega / 期望收益，并绘制水下回撤曲线。
      </p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <input placeholder="回测 run_id" value={runId} onChange={(e) => setRunId(e.target.value)}
          style={{ padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, width: 280 }} />
        <input placeholder="可选基准标的(如 000300.SH)" value={bench} onChange={(e) => setBench(e.target.value)}
          style={{ padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6, width: 200 }} />
        <button onClick={run} disabled={loading}
          style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          {loading ? '计算中…' : '计算指标'}
        </button>
      </div>

      {err ? <div style={{ color: '#dc2626' }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ fontSize: 13, color: '#374151', marginBottom: 8 }}>
            策略：{data.strategy} · 标的：{(data.symbols || []).join(', ')} · 交易日：{m?.days}
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
            <StatCard label="年化波动" value={fmtPct(risk.volatility)} />
            <StatCard label="下行波动(索提诺分母)" value={fmtPct(risk.downside_deviation)} />
            <StatCard label="索提诺" value={fmtNum(risk.sortino)} />
            <StatCard label="VaR95(年化)" value={fmtPct(er.var95_annual)} tone="bad" />
            <StatCard label="CVaR95(年化)" value={fmtPct(er.cvar95_annual)} tone="bad" />
            <StatCard label="Calmar" value={fmtNum(er.calmar)} tone={er.calmar > 0 ? 'good' : 'bad'} />
            <StatCard label="Omega" value={fmtNum(er.omega)} tone={er.omega >= 1 ? 'good' : 'bad'} />
            <StatCard label="期望收益/笔" value={fmtNum(er.expectancy, 2)} tone={er.expectancy > 0 ? 'good' : 'bad'} />
            <StatCard label="最大回撤" value={fmtPct(m?.max_drawdown)} tone="bad" />
            <StatCard label="夏普" value={fmtNum(m?.sharpe)} />
          </div>

          <h3 style={{ fontSize: 14 }}>水下回撤曲线</h3>
          <UnderwaterChart underwater={er.underwater || []} />

          {periods.length ? (
            <div style={{ marginTop: 16 }}>
              <h3 style={{ fontSize: 14 }}>回撤区间（共 {periods.length} 段）</h3>
              <table style={{ borderCollapse: 'collapse', fontSize: 13, width: '100%' }}>
                <thead>
                  <tr style={{ background: '#f3f4f6' }}>
                    <th style={th}>起点</th><th style={th}>终点</th><th style={th}>深度</th><th style={th}>持续(交易日)</th>
                  </tr>
                </thead>
                <tbody>
                  {periods.map((p, i) => (
                    <tr key={i}>
                      <td style={td}>{p.start}</td><td style={td}>{p.end}</td>
                      <td style={{ ...td, color: '#dc2626' }}>{fmtPct(p.depth)}</td>
                      <td style={td}>{p.days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

const th = { border: '1px solid #e5e7eb', padding: '6px 8px', textAlign: 'left' }
const td = { border: '1px solid #e5e7eb', padding: '6px 8px' }
