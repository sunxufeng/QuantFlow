import { useCallback, useEffect, useState } from 'react'
import { fetchLogs, fetchOverview } from './api.js'

const LEVELS = ['', 'DEBUG', 'INFO', 'WARNING', 'ERROR']

function OverviewCards({ data }) {
  const server = data?.server || {}
  const runs = data?.runs || {}
  const cards = [
    { label: '服务运行时长', value: `${Math.round(server.uptime_seconds || 0)}s` },
    { label: '累计运行', value: runs.total ?? '-' },
    { label: '运行中', value: runs.running ?? '-' },
    { label: '成功 / 失败', value: `${runs.succeeded ?? '-'} / ${runs.failed ?? '-'}` },
    { label: '注册节点', value: data?.nodes?.registered ?? '-' },
    { label: 'WS 连接', value: data?.ws_connections ?? '-' },
  ]
  if (data?.users) cards.push({ label: '用户', value: data.users.total })
  if (data?.projects) cards.push({ label: '项目', value: data.projects.total })
  return (
    <div className="qf-mcards">
      {cards.map((c) => (
        <div key={c.label} className="qf-mcard">
          <div className="qf-mcard-value">{c.value}</div>
          <div className="qf-mcard-label">{c.label}</div>
        </div>
      ))}
    </div>
  )
}

export default function Monitoring() {
  const [overview, setOverview] = useState(null)
  const [logs, setLogs] = useState([])
  const [level, setLevel] = useState('')
  const [keyword, setKeyword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refreshOverview = useCallback(() => {
    fetchOverview().then(setOverview).catch((e) => setError(`概览加载失败: ${e.message}`))
  }, [])

  const refreshLogs = useCallback(() => {
    setBusy(true)
    setError('')
    fetchLogs({ level, keyword })
      .then((res) => setLogs(res.items || []))
      .catch((e) => setError(`日志加载失败: ${e.message}`))
      .finally(() => setBusy(false))
  }, [level, keyword])

  useEffect(() => {
    refreshOverview()
    refreshLogs()
  }, [refreshOverview, refreshLogs])

  return (
    <div className="qf-monitor">
      <div className="qf-toolbar">
        <span className="qf-toolbar-title">系统概览</span>
        <span className="qf-toolbar-sep" />
        <button className="qf-btn" onClick={() => { refreshOverview(); refreshLogs() }} disabled={busy}>
          刷新
        </button>
        {error && <span className="qf-error qf-inline-error">{error}</span>}
      </div>
      <OverviewCards data={overview} />

      <div className="qf-monitor-section">
        <div className="qf-toolbar">
          <span className="qf-toolbar-title">日志查询</span>
          <span className="qf-toolbar-sep" />
          <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="日志级别">
            {LEVELS.map((lv) => (
              <option key={lv} value={lv}>{lv || '全部级别'}</option>
            ))}
          </select>
          <input
            className="qf-name-input"
            placeholder="关键字过滤（消息/路径）"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ width: 220 }}
          />
        </div>
        <div className="qf-log-list">
          {logs.length === 0 && <div className="qf-prop-hint">暂无日志记录</div>}
          {logs.map((item, i) => (
            <div key={`${item.ts}-${i}`} className="qf-log-item">
              <span className={`qf-log-level qf-log-${item.level.toLowerCase()}`}>{item.level}</span>
              <span className="qf-log-ts">{item.ts.replace('T', ' ').slice(0, 19)}</span>
              <span className="qf-log-logger">{item.logger}</span>
              <span className="qf-log-msg">{item.message}</span>
              {item.request_id && <span className="qf-log-rid">{item.request_id}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
