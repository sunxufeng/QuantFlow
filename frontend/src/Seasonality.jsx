import { useState } from 'react'
import { runSeasonality } from './api.js'

const inp = { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 }
const pct = (v) => (v === null || v === undefined) ? '—' : `${(v * 100).toFixed(2)}%`

function Stat({ label, value, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

// 横向条形图：每组一行 label + 条形（均值收益，红绿表示正负）
function BarRow({ label, mean, count, maxAbs }) {
  if (mean === null || mean === undefined) return null
  const w = 300
  const half = w / 2
  const bw = (Math.abs(mean) / (maxAbs || 1)) * half
  const positive = mean >= 0
  const barX = positive ? half : half - bw
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '3px 0' }}>
      <div style={{ width: 56, fontSize: 12, color: '#374151', textAlign: 'right' }}>{label}</div>
      <svg width={w} height={16} style={{ background: '#f9fafb', borderRadius: 4 }}>
        <line x1={half} y1={0} x2={half} y2={16} stroke="#e5e7eb" />
        <rect x={barX} y={3} width={bw} height={10} fill={positive ? '#16a34a' : '#dc2626'} rx={2} />
      </svg>
      <div style={{ width: 74, fontSize: 12, color: positive ? '#16a34a' : '#dc2626' }}>{pct(mean)}</div>
      <div style={{ width: 56, fontSize: 11, color: '#9ca3af' }}>n={count ?? '—'}</div>
    </div>
  )
}

function MonthChart({ byMonth }) {
  const vals = byMonth.map((m) => m.mean_return).filter((v) => v !== null && v !== undefined)
  const maxAbs = Math.max(...vals.map((v) => Math.abs(v)), 1e-9)
  return (
    <div>
      {byMonth.map((m) => (
        <BarRow key={m.month} label={m.name} mean={m.mean_return} count={m.count} maxAbs={maxAbs} />
      ))}
    </div>
  )
}

function WeekdayChart({ byWeekday }) {
  const vals = byWeekday.map((w) => w.mean_return).filter((v) => v !== null && v !== undefined)
  const maxAbs = Math.max(...vals.map((v) => Math.abs(v)), 1e-9)
  return (
    <div>
      {byWeekday.map((w) => (
        <BarRow key={w.weekday} label={w.name} mean={w.mean_return} count={w.count} maxAbs={maxAbs} />
      ))}
    </div>
  )
}

function TomCompare({ tom }) {
  const t = tom.turn, nt = tom.non_turn, edge = tom.edge
  const rows = [
    { name: '月初/月末', s: t },
    { name: '其余时段', s: nt },
  ]
  const maxAbs = Math.max(Math.abs(t.mean_return || 0), Math.abs(nt.mean_return || 0), 1e-9)
  return (
    <div>
      {rows.map((r) => (
        <BarRow key={r.name} label={r.name} mean={r.s.mean_return} count={r.s.count} maxAbs={maxAbs} />
      ))}
      <div style={{ marginTop: 6, fontSize: 13, color: '#374151' }}>
        日历效应 edge（月初月末 − 其余）：
        <b style={{ color: (edge || 0) >= 0 ? '#16a34a' : '#dc2626' }}>{pct(edge)}</b>
        {' · '}{tom.interpretation}
      </div>
    </div>
  )
}

export default function Seasonality() {
  const [symbol, setSymbol] = useState('TEST.STOCK')
  const [start, setStart] = useState('2022-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [useSynth, setUseSynth] = useState(true)
  const [mu, setMu] = useState('0.08')
  const [sigma, setSigma] = useState('0.20')
  const [seed, setSeed] = useState('7')
  const [regime, setRegime] = useState(true)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const run = async () => {
    setErr('')
    if (!symbol.trim()) { setErr('请填写标的代码'); return }
    setLoading(true)
    try {
      const payload = {
        symbol: symbol.trim(),
        start,
        end,
        synthetic: useSynth
          ? { initial_price: 100.0, mu_annual: parseFloat(mu), sigma_annual: parseFloat(sigma), seed: parseInt(seed, 10), regime: !!regime }
          : null,
      }
      const res = await runSeasonality(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const sum = data?.summary || {}

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>季节性 / 日历效应分析 <span style={{ fontSize: 12, color: '#16a34a' }}>V21</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        将日收益率按自然月、周几、月初/月末窗口分组聚合，识别季节性规律（无需真实行情源，可一键切换 GBM 合成行情）。
      </p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <input placeholder="标的代码" value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ ...inp, width: 130 }} />
        <input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={inp} />
        <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={inp} />
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13 }}>
          <input type="checkbox" checked={useSynth} onChange={(e) => setUseSynth(e.target.checked)} /> 合成行情
        </label>
        {useSynth ? (
          <>
            <input placeholder="年化漂移μ" value={mu} onChange={(e) => setMu(e.target.value)} style={{ ...inp, width: 100 }} />
            <input placeholder="年化波动σ" value={sigma} onChange={(e) => setSigma(e.target.value)} style={{ ...inp, width: 100 }} />
            <input placeholder="种子" value={seed} onChange={(e) => setSeed(e.target.value)} style={{ ...inp, width: 70 }} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13 }}>
              <input type="checkbox" checked={regime} onChange={(e) => setRegime(e.target.checked)} /> 牛熊切换
            </label>
          </>
        ) : null}
        <button onClick={run} disabled={loading}
          style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          {loading ? '分析中…' : '分析'}
        </button>
      </div>

      {err ? <div style={{ color: '#dc2626' }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <Stat label="样本交易日" value={data.n_days} />
            <Stat label="数据源" value={data.source === 'synthetic' ? '合成行情' : '真实行情'} />
            <Stat label="最佳月" value={sum.best_month ? `${sum.best_month.name} ${pct(sum.best_month.mean_return)}` : '—'} tone="good" />
            <Stat label="最差月" value={sum.worst_month ? `${sum.worst_month.name} ${pct(sum.worst_month.mean_return)}` : '—'} tone="bad" />
            <Stat label="最佳周几" value={sum.best_weekday ? `${sum.best_weekday.name} ${pct(sum.best_weekday.mean_return)}` : '—'} tone="good" />
            <Stat label="最差周几" value={sum.worst_weekday ? `${sum.worst_weekday.name} ${pct(sum.worst_weekday.mean_return)}` : '—'} tone="bad" />
          </div>

          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <div style={{ minWidth: 380 }}>
              <h3 style={{ fontSize: 14 }}>按月平均日收益</h3>
              <MonthChart byMonth={data.by_month} />
            </div>
            <div style={{ minWidth: 380 }}>
              <h3 style={{ fontSize: 14 }}>按周几平均日收益</h3>
              <WeekdayChart byWeekday={data.by_weekday} />
            </div>
          </div>

          <div style={{ marginTop: 12, minWidth: 380 }}>
            <h3 style={{ fontSize: 14 }}>月初/月末效应（窗口 {data.tom_window} 交易日）</h3>
            <TomCompare tom={data.turn_of_month} />
          </div>
        </div>
      ) : null}
    </div>
  )
}
