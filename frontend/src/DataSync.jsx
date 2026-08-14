import { useCallback, useEffect, useState } from 'react'
import { marketSyncStatus, marketSyncNow } from './api.js'

const STATUS_LABELS = {
  success: '成功',
  failed: '失败',
  never_run: '未运行',
  running: '运行中',
}

const STATUS_COLOR = {
  success: '#16a34a',
  failed: '#e11d48',
  never_run: '#64748b',
  running: '#6366f1',
}

function formatTime(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

export default function DataSync() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return marketSyncStatus()
      .then(setStatus)
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const onSync = async () => {
    setSyncing(true)
    setError('')
    try {
      await marketSyncNow()
      await refresh()
    } catch (e) {
      setError(`同步失败: ${e.message}`)
    } finally {
      setSyncing(false)
    }
  }

  const symbols = status?.symbols ? status.symbols.split(',') : []

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>数据自动更新（N4）</h3>
        <button
          className="qf-btn qf-btn-primary"
          onClick={onSync}
          disabled={syncing}
        >
          {syncing ? '同步中…' : '立即同步'}
        </button>
      </div>
      {error && <div className="qf-error">{error}</div>}
      {loading && !status && <div className="qf-busy">加载中…</div>}
      {status && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12, marginTop: 12 }}>
          <div className="qf-mcard">
            <div className="qf-mcard-label">最近状态</div>
            <div className="qf-mcard-value" style={{ color: STATUS_COLOR[status.status] || '#334155' }}>
              {STATUS_LABELS[status.status] || status.status}
            </div>
          </div>
          <div className="qf-mcard">
            <div className="qf-mcard-label">数据源</div>
            <div className="qf-mcard-value" style={{ fontSize: 14 }}>{status.source}</div>
          </div>
          <div className="qf-mcard">
            <div className="qf-mcard-label">已写入 K 线</div>
            <div className="qf-mcard-value">{status.bars_written ?? 0}</div>
          </div>
          <div className="qf-mcard">
            <div className="qf-mcard-label">库中总 K 线</div>
            <div className="qf-mcard-value">{status.stored_bars ?? 0}</div>
          </div>
          <div className="qf-mcard">
            <div className="qf-mcard-label">开始时间</div>
            <div className="qf-mcard-value" style={{ fontSize: 13 }}>{formatTime(status.started_at)}</div>
          </div>
          <div className="qf-mcard">
            <div className="qf-mcard-label">结束时间</div>
            <div className="qf-mcard-value" style={{ fontSize: 13 }}>{formatTime(status.finished_at)}</div>
          </div>
        </div>
      )}
      {symbols.length > 0 && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 8 }}>同步标的 ({symbols.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {symbols.map((s) => (
              <span key={s} style={{ padding: '4px 8px', borderRadius: 6, background: '#eef2ff', color: '#4338ca', fontSize: 12 }}>{s}</span>
            ))}
          </div>
        </div>
      )}
      {status?.error && (
        <div style={{ marginTop: 18, padding: 12, borderRadius: 8, background: '#fef2f2', color: '#991b1b', border: '1px solid #fecaca' }}>
          <strong>错误信息：</strong>{status.error}
        </div>
      )}
      <div className="qf-hint" style={{ marginTop: 18 }}>
        说明：后台启动时会自动执行一次行情同步；也可点击「立即同步」手动触发。生产环境可配置 QF_DATA_SYNC_INTERVAL_MIN 启用定时增量同步。
      </div>
    </div>
  )
}
