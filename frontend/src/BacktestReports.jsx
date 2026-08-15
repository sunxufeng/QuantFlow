import { useCallback, useEffect, useState } from 'react'
import { backtestReport, backtestReports, exportBacktestReport, fetchBars, patchReport, reportFactors, reportTags } from './api.js'
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

function EquityChart({ curve, benchmark }) {
  if (!curve || !curve.length) return null
  const W = 600
  const H = 120
  const pad = 10
  const vals = curve.map((p) => Number(p.total_value) || 0)
  let lo = Math.min(...vals)
  let hi = Math.max(...vals)
  const benchVals = benchmark && benchmark.length ? benchmark.map((p) => Number(p.value) || 0) : null
  if (benchVals) {
    lo = Math.min(lo, ...benchVals)
    hi = Math.max(hi, ...benchVals)
  }
  const span = hi - lo || 1
  const stepX = curve.length > 1 ? (W - pad * 2) / (curve.length - 1) : 0
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  const path = curve
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * stepX).toFixed(1)},${y(Number(p.total_value) || 0).toFixed(1)}`)
    .join(' ')
  const area = `0,${H - pad} ${path} ${W - pad},${H - pad}`
  const benchPath = benchVals
    ? benchVals.map((v, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
    : null
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: H }}>
      <polyline points={area} fill="#15803d" fillOpacity="0.08" stroke="none" />
      {benchPath && (
        <polyline points={benchPath} fill="none" stroke="#94a3b8" strokeWidth="1.4" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
      )}
      <polyline points={path} fill="none" stroke="#15803d" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function KlineChart({ bars, trades, symbol }) {
  if (!bars || bars.length < 2) return <div className="qf-hint">该标的可用行情不足，无法绘制 K 线。</div>
  const W = 720
  const H = 380
  const padL = 44
  const padR = 12
  const padT = 12
  const padB = 18
  const volH = 70
  const priceH = H - volH - padT - padB
  const volBase = padT + priceH + 8
  const volBottom = volBase + volH
  const n = bars.length
  const step = Math.max(1, Math.floor(n / 300))
  const idxs = []
  for (let i = 0; i < n; i += step) idxs.push(i)
  if (idxs[idxs.length - 1] !== n - 1) idxs.push(n - 1)
  const bs = idxs.map((i) => bars[i])
  const closes = bars.map((b) => Number(b.close) || 0)
  const lo = Math.min(...bars.map((b) => Number(b.low) || 0))
  const hi = Math.max(...bars.map((b) => Number(b.high) || 0))
  const span = hi - lo || 1
  const x = (k) => padL + (k / (idxs.length - 1)) * (W - padL - padR)
  const y = (v) => padT + (1 - (v - lo) / span) * priceH
  const ma = (period) =>
    closes.map((_, i) => {
      if (i < period - 1) return null
      let s = 0
      for (let j = i - period + 1; j <= i; j++) s += closes[j]
      return s / period
    })
  const ma5 = ma(5)
  const ma20 = ma(20)
  const ma60 = ma(60)
  const maLine = (arr) =>
    idxs
      .map((i, k) => {
        const v = arr[i]
        if (v == null) return ''
        return `${k === 0 ? 'M' : 'L'}${x(k).toFixed(1)},${y(v).toFixed(1)}`
      })
      .filter(Boolean)
      .join(' ')
  const vols = bars.map((b) => Number(b.volume) || 0)
  const maxVol = Math.max(...vols, 1)
  const volY = (v) => volBase + (1 - v / maxVol) * volH
  const dateIdx = {}
  bars.forEach((b, i) => { dateIdx[b.date] = i })
  const markers = (trades || [])
    .filter((t) => t.symbol === symbol)
    .map((t) => {
      const i = dateIdx[t.date]
      if (i == null) return null
      const k = idxs.indexOf(i)
      if (k < 0) return null
      const up = t.side === 'buy'
      const yy = up ? y(bars[i].high) - 9 : y(bars[i].low) + 9
      return { k, cx: x(k), cy: yy, up }
    })
    .filter(Boolean)
  const cw = Math.max(2, ((W - padL - padR) / idxs.length) * 0.6)
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: H }}>
        <line x1={padL} y1={padT} x2={padL} y2={padT + priceH} stroke="#cbd5e1" />
        <line x1={padL} y1={volBase} x2={W - padR} y2={volBase} stroke="#e2e8f0" />
        {bs.map((b, k) => {
          const up = Number(b.close) >= Number(b.open)
          const color = up ? '#15803d' : '#dc2626'
          const yO = y(Number(b.open))
          const yC = y(Number(b.close))
          const top = Math.min(yO, yC)
          const h = Math.max(1, Math.abs(yC - yO))
          return (
            <g key={k}>
              <line x1={x(k)} y1={y(Number(b.high))} x2={x(k)} y2={y(Number(b.low))} stroke={color} strokeWidth="1" vectorEffect="non-scaling-stroke" />
              <rect x={x(k) - cw / 2} y={top} width={cw} height={h} fill={color} />
            </g>
          )
        })}
        <path d={maLine(ma5)} fill="none" stroke="#d97706" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
        <path d={maLine(ma20)} fill="none" stroke="#2563eb" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
        <path d={maLine(ma60)} fill="none" stroke="#7c3aed" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
        {bs.map((b, k) => {
          const up = Number(b.close) >= Number(b.open)
          return (
            <rect
              key={k}
              x={x(k) - cw / 2}
              y={volY(Number(b.volume) || 0)}
              width={cw}
              height={volBottom - volY(Number(b.volume) || 0)}
              fill={up ? '#86efac' : '#fca5a5'}
              opacity="0.7"
            />
          )
        })}
        {markers.map((mk, i) => (
          <path
            key={i}
            d={mk.up ? `M${mk.cx},${mk.cy} l-5,8 l10,0 z` : `M${mk.cx},${mk.cy} l-5,-8 l10,0 z`}
            fill={mk.up ? '#15803d' : '#dc2626'}
          />
        ))}
        <text x={padL} y={padT - 2} fill="#64748b" fontSize="10">{hi.toFixed(2)}</text>
        <text x={padL} y={padT + priceH - 2} fill="#64748b" fontSize="10">{lo.toFixed(2)}</text>
        <text x={W - padR} y={H - 4} fill="#64748b" fontSize="9" textAnchor="end">{bs[bs.length - 1]?.date}</text>
        <text x={padL} y={H - 4} fill="#64748b" fontSize="9">{bs[0]?.date}</text>
      </svg>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 4, fontSize: 11 }}>
        <span style={{ color: '#d97706' }}>— MA5</span>
        <span style={{ color: '#2563eb' }}>— MA20</span>
        <span style={{ color: '#7c3aed' }}>— MA60</span>
        <span style={{ color: '#15803d' }}>▲ 买入</span>
        <span style={{ color: '#dc2626' }}>▼ 卖出</span>
      </div>
    </div>
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
  const [klineSymbol, setKlineSymbol] = useState('')
  const [klineBars, setKlineBars] = useState(null)
  const [klineLoading, setKlineLoading] = useState(false)

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

  // K 线 / 信号：随报告或所选标的变化拉取行情
  useEffect(() => {
    if (!detail) return
    const syms = detail.symbols || []
    if (syms.length === 0) { setKlineBars(null); return }
    const sym = syms.includes(klineSymbol) ? klineSymbol : syms[0]
    if (sym !== klineSymbol) { setKlineSymbol(sym); return }
    setKlineLoading(true)
    fetchBars(sym, detail.start_date, detail.end_date)
      .then((d) => setKlineBars(d.bars || []))
      .catch(() => setKlineBars([]))
      .finally(() => setKlineLoading(false))
  }, [detail, klineSymbol])

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
          <EquityChart curve={detail.equity_curve} benchmark={detail.benchmark_curve} />
          <div className="qf-hint">
            标的：{(detail.symbols || []).join(', ')} ｜ 区间：{detail.start_date} ~ {detail.end_date} ｜
            交易笔数：{Array.isArray(detail.trades) ? detail.trades.length : 0}
            {Array.isArray(detail.factors) && detail.factors.length > 0 && (
              <span> ｜ 关联因子：{detail.factors.join(', ')}</span>
            )}
          </div>

          {detail.benchmark_symbol && detail.metrics?.attribution?.benchmark && (
            <>
              <div className="qf-an-title">基准对比（V14 · {detail.benchmark_symbol} 买入持有）</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 6 }}>
                {(() => {
                  const b = detail.metrics.attribution.benchmark
                  const cells = [
                    ['基准收益', `${((b.benchmark_return || 0) * 100).toFixed(2)}%`],
                    ['超额收益', `${((b.excess_return || 0) * 100).toFixed(2)}%`],
                    ['Alpha', `${(b.alpha || 0).toFixed(2)}%`],
                    ['Beta', (b.beta || 0).toFixed(3)],
                    ['跟踪误差(年化)', `${((b.tracking_error || 0) * 100).toFixed(2)}%`],
                    ['信息比率', (b.information_ratio || 0).toFixed(2)],
                  ]
                  return cells.map(([k, v]) => (
                    <div key={k} className="qf-mcard" style={{ minWidth: 130 }}>
                      <div className="qf-mcard-label">{k}</div>
                      <div className="qf-mcard-value" style={{ fontSize: 15 }}>{v}</div>
                    </div>
                  ))
                })()}
              </div>
              <div className="qf-hint" style={{ marginTop: 6 }}>
                净值曲线图中灰色虚线为基准；Beta 衡量组合相对基准的系统性暴露，信息比率 = 年化超额收益 / 跟踪误差。
              </div>
            </>
          )}

          <div className="qf-an-title">K 线 / 技术指标 / 买卖信号（V13）</div>
          {(detail.symbols || []).length > 0 && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>标的：</span>
              {(detail.symbols || []).map((s) => (
                <button
                  key={s}
                  className={s === klineSymbol ? 'qf-btn qf-btn-primary qf-btn-sm' : 'qf-btn qf-btn-sm'}
                  onClick={() => setKlineSymbol(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {klineLoading && <div className="qf-busy">行情加载中…</div>}
          {!klineLoading && klineSymbol && (
            <KlineChart bars={klineBars || []} trades={detail.trades || []} symbol={klineSymbol} />
          )}
          {(detail.symbols || []).length === 0 && <div className="qf-hint">该报告无标的行情可绘制。</div>}

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
