import React, { useState } from 'react'
import { runBenchmarkWeighted } from './api.js'

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{ flex: '1 1 120px', minWidth: 120, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ fontSize: 12, color: '#8a94a6' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: color || '#1f2733', marginTop: 4 }}>{value ?? '—'}</div>
      {sub && <div style={{ fontSize: 11, color: '#aab2c0', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function OverlayChart({ dates, series }) {
  // series: [{ name, color, points:[{date,value}] }]  → 归一化叠加对比
  if (!series.length) return null
  const W = 680, H = 240, P = 34
  const all = series.flatMap((s) => s.points.map((p) => p.value))
  const lo = Math.min(...all, 0.9)
  const hi = Math.max(...all, 1.1)
  const n = dates.length
  const x = (i) => P + (i / Math.max(1, n - 1)) * (W - 2 * P)
  const y = (v) => H - P - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - 2 * P)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ background: '#fff', border: '1px solid #eceef1', borderRadius: 10 }}>
      {series.map((s) => {
        const path = s.points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
        return <path key={s.name} d={path} fill="none" stroke={s.color} strokeWidth="2" />
      })}
      <g>
        {series.map((s, k) => (
          <g key={s.name} transform={`translate(${P + 6}, ${P + 4 + k * 16})`}>
            <rect width="10" height="10" fill={s.color} y="-9" />
            <text x="16" y="0" fontSize="11" fill="#555">{s.name}</text>
          </g>
        ))}
      </g>
    </svg>
  )
}

const PALETTE = ['#3b6cf6', '#f0913b', '#1a9c5b', '#9b59b6', '#e74c3c', '#16a2b8']

export default function WeightedBenchmarks() {
  const [runId, setRunId] = useState('')
  const [benchmarks, setBenchmarks] = useState([{ name: '沪深300篮子', weight: 1, symbols: 'TEST.BANK,TEST.FUND' }])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [data, setData] = useState(null)

  function updateBm(i, key, value) {
    setBenchmarks((arr) => arr.map((b, k) => k === i ? { ...b, [key]: value } : b))
  }
  function addBm() {
    setBenchmarks((arr) => [...arr, { name: `基准${arr.length + 1}`, weight: 1, symbols: '' }])
  }
  function removeBm(i) {
    setBenchmarks((arr) => arr.filter((_, k) => k !== i))
  }

  async function run() {
    if (!runId.trim()) { setErr('请先填写已存报告的 run_id'); return }
    setLoading(true); setErr('')
    try {
      const payload = {
        run_id: runId.trim(),
        benchmarks: benchmarks.map((b) => ({
          name: b.name,
          weight: Number(b.weight) || 1,
          symbols: b.symbols.split(',').map((s) => s.trim()).filter(Boolean),
        })),
      }
      const res = await runBenchmarkWeighted(payload)
      setData(res)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  const rel = data?.composite_relative || {}
  const dates = data?.strategy_curve?.map((p) => p.date) || []

  const norm = (pts) => {
    if (!pts || !pts.length) return []
    const base = pts[0]?.value || 1
    return pts.map((p) => ({ date: p.date, value: (p.value || 0) / base }))
  }
  const overlaySeries = []
  if (data) {
    overlaySeries.push({ name: `策略(${data.strategy})`, color: '#222', points: norm(data.strategy_curve) })
    overlaySeries.push({ name: '加权复合基准', color: '#3b6cf6', points: norm(data.composite_curve) })
    ;(data.benchmarks || []).forEach((b, i) => overlaySeries.push({ name: `${b.name} (w=${b.weight})`, color: PALETTE[(i + 1) % PALETTE.length], points: norm(b.curve) }))
  }

  return (
    <div style={{ padding: 18 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20 }}>多基准加权对比 <span style={{ fontSize: 12, color: '#b0b8c4' }}>V17 · 无凭证</span></h2>
      <p style={{ color: '#8a94a6', fontSize: 13, marginTop: 0 }}>
        选一个已存报告作为策略曲线，叠加多个加权基准组成「复合基准」，计算相对绩效（beta / alpha / 跟踪误差 / 信息比率 / 超额收益）。
      </p>

      <div style={{ background: '#fafbfc', border: '1px solid #eceef1', borderRadius: 10, padding: 14 }}>
        <label style={{ fontSize: 12, color: '#6b7382' }}>已存报告 run_id<br />
          <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="报告中心复制 run_id" style={{ width: 320, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} />
        </label>

        <div style={{ marginTop: 12, fontSize: 13, fontWeight: 600, color: '#1f2733' }}>基准列表（带权重）</div>
        {benchmarks.map((b, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
            <input value={b.name} onChange={(e) => updateBm(i, 'name', e.target.value)} placeholder="名称" style={{ width: 150, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} />
            <input value={b.weight} type="number" min={0.01} step={0.1} onChange={(e) => updateBm(i, 'weight', e.target.value)} title="权重" style={{ width: 80, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} />
            <input value={b.symbols} onChange={(e) => updateBm(i, 'symbols', e.target.value)} placeholder="标的(逗号分隔)" style={{ width: 260, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} />
            <button onClick={() => removeBm(i)} style={{ padding: '6px 10px', background: '#fff', border: '1px solid #dfe3e8', borderRadius: 6, cursor: 'pointer', color: '#d23' }}>删除</button>
          </div>
        ))}
        <button onClick={addBm} style={{ marginTop: 8, padding: '6px 12px', background: '#fff', border: '1px solid #3b6cf6', color: '#3b6cf6', borderRadius: 6, cursor: 'pointer' }}>+ 增加基准</button>

        <div style={{ marginTop: 12 }}>
          <button onClick={run} disabled={loading} style={{ padding: '8px 18px', background: '#3b6cf6', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, cursor: 'pointer' }}>
            {loading ? '对比中…' : '运行对比'}
          </button>
        </div>
      </div>
      {err && <div style={{ color: '#d23', marginTop: 10 }}>错误：{err}</div>}

      {data && (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
            <StatCard label="Beta" value={rel.beta} />
            <StatCard label="Alpha" value={rel.alpha} sub="年化" color="#1a9c5b" />
            <StatCard label="跟踪误差" value={rel.tracking_error} />
            <StatCard label="信息比率" value={rel.information_ratio} color="#3b6cf6" />
            <StatCard label="超额收益" value={rel.excess_return} />
            <StatCard label="基准收益" value={rel.benchmark_return} />
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#1f2733', marginBottom: 6 }}>归一化净值叠加（起点=1）</div>
            <OverlayChart dates={dates} series={overlaySeries} />
          </div>

          <div style={{ marginTop: 16, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: 14, overflowX: 'auto' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#1f2733', marginBottom: 8 }}>基准构成（实际权重）</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ color: '#8a94a6', textAlign: 'left' }}>
                  <th style={{ padding: '6px 8px' }}>名称</th>
                  <th style={{ padding: '6px 8px' }}>权重</th>
                </tr>
              </thead>
              <tbody>
                {(data.benchmarks || []).map((b, i) => (
                  <tr key={i} style={{ borderTop: '1px solid #f2f4f7' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 600 }}>{b.name}</td>
                    <td style={{ padding: '6px 8px' }}>{b.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
