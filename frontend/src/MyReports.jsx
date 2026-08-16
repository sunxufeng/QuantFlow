import React, { useEffect, useState } from 'react'
import { listReportArchive, getReportArchive, deleteReportArchive } from './api.js'
import ExportBar from './ExportBar.jsx'

const btn = {
  padding: '6px 12px', borderRadius: 8, border: '1px solid #2f6df6',
  background: '#2f6df6', color: '#fff', cursor: 'pointer', fontSize: 13,
}
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

export default function MyReports() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null) // 当前打开的存档详情

  const refresh = async () => {
    setLoading(true); setErr('')
    try { setItems((await listReportArchive()).items || []) } catch (e) { setErr(e.message || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { refresh() }, [])

  const openItem = async (id) => {
    try {
      const rec = await getReportArchive(id)
      setOpen(rec)
    } catch (e) { setErr(e.message || '打开失败') }
  }
  const remove = async (id) => {
    if (!window.confirm('确认删除该报告存档？')) return
    try { await deleteReportArchive(id); setOpen(null); await refresh() } catch (e) { setErr(e.message || '删除失败') }
  }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>我的报告 <span style={{ fontSize: 12, color: '#16a34a' }}>V98</span></h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>平台内生成的综合 / 分析报告可保存到此处，随时回看与再导出（按账户隔离）。</p>

      {err && <div style={{ color: '#c0392b', marginTop: 8 }}>⚠ {err}</div>}

      {!open && (
        <div style={{ marginTop: 12 }}>
          {loading && <div style={{ color: '#888' }}>加载中…</div>}
          {!loading && items.length === 0 && <div style={{ color: '#888' }}>暂无存档，可在「综合报告」中点击「保存到存档」。</div>}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginTop: 8 }}>
            <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>名称</th><th>类型</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} style={{ borderTop: '1px solid #eee' }}>
                  <td>{it.name}</td>
                  <td>{it.type}</td>
                  <td style={{ color: '#888' }}>{it.created_at}</td>
                  <td>
                    <button style={{ ...btn, padding: '4px 10px', marginRight: 6 }} onClick={() => openItem(it.id)}>查看</button>
                    <button style={{ ...btn, padding: '4px 10px', background: '#fff', color: '#c0392b', borderColor: '#c0392b' }} onClick={() => remove(it.id)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <div style={{ marginTop: 12, background: '#fff', border: '1px solid #e6e9ef', borderRadius: 12, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div><b>{open.name}</b> <span style={{ color: '#888', fontSize: 12 }}>{open.type} · {open.created_at}</span></div>
            <button style={{ ...btn, background: '#fff', color: '#2f6df6' }} onClick={() => setOpen(null)}>返回列表</button>
          </div>
          {open.content?.export_sections ? (
            <>
              <ExportBar sections={open.content.export_sections} baseName={`report_${open.id}`} title={open.name} />
              <KV data={open.content.summary} />
            </>
          ) : (
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{JSON.stringify(open.content, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  )
}
