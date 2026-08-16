import React from 'react'

// V100 共享状态块：统一的加载 / 错误 / 空态展示，避免各视图重复编写相同的提示样式。
export default function StatusBlock({ loading, empty, error, loadingText = '加载中…', emptyText = '暂无数据', children }) {
  if (loading) {
    return (
      <div style={{ padding: 28, color: '#888', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid #cbd5e1', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'qf-spin 0.8s linear infinite' }} />
        {loadingText}
      </div>
    )
  }
  if (error) {
    return (
      <div style={{ padding: 16, color: '#c0392b', fontSize: 13, background: '#fff', border: '1px solid #fecaca', borderRadius: 8 }}>
        ⚠ {error}
      </div>
    )
  }
  if (empty) {
    return <div style={{ padding: 28, color: '#888', fontSize: 13 }}>{emptyText}</div>
  }
  return children || null
}
