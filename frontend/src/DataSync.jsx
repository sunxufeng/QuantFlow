import { useCallback, useEffect, useState } from 'react'
import { marketSyncStatus, marketSyncNow, marketCache, marketRefresh } from './api.js'

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

  // V5.0：行情缓存 / 数据源管理
  const [cache, setCache] = useState(null)
  const [cacheLoading, setCacheLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshSyms, setRefreshSyms] = useState('')
  const [refreshStart, setRefreshStart] = useState('2024-01-01')
  const [refreshEnd, setRefreshEnd] = useState('2024-02-01')
  const [refreshMsg, setRefreshMsg] = useState('')

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return marketSyncStatus()
      .then(setStatus)
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  const loadCache = useCallback(() => {
    setCacheLoading(true)
    return marketCache()
      .then(setCache)
      .catch((e) => setError(`缓存加载失败: ${e.message}`))
      .finally(() => setCacheLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { loadCache() }, [loadCache])

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

  const onCacheRefresh = async () => {
    setRefreshing(true)
    setRefreshMsg('')
    setError('')
    try {
      const syms = refreshSyms.trim()
        ? refreshSyms.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean)
        : null
      const res = await marketRefresh({ symbols: syms, start: refreshStart, end: refreshEnd })
      const total = (res.refreshed || []).reduce((a, r) => a + (r.count || 0), 0)
      setRefreshMsg(`已刷新 ${res.refreshed?.length || 0} 个标的，写入 ${total} 根 K 线（数据源：${res.provider}）`)
      await loadCache()
    } catch (e) {
      setError(`刷新失败: ${e.message}`)
    } finally {
      setRefreshing(false)
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

      {/* V5.0 行情缓存 / 数据源管理面板 */}
      <div style={{ marginTop: 28, borderTop: '1px solid var(--border)', paddingTop: 18 }}>
        <div className="qf-result-head">
          <h3>行情缓存与数据源（V5.0）</h3>
          <button className="qf-btn" onClick={loadCache} disabled={cacheLoading}>
            {cacheLoading ? '加载中…' : '刷新状态'}
          </button>
        </div>
        <div className="qf-hint" style={{ marginBottom: 12 }}>
          查看当前数据源模式与本地行情缓存（SQLite 落库）状态；可强制从数据源重新拉取并落库。数据源切换通过环境变量 QF_MARKET_PROVIDER（fixture / tushare）完成。
        </div>

        {cache && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              <div className="qf-mcard">
                <div className="qf-mcard-label">数据源模式</div>
                <div className="qf-mcard-value" style={{ fontSize: 14 }}>{cache.provider_mode}</div>
              </div>
              <div className="qf-mcard">
                <div className="qf-mcard-label">当前数据源</div>
                <div className="qf-mcard-value" style={{ fontSize: 14 }}>{cache.provider}</div>
              </div>
              <div className="qf-mcard">
                <div className="qf-mcard-label">复权方式</div>
                <div className="qf-mcard-value" style={{ fontSize: 14 }}>{cache.adjustment}</div>
              </div>
              <div className="qf-mcard">
                <div className="qf-mcard-label">缓存后端</div>
                <div className="qf-mcard-value" style={{ fontSize: 14 }}>{cache.cache_backend}</div>
              </div>
              <div className="qf-mcard">
                <div className="qf-mcard-label">缓存 TTL（秒）</div>
                <div className="qf-mcard-value">{cache.cache_ttl_seconds}</div>
              </div>
              <div className="qf-mcard">
                <div className="qf-mcard-label">库中总 K 线</div>
                <div className="qf-mcard-value">{cache.total_bars}</div>
              </div>
            </div>

            <div style={{ marginTop: 18, fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 8 }}>
              本地缓存标的（{cache.symbols?.length || 0}）
            </div>
            {cache.symbols?.length > 0 ? (
              <div style={{ overflowX: 'auto' }}>
                <table className="qf-table">
                  <thead>
                    <tr><th>标的</th><th>K 线数</th><th>起始日</th><th>结束日</th></tr>
                  </thead>
                  <tbody>
                    {cache.symbols.map((s) => (
                      <tr key={s.symbol}>
                        <td>{s.symbol}</td>
                        <td>{s.count}</td>
                        <td className="qf-hint">{s.first_date}</td>
                        <td className="qf-hint">{s.last_date}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="qf-hint">缓存为空，点击「强制刷新」从数据源拉取。</div>
            )}

            <div style={{ marginTop: 18, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <input
                value={refreshSyms}
                onChange={(e) => setRefreshSyms(e.target.value)}
                placeholder="标的（留空刷新全部，逗号分隔）"
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', minWidth: 220 }}
              />
              <input
                value={refreshStart}
                onChange={(e) => setRefreshStart(e.target.value)}
                placeholder="开始日"
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', width: 130 }}
              />
              <input
                value={refreshEnd}
                onChange={(e) => setRefreshEnd(e.target.value)}
                placeholder="结束日"
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', width: 130 }}
              />
              <button className="qf-btn qf-btn-primary" onClick={onCacheRefresh} disabled={refreshing}>
                {refreshing ? '刷新中…' : '强制刷新落库'}
              </button>
            </div>
            {refreshMsg && <div className="qf-success" style={{ marginTop: 10 }}>{refreshMsg}</div>}
          </>
        )}
        {!cache && cacheLoading && <div className="qf-busy">加载缓存状态…</div>}
      </div>
    </div>
  )
}
