import { useState } from 'react'
import { runDataQuality } from './api.js'

const EXAMPLE = JSON.stringify([
  { timestamp: '2024-01-01', open: 10, high: 10.5, low: 9.8, close: 10.2, volume: 1000 },
  { timestamp: '2024-01-02', open: 10.2, high: 9.0, low: 9.5, close: 9.6, volume: 1200 },
  { timestamp: '2024-01-02', open: 9.6, high: 9.9, low: 9.4, close: 9.8, volume: 0 },
  { timestamp: '2024-01-05', open: null, high: 10.1, low: 9.7, close: 9.9, volume: 800 }
], null, 2)

const SEV_COLOR = { high: '#dc2626', medium: '#f59e0b', low: '#6b7280' }
const GRADE_COLOR = { A: '#16a34a', B: '#22c55e', C: '#eab308', D: '#f59e0b', E: '#dc2626' }

export default function DataQuality() {
  const [symbol, setSymbol] = useState('')
  const [intervalDays, setIntervalDays] = useState('1')
  const [asOf, setAsOf] = useState('')
  const [outlierZ, setOutlierZ] = useState('5')
  const [text, setText] = useState(EXAMPLE)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    let bars
    try {
      bars = JSON.parse(text)
    } catch (e) {
      setErr('JSON 解析失败：' + e.message)
      return
    }
    const payload = { bars }
    if (symbol.trim()) payload.symbol = symbol.trim()
    if (intervalDays.trim()) payload.expected_interval_days = parseFloat(intervalDays)
    if (asOf.trim()) payload.as_of = asOf.trim()
    if (outlierZ.trim()) payload.outlier_z = parseFloat(outlierZ)
    setLoading(true)
    try {
      const res = await runDataQuality(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const loadExample = () => setText(EXAMPLE)

  return (
    <div style={{ padding: 20, maxWidth: 980 }}>
      <h2 style={{ margin: '0 0 4px' }}>行情数据质量校验 <span style={{ fontSize: 12, color: '#9ca3af' }}>V27</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>对一段行情做结构化体检：缺失值、OHLC 一致性、重复/乱序、缺口、异常收益、陈旧性。</p>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <label>标的<input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="如 600519.SH（仅标注）" style={inp} /></label>
        <label>期望间隔(天)<input value={intervalDays} onChange={(e) => setIntervalDays(e.target.value)} style={inp} /></label>
        <label>校验基准日<input value={asOf} onChange={(e) => setAsOf(e.target.value)} placeholder="YYYY-MM-DD" style={inp} /></label>
        <label>异常阈值(z)<input value={outlierZ} onChange={(e) => setOutlierZ(e.target.value)} style={inp} /></label>
        <button onClick={loadExample} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #d1d5db', background: '#f9fafb', cursor: 'pointer', alignSelf: 'flex-end' }}>填入示例</button>
      </div>

      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={10} style={{
        width: '100%', fontFamily: 'monospace', fontSize: 13, padding: 10, border: '1px solid #d1d5db', borderRadius: 8
      }} />

      <div style={{ margin: '10px 0' }}>
        <button onClick={run} disabled={loading} style={{
          padding: '8px 20px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer'
        }}>{loading ? '校验中…' : '运行校验'}</button>
      </div>
      {err ? <div style={{ color: '#dc2626', marginBottom: 10 }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
            <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: '#6b7280' }}>质量分</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: GRADE_COLOR[data.grade] || '#1f2937' }}>{data.score}</div>
            </div>
            <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: '#6b7280' }}>等级</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: GRADE_COLOR[data.grade] || '#1f2937' }}>{data.grade}</div>
            </div>
            <div style={{ fontSize: 13, color: '#374151' }}>
              <div>样本数：{data.summary.total_bars}</div>
              <div>区间：{data.summary.date_min} ~ {data.summary.date_max}</div>
              <div>问题总数：<b style={{ color: data.summary.issues_total ? '#dc2626' : '#16a34a' }}>{data.summary.issues_total}</b>
                （高 {data.summary.by_severity.high} / 中 {data.summary.by_severity.medium} / 低 {data.summary.by_severity.low}）</div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            {Object.entries(data.summary).filter(([k]) => ['missing_fields', 'non_positive', 'ohlc_error', 'duplicate_ts', 'non_monotonic', 'zero_volume', 'outlier', 'gap', 'stale'].includes(k) && data.summary[k] > 0).map(([k, v]) => (
              <span key={k} style={{ fontSize: 12, background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca', borderRadius: 12, padding: '2px 10px' }}>{k}: {v}</span>
            ))}
          </div>

          {data.issues.length > 0 ? (
            <table style={tbl}>
              <thead><tr>{['#', '时间戳', '严重度', '类别', '说明'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
              <tbody>
                {data.issues.map((it, i) => (
                  <tr key={i}>
                    <td style={td}>{it.index >= 0 ? it.index : '—'}</td>
                    <td style={td}>{it.ts || '—'}</td>
                    <td style={{ ...td, color: SEV_COLOR[it.severity], fontWeight: 600 }}>{it.severity}</td>
                    <td style={td}>{it.category}</td>
                    <td style={td}>{it.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ color: '#16a34a', padding: 12, border: '1px solid #bbf7d0', background: '#f0fdf4', borderRadius: 8 }}>✓ 未发现问题</div>
          )}
        </div>
      ) : null}
    </div>
  )
}

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6, width: 150 }
const tbl = { width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 13 }
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '2px solid #e5e7eb', color: '#374151' }
const td = { padding: '6px 8px', borderBottom: '1px solid #f0f0f0' }
