import { useState } from 'react'
import { runForwardSim } from './api.js'

function FanChart({ bands }) {
  const w = 720, h = 220, pad = 24
  if (!bands || bands.length < 2) return <div style={{ color: '#9ca3af' }}>无数据</div>
  const n = bands.length
  const lows = bands.map((b) => b.p_low)
  const highs = bands.map((b) => b.p_high)
  const meds = bands.map((b) => b.p50)
  const minY = Math.min(...lows), maxY = Math.max(...highs)
  const x = (i) => pad + (i / (n - 1)) * (w - 2 * pad)
  const y = (v) => pad + (1 - (v - minY) / (maxY - minY || 1)) * (h - 2 * pad)
  const area = (upper, lower) => {
    const up = upper.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
    const dn = lower.map((v, i) => `L${x(n - 1 - i).toFixed(1)},${y(lower[n - 1 - i]).toFixed(1)}`).join(' ')
    return `${up} ${dn} Z`
  }
  const med = meds.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`}>
      <path d={area(highs, lows)} fill="rgba(37,99,235,0.12)" />
      <path d={med} fill="none" stroke="#2563eb" strokeWidth="2" />
      <text x={pad} y={pad - 6} fontSize="11" fill="#9ca3af">上沿 {maxY.toFixed(0)}</text>
      <text x={pad} y={h - pad + 14} fontSize="11" fill="#9ca3af">下沿 {minY.toFixed(0)}</text>
    </svg>
  )
}

function Histogram({ hist }) {
  if (!hist || !hist.counts || !hist.counts.length) return <div style={{ color: '#9ca3af' }}>无数据</div>
  const w = 720, h = 160, pad = 24
  const counts = hist.counts
  const maxC = Math.max(...counts) || 1
  const n = counts.length
  const bw = (w - 2 * pad) / n
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`}>
      {counts.map((c, i) => {
        const bh = (c / maxC) * (h - 2 * pad)
        return <rect key={i} x={pad + i * bw} y={h - pad - bh} width={bw - 1} height={bh} fill="#6366f1" />
      })}
    </svg>
  )
}

export default function ForwardSim() {
  const [runId, setRunId] = useState('')
  const [horizon, setHorizon] = useState('252')
  const [nPaths, setNPaths] = useState('200')
  const [seed, setSeed] = useState('42')
  const [target, setTarget] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    if (!runId.trim()) { setErr('请填写 run_id'); return }
    setLoading(true)
    try {
      const payload = { run_id: runId.trim(), horizon: parseInt(horizon, 10), n_paths: parseInt(nPaths, 10), seed: parseInt(seed, 10) }
      if (target.trim()) payload.target_return = parseFloat(target)
      const res = await runForwardSim(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const s = data?.summary
  const fr = s?.future_return || {}

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>前向模拟 <span style={{ fontSize: 12, color: '#16a34a' }}>V20</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        基于回测的日收益经验分布，向未来投影 {horizon || 252} 个交易日，生成多条未来净值路径的置信带与期末分布。
      </p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <input placeholder="回测 run_id" value={runId} onChange={(e) => setRunId(e.target.value)} style={inp} />
        <input placeholder="投影天数" value={horizon} onChange={(e) => setHorizon(e.target.value)} style={{ ...inp, width: 100 }} />
        <input placeholder="路径数" value={nPaths} onChange={(e) => setNPaths(e.target.value)} style={{ ...inp, width: 90 }} />
        <input placeholder="种子" value={seed} onChange={(e) => setSeed(e.target.value)} style={{ ...inp, width: 80 }} />
        <input placeholder="目标收益(可选,如0.1)" value={target} onChange={(e) => setTarget(e.target.value)} style={{ ...inp, width: 160 }} />
        <button onClick={run} disabled={loading}
          style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          {loading ? '模拟中…' : '前向模拟'}
        </button>
      </div>

      {err ? <div style={{ color: '#dc2626' }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <Stat label="起点净值" value={data.start_value} />
            <Stat label="未来收益 P50" value={pct(fr.p50)} />
            <Stat label="未来收益 P5~P95" value={`${pct(fr.p5)}~${pct(fr.p95)}`} />
            <Stat label="达成目标概率" value={data.prob_target === null ? '—' : `${(data.prob_target * 100).toFixed(1)}%`} tone={data.prob_target >= 0.5 ? 'good' : 'bad'} />
          </div>
          <h3 style={{ fontSize: 14 }}>未来净值置信带（P5~P95）</h3>
          <FanChart bands={data.bands} />
          <h3 style={{ fontSize: 14 }}>期末净值分布</h3>
          <Histogram hist={data.histogram} />
        </div>
      ) : null}
    </div>
  )
}

const inp = { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 }
const pct = (v) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(2)}%`
function Stat({ label, value, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}
