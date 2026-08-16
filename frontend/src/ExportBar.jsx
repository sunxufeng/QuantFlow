import React from 'react'
import { exportSectionsToExcel, exportSectionsToPdf } from './exportUtils.js'

// 通用导出工具条（V96）：在任何结果视图里传入 sections 即可获得 Excel/PDF 导出按钮。
// sections: [{ title, kv?: {k:v}, rows?: [{...}], columns?: [keys] }]
export default function ExportBar({ sections, baseName = 'quantflow_export', title = 'QuantFlow 导出' }) {
  if (!sections || !sections.length) return null
  const excel = () => exportSectionsToExcel(sections, `${baseName}.xls`, title)
  const pdf = () => exportSectionsToPdf(sections, title)
  return (
    <div style={{ display: 'flex', gap: 8, margin: '10px 0', flexWrap: 'wrap', alignItems: 'center' }}>
      <button
        onClick={excel}
        style={{ padding: '6px 14px', borderRadius: 8, border: '1px solid #2563eb', background: '#2563eb', color: '#fff', cursor: 'pointer', fontSize: 13 }}
      >
        导出 Excel
      </button>
      <button
        onClick={pdf}
        style={{ padding: '6px 14px', borderRadius: 8, border: '1px solid #2563eb', background: '#fff', color: '#2563eb', cursor: 'pointer', fontSize: 13 }}
      >
        导出 PDF
      </button>
    </div>
  )
}
