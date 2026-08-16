import React, { useState } from 'react'
import { runConsolidate, saveReportArchive } from './api.js'
import ExportBar from './ExportBar.jsx'

const btn = {
  padding: '8px 16px', borderRadius: 8, border: '1px solid #2f6df6',
  background: '#2f6df6', color: '#fff', cursor: 'pointer', fontSize: 13,
}
const Card = ({ title, children }) => (
  <div style={{ background: '#fff', border: '1px solid #e6e9ef', borderRadius: 12, padding: 16, marginBottom: 14 }}>
    <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 14 }}>{title}</div>
    {children}
  </div>
)
const KV = ({ data }) => (
  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 8 }}>
    {Object.entries(data || {}).map(([k, v]) => (
      <div key={k} style={{ background: '#f7f9fc', borderRadius: 8, padding: '8px 10px' }}>
        <div style={{ fontSize: 11, color: '#888' }}>{k}</div>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v)}</div>
      </div>
    ))}
  </div>
)
const num = (id, val, ph) => (
  <input id={id} defaultValue={val} placeholder={ph} style={{ width: 90, padding: 6, marginRight: 6, borderRadius: 8, border: '1px solid #ccc' }} />
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }

function gen(n, drift, vol, seed) {
  let s = seed, out = []
  const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff }
  for (let i = 0; i < n; i++) out.push(+(drift + (rnd() - 0.5) * 2 * vol).toFixed(6))
  return out
}

export default function ConsolidateReport() {
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const [saved, setSaved] = useState(false)

  const run = async () => {
    setLoading(true); setErr(null)
    try {
      const payload = {
        returns: JSON.parse(document.getElementById('crf').value),
        periods_per_year: +document.getElementById('crppy').value || 252,
        confidence: +document.getElementById('crconf').value || 0.95,
      }
      const w = document.getElementById('crw').value.trim()
      if (w) payload.weights = JSON.parse(w)
      const b = document.getElementById('crb').value.trim()
      if (b) payload.benchmark = JSON.parse(b)
      setRes(await runConsolidate(payload))
      setSaved(false)
    } catch (e) {
      setErr(jsonErr(e.message))
    } finally { setLoading(false) }
  }

  const save = async () => {
    if (!res) return
    try {
      await saveReportArchive('综合报告 ' + new Date().toLocaleString(), 'consolidate', res)
      setSaved(true)
    } catch (e) { setErr(jsonErr(e.message)) }
  }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>综合报告 <span style={{ fontSize: 12, color: '#16a34a' }}>V97</span></h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>聚合绩效 / 风险 / 看板为一份多章节报告（复用平台既有分析纯函数），可一键导出 Excel / PDF。</p>

      <Card title="输入">
        <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>returns：收益率数组（必填）；weights：{"{名称:权重}"}（可选）；benchmark：收益率数组（可选）。</div>
        <textarea id="crf" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify(gen(120, 0.0006, 0.01, 7))} />
        <textarea id="crw" rows={2} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} placeholder='可选权重 {"A":0.4,"B":0.3,"C":0.3}' />
        <textarea id="crb" rows={2} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} placeholder="可选基准（收益率数组）" />
        <div style={{ marginTop: 8 }}>
          {num('crppy', 252, 'ppz')}{num('crconf', 0.95, '置信度')}
          <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={run}>{loading ? '生成中…' : '生成综合报告'}</button>
          <button style={{ ...btn, marginLeft: 8, background: '#fff', color: '#2f6df6' }} disabled={!res} onClick={save}>保存到存档</button>
          {saved && <span style={{ color: '#16a34a', alignSelf: 'center' }}>已保存</span>}
        </div>
      </Card>

      {res && (
        <Card title="综合报告">
          <ExportBar sections={res.export_sections} baseName="consolidate_report" title="QuantFlow 综合报告" />
          <div style={{ fontWeight: 600, fontSize: 13, margin: '6px 0' }}>头条指标</div>
          <KV data={res.summary} />
          <div style={{ fontWeight: 600, fontSize: 13, margin: '14px 0 6px' }}>绩效明细</div>
          <KV data={res.performance} />
          <div style={{ fontWeight: 600, fontSize: 13, margin: '14px 0 6px' }}>风险明细</div>
          <KV data={res.risk} />
          <div style={{ fontWeight: 600, fontSize: 13, margin: '14px 0 6px' }}>风险看板</div>
          <KV data={res.dashboard} />
          {res.benchmark && (<><div style={{ fontWeight: 600, fontSize: 13, margin: '14px 0 6px' }}>基准对比</div><KV data={res.benchmark} /></>)}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', marginTop: 10 }}>⚠ {err}</div>}
    </div>
  )
}
