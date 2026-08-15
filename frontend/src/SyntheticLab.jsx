import { useState } from 'react'
import { runSyntheticBacktest } from './api.js'

function LineChart({ points, color = '#2563eb' }) {
  const w = 720, h = 200, pad = 24
  if (!points || points.length < 2) return <div style={{ color: '#9ca3af' }}>无数据</div>
  const xs = points.map((_, i) => i)
  const ys = points
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const x = (i) => pad + (i / (points.length - 1)) * (w - 2 * pad)
  const y = (v) => pad + (1 - (v - minY) / (maxY - minY || 1)) * (h - 2 * pad)
  const path = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`}>
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#eee" />
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" />
      <text x={pad} y={pad - 6} fontSize="11" fill="#9ca3af">高 {maxY.toFixed(0)}</text>
      <text x={pad} y={h - pad + 14} fontSize="11" fill="#9ca3af">低 {minY.toFixed(0)}</text>
    </svg>
  )
}

export default function SyntheticLab() {
  const [symbols, setSymbols] = useState('SYN.A,SYN.B')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [mu, setMu] = useState('0.08')
  const [sigma, setSigma] = useState('0.20')
  const [seed, setSeed] = useState('42')
  const [regime, setRegime] = useState(false)
  const [strategy, setStrategy] = useState('ma_cross')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    const syms = symbols.split(',').map((s) => s.trim()).filter(Boolean)
    if (!syms.length) { setErr('请填写标的'); return }
    setLoading(true)
    try {
      const res = await runSyntheticBacktest({
        strategy, params: {}, symbols: syms, start, end,
        mu_annual: parseFloat(mu), sigma_annual: parseFloat(sigma),
        seed: parseInt(seed, 10), regime,
      })
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const m = data?.metrics
  const curve = (data?.equity_curve || []).map((p) => p.total_value)

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>合成行情实验室 <span style={{ fontSize: 12, color: '#16a34a' }}>V20</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        用几何布朗运动（可选牛/熊状态切换）生成逼真日线，无需真实行情源即可回测策略。
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(220px, 1fr))', gap: 8, marginBottom: 12 }}>
        <input placeholder="标的(逗号分隔)" value={symbols} onChange={(e) => setSymbols(e.target.value)} style={inp} />
        <input placeholder="策略名" value={strategy} onChange={(e) => setStrategy(e.target.value)} style={inp} />
        <input placeholder="起始" value={start} onChange={(e) => setStart(e.target.value)} style={inp} />
        <input placeholder="结束" value={end} onChange={(e) => setEnd(e.target.value)} style={inp} />
        <input placeholder="年化漂移 mu" value={mu} onChange={(e) => setMu(e.target.value)} style={inp} />
        <input placeholder="年化波动 sigma" value={sigma} onChange={(e) => setSigma(e.target.value)} style={inp} />
        <input placeholder="随机种子" value={seed} onChange={(e) => setSeed(e.target.value)} style={inp} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={regime} onChange={(e) => setRegime(e.target.checked)} /> 启用牛/熊状态切换
        </label>
      </div>
      <button onClick={run} disabled={loading}
        style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
        {loading ? '生成并回测…' : '生成并回测'}
      </button>

      {err ? <div style={{ color: '#dc2626', marginTop: 8 }}>{err}</div> : null}

      {data ? (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <Stat label="总收益" value={pct(m?.total_return)} />
            <Stat label="年化" value={pct(m?.annual_return)} />
            <Stat label="夏普" value={fmt(m?.sharpe)} />
            <Stat label="最大回撤" value={pct(m?.max_drawdown)} tone="bad" />
            <Stat label="交易日" value={m?.days} />
          </div>
          <h3 style={{ fontSize: 14 }}>净值曲线（合成行情回测）</h3>
          <LineChart points={curve} />
        </div>
      ) : null}
    </div>
  )
}

const inp = { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 }
const pct = (v) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(2)}%`
const fmt = (v) => (v === null || v === undefined) ? '—' : Number(v).toFixed(4)
function Stat({ label, value, tone }) {
  const color = tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}
