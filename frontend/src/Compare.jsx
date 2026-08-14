import { useCallback, useEffect, useMemo, useState } from 'react'
import { backtestReports, backtestCompare, backtestLeaderboard } from './api.js'

const METRIC_LABELS = {
  total_return: '总收益',
  annual_return: '年化',
  sharpe: '夏普',
  max_drawdown: '最大回撤',
  win_rate: '胜率',
}
const METRIC_KEYS = Object.keys(METRIC_LABELS)

const SERIES_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#3b82f6', '#8b5cf6', '#ec4899', '#14b8a6']

const fmtPct = (v) =>
  v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
const fmtNum = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d))

function EquityOverlay({ items }) {
  const W = 680
  const H = 240
  const pad = { l: 44, r: 12, t: 12, b: 22 }
  const { paths, yMin, yMax, xLabels } = useMemo(() => {
    const all = items.flatMap((it) => (it.curve_pct || []).map((p) => p.pct))
    if (!all.length) return { paths: [], yMin: 0, yMax: 0, xLabels: [] }
    const lo = Math.min(0, ...all)
    const hi = Math.max(0, ...all)
    const span = hi - lo || 1
    const maxLen = Math.max(...items.map((it) => (it.curve_pct || []).length))
    const innerW = W - pad.l - pad.r
    const innerH = H - pad.t - pad.b
    const xOf = (i) => pad.l + (maxLen <= 1 ? 0 : (i / (maxLen - 1)) * innerW)
    const yOf = (pct) => pad.t + innerH - ((pct - lo) / span) * innerH
    const paths = items.map((it) => {
      const pts = (it.curve_pct || [])
        .map((p, i) => `${xOf(i).toFixed(1)},${yOf(p.pct).toFixed(1)}`)
        .join(' ')
      return { run_id: it.run_id, color: '', d: pts }
    })
    const step = Math.max(1, Math.floor(maxLen / 6))
    const xLabels = []
    for (let i = 0; i < maxLen; i += step) xLabels.push({ x: xOf(i), i })
    return { paths, yMin: lo, yMax: hi, xLabels }
  }, [items])

  if (!items.length) return null
  const innerH = H - pad.t - pad.b
  const yOf = (pct) => pad.t + innerH - ((pct - yMin) / ((yMax - yMin) || 1)) * innerH

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', background: '#fff', border: '1px solid var(--border)', borderRadius: 8 }}>
      {/* 0% 基准线 */}
      <line x1={pad.l} y1={yOf(0)} x2={W - pad.r} y2={yOf(0)} stroke="#cbd5e1" strokeDasharray="4 3" />
      <text x={4} y={yOf(0) + 3} fontSize="9" fill="#94a3b8">0%</text>
      {[yMin, (yMin + yMax) / 2, yMax].map((v, i) => (
        <text key={i} x={4} y={yOf(v) + 3} fontSize="9" fill="#94a3b8">
          {v.toFixed(0)}%
        </text>
      ))}
      {paths.map((p, idx) => (
        <polyline
          key={p.run_id + idx}
          points={p.d}
          fill="none"
          stroke={SERIES_COLORS[idx % SERIES_COLORS.length]}
          strokeWidth="1.6"
        />
      ))}
      {xLabels.map((l) => (
        <text key={l.i} x={l.x} y={H - 6} fontSize="9" fill="#94a3b8" textAnchor="middle">
          {l.i}
        </text>
      ))}
    </svg>
  )
}

export default function Compare() {
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState([])
  const [compare, setCompare] = useState(null)
  const [lbMetric, setLbMetric] = useState('sharpe')
  const [lbOrder, setLbOrder] = useState('desc')
  const [leaderboard, setLeaderboard] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    backtestReports()
      .then((d) => setReports(d.summaries || []))
      .catch((e) => setError(`加载报告失败: ${e.message}`))
  }, [])

  const toggle = useCallback((rid) => {
    setSelected((prev) =>
      prev.includes(rid) ? prev.filter((x) => x !== rid) : [...prev, rid]
    )
  }, [])

  const runCompare = useCallback(() => {
    if (selected.length < 2) {
      setError('请至少选择 2 个回测任务进行对比')
      return
    }
    setLoading(true)
    setError('')
    backtestCompare(selected)
      .then((d) => setCompare(d))
      .catch((e) => setError(`对比失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [selected])

  const loadLeaderboard = useCallback(() => {
    setLoading(true)
    backtestLeaderboard(lbMetric, lbOrder)
      .then(setLeaderboard)
      .catch((e) => setError(`排行榜加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [lbMetric, lbOrder])

  useEffect(() => {
    loadLeaderboard()
  }, [loadLeaderboard])

  const selectedReports = reports.filter((r) => selected.includes(r.run_id))

  return (
    <div className="qf-reports" style={{ padding: 16 }}>
      <div className="qf-reports-head">
        <div>
          <div className="qf-reports-title">回测对比与策略排行榜</div>
          <div className="qf-reports-tabs" style={{ marginTop: 4 }}>
            <span className="qf-hint">从已有回测报告中勾选 2 个及以上，横向对比指标与净值曲线</span>
          </div>
        </div>
      </div>

      {error && <div className="qf-error" style={{ color: '#ef4444', fontSize: 12, margin: '8px 0' }}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 14, alignItems: 'start' }}>
        {/* 左侧：可选报告清单 */}
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', maxHeight: 420, overflowY: 'auto' }}>
          <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 600, color: '#475569' }}>
            回测任务（{reports.length}）
          </div>
          {reports.length === 0 && <div style={{ padding: 12, fontSize: 12, color: '#94a3b8' }}>暂无报告</div>}
          {reports.map((r) => (
            <label
              key={r.run_id}
              style={{
                display: 'flex', gap: 8, alignItems: 'center', padding: '7px 10px',
                borderBottom: '1px solid #f1f5f9', cursor: 'pointer', fontSize: 12,
                background: selected.includes(r.run_id) ? 'rgba(99,102,241,.08)' : '#fff',
              }}
            >
              <input type="checkbox" checked={selected.includes(r.run_id)} onChange={() => toggle(r.run_id)} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {r.strategy}
                </div>
                <div style={{ fontSize: 11, color: '#94a3b8' }}>
                  {(r.symbols || []).join(',')} · {fmtPct(r.total_return)}
                </div>
              </div>
            </label>
          ))}
          <div style={{ padding: 10 }}>
            <button className="qf-btn qf-btn-primary" disabled={selected.length < 2 || loading} onClick={runCompare}>
              对比选中（{selected.length}）
            </button>
          </div>
        </div>

        {/* 右侧：对比结果 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {compare && compare.items.length > 0 && (
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
              <div className="qf-reports-title" style={{ fontSize: 14, marginBottom: 8 }}>指标对比</div>
              <table className="qf-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    {compare.items.map((it, i) => (
                      <th key={it.run_id} style={{ color: SERIES_COLORS[i % SERIES_COLORS.length] }}>
                        {it.strategy}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>标的</td>
                    {compare.items.map((it) => (
                      <td key={it.run_id}>{(it.symbols || []).join(',')}</td>
                    ))}
                  </tr>
                  <tr>
                    <td>区间</td>
                    {compare.items.map((it) => (
                      <td key={it.run_id}>{it.start_date} ~ {it.end_date}</td>
                    ))}
                  </tr>
                  {METRIC_KEYS.map((mk) => (
                    <tr key={mk}>
                      <td>{METRIC_LABELS[mk]}</td>
                      {compare.items.map((it) => {
                        const v = it.metrics?.[mk]
                        if (mk === 'total_return' || mk === 'annual_return' || mk === 'max_drawdown' || mk === 'win_rate') {
                          return <td key={it.run_id}>{v == null ? '—' : fmtPct(v)}</td>
                        }
                        return <td key={it.run_id}>{fmtNum(v)}</td>
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="qf-reports-title" style={{ fontSize: 14, margin: '14px 0 6px' }}>累计收益曲线（归一化 %）</div>
              <EquityOverlay items={compare.items} />
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 6 }}>
                {compare.items.map((it, i) => (
                  <span key={it.run_id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#475569' }}>
                    <span style={{ width: 10, height: 3, background: SERIES_COLORS[i % SERIES_COLORS.length], display: 'inline-block', borderRadius: 2 }} />
                    {it.strategy}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 排行榜 */}
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <div className="qf-reports-title" style={{ fontSize: 14 }}>策略排行榜</div>
              <select className="qf-select" value={lbMetric} onChange={(e) => setLbMetric(e.target.value)} style={{ fontSize: 12, padding: '3px 6px' }}>
                {METRIC_KEYS.map((mk) => (
                  <option key={mk} value={mk}>{METRIC_LABELS[mk]}</option>
                ))}
              </select>
              <select className="qf-select" value={lbOrder} onChange={(e) => setLbOrder(e.target.value)} style={{ fontSize: 12, padding: '3px 6px' }}>
                <option value="desc">从高到低</option>
                <option value="asc">从低到高</option>
              </select>
              <button className="qf-btn qf-btn-sm" onClick={loadLeaderboard}>刷新</button>
            </div>
            {leaderboard && (
              <table className="qf-table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>策略</th>
                    <th>标的</th>
                    <th>区间</th>
                    <th>{leaderboard.metric_label}</th>
                    <th>总收益</th>
                    <th>夏普</th>
                    <th>回撤</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.items.length === 0 && (
                    <tr><td colSpan={8} className="qf-hint">暂无含该指标的回测报告</td></tr>
                  )}
                  {leaderboard.items.map((row, i) => (
                    <tr key={row.run_id}>
                      <td>{i + 1}</td>
                      <td>{row.strategy}</td>
                      <td>{(row.symbols || []).join(',')}</td>
                      <td>{row.start_date} ~ {row.end_date}</td>
                      <td style={{ fontWeight: 600, color: 'var(--primary)' }}>{fmtNum(row.value)}</td>
                      <td>{fmtPct(row.metrics?.total_return)}</td>
                      <td>{fmtNum(row.metrics?.sharpe)}</td>
                      <td>{fmtPct(row.metrics?.max_drawdown)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
