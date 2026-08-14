import { useCallback, useEffect, useState } from 'react'
import { getToken } from './api.js'

const RESOURCES = [
  { value: 'factors', label: '因子库' },
  { value: 'templates', label: '工作流模板库' },
  { value: 'backtests', label: '回测 / 工作流运行记录' },
]
const FORMATS = [
  { value: 'json', label: 'JSON' },
  { value: 'csv', label: 'CSV（含 BOM，Excel 友好）' },
]

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function filenameFromDisposition(disposition, fallback) {
  if (!disposition) return fallback
  const m = /filename="?([^";]+)"?/.exec(disposition)
  return m ? m[1] : fallback
}

export default function ExportCenter() {
  const [resource, setResource] = useState('factors')
  const [format, setFormat] = useState('json')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  const doExport = useCallback(async () => {
    setBusy(true)
    setError('')
    setMsg('')
    try {
      const res = await fetch(`/api/export?resource=${encodeURIComponent(resource)}&format=${encodeURIComponent(format)}`, {
        headers: { Authorization: `Bearer ${getToken() || ''}` },
      })
      if (!res.ok) {
        const er = await res.json().catch(() => ({}))
        throw new Error(er.detail || `导出失败(${res.status})`)
      }
      const blob = await res.blob()
      const fname = filenameFromDisposition(res.headers.get('content-disposition'), `quantflow_${resource}.${format}`)
      triggerDownload(blob, fname)
      // 尝试解析行数用于提示
      let count = '?'
      try {
        const text = await blob.text()
        if (format === 'json') {
          const j = JSON.parse(text)
          count = Array.isArray(j.items) ? j.items.length : '?'
        } else {
          const lines = text.replace(/^\ufeff/, '').trim().split('\n')
          count = Math.max(0, lines.length - 1)
        }
      } catch (_) { /* 仅提示用，失败忽略 */ }
      setMsg(`已导出 ${resource}（${format}）共 ${count} 行 → ${fname}`)
    } catch (err) {
      setError(err.message || '导出失败')
    } finally {
      setBusy(false)
    }
  }, [resource, format])

  return (
    <div className="qf-templates" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="qf-templates-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2>批量导出中心</h2>
        <span className="qf-hint">V6.2 · 将因子 / 模板 / 回测记录批量导出为 CSV 或 JSON</span>
      </div>

      {error && <div className="qf-error">{error}</div>}
      {msg && <div className="qf-success">{msg}</div>}

      <div style={{ marginTop: 12, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>导出配置</div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <label className="qf-prop-field" style={{ flex: '1 1 220px', marginBottom: 10 }}>
            <span className="qf-prop-label">导出对象</span>
            <select className="qf-name-input" value={resource} onChange={(e) => setResource(e.target.value)}>
              {RESOURCES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="qf-prop-field" style={{ flex: '1 1 220px', marginBottom: 10 }}>
            <span className="qf-prop-label">格式</span>
            <select className="qf-name-input" value={format} onChange={(e) => setFormat(e.target.value)}>
              {FORMATS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <button className="qf-btn qf-btn-primary" onClick={doExport} disabled={busy} style={{ marginBottom: 10 }}>
            {busy ? '导出中…' : '导出并下载'}
          </button>
        </div>
        <div className="qf-hint" style={{ marginTop: 4 }}>
          - 因子 / 模板仅导出当前账户所有的内容；回测记录导出全部运行历史（含 result）。<br />
          - CSV 带 UTF-8 BOM，可直接用 Excel 打开中文不乱码；JSON 为结构化数组（items）。
        </div>
      </div>
    </div>
  )
}
