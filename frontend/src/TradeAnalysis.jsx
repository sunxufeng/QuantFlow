import { useState } from 'react'
import { runTradeAnalysis } from './api.js'

const inp = { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 }
const num = (v, d = 2) => (v === null || v === undefined) ? '—' : Number(v).toFixed(d)
const pct = (v) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(2)}%`
const money = (v) => (v === null || v === undefined) ? '—' : (v >= 0 ? '+' : '') + Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })

function Stat({ label, value, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

export default function TradeAnalysis() {
  const [runId, setRunId] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    if (!runId.trim()) { setErr('请填写 run_id'); return }
    setLoading(true)
    try {
      const res = await runTradeAnalysis({ run_id: runId.trim() })
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const s = data?.summary || {}

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>成交分析 <span style={{ fontSize: 12, color: '#16a34a' }}>V25</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        基于回测报告的逐笔成交，统计交易笔数、胜率、平均盈亏、盈亏比、盈利因子与期望收益，并给出按标的拆分与逐笔流水（blotter）。
      </p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <input placeholder="回测 run_id" value={runId} onChange={(e) => setRunId(e.target.value)} style={{ ...inp, width: 280 }} />
        <button onClick={run} disabled={loading}
          style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          {loading ? '分析中…' : '分析成交'}
        </button>
      </div>

      {err ? <div style={{ color: '#dc2626' }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <Stat label="交易笔数" value={s.total_trades} />
            <Stat label="总盈亏" value={money(s.total_pnl)} tone={s.total_pnl >= 0 ? 'good' : 'bad'} />
            <Stat label="胜率" value={pct(s.win_rate)} />
            <Stat label="盈利因子" value={num(s.profit_factor, 3)} tone={(s.profit_factor || 0) >= 1 ? 'good' : 'bad'} />
            <Stat label="盈亏比" value={num(s.payoff_ratio, 3)} />
            <Stat label="期望收益" value={num(s.expectancy, 4)} />
            <Stat label="平均盈利" value={money(s.avg_win)} tone="good" />
            <Stat label="平均亏损" value={money(s.avg_loss)} tone="bad" />
            <Stat label="最大单笔盈利" value={money(s.largest_win)} tone="good" />
            <Stat label="最大单笔亏损" value={money(s.largest_loss)} tone="bad" />
          </div>

          <h3 style={{ fontSize: 14 }}>按标的拆分</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 12 }}>
            <thead>
              <tr style={{ color: '#6b7280', textAlign: 'right' }}>
                <th style={{ textAlign: 'left' }}>标的</th>
                <th>笔数</th><th>胜率</th><th>盈亏</th>
              </tr>
            </thead>
            <tbody>
              {(data.by_symbol || []).map((b) => (
                <tr key={b.symbol} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td>{b.symbol}</td>
                  <td style={{ textAlign: 'right' }}>{b.trades}</td>
                  <td style={{ textAlign: 'right' }}>{pct(b.win_rate)}</td>
                  <td style={{ textAlign: 'right', color: b.total_pnl >= 0 ? '#16a34a' : '#dc2626' }}>{money(b.total_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 14 }}>逐笔流水（blotter，{data.blotter?.length || 0} 笔）</h3>
          <div style={{ maxHeight: 360, overflow: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead style={{ position: 'sticky', top: 0, background: '#f8fafc' }}>
                <tr style={{ color: '#6b7280', textAlign: 'right' }}>
                  <th style={{ textAlign: 'left' }}>日期</th>
                  <th style={{ textAlign: 'left' }}>标的</th>
                  <th>方向</th><th>股数</th><th>价格</th><th>盈亏</th><th>累计盈亏</th>
                </tr>
              </thead>
              <tbody>
                {(data.blotter || []).map((t, i) => (
                  <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                    <td>{t.date}</td>
                    <td>{t.symbol}</td>
                    <td style={{ textAlign: 'right' }}>{t.side}</td>
                    <td style={{ textAlign: 'right' }}>{t.shares}</td>
                    <td style={{ textAlign: 'right' }}>{num(t.price, 2)}</td>
                    <td style={{ textAlign: 'right', color: (t.pnl || 0) >= 0 ? '#16a34a' : '#dc2626' }}>{money(t.pnl)}</td>
                    <td style={{ textAlign: 'right' }}>{money(t.cumulative_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  )
}
