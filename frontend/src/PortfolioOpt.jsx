import { useState } from 'react'
import { runPortfolioOptimize } from './api.js'

const inp = { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 }
const pct = (v) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(2)}%`
const num = (v, d = 3) => (v === null || v === undefined) ? '—' : Number(v).toFixed(d)

function Stat({ label, value, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

const SERIES_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6']

function FrontierChart({ frontier, ms, mv, symbols }) {
  if (!frontier || !frontier.length) return <div style={{ color: '#9ca3af' }}>无数据</div>
  const W = 720, H = 320, pad = { l: 48, r: 16, t: 16, b: 32 }
  const vols = frontier.map((p) => p.expected_vol)
  const rets = frontier.map((p) => p.expected_return)
  const vMin = Math.min(...vols, mv.expected_vol) * 0.95
  const vMax = Math.max(...vols, ms.expected_vol) * 1.05
  const rMin = Math.min(...rets, mv.expected_return) * 0.95
  const rMax = Math.max(...rets, ms.expected_return) * 1.05
  const xOf = (v) => pad.l + ((v - vMin) / ((vMax - vMin) || 1)) * (W - pad.l - pad.r)
  const yOf = (r) => H - pad.b - ((r - rMin) / ((rMax - rMin) || 1)) * (H - pad.t - pad.b)
  const pts = frontier.map((p) => `${xOf(p.expected_vol).toFixed(1)},${yOf(p.expected_return).toFixed(1)}`).join(' ')
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8 }}>
      <line x1={pad.l} y1={yOf(0)} x2={W - pad.r} y2={yOf(0)} stroke="#e5e7eb" />
      <line x1={xOf(0)} y1={pad.t} x2={xOf(0)} y2={H - pad.b} stroke="#e5e7eb" />
      <polyline points={pts} fill="none" stroke="#6366f1" strokeWidth="2" />
      <circle cx={xOf(ms.expected_vol)} cy={yOf(ms.expected_return)} r="6" fill="#10b981" stroke="#fff" strokeWidth="1.5">
        <title>最大夏普</title>
      </circle>
      <circle cx={xOf(mv.expected_vol)} cy={yOf(mv.expected_return)} r="6" fill="#ef4444" stroke="#fff" strokeWidth="1.5">
        <title>最小方差</title>
      </circle>
      <text x={W - pad.r} y={H - 10} fontSize="10" fill="#94a3b8" textAnchor="end">风险(年化σ) →</text>
      <text x={pad.l} y={pad.t - 2} fontSize="10" fill="#94a3b8">收益(年化μ) ↑</text>
    </svg>
  )
}

function WeightsTable({ title, port, symbols, highlight }) {
  if (!port) return null
  return (
    <div style={{ flex: 1, minWidth: 280 }}>
      <h3 style={{ fontSize: 14, margin: '4px 0' }}>
        {title} {highlight ? <span style={{ color: highlight }}>●</span> : null}
      </h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ color: '#6b7280', textAlign: 'right' }}>
            <th style={{ textAlign: 'left' }}>资产</th>
            <th>权重</th>
          </tr>
        </thead>
        <tbody>
          {symbols.map((s, i) => (
            <tr key={s}>
              <td>{s}</td>
              <td style={{ textAlign: 'right' }}>{pct(port.weights[i])}</td>
            </tr>
          ))}
          <tr style={{ fontWeight: 700, borderTop: '1px solid #e5e7eb' }}>
            <td>预期收益</td>
            <td style={{ textAlign: 'right' }}>{pct(port.expected_return)}</td>
          </tr>
          <tr>
            <td>预期波动</td>
            <td style={{ textAlign: 'right' }}>{pct(port.expected_vol)}</td>
          </tr>
          <tr>
            <td>夏普</td>
            <td style={{ textAlign: 'right' }}>{num(port.sharpe)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default function PortfolioOpt() {
  const [symbols, setSymbols] = useState('A.SHV, B.TECH, C.FIN, D.ENR')
  const [start, setStart] = useState('2022-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [longOnly, setLongOnly] = useState(true)
  const [rf, setRf] = useState('0.02')
  const [useSynth, setUseSynth] = useState(true)
  const [mu, setMu] = useState('0.08')
  const [sigma, setSigma] = useState('0.20')
  const [seed, setSeed] = useState('7')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    const syms = symbols.split(',').map((s) => s.trim()).filter(Boolean)
    if (syms.length < 2) { setErr('请至少填写 2 个资产（逗号分隔）'); return }
    setLoading(true)
    try {
      const payload = {
        symbols: syms, start, end, long_only: longOnly, rf: parseFloat(rf),
        synthetic: useSynth
          ? { mu_annual: parseFloat(mu), sigma_annual: parseFloat(sigma), seed: parseInt(seed, 10), regime: true }
          : null,
      }
      const res = await runPortfolioOptimize(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const syms = data?.symbols || []

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>投资组合优化 <span style={{ fontSize: 12, color: '#16a34a' }}>V23</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        Markowitz 均值-方差框架：最小方差组合、最大夏普组合，并在目标收益区间采样有效前沿（绿点=最大夏普，红点=最小方差）。可一键切换 GBM 合成行情，无需真实数据。
      </p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <input placeholder="资产逗号分隔" value={symbols} onChange={(e) => setSymbols(e.target.value)} style={{ ...inp, width: 240 }} />
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={inp} />
        <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={inp} />
        <input placeholder="无风险rf" value={rf} onChange={(e) => setRf(e.target.value)} style={{ ...inp, width: 90 }} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13 }}>
          <input type="checkbox" checked={longOnly} onChange={(e) => setLongOnly(e.target.checked)} /> 多头
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13 }}>
          <input type="checkbox" checked={useSynth} onChange={(e) => setUseSynth(e.target.checked)} /> 合成行情
        </label>
        {useSynth ? (
          <>
            <input placeholder="μ" value={mu} onChange={(e) => setMu(e.target.value)} style={{ ...inp, width: 70 }} />
            <input placeholder="σ" value={sigma} onChange={(e) => setSigma(e.target.value)} style={{ ...inp, width: 70 }} />
            <input placeholder="种子" value={seed} onChange={(e) => setSeed(e.target.value)} style={{ ...inp, width: 70 }} />
          </>
        ) : null}
        <button onClick={run} disabled={loading}
          style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          {loading ? '优化中…' : '优化'}
        </button>
      </div>

      {err ? <div style={{ color: '#dc2626' }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <Stat label="资产数" value={data.n_assets} />
            <Stat label="样本期数" value={data.n_periods} />
            <Stat label="数据源" value={data.source === 'synthetic' ? '合成行情' : '真实行情'} />
            <Stat label="最大夏普" value={num(data.max_sharpe?.sharpe)} tone="good" />
            <Stat label="最小方差波动" value={pct(data.min_variance?.expected_vol)} tone="good" />
          </div>

          <h3 style={{ fontSize: 14 }}>有效前沿</h3>
          <FrontierChart frontier={data.frontier} ms={data.max_sharpe} mv={data.min_variance} symbols={syms} />

          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 12 }}>
            <WeightsTable title="最小方差组合" port={data.min_variance} symbols={syms} highlight="#ef4444" />
            <WeightsTable title="最大夏普组合" port={data.max_sharpe} symbols={syms} highlight="#10b981" />
            <WeightsTable title="等权组合(参考)" port={data.equal_weight} symbols={syms} />
          </div>
        </div>
      ) : null}
    </div>
  )
}
