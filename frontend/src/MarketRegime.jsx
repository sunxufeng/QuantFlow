import { useState } from 'react'
import { runRegime, runVolForecast, runSectorRotation, runCorrelationNetwork, runEtfRotation } from './api.js'

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6 }
const btn = { padding: '8px 16px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
const tabBtn = (active) => ({ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: active ? '#2563eb' : '#fff', color: active ? '#fff' : '#374151', cursor: 'pointer', marginRight: 6 })
const S_RET = JSON.stringify([0.012, -0.008, 0.015, -0.02, 0.005, -0.011, 0.018, -0.006, 0.009, -0.014, 0.022, -0.017, 0.003, 0.01, -0.019, 0.013, -0.009, 0.006, -0.016, 0.011], null, 0)
const S_SECTORS = JSON.stringify({ 科技: [0.01, 0.012, -0.004, 0.015, 0.008], 金融: [0.003, 0.002, -0.001, 0.004, 0.001], 能源: [-0.008, -0.005, -0.012, -0.006, -0.009], 消费: [0.006, 0.004, 0.002, 0.007, 0.005] }, null, 0)
const S_MATRIX = JSON.stringify([[0.01, 0.009, -0.002, 0.001], [0.008, 0.01, -0.001, 0.002], [-0.003, -0.001, 0.011, 0.009], [0.001, 0.002, 0.008, 0.01]], null, 0)
const S_ASSETS = JSON.stringify(['A', 'B', 'C', 'D'])
const S_ETF = JSON.stringify([[0.01, 0.002, -0.004, 0.001], [0.012, 0.001, -0.003, 0.0], [0.009, 0.003, -0.005, 0.002], [0.011, 0.002, -0.002, 0.001], [0.013, 0.0, -0.004, 0.003]], null, 0)

function Card({ label, value, color }) {
  return (<div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 14px', textAlign: 'center', minWidth: 110 }}>
    <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div><div style={{ fontSize: 18, fontWeight: 800, color }}>{value}</div></div>)
}

const REGIME_COLOR = { bull: '#16a34a', volatile_up: '#ca8a04', sideways: '#6b7280', volatile_down: '#ea580c', bear: '#dc2626' }

export default function MarketRegime() {
  const [tab, setTab] = useState('regime')
  const [ret, setRet] = useState(S_RET)
  const [sectors, setSectors] = useState(S_SECTORS)
  const [matrix, setMatrix] = useState(S_MATRIX)
  const [assets, setAssets] = useState(S_ASSETS)
  const [etf, setEtf] = useState(S_ETF)
  const [shortMa, setShortMa] = useState('20')
  const [longMa, setLongMa] = useState('60')
  const [volMethod, setVolMethod] = useState('ewma')
  const [horizon, setHorizon] = useState('21')
  const [window, setWindow] = useState('40')
  const [lookback, setLookback] = useState('3')
  const [holdTop, setHoldTop] = useState('2')
  const [rebalance, setRebalance] = useState('W')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const ta = { width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace', padding: 6, border: '1px solid #d1d5db', borderRadius: 6 }
  const parse = (s) => { try { return JSON.parse(s) } catch (e) { throw new Error('JSON 解析失败：' + e.message) } }
  const run = async (fn, payload) => { setErr(''); setLoading(true); try { setData(await fn(payload)) } catch (e) { setErr(e?.message || '请求失败') } finally { setLoading(false) } }

  const tabs = [
    { k: 'regime', label: 'V47 市场状态' }, { k: 'vol', label: 'V48 波动率预测' }, { k: 'sector', label: 'V49 板块轮动' },
    { k: 'corr', label: 'V50 相关性网络' }, { k: 'etf', label: 'V51 ETF轮动' },
  ]

  return (
    <div style={{ padding: 20, maxWidth: 1100 }}>
      <h2 style={{ margin: '0 0 4px' }}>市场状态与择时 <span style={{ fontSize: 12, color: '#9ca3af' }}>V47–V51</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>市场状态检测、波动率预测(EWMA/GARCH)、板块轮动信号、相关性聚类网络、ETF 动量轮动回测。</p>
      <div style={{ marginBottom: 10 }}>{tabs.map((t) => <button key={t.k} style={tabBtn(tab === t.k)} onClick={() => setTab(t.k)}>{t.label}</button>)}</div>
      <button style={{ ...btn, background: '#6b7280', marginBottom: 8 }} onClick={() => { setRet(S_RET); setSectors(S_SECTORS); setMatrix(S_MATRIX); setAssets(S_ASSETS); setEtf(S_ETF) }}>载入示例</button>
      {err ? <div style={{ color: '#dc2626', marginBottom: 8 }}>{err}</div> : null}

      {tab === 'regime' && (
        <div>
          <label>短均线<input value={shortMa} onChange={(e) => setShortMa(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label>长均线<input value={longMa} onChange={(e) => setLongMa(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益序列 JSON（[r1, r2, ...]）</label>
          <textarea value={ret} onChange={(e) => setRet(e.target.value)} rows={4} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runRegime, { returns: parse(ret), short_ma: parseInt(shortMa), long_ma: parseInt(longMa) })}>{loading ? '计算中…' : '检测状态'}</button></div>
          {data ? <div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="当前状态" value={data.regime_cn} color={REGIME_COLOR[data.regime]} /><Card label="状态评分" value={data.score} color="#374151" /><Card label="趋势差" value={(data.trend_spread * 100).toFixed(1) + '%'} color="#374151" /><Card label="年化波动" value={(data.ann_vol * 100).toFixed(1) + '%'} color="#374151" /></div>
            <p style={{ fontSize: 12, color: '#6b7280' }}>状态分布：{Object.entries(data.regime_counts).map(([k, v]) => `${k} ${v}`).join(' / ')}</p>
            <RegimeBars series={data.series} /></div> : null}
        </div>
      )}

      {tab === 'vol' && (
        <div>
          <label>方法<select value={volMethod} onChange={(e) => setVolMethod(e.target.value)} style={inp}><option value="ewma">EWMA</option><option value="garch">GARCH(1,1)</option></select></label>
          <label>预测步长<input value={horizon} onChange={(e) => setHorizon(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益序列 JSON</label>
          <textarea value={ret} onChange={(e) => setRet(e.target.value)} rows={4} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runVolForecast, { returns: parse(ret), method: volMethod, horizon: parseInt(horizon) })}>{loading ? '计算中…' : '预测波动率'}</button></div>
          {data ? <div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="最新年化波动" value={(data.latest_annualized_vol * 100).toFixed(1) + '%'} color="#374151" /><Card label="长期波动" value={(data.long_run_annualized_vol * 100).toFixed(1) + '%'} color="#2563eb" /></div>
            <VolBars forecasts={data.forecasts} /></div> : null}
        </div>
      )}

      {tab === 'sector' && (
        <div>
          <label>动量窗口<input value={window} onChange={(e) => setWindow(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>板块收益 JSON（{"{板块:[r,...]}"}）</label>
          <textarea value={sectors} onChange={(e) => setSectors(e.target.value)} rows={5} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runSectorRotation, { sector_returns: parse(sectors), window: parseInt(window) })}>{loading ? '计算中…' : '生成轮动信号' }</button></div>
          {data ? <div><table style={{ borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr><th style={th}>排名</th><th style={th}>板块</th><th style={th}>动量</th><th style={th}>信号</th></tr></thead>
            <tbody>{data.ranked.map((r) => <tr key={r.sector}><td style={td}>{r.rank}</td><td style={td}>{r.sector}</td><td style={td}>{(r.momentum * 100).toFixed(1)}%</td><td style={{ ...td, color: r.signal === 'overweight' ? '#16a34a' : r.signal === 'underweight' ? '#dc2626' : '#6b7280' }}>{r.signal}</td></tr>)}</tbody>
          </table></div> : null}
        </div>
      )}

      {tab === 'corr' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益矩阵 JSON（[[r_a1,r_b1,...],[...]]）</label>
          <textarea value={matrix} onChange={(e) => setMatrix(e.target.value)} rows={4} style={ta} />
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>资产列表 JSON（["A","B",...]）</label>
          <textarea value={assets} onChange={(e) => setAssets(e.target.value)} rows={2} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runCorrelationNetwork, { returns: parse(matrix), assets: parse(assets) })}>{loading ? '计算中…' : '聚类网络' }</button></div>
          {data ? <div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="聚类数" value={data.n_clusters} color="#374151" /><Card label="簇内相关" value={data.avg_intra_cluster_corr} color="#16a34a" /><Card label="簇间相关" value={data.avg_inter_cluster_corr} color="#ea580c" /></div>
            <CorrHeatmap assets={data.assets} corr={data.correlation} cluster={data.asset_cluster} /></div> : null}
        </div>
      )}

      {tab === 'etf' && (
        <div>
          <label>回看期<input value={lookback} onChange={(e) => setLookback(e.target.value)} style={{ ...inp, width: 50 }} /></label>
          <label>持有数<input value={holdTop} onChange={(e) => setHoldTop(e.target.value)} style={{ ...inp, width: 50 }} /></label>
          <label>再平衡<select value={rebalance} onChange={(e) => setRebalance(e.target.value)} style={inp}><option value="W">周</option><option value="M">月</option><option value="D">日</option></select></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益矩阵 JSON（[[r_a1,r_b1,...],[...]]）</label>
          <textarea value={etf} onChange={(e) => setEtf(e.target.value)} rows={4} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runEtfRotation, { returns: parse(etf), assets: parse(assets), lookback: parseInt(lookback) * 5, hold_top: parseInt(holdTop), rebalance })}>{loading ? '计算中…' : '回测轮动' }</button></div>
          {data ? <div><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <Card label="策略收益" value={(data.total_return * 100).toFixed(1) + '%'} color="#16a34a" /><Card label="基准收益" value={(data.benchmark_total_return * 100).toFixed(1) + '%'} color="#374151" /><Card label="超额" value={(data.excess_return * 100).toFixed(1) + '%'} color={data.excess_return >= 0 ? '#16a34a' : '#dc2626'} /><Card label="年化" value={(data.annual_return * 100).toFixed(1) + '%'} color="#374151" /><Card label="夏普" value={data.sharpe} color="#2563eb" /><Card label="最大回撤" value={(data.max_drawdown * 100).toFixed(1) + '%'} color="#dc2626" /><Card label="胜率" value={(data.win_rate * 100).toFixed(0) + '%'} color="#374151" /></div>
          </div> : null}
        </div>
      )}
    </div>
  )
}

const th = { border: '1px solid #e5e7eb', padding: '4px 10px', background: '#f9fafb' }
const td = { border: '1px solid #e5e7eb', padding: '4px 10px' }

function RegimeBars({ series }) {
  const last = series.slice(-60)
  const colors = last.map((s) => REGIME_COLOR[s.regime])
  const w = 8
  return (<svg width={last.length * w} height={90} style={{ maxWidth: '100%' }}>
    {last.map((s, i) => <rect key={i} x={i * w} y={45 - s.score * 40} width={w - 1} height={Math.abs(s.score * 40)} fill={colors[i]} />)}
  </svg>)
}

function VolBars({ forecasts }) {
  const vals = forecasts.map((f) => f.annualized_vol)
  const max = Math.max(...vals, 0.0001)
  const w = 16
  return (<svg width={forecasts.length * w} height={90} style={{ maxWidth: '100%' }}>
    {forecasts.map((f, i) => <rect key={i} x={i * w} y={90 - (f.annualized_vol / max) * 80} width={w - 2} height={(f.annualized_vol / max) * 80} fill="#2563eb" />)}
    <text x={2} y={84} fontSize={9} fill="#6b7280">h1</text>
    <text x={(forecasts.length - 3) * w} y={84} fontSize={9} fill="#6b7280">h{forecasts.length}</text>
  </svg>)
}

function CorrHeatmap({ assets, corr, cluster }) {
  const n = assets.length
  const cell = 42
  const colors = ['#fee2e2', '#ffedd5', '#fef9c3', '#dcfce7', '#bbf7d0']
  const pick = (v) => colors[Math.min(colors.length - 1, Math.max(0, Math.round((v + 1) / 2 * (colors.length - 1))))]
  return (<div>
    <svg width={(n + 1) * cell} height={(n + 1) * cell} style={{ maxWidth: '100%' }}>
      {assets.map((a, i) => <text key={'r' + a} x={2} y={(i + 1) * cell + cell / 2} fontSize={10}>{a}</text>)}
      {assets.map((a, j) => <text key={'c' + a} x={(j + 1) * cell + cell / 2} y={cell / 2} fontSize={10} textAnchor="middle">{a}</text>)}
      {corr.map((row, i) => row.map((v, j) => (
        <g key={i + '_' + j}>
          <rect x={(j + 1) * cell} y={(i + 1) * cell} width={cell - 1} height={cell - 1} fill={pick(v)} stroke={cluster[assets[i]] === cluster[assets[j]] ? '#111827' : '#e5e7eb'} strokeWidth={cluster[assets[i]] === cluster[assets[j]] ? 1.5 : 0.5} />
          <text x={(j + 1) * cell + cell / 2} y={(i + 1) * cell + cell / 2} fontSize={9} textAnchor="middle" fill="#374151">{v.toFixed(2)}</text>
        </g>
      )))}
    </svg>
    <p style={{ fontSize: 12, color: '#6b7280' }}>黑边 = 同簇；颜色越绿相关性越高。</p>
  </div>)
}
