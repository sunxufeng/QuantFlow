import { useEffect, useState } from 'react'
import { getFactorBacktestCatalog, runFactorBacktest } from './api.js'

export default function FactorBacktest() {
  const [catalog, setCatalog] = useState([])
  const [factor, setFactor] = useState('')
  const [universe, setUniverse] = useState('TEST.STOCK,TEST.BANK,TEST.FUND,TEST.FUTURE')
  const [quantiles, setQuantiles] = useState('5')
  const [neutralized, setNeutralized] = useState(false)
  const [source, setSource] = useState('synthetic')
  const [start, setStart] = useState('2023-01-01')
  const [end, setEnd] = useState('2023-12-31')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    getFactorBacktestCatalog().then((r) => {
      setCatalog(r.factors || [])
      if (r.factors && r.factors.length) setFactor(r.factors[0].name)
    }).catch(() => {})
  }, [])

  const run = async () => {
    setErr('')
    const syms = universe.split(',').map((s) => s.trim()).filter(Boolean)
    const payload = {
      factor: factor || (catalog[0] && catalog[0].name),
      universe: syms,
      start, end,
      quantiles: parseInt(quantiles, 10) || 5,
      neutralized,
      source,
      seed: 12345,
    }
    setLoading(true)
    try {
      const res = await runFactorBacktest(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const m = data ? data.metrics : null
  const minCr = data ? Math.min(...data.cum_return, 0) : -0.1
  const maxCr = data ? Math.max(...data.cum_return, 0.0001) : 0.1

  return (
    <div style={{ padding: 20, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>因子回测（多空组合） <span style={{ fontSize: 12, color: '#9ca3af' }}>V30</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>把因子滚动计算、逐期横截面分组，构建多空组合，得到可交易的因子收益序列与 IC 时序。</p>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
        <label>因子
          <select value={factor} onChange={(e) => setFactor(e.target.value)} style={inp}>
            {catalog.map((f) => <option key={f.name + f.kind} value={f.name}>{f.name}{f.kind === 'expression' ? '（表达式）' : ''}</option>)}
          </select>
        </label>
        <label>股票池<input value={universe} onChange={(e) => setUniverse(e.target.value)} style={{ ...inp, width: 280 }} placeholder="逗号分隔" /></label>
        <label>起始<input value={start} onChange={(e) => setStart(e.target.value)} style={inp} /></label>
        <label>结束<input value={end} onChange={(e) => setEnd(e.target.value)} style={inp} /></label>
        <label>分组<input value={quantiles} onChange={(e) => setQuantiles(e.target.value)} style={{ ...inp, width: 70 }} /></label>
        <label>来源
          <select value={source} onChange={(e) => setSource(e.target.value)} style={inp}>
            <option value="synthetic">合成(离线)</option>
            <option value="live">实盘行情</option>
          </select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={neutralized} onChange={(e) => setNeutralized(e.target.checked)} /> 中性化
        </label>
      </div>

      <div style={{ margin: '12px 0' }}>
        <button onClick={run} disabled={loading} style={btn}>{loading ? '回测中…' : '运行因子回测'}</button>
      </div>
      {err ? <div style={{ color: '#dc2626', marginBottom: 10 }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
            <Card label="年化收益" value={(m.ann_return * 100).toFixed(2) + '%'} color={m.ann_return >= 0 ? '#16a34a' : '#dc2626'} />
            <Card label="夏普" value={String(m.sharpe)} color="#374151" />
            <Card label="最大回撤" value={(m.max_drawdown * 100).toFixed(2) + '%'} color="#dc2626" />
            <Card label="IC均值" value={String(m.ic_mean)} color="#374151" />
            <Card label="IR" value={String(m.ir)} color="#374151" />
            <Card label="IC>0占比" value={(m.ic_positive_ratio * 100).toFixed(0) + '%'} color="#2563eb" />
          </div>

          <h3 style={{ fontSize: 14, margin: '6px 0' }}>累计因子收益（多空组合）</h3>
          <Sparkline values={data.cum_return} min={minCr} max={maxCr} color="#2563eb" />
          <p style={{ fontSize: 12, color: '#6b7280' }}>样本数 {m.n} · 中性化 {data.neutralized ? '开' : '关'} · 来源 {data.source}</p>

          <h3 style={{ fontSize: 14, margin: '16px 0 6px' }}>IC 时序（因子值与下期收益秩相关）</h3>
          <Sparkline values={data.ic_series.map((x) => x.ic ?? 0)} min={-1} max={1} color="#7c3aed" zeroLine />
        </div>
      ) : null}
    </div>
  )
}

function Card({ label, value, color }) {
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 16px', textAlign: 'center', minWidth: 110 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color }}>{value}</div>
    </div>
  )
}

function Sparkline({ values, min, max, color, zeroLine }) {
  const W = 1000, H = 160
  if (!values || values.length === 0) return <div style={{ color: '#9ca3af' }}>无数据</div>
  const n = values.length
  const x = (i) => (i / (n - 1)) * W
  const y = (v) => H - ((v - min) / (max - min)) * H
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const baseY = zeroLine ? y(0) : H
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 160, background: '#fafafa', border: '1px solid #eef2f7', borderRadius: 8 }}>
      {zeroLine ? <line x1={0} y1={baseY} x2={W} y2={baseY} stroke="#cbd5e1" strokeDasharray="4 4" /> : null}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
    </svg>
  )
}

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6 }
const btn = { padding: '8px 20px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
