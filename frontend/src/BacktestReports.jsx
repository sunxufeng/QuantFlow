import { useCallback, useEffect, useState } from 'react'
import { backtestReport, backtestReports, exportBacktestReport, patchReport, reportFactors, reportTags } from './api.js'
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
  const [allTags, setAllTags] = useState([])
  const [tagFilter, setTagFilter] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editNotes, setEditNotes] = useState('')
  const [savingTag, setSavingTag] = useState(false)
  const [factorData, setFactorData] = useState(null)
  const [factorLoading, setFactorLoading] = useState(false)

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return backtestReports()
      .then((res) => setSummaries(res.summaries || []))
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
    reportTags().then((r) => setAllTags((r.items || []).map((it) => it[0]))).catch(() => {})
  }, [refresh])

  const openDetail = useCallback((runId) => {
    setDetailLoading(true)
    setDetail(null)
    setFactorData(null)
    backtestReport(runId)
      .then((d) => {
        setDetail(d)
        setEditTags((d.tags || []).join(', '))
        setEditNotes(d.notes || '')
        setFactorLoading(true)
        reportFactors(runId)
          .then(setFactorData)
          .catch(() => setFactorData({ items: [], notice: '因子 IC/IR 加载失败' }))
          .finally(() => setFactorLoading(false))
      })
      .catch((e) => setError(`报告加载失败: ${e.message}`))
      .finally(() => setDetailLoading(false))
  }, [])

  const saveMeta = useCallback(() => {
    if (!detail) return
    setSavingTag(true)
    const tags = editTags.split(',').map((t) => t.trim()).filter(Boolean)
    patchReport(detail.run_id, { tags, notes: editNotes })
      .then((d) => {
        setDetail(d)
        setEditTags((d.tags || []).join(', '))
        setEditNotes(d.notes || '')
        return refresh()
      })
      .then(() => reportTags().then((r) => setAllTags((r.items || []).map((it) => it[0]))).catch(() => {}))
      .catch((e) => setError(`保存失败: ${e.message}`))
      .finally(() => setSavingTag(false))
  }, [detail, editTags, editNotes, refresh])

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

      {tab === 'reports' && allTags.length > 0 && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '8px 0' }}>
          <span className="qf-prop-label">按实验标签筛选</span>
          <select className="qf-name-input" style={{ width: 200 }}
            value={tagFilter} onChange={(e) => setTagFilter(e.target.value)}>
            <option value="">全部</option>
            {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          {tagFilter && <button className="qf-btn qf-btn-sm" onClick={() => setTagFilter('')}>清除</button>}
        </div>
      )}

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
              {summaries
                .filter((s) => !tagFilter || (s.tags || []).includes(tagFilter))
                .map((s) => (
                <tr key={s.run_id} className={compareId === s.run_id ? 'qf-row-active' : ''}>
                  <td>
                    {s.strategy}
                    {(s.tags || []).length > 0 && (
                      <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {s.tags.map((t) => (
                          <span key={t} className="qf-tag" style={{ background: '#6366f1', color: '#fff' }}>{t}</span>
                        ))}
                      </div>
                    )}
                  </td>
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
          <div className="qf-an-title">实验标签与备注（V9.0）</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-start', marginBottom: 8 }}>
            <label className="qf-prop-field" style={{ margin: 0, flex: 1, minWidth: 220 }}>
              <span className="qf-prop-label">标签（逗号分隔，如 基线,参数组A）</span>
              <input className="qf-name-input" value={editTags}
                onChange={(e) => setEditTags(e.target.value)} placeholder="基线, 参数组A" />
            </label>
            <button className="qf-btn qf-btn-primary qf-btn-sm" onClick={saveMeta} disabled={savingTag}>
              {savingTag ? '保存中…' : '保存标签/备注'}
            </button>
          </div>
          <label className="qf-prop-field" style={{ margin: 0, display: 'block' }}>
            <span className="qf-prop-label">备注</span>
            <textarea className="qf-name-input" value={editNotes} rows={2}
              onChange={(e) => setEditNotes(e.target.value)}
              placeholder="记录本次实验的设计意图、参数选择、结论…" style={{ width: '100%' }} />
          </label>
          {(detail.tags || []).length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {detail.tags.map((t) => (
                <span key={t} className="qf-tag" style={{ background: '#6366f1', color: '#fff' }}>{t}</span>
              ))}
            </div>
          )}
          <div className="qf-an-title">净值曲线</div>
          <EquityChart curve={detail.equity_curve} />
          <div className="qf-hint">
            标的：{(detail.symbols || []).join(', ')} ｜ 区间：{detail.start_date} ~ {detail.end_date} ｜
            交易笔数：{Array.isArray(detail.trades) ? detail.trades.length : 0}
            {Array.isArray(detail.factors) && detail.factors.length > 0 && (
              <span> ｜ 关联因子：{detail.factors.join(', ')}</span>
            )}
          </div>

          {Array.isArray(detail.factors) && detail.factors.length > 0 && (
            <>
              <div className="qf-an-title">策略关联因子 IC/IR（V3.2）</div>
              {factorLoading && <div className="qf-busy">因子计算中…</div>}
              {!factorLoading && factorData && (
                <>
                  {factorData.notice && <div className="qf-hint">{factorData.notice}</div>}
                  <div style={{ overflowX: 'auto' }}>
                    <table className="qf-table">
                      <thead>
                        <tr>
                          <th>因子</th>
                          <th>平均 IC</th>
                          <th>IC 标准差</th>
                          <th>IR</th>
                          <th>IC&gt;0 占比</th>
                          <th>样本期数</th>
                        </tr>
                      </thead>
                      <tbody>
                        {factorData.items.map((it) => (
                          <tr key={it.factor}>
                            <td>{it.factor}</td>
                            <td>{fmtNum(it.mean_ic, 4)}</td>
                            <td>{fmtNum(it.std_ic, 4)}</td>
                            <td>{fmtNum(it.ir, 4)}</td>
                            <td>{fmtPct(it.ic_positive_ratio)}</td>
                            <td>{it.observations}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {factorData.unknown && factorData.unknown.length > 0 && (
                    <div className="qf-hint">未知因子（已过滤）：{factorData.unknown.join(', ')}</div>
                  )}
                </>
              )}
            </>
          )}
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
