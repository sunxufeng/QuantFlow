import { useEffect, useState, useCallback } from 'react'
import { listTemplates } from './api.js'

export default function Templates({ onApply }) {
  const [templates, setTemplates] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [applyingId, setApplyingId] = useState('')

  const refresh = useCallback(() => {
    setError('')
    return listTemplates()
      .then(setTemplates)
      .catch((e) => setError(`模板库加载失败: ${e.message}`))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleApply = useCallback((tpl) => {
    setApplyingId(tpl.id)
    setBusy(true)
    try {
      onApply(tpl)
    } finally {
      setBusy(false)
      setApplyingId('')
    }
  }, [onApply])

  return (
    <div className="qf-templates">
      <div className="qf-templates-head">
        <h2>示例工作流模板库</h2>
        <button className="qf-btn qf-btn-sm" onClick={refresh} disabled={busy}>刷新</button>
      </div>
      <p className="qf-templates-sub">
        点击「加载到画布」即可把内置策略模板一键载入编辑器，修改后可直接运行。
      </p>
      {error && <div className="qf-error">{error}</div>}
      <div className="qf-template-grid">
        {templates.map((tpl) => (
          <div className="qf-template-card" key={tpl.id}>
            <div className="qf-template-card-head">
              <h3>{tpl.name}</h3>
              <div className="qf-template-tags">
                {(tpl.tags || []).map((tag) => (
                  <span className="qf-tag" key={tag}>{tag}</span>
                ))}
              </div>
            </div>
            <p className="qf-template-desc">{tpl.description}</p>
            <div className="qf-template-meta">
              {tpl.nodes?.length || 0} 个节点 · {tpl.edges?.length || 0} 条连接
            </div>
            <div className="qf-template-actions">
              <button
                className="qf-btn qf-btn-primary"
                onClick={() => handleApply(tpl)}
                disabled={busy}
              >
                {applyingId === tpl.id ? '加载中…' : '加载到画布'}
              </button>
            </div>
          </div>
        ))}
        {!error && templates.length === 0 && (
          <div className="qf-prop-hint">暂无模板</div>
        )}
      </div>
    </div>
  )
}
