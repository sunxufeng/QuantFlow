import { useCallback, useEffect, useState } from 'react'
import { backtestReport, backtestReports, exportBacktestReport } from './api.js'
import FuturesBacktest from './FuturesBacktest.jsx'
import Optimizer from './Optimizer.jsx'

function fmtPct(v) {
  if (v == null) return '-'
  const n = Number(v) * 100
  return `${n.toFixed(2)}%`
}

function fmtNum(v, d = 2) {
  if (v == null) return '-'
  return Number(v).toFixed(d)
}

function EquityChart({ curve }) {
  if (!curve || !curve.length) return null
  const W = 600
  const H = 120
  const pad = 10
  const vals = curve.map((p) => Number(p.total_value) || 0)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const span = hi - lo || 1
  const stepX = curve.length > 1 ? (W - pad * 2) / (curve.length - 1) : 0
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  const path = curve
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * stepX).toFixed(1)},${y(Number(p.total_value) || 0).toFixed(1)}`)
    .join(' ')
  const area = `0,${H - pad} ${path} ${W - pad},${H - pad}`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: H }}>
      <polyline points={area} fill="#15803d" fillOpacity="0.08" stroke="none" />
      <polyline points={path} fill="none" stroke="#15803d" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function MetricCards({ m }) {
  if (!m) return null
  const cards = [
    ['总收益', fmtPct(m.total_return)],
    ['年化收益', fmtPct(m.annual_return)],
    ['夏普', fmtNum(m.sharpe)],
    ['最大回撤', fmtPct(m.max_drawdown)],
    ['胜率', fmtPct(m.win_rate)],
  ]
  return (
    <div className="qf-mcards">
      {cards.map(([label, value]) => (
        <div className="qf-mcard" key={label}>
          <div className="qf-mcard-label">{label}</div>
          <div className="qf-mcard-value">{value}</div>
        </div>
      ))}
    </div>
  )
}

export default function BacktestReports() {
  const [summaries, setSummaries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [compareId, setCompareId] = useState(null)
  const [compare, setCompare] = useState(null)
  const [tab, setTab] = useState('reports')

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return backtestReports()
      .then((res) => setSummaries(res.summaries || []))
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const openDetail = useCallback((runId) => {
    setDetailLoading(true)
    setDetail(null)
    backtestReport(runId)
      .then(setDetail)
      .catch((e) => setError(`报告加载失败: ${e.message}`))
      .finally(() => setDetailLoading(false))
  }, [])

  const toggleCompare = useCallback((runId) => {
    if (compareId === runId) {
      setCompareId(null)
      setCompare(null)
      return
    }
    setCompareId(runId)
    backtestReport(runId).then(setCompare).catch(() => {})
  }, [compareId])

  const tabBtn = (key, label) => (
    <button
      type="button"
      onClick={() => setTab(key)}
      className={tab === key ? 'qf-reports-tab qf-reports-tab-active' : 'qf-reports-tab'}
    >
      {label}
    </button>
  )

  return (
    <div className="qf-monitor qf-reports" style={{ padding: 14 }}>
      <div className="qf-reports-head">
        <h3 className="qf-reports-title">回测报告中心（V1.6）</h3>
        <div className="qf-reports-tabs">
          {tabBtn('reports', '报告列表')}
          {tabBtn('futures', '期货回测')}
          {tabBtn('optimize', '参数优化')}
          <button className="qf-btn qf-btn-primary" onClick={refresh}>刷新</button>
        </div>
      </div>
      {error && <div className="qf-error">{error}</div>}
      {loading && <div className="qf-busy">加载中…</div>}

      {tab === 'futures' && (
        <FuturesBacktest onRun={() => refresh()} />
      )}

      {tab === 'optimize' && (
        <Optimizer />
      )}

      {tab === 'reports' && (
      <>
      {!loading && summaries.length === 0 && (
        <div className="qf-hint">暂无回测报告。在「工作流编辑器」运行回测节点后将自动留痕，可在此横向对比策略表现。</div>
      )}

      {summaries.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="qf-table">
            <thead>
              <tr>
                <th>策略</th>
                <th>标的</th>
                <th>区间</th>
                <th>总收益</th>
                <th>年化</th>
                <th>夏普</th>
                <th>最大回撤</th>
                <th>胜率</th>
                <th style={{ width: 110 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map((s) => (
                <tr key={s.run_id} className={compareId === s.run_id ? 'qf-row-active' : ''}>
                  <td>{s.strategy}</td>
                  <td>{(s.symbols || []).join(', ')}</td>
                  <td className="qf-hint">{s.start_date} ~ {s.end_date}</td>
                  <td className={Number(s.total_return) >= 0 ? 'qf-up' : 'qf-down'}>{fmtPct(s.total_return)}</td>
                  <td>{fmtPct(s.annual_return)}</td>
                  <td>{fmtNum(s.sharpe)}</td>
                  <td>{fmtPct(s.max_drawdown)}</td>
                  <td>{fmtPct(s.win_rate)}</td>
                  <td>
                    <button className="qf-btn qf-btn-sm" onClick={() => openDetail(s.run_id)}>查看</button>
                    <button className="qf-btn qf-btn-sm" onClick={() => toggleCompare(s.run_id)}>
                      {compareId === s.run_id ? '取消' : '对比'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className="qf-an-block">
          <div className="qf-an-title">
            <span>报告详情 · {detail.strategy} · {detail.run_id}</span>
            <span style={{ display: 'flex', gap: 6 }}>
              <button className="qf-btn qf-btn-sm" onClick={() => exportBacktestReport(detail.run_id, 'csv').catch((e) => setError(`导出失败: ${e.message}`))}>CSV</button>
              <button className="qf-btn qf-btn-sm" onClick={() => exportBacktestReport(detail.run_id, 'json').catch((e) => setError(`导出失败: ${e.message}`))}>JSON</button>
            </span>
          </div>
          <MetricCards m={detail.metrics} />
          <div className="qf-an-title">净值曲线</div>
          <EquityChart curve={detail.equity_curve} />
          <div className="qf-hint">
            标的：{(detail.symbols || []).join(', ')} ｜ 区间：{detail.start_date} ~ {detail.end_date} ｜
            交易笔数：{Array.isArray(detail.trades) ? detail.trades.length : 0}
          </div>
        </div>
      )}

      {compare && (
        <div className="qf-an-block">
          <div className="qf-an-title">对比基准 · {compare.strategy} · {compare.run_id}</div>
          <MetricCards m={compare.metrics} />
          <EquityChart curve={compare.equity_curve} />
        </div>
      )}
      </>
      )}
    </div>
  )
}
