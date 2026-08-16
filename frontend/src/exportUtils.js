// 零依赖前端导出工具（V95）：Excel(.xls) 与 PDF(打印)。
// 不引入任何第三方库，避免构建/服务端依赖；Excel 用 HTML-table Blob（Excel 可直接打开），
// PDF 用新窗口打印视图（浏览器「另存为 PDF」）。

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function xmlEscape(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

// sections: [{ title, kv?: {k:v}, rows?: [{...}], columns?: [keys] }]
export function sectionsToExcelHtml(sections, title) {
  let html =
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" ' +
    'xmlns:x="urn:schemas-microsoft-com:office:excel" ' +
    'xmlns="http://www.w3.org/TR/REC-html40">'
  html += '<head><meta charset="utf-8"></head><body>'
  html += `<h2>${xmlEscape(title || 'QuantFlow 导出')}</h2>`
  for (const sec of sections || []) {
    if (sec.title) html += `<h3>${xmlEscape(sec.title)}</h3>`
    if (sec.kv) {
      html += '<table border="1" cellpadding="4" cellspacing="0"><tr><th>指标</th><th>值</th></tr>'
      for (const [k, v] of Object.entries(sec.kv)) {
        html += `<tr><td>${xmlEscape(k)}</td><td>${xmlEscape(formatCell(v))}</td></tr>`
      }
      html += '</table>'
    }
    if (sec.rows && sec.rows.length) {
      const cols = sec.columns || Object.keys(sec.rows[0] || {})
      html += '<table border="1" cellpadding="4" cellspacing="0"><thead><tr>' +
        cols.map((c) => `<th>${xmlEscape(c)}</th>`).join('') + '</tr></thead><tbody>'
      for (const r of sec.rows) {
        html += '<tr>' + cols.map((c) => `<td>${xmlEscape(formatCell(r[c]))}</td>`).join('') + '</tr>'
      }
      html += '</tbody></table>'
    }
  }
  html += '</body></html>'
  return html
}

export function formatCell(v) {
  if (v === null || v === undefined) return ''
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(v)
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// 单 sheet 导出：把 sections 写进一个工作表。
export function exportSectionsToExcel(sections, filename, title) {
  const html = sectionsToExcelHtml(sections, title || filename)
  const blob = new Blob(['﻿' + html], { type: 'application/vnd.ms-excel;charset=utf-8' })
  const fname = filename.endsWith('.xls') ? filename : `${filename}.xls`
  downloadBlob(blob, fname)
}

// 多 sheet 导出：sheets: [{ name, sections }]，每个 sheet 一个工作表。
export function exportWorkbook(sheets, filename, title) {
  let html =
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" ' +
    'xmlns:x="urn:schemas-microsoft-com:office:excel" ' +
    'xmlns="http://www.w3.org/TR/REC-html40">'
  html += '<head><meta charset="utf-8">'
  // 定义多个 worksheet
  html += '<x:ExcelWorkbook><x:ExcelWorksheets>'
  for (const s of sheets || []) {
    html += `<x:ExcelWorksheet><x:Name>${xmlEscape(s.name)}</x:Name><x:WorksheetOptions/><x:Data>` +
      sectionsToExcelHtml(s.sections, s.name) + '</x:Data></x:ExcelWorksheet>'
  }
  html += '</x:ExcelWorksheets></x:ExcelWorkbook>'
  html += '</head><body></body></html>'
  const blob = new Blob(['﻿' + html], { type: 'application/vnd.ms-excel;charset=utf-8' })
  const fname = filename.endsWith('.xls') ? filename : `${filename}.xls`
  downloadBlob(blob, fname)
}

export function exportSectionsToPdf(sections, title) {
  const html = sectionsToExcelHtml(sections, title)
  const w = window.open('', '_blank')
  if (!w) {
    alert('请允许弹出窗口以导出 PDF')
    return
  }
  w.document.write(
    '<!DOCTYPE html><html><head><meta charset="utf-8"><title>' +
      xmlEscape(title || 'QuantFlow 报告') +
      '</title><style>body{font-family:-apple-system,Segoe UI,sans-serif;color:#222}' +
      'h2{margin:8px 0}h3{margin:14px 0 4px}table{border-collapse:collapse;margin:6px 0}' +
      'td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px}' +
      '@media print{button{display:none}}</style></head><body>' +
      html +
      '<button onclick="window.print()" style="margin-top:16px;padding:8px 16px">打印 / 另存为 PDF</button>' +
      '</body></html>'
  )
  w.document.close()
}
