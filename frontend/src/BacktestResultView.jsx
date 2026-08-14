import { useMemo } from 'react'

function Sparkline({ rows }) {
  const { path, area, min, max } = useMemo(() => {
    if (!rows || !rows.length) return { path: '', area: '', min: 0, max: 0 }
    const vals = rows.map((r) => Number(r.total_value) || 0)
    const lo = Math.min(...vals)
    const hi = Math.max(...vals)
    const w = 100
    const h = 32
    const span = hi - lo || 1
    const step = w / Math.max(vals.length - 1, 1)
    const pts = vals.map((v, i) => [i * step, h - ((v - lo) / span) * h])
    const p = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    const a = `0,${h} ${p} ${w},${h}`
    return { path: p, area: a, min: lo, max: hi }
  }, [rows])

  if (!path) return null
  const up = max >= min
  const stroke = up ? '#15803d' : '#dc2626'
  return (
    <svg viewBox="0 0 100 32" preserveAspectRatio="none" style={{ width: '100%', height: 48 }}>
      <polyline points={area} fill={stroke} fillOpacity="0.08" stroke="none" />
      <polyline points={path} fill="none" stroke={stroke} strokeWidth="1" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

function fmt(v) {
  if (v == null) return '-'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4)
  return String(v)
}

function UnderwaterChart({ rows }) {
  const { area, lo, hi } = useMemo(() => {
    if (!rows || !rows.length) return { area: '', lo: 0, hi: 0 }
    const vals = rows.map((r) => Number(r.total_value) || 0)
    let peak = vals[0]
    const dd = vals.map((v) => {
      peak = Math.max(peak, v)
      return v / peak - 1.0
    })
    const lo = Math.min(...dd)
    const hi = 0
    const w = 100
    const h = 36
    const span = hi - lo || 1
    const step = w / Math.max(dd.length - 1, 1)
    const pts = dd.map((d, i) => [i * step, h - ((d - lo) / span) * h])
    const p = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
    return { area: `0,${h} ${p} ${w},${h}`, lo, hi }
  }, [rows])
  if (!area) return null
  return (
    <svg viewBox="0 0 100 36" preserveAspectRatio="none" style={{ width: '100%', height: 52 }}>
      <polyline points={area} fill="#dc2626" fillOpacity="0.12" stroke="none" />
      <line x1="0" y1="0" x2="100" y2="0" stroke="#dc2626" strokeOpacity="0.4" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export default function BacktestResultView({ outputs }) {
  const summary = outputs?.summary
  const equity = outputs?.equity
  const attributionRaw = outputs?.attribution
  const attr = useMemo(() => {
    if (!attributionRaw) return null
    try {
      return typeof attributionRaw === 'string' ? JSON.parse(attributionRaw) : attributionRaw
    } catch {
      return null
    }
  }, [attributionRaw])

  const summaryRows = summary?.rows || (summary?.__type__ === 'table' ? summary.rows : [])
  const equityRows = equity?.rows || (equity?.__type__ === 'table' ? equity.rows : [])

  if (!summaryRows?.length) return null

  const metrics = Object.fromEntries(summaryRows.map((r) => [r.metric, r.value]))
  const monthly = attr?.curve?.monthly_returns || []
  const drawdowns = attr?.curve?.drawdown_periods || []
  const bench = attr?.benchmark || {}
  const risk = attr?.risk || {}
  const trade = attr?.trade || {}
  const hasDecomp = trade.win_pnl != null && trade.loss_pnl != null

  return (
    <div className="qf-bt">
      <div className="qf-bt-head">
        <div>
          <div className="qf-bt-title">策略回测 · {fmt(metrics.strategy) || '—'}</div>
          <div className="qf-hint">{fmt(metrics.symbol)} · {fmt(metrics.days)} 交易日 · {fmt(metrics.trade_count)} 笔交易</div>
        </div>
        <div className="qf-bt-final">
          <div className="qf-bt-final-v">{fmt(metrics.final_value)}</div>
          <div className={`qf-bt-ret ${metrics.total_return >= 0 ? 'qf-up' : 'qf-down'}`}>
            总收益 {(Number(metrics.total_return) * 100).toFixed(2)}%
          </div>
        </div>
      </div>

      <Sparkline rows={equityRows} />

      <div className="qf-bt-cards">
        {[
          ['夏普', metrics.sharpe != null ? Number(metrics.sharpe).toFixed(2) : '-'],
          ['最大回撤', metrics.max_drawdown != null ? (Number(metrics.max_drawdown) * 100).toFixed(2) + '%' : '-'],
          ['年化收益', metrics.annual_return != null ? (Number(metrics.annual_return) * 100).toFixed(2) + '%' : '-'],
          ['胜率', metrics.win_rate != null ? (Number(metrics.win_rate) * 100).toFixed(1) + '%' : '-'],
          ['盈亏比', metrics['盈亏比(profit_factor)'] != null ? Number(metrics['盈亏比(profit_factor)']).toFixed(2) : '-'],
          ['最大连胜', metrics.max_win_streak ?? '-'],
          ['最大连亏', metrics.max_loss_streak ?? '-'],
          ['持仓暴露比', metrics['持仓暴露比'] != null ? (Number(metrics['持仓暴露比']) * 100).toFixed(1) + '%' : '-'],
        ].map(([k, v]) => (
          <div key={k} className="qf-bt-card">
            <div className="qf-bt-card-l">{k}</div>
            <div className="qf-bt-card-v">{v}</div>
          </div>
        ))}
      </div>

      {drawdowns.length > 0 && (
        <div className="qf-bt-sec">
          <div className="qf-bt-sec-h">回撤区间（共 {drawdowns.length} 段，最长 {attr?.curve?.max_drawdown_days ?? 0} 天）</div>
          <div className="qf-bt-dd">
            {drawdowns.slice(0, 5).map((d, i) => (
              <span key={i} className="qf-bt-dd-pill" title={`${d.start} → ${d.end}`}>
                {d.start} ~ {d.end}：{(Number(d.depth) * 100).toFixed(1)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {monthly.length > 0 && (
        <div className="qf-bt-sec">
          <div className="qf-bt-sec-h">月度收益</div>
          <div className="qf-bt-monthly">
            {monthly.map((m) => (
              <span
                key={m.month}
                className="qf-bt-month"
                style={{ background: Number(m.return) >= 0 ? 'rgba(21,128,61,0.12)' : 'rgba(220,38,38,0.12)' }}
                title={`${m.month}：${(Number(m.return) * 100).toFixed(2)}%`}
              >
                {m.month.slice(5)} {(Number(m.return) * 100).toFixed(1)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {Object.keys(bench).length > 0 && (
        <div className="qf-bt-sec">
          <div className="qf-bt-sec-h">基准对比（买入持有）</div>
          <div className="qf-bt-cards">
            {[
              ['基准收益', (Number(bench.benchmark_return) * 100).toFixed(2) + '%'],
              ['超额收益', (Number(bench.excess_return) * 100).toFixed(2) + '%'],
              ['Alpha(年化)', (Number(bench.alpha) * 100).toFixed(2) + '%'],
              ['Beta', Number(bench.beta).toFixed(2)],
            ].map(([k, v]) => (
              <div key={k} className="qf-bt-card">
                <div className="qf-bt-card-l">{k}</div>
                <div className="qf-bt-card-v">{v}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="qf-bt-sec">
        <div className="qf-bt-sec-h">风险归因（V4.1）</div>
        <div className="qf-bt-cards">
          {[
            ['年化波动率', risk.volatility != null ? (Number(risk.volatility) * 100).toFixed(2) + '%' : '-'],
            ['下行波动率', risk.downside_deviation != null ? (Number(risk.downside_deviation) * 100).toFixed(2) + '%' : '-'],
            ['索提诺比率', risk.sortino != null ? Number(risk.sortino).toFixed(2) : '-'],
            ['最大回撤', metrics.max_drawdown != null ? (Number(metrics.max_drawdown) * 100).toFixed(2) + '%' : '-'],
            ['回撤天数', attr?.curve?.max_drawdown_days ?? '-'],
            ['持仓暴露比', metrics['持仓暴露比'] != null ? (Number(metrics['持仓暴露比']) * 100).toFixed(1) + '%' : '-'],
          ].map(([k, v]) => (
            <div key={k} className="qf-bt-card">
              <div className="qf-bt-card-l">{k}</div>
              <div className="qf-bt-card-v">{v}</div>
            </div>
          ))}
        </div>
        {equityRows.length > 1 && (
          <div className="qf-bt-sub">
            <span className="qf-bt-sub-h">水下回撤曲线（Underwater）</span>
            <UnderwaterChart rows={equityRows} />
          </div>
        )}
      </div>

      {hasDecomp && (
        <div className="qf-bt-sec">
          <div className="qf-bt-sec-h">收益分解（平仓盈亏贡献）</div>
          <div className="qf-bt-decomp">
            <div className="qf-bt-decomp-bar qf-up" style={{ flex: Math.max(trade.win_pnl, 1) }}>
              <span>盈利 {Number(trade.win_pnl).toFixed(0)}</span>
            </div>
            <div className="qf-bt-decomp-bar qf-down" style={{ flex: Math.max(-trade.loss_pnl, 1) }}>
              <span>亏损 {Number(trade.loss_pnl).toFixed(0)}</span>
            </div>
          </div>
          <div className="qf-hint" style={{ marginTop: 6 }}>
            盈亏比 {trade.profit_factor != null ? Number(trade.profit_factor).toFixed(2) : '-'} ·
            平均盈利 {Number(trade.avg_win || 0).toFixed(0)} · 平均亏损 {Number(trade.avg_loss || 0).toFixed(0)} ·
            最大连胜 {trade.max_win_streak ?? '-'} / 最大连亏 {trade.max_loss_streak ?? '-'}
          </div>
        </div>
      )}
    </div>
  )
}
