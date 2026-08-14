import { useEffect, useState, useCallback } from 'react'
import { listTemplates, listMyTemplates, deleteTemplate, templateMarket, shareTemplate } from './api.js'

export default function Templates({ onApply }) {
  const [tab, setTab] = useState('builtin') // builtin | mine | market
  const [templates, setTemplates] = useState([])
  const [mine, setMine] = useState([])
  const [market, setMarket] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [applyingId, setApplyingId] = useState('')

  const refresh = useCallback(() => {
    setError('')
    return Promise.all([listTemplates(), listMyTemplates()])
      .then(([builtin, personal]) => {
        setTemplates(builtin)
        setMine(personal)
      })
      .catch((e) => setError(`模板库加载失败: ${e.message}`))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (tab === 'market') {
      templateMarket().then(setMarket).catch((e) => setError(`模板市场加载失败: ${e.message}`))
    }
  }, [tab])

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

  const handleDelete = useCallback((tpl) => {
    if (!window.confirm(`确认删除个人模板「${tpl.name}」？`)) return
    setBusy(true)
    deleteTemplate(tpl.id)
      .then(() => setMine((prev) => prev.filter((t) => t.id !== tpl.id)))
      .catch((e) => setError(`删除失败: ${e.message}`))
      .finally(() => setBusy(false))
  }, [])

  const toggleShare = useCallback((tpl) => {
    setBusy(true)
    shareTemplate(tpl.id, !tpl.is_public)
      .then((updated) => setMine((prev) => prev.map((t) => (t.id === tpl.id ? updated : t))))
      .catch((e) => setError(`发布失败: ${e.message}`))
      .finally(() => setBusy(false))
  }, [])

  const tabBtn = (key, label) => ({
    padding: '6px 16px',
    border: 'none',
    background: tab === key ? '#6366f1' : 'transparent',
    color: tab === key ? '#fff' : 'var(--text)',
    cursor: 'pointer',
    fontSize: 12,
    borderRadius: 8,
  })

  return (
    <div className="qf-templates">
      <div className="qf-templates-head">
        <h2>工作流模板库</h2>
        <div style={{ display: 'inline-flex', gap: 6 }}>
          <button type="button" style={tabBtn('builtin', 'builtin')} onClick={() => setTab('builtin')}>示例</button>
          <button type="button" style={tabBtn('mine', 'mine')} onClick={() => setTab('mine')}>我的</button>
          <button type="button" style={tabBtn('market', 'market')} onClick={() => setTab('market')}>模板市场</button>
          <button className="qf-btn qf-btn-sm" onClick={refresh} disabled={busy} style={{ marginLeft: 6 }}>刷新</button>
        </div>
      </div>
      <p className="qf-templates-sub">
        点击「加载到画布」即可把模板一键载入编辑器，修改后可直接运行；在编辑器里可把当前画布「存为模板」。
        「我的」模板可一键发布到「模板市场」供他人复用。
      </p>
      {error && <div className="qf-error">{error}</div>}

      {tab === 'builtin' && (
        <>
          <h3 className="qf-templates-section">示例模板</h3>
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
          <div className="qf-prop-hint">暂无示例模板</div>
        )}
      </div>
        </>
      )}

      {tab === 'mine' && (
        <>
          <h3 className="qf-templates-section">我的模板</h3>
          <div className="qf-template-grid">
        {mine.map((tpl) => (
          <div className="qf-template-card" key={tpl.id}>
            <div className="qf-template-card-head">
              <h3>{tpl.name}</h3>
              <div className="qf-template-tags">
                {tpl.is_public && <span className="qf-tag" style={{ background: '#16a34a', color: '#fff' }}>已发布</span>}
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
              <button
                className="qf-btn qf-btn-sm"
                onClick={() => toggleShare(tpl)}
                disabled={busy}
              >
                {tpl.is_public ? '取消发布' : '发布到市场'}
              </button>
              <button
                className="qf-btn qf-btn-danger"
                onClick={() => handleDelete(tpl)}
                disabled={busy}
              >
                删除
              </button>
            </div>
          </div>
        ))}
        {!error && mine.length === 0 && (
          <div className="qf-prop-hint">还没有个人模板，去编辑器点「存为模板」保存一个吧</div>
        )}
      </div>
        </>
      )}

      {tab === 'market' && (
        <>
          <h3 className="qf-templates-section">模板市场（公开模板，可一键复用）</h3>
          <div className="qf-template-grid">
            {market.map((tpl) => (
              <div className="qf-template-card" key={tpl.id}>
                <div className="qf-template-card-head">
                  <h3>{tpl.name}</h3>
                  <div className="qf-template-tags">
                    {tpl.builtin
                      ? <span className="qf-tag" style={{ background: '#6366f1', color: '#fff' }}>官方</span>
                      : <span className="qf-tag" style={{ background: '#16a34a', color: '#fff' }}>社区</span>}
                    {(tpl.tags || []).map((tag) => (
                      <span className="qf-tag" key={tag}>{tag}</span>
                    ))}
                  </div>
                </div>
                <p className="qf-template-desc">{tpl.description || '（无描述）'}</p>
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
            {!error && market.length === 0 && (
              <div className="qf-prop-hint">模板市场暂无公开模板，去「我的」发布一个吧</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
