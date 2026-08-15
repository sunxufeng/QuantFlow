import React, { useState } from 'react'
import { runFactorDecay } from './api.js'

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{ flex: '1 1 140px', minWidth: 140, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ fontSize: 12, color: '#8a94a6' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || '#1f2733', marginTop: 4 }}>{value ?? '—'}</div>
      {sub && <div style={{ fontSize: 11, color: '#aab2c0', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function RollingChart({ dates, series, title, color }) {
  if (!series || series.length === 0) return null
  const W = 680, H = 220, P = 30
  const n = series.length
  const lo = Math.min(...series, -0.2)
  const hi = Math.max(...series, 0.2)
  const x = (i) => P + (i / Math.max(1, n - 1)) * (W - 2 * P)
  const y = (v) => H - P - ((v - lo) / Math.max(1e-9, hi - lo)) * (H - 2 * P)
  const path = series.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#1f2733', marginBottom: 6 }}>{title}</div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ background: '#fff', border: '1px solid #eceef1', borderRadius: 10 }}>
        <line x1={P} y1={y(0)} x2={W - P} y2={y(0)} stroke="#eee" strokeDasharray="3 3" />
        <path d={path} fill="none" stroke={color} strokeWidth="2" />
        {series.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r="1.6" fill={color} />
        ))}
      </svg>
    </div>
  )
}

export default function FactorDecay() {
  const [symbols, setSymbols] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [window, setWindow] = useState(10)
  const [forward, setForward] = useState(1)
  const [rollWindow, setRollWindow] = useState(10)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState('')

  async function run() {
    setLoading(true); setErr('')
    try {
      const payload = {
        window: Number(window),
        forward: Number(forward),
        roll_window: Number(rollWindow),
      }
      if (symbols.trim()) payload.symbols = symbols.split(',').map((s) => s.trim()).filter(Boolean)
      if (start) payload.start = start
      if (end) payload.end = end
      const res = await runFactorDecay(payload)
      setData(res)
      setSelected(res.factors?.[0]?.factor || '')
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  const factors = data?.factors || []
  const sel = factors.find((f) => f.factor === selected) || factors[0]

  return (
    <div style={{ padding: 18 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20 }}>因子 IC 衰减 / 稳定性分析 <span style={{ fontSize: 12, color: '#b0b8c4' }}>V17 · 无凭证</span></h2>
      <p style={{ color: '#8a94a6', fontSize: 13, marginTop: 0 }}>
        对每个因子计算逐期 IC，再做滚动均值、线性趋势（斜率为负即衰减）与前/后半段对比，判断因子预测力是否随时间退化。
      </p>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', background: '#fafbfc', border: '1px solid #eceef1', borderRadius: 10, padding: 14 }}>
        <label style={{ fontSize: 12, color: '#6b7382' }}>标的(逗号分隔，留空=内置池)<br />
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="TEST.STOCK,TEST.BANK" style={{ width: 220, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} />
        </label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>起始<br /><input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={{ padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>结束<br /><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={{ padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>窗口<br /><input type="number" value={window} min={2} onChange={(e) => setWindow(e.target.value)} style={{ width: 70, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>前瞻<br /><input type="number" value={forward} min={1} onChange={(e) => setForward(e.target.value)} style={{ width: 70, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>滚动窗口<br /><input type="number" value={rollWindow} min={2} onChange={(e) => setRollWindow(e.target.value)} style={{ width: 70, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <button onClick={run} disabled={loading} style={{ padding: '8px 18px', background: '#3b6cf6', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, cursor: 'pointer' }}>
          {loading ? '分析中…' : '运行分析'}
        </button>
      </div>
      {err && <div style={{ color: '#d23', marginTop: 10 }}>错误：{err}</div>}

      {data && (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
            <StatCard label="因子数" value={factors.length} sub={`滚动窗口 ${data.roll_window}`} />
            <StatCard label="前瞻天数" value={data.forward_days} />
            <StatCard label="研究标的" value={(data.symbols || []).length} sub="个" />
          </div>

          <div style={{ marginTop: 16, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: 14, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ color: '#8a94a6', textAlign: 'right' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>因子</th>
                  <th style={{ padding: '6px 8px' }}>均值IC</th>
                  <th style={{ padding: '6px 8px' }}>std_IC</th>
                  <th style={{ padding: '6px 8px' }}>IR</th>
                  <th style={{ padding: '6px 8px' }}>IC&gt;0占比</th>
                  <th style={{ padding: '6px 8px' }}>趋势斜率</th>
                  <th style={{ padding: '6px 8px' }}>前半IC</th>
                  <th style={{ padding: '6px 8px' }}>后半IC</th>
                  <th style={{ padding: '6px 8px' }}>衰减</th>
                </tr>
              </thead>
              <tbody>
                {factors.map((f) => {
                  const decay = f.decay
                  const decayColor = decay == null ? '#999' : decay < 0 ? '#d23' : '#1a9c5b'
                  return (
                    <tr key={f.factor} style={{ borderTop: '1px solid #f2f4f7', textAlign: 'right', background: f.factor === selected ? '#f5f8ff' : 'transparent', cursor: 'pointer' }} onClick={() => setSelected(f.factor)}>
                      <td style={{ textAlign: 'left', padding: '6px 8px', fontWeight: 600 }}>{f.factor}</td>
                      <td style={{ padding: '6px 8px' }}>{f.mean_ic ?? '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{f.std_ic ?? '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{f.ir ?? '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{f.ic_positive_ratio ?? '—'}</td>
                      <td style={{ padding: '6px 8px', color: (f.trend_slope || 0) < 0 ? '#d23' : '#1a9c5b' }}>{f.trend_slope ?? '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{f.first_half_mean_ic ?? '—'}</td>
                      <td style={{ padding: '6px 8px' }}>{f.second_half_mean_ic ?? '—'}</td>
                      <td style={{ padding: '6px 8px', color: decayColor, fontWeight: 600 }}>{decay == null ? '—' : decay.toFixed(4)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {sel && (
            <>
              <div style={{ marginTop: 12 }}>
                <span style={{ fontSize: 13, color: '#6b7382' }}>展示因子：</span>
                <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ padding: '5px 8px', border: '1px solid #dfe3e8', borderRadius: 6 }}>
                  {factors.map((f) => <option key={f.factor} value={f.factor}>{f.factor}</option>)}
                </select>
              </div>
              <RollingChart dates={[]} series={sel.roll_means} title={`${sel.factor} · 滚动均值 IC（窗口=${data.roll_window}）`} color="#3b6cf6" />
              <RollingChart dates={[]} series={sel.ic_series} title={`${sel.factor} · 逐期原始 IC`} color="#f0913b" />
            </>
          )}
        </>
      )}
    </div>
  )
}
