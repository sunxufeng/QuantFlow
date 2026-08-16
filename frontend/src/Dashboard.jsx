import { useCallback, useEffect, useState } from 'react'
import { backtestReports, fetchOverview, fetchProjects, fetchWorkspace, listRuns } from './api.js'
import StatusBlock from './StatusBlock.jsx'

const fmtMoney = (v) =>
  v == null
    ? '-'
    : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })

function StatCard({ label, value, sub, accent }) {
  return (
    <div className="qf-mcard">
      <div className="qf-mcard-value" style={accent ? { color: accent } : undefined}>{value}</div>
      <div className="qf-mcard-label">{label}{sub ? ` · ${sub}` : ''}</div>
    </div>
  )
}

function WorkspacePanel({ title, onGoto, children }) {
  return (
    <div style={{ flex: '1 1 320px', minWidth: 300, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)' }}>{title}</div>
        {onGoto && <button className="qf-btn qf-btn-sm" onClick={onGoto}>前往</button>}
      </div>
      {children}
    </div>
  )
}

function Row({ label, value, accent }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '5px 0', borderBottom: '1px solid #f1f5f9', fontSize: 13 }}>
      <span className="qf-hint">{label}</span>
      <span style={{ fontWeight: 600, color: accent || 'var(--text)' }}>{value}</span>
    </div>
  )
}

export default function Dashboard({ onNavigate }) {
  const [projects, setProjects] = useState([])
  const [runs, setRuns] = useState([])
  const [reports, setReports] = useState([])
  const [overview, setOverview] = useState(null)
  const [workspace, setWorkspace] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    Promise.all([
      fetchProjects().catch(() => []),
      listRuns(20).then((r) => r.items || []).catch(() => []),
      backtestReports().then((r) => r.summaries || []).catch(() => []),
      fetchOverview().catch(() => null),
      fetchWorkspace().catch(() => null),
    ])
      .then(([p, r, rep, ov, ws]) => {
        setProjects(p || [])
        setRuns(r || [])
        setReports((rep || []).slice(0, 6))
        setOverview(ov)
        setWorkspace(ws)
      })
      .catch((e) => setError(`概览加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const runStats = overview?.runs || { total: 0, succeeded: 0, failed: 0, running: 0 }
  const recentFail = runs.filter((r) => r.status === 'failed').length

  const t = workspace?.trading
  const a = workspace?.alerts
  const w = workspace?.watchlist
  const sc = workspace?.scheduler
  const f = workspace?.factors

  const dataSync = sc?.data_sync
  const alertEval = sc?.alert_eval

  return (
    <div className="qf-templates" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="qf-templates-head">
        <h2>概览</h2>
        <button className="qf-btn qf-btn-sm" onClick={load} disabled={loading}>
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>
      <div className="qf-templates-sub">
        欢迎使用 QuantFlow 量化工作流平台 · 当前版本 v{overview?.server?.version || workspace ? '7.0.1' : '1.7.0'}
      </div>

      <StatusBlock loading={loading} error={error} loadingText="正在加载概览…">
      <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
        <StatCard label="项目" value={projects.length} />
        <StatCard label="运行总数" value={runStats.total} sub={`成功 ${runStats.succeeded}`} accent="#22c55e" />
        <StatCard label="运行中" value={runStats.running} accent="#f59e0b" />
        <StatCard label="失败运行" value={recentFail} accent={recentFail ? '#ef4444' : undefined} />
        <StatCard label="回测报告" value={reports.length} />
        <StatCard label="已注册节点" value={overview?.nodes?.registered || '-'} />
        <StatCard label="在线用户连接" value={overview?.ws_connections || 0} />
        {overview?.users && <StatCard label="用户数" value={overview.users.total} />}
      </div>

      {/* V7.0 投研工作区总览 */}
      <div style={{ marginTop: 22 }}>
        <div style={{ fontWeight: 600, fontSize: 15, color: 'var(--text)', marginBottom: 12 }}>投研工作区</div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <WorkspacePanel title="模拟账户" onGoto={() => onNavigate('trade')}>
            {!t && <div className="qf-prop-hint">暂无账户数据</div>}
            {t && (
              <>
                <Row label="权益" value={fmtMoney(t.equity)} accent="#0891b2" />
                <Row label="初始资金" value={fmtMoney(t.initial_cash)} />
                <Row label="可用现金" value={fmtMoney(t.cash)} />
                <Row label="持仓市值" value={fmtMoney(t.market_value)} />
                <Row label="已实现盈亏" value={fmtMoney(t.realized_pnl)} accent={t.realized_pnl >= 0 ? '#e11d48' : '#0891b2'} />
                <Row label="持仓数" value={t.position_count ?? '-'} />
                <Row label="挂单数" value={t.open_orders ?? '-'} />
              </>
            )}
          </WorkspacePanel>

          <WorkspacePanel title="价格预警" onGoto={() => onNavigate('alerts')}>
            {!a && <div className="qf-prop-hint">暂无预警规则</div>}
            {a && (
              <>
                <Row label="规则总数" value={a.total} />
                <Row label="已启用" value={a.enabled} accent={a.enabled ? '#22c55e' : undefined} />
                <Row label="已触发" value={a.triggered} accent={a.triggered ? '#ef4444' : undefined} />
              </>
            )}
          </WorkspacePanel>

          <WorkspacePanel title="自选股" onGoto={() => onNavigate('watch')}>
            {!w && <div className="qf-prop-hint">暂无自选股</div>}
            {w && <Row label="监控标的数" value={w.count} />}
          </WorkspacePanel>

          <WorkspacePanel title="因子库" onGoto={() => onNavigate('factor')}>
            {!f && <div className="qf-prop-hint">暂无因子</div>}
            {f && <Row label="我的因子数" value={f.count} />}
          </WorkspacePanel>

          <WorkspacePanel title="调度状态" onGoto={() => onNavigate('sched')}>
            {!sc && <div className="qf-prop-hint">暂无调度数据</div>}
            {sc && (
              <>
                <Row
                  label="行情自动同步"
                  value={dataSync ? (dataSync.status === 'running' ? '同步中' : (dataSync.status || 'unknown')) : '未知'}
                  accent={dataSync?.status === 'running' ? '#f59e0b' : dataSync ? '#22c55e' : '#94a3b8'}
                />
                {dataSync?.finished_at && <Row label="上次同步" value={new Date(dataSync.finished_at).toLocaleString()} />}
                <Row
                  label="预警自动巡检"
                  value={alertEval?.running ? '运行中' : '已停止'}
                  accent={alertEval?.running ? '#22c55e' : '#94a3b8'}
                />
                {alertEval?.last_run_at && <Row label="上次巡检" value={new Date(alertEval.last_run_at).toLocaleString()} />}
              </>
            )}
          </WorkspacePanel>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 16, marginTop: 20, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 10 }}>最近运行</div>
          {runs.length === 0 && <div className="qf-prop-hint">暂无运行记录</div>}
          {runs.slice(0, 6).map((r) => (
            <div key={r.run_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: '1px solid #f1f5f9', fontSize: 13 }}>
              <span className={`qf-run-dot qf-run-${r.status}`} style={{ margin: 0 }} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.workflow_name || r.run_id.slice(0, 8)}</span>
              <span className="qf-hint">{new Date(r.started_at).toLocaleTimeString()}</span>
            </div>
          ))}
        </div>

        <div style={{ flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 10 }}>最近回测报告</div>
          {reports.length === 0 && <div className="qf-prop-hint">暂无回测报告</div>}
          {reports.map((s) => (
            <div key={s.run_id} style={{ padding: '6px 0', borderBottom: '1px solid #f1f5f9', fontSize: 13 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.strategy}</span>
                <span style={{ color: Number(s.total_return) >= 0 ? '#e11d48' : '#0891b2', fontWeight: 600 }}>
                  {s.total_return != null ? `${(Number(s.total_return) * 100).toFixed(2)}%` : '-'}
                </span>
              </div>
              <div className="qf-hint">{(s.symbols || []).join(', ')} · {s.start_date} ~ {s.end_date}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 20 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 10 }}>快速开始</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button className="qf-btn qf-btn-primary" onClick={() => onNavigate('editor')}>新建工作流</button>
          <button className="qf-btn" onClick={() => onNavigate('templates')}>浏览模板库</button>
          <button className="qf-btn" onClick={() => onNavigate('factor')}>打开因子库</button>
          <button className="qf-btn" onClick={() => onNavigate('reports')}>回测报告</button>
        </div>
      </div>
      </StatusBlock>
    </div>
  )
}
