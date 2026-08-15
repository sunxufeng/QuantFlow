import { useState } from 'react'
import { runPairsCoint, runPairsBacktest, runOptionPrice, runOptionGreeks, runOptionIV, runGridBacktest, runDcaBacktest, runMultiTrend } from './api.js'

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6 }
const btn = { padding: '8px 16px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
const tabBtn = (active) => ({ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: active ? '#2563eb' : '#fff', color: active ? '#fff' : '#374151', cursor: 'pointer', marginRight: 6 })
const S_X = JSON.stringify([100, 101, 103, 102, 105, 107, 106, 109, 111, 110, 113, 115, 114, 117, 119, 118, 121, 123, 122, 125].map((v, i) => v + (i % 2 ? 1 : -1)), null, 0)
const S_Y = JSON.stringify([80, 81.5, 83, 82, 85, 87, 86, 89, 91, 90, 93, 95, 94, 97, 99, 98, 101, 103, 102, 105].map((v, i) => v + (i % 2 ? 0.8 : -0.8)), null, 0)
const S_PRICES = JSON.stringify([100, 102, 99, 103, 101, 105, 98, 106, 104, 108, 103, 110, 107, 112, 109, 114, 111, 116, 113, 118], null, 0)
const S_DATES = JSON.stringify(Array.from({ length: 20 }, (_, i) => `2023-${1 + i / 6 | 0}-${1 + i}`))
const S_RMAT = JSON.stringify([[0.01, 0.002, -0.004], [0.012, 0.001, -0.003], [0.009, 0.003, -0.005], [0.011, 0.002, -0.002], [0.013, 0.0, -0.004]], null, 0)
const S_ASSETS = JSON.stringify(['A', 'B', 'C'])

function Card({ label, value, color }) {
  return (<div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 14px', textAlign: 'center', minWidth: 100 }}>
    <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div><div style={{ fontSize: 18, fontWeight: 800, color }}>{value}</div></div>)
}

export default function StrategyExt() {
  const [tab, setTab] = useState('pairs')
  const [x, setX] = useState(S_X)
  const [y, setY] = useState(S_Y)
  const [prices, setPrices] = useState(S_PRICES)
  const [dates, setDates] = useState(S_DATES)
  const [rmat, setRmat] = useState(S_RMAT)
  const [assets, setAssets] = useState(S_ASSETS)
  const [S, setS] = useState('100'); const [K, setK] = useState('100'); const [T, setT] = useState('1.0'); const [r, setR] = useState('0.02'); const [sigma, setSigma] = useState('0.2'); const [opt, setOpt] = useState('call'); const [mktPrice, setMktPrice] = useState('10')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const ta = { width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace', padding: 6, border: '1px solid #d1d5db', borderRadius: 6 }
  const parse = (s) => { try { return JSON.parse(s) } catch (e) { throw new Error('JSON 解析失败：' + e.message) } }
  const run = async (fn, payload) => { setErr(''); setLoading(true); try { setData(await fn(payload)) } catch (e) { setErr(e?.message || '请求失败') } finally { setLoading(false) } }

  const tabs = [
    { k: 'pairs', label: 'V52 配对协整' }, { k: 'option', label: 'V53 期权Greeks' }, { k: 'grid', label: 'V54 网格' },
    { k: 'dca', label: 'V55 定投' }, { k: 'trend', label: 'V56 多资产趋势' },
  ]

  return (
    <div style={{ padding: 20, maxWidth: 1100 }}>
      <h2 style={{ margin: '0 0 4px' }}>策略库扩展 <span style={{ fontSize: 12, color: '#9ca3af' }}>V52–V56</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>协整配对交易、期权定价与 Greeks、网格交易、定投(DCA)、多资产趋势跟随。</p>
      <div style={{ marginBottom: 10 }}>{tabs.map((t) => <button key={t.k} style={tabBtn(tab === t.k)} onClick={() => setTab(t.k)}>{t.label}</button>)}</div>
      <button style={{ ...btn, background: '#6b7280', marginBottom: 8 }} onClick={() => { setX(S_X); setY(S_Y); setPrices(S_PRICES); setDates(S_DATES); setRmat(S_RMAT); setAssets(S_ASSETS) }}>载入示例</button>
      {err ? <div style={{ color: '#dc2626', marginBottom: 8 }}>{err}</div> : null}

      {tab === 'pairs' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>价格序列 X JSON</label>
          <textarea value={x} onChange={(e) => setX(e.target.value)} rows={3} style={ta} />
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>价格序列 Y JSON</label>
          <textarea value={y} onChange={(e) => setY(e.target.value)} rows={3} style={ta} />
          <div style={{ margin: '10px 0' }}>
            <button style={btn} disabled={loading} onClick={() => run(runPairsCoint, { x: parse(x), y: parse(y) })}>{loading ? '检验中…' : '协整检验'}</button>{' '}
            <button style={{ ...btn, background: '#16a34a' }} disabled={loading} onClick={() => run(runPairsBacktest, { x: parse(x), y: parse(y), window: 6 })}>配对回测</button>
          </div>
          {data ? <div><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <Card label="对冲比" value={data.hedge_ratio ?? '-'} color="#374151" /><Card label="ADF" value={data.adf_stat ?? '-'} color="#374151" /><Card label="协整" value={data.is_cointegrated ? '是' : '否'} color={data.is_cointegrated ? '#16a34a' : '#dc2626'} /><Card label="半衰期" value={data.half_life ?? '-'} color="#2563eb" />
            {data.total_pnl !== undefined ? <Card label="累计PnL" value={data.total_pnl} color={data.total_pnl >= 0 ? '#16a34a' : '#dc2626'} /> : null}
            {data.total_pnl !== undefined ? <Card label="交易数" value={data.n_trades} color="#374151" /> : null}
            {data.sharpe !== undefined ? <Card label="夏普" value={data.sharpe} color="#2563eb" /> : null}
          </div></div> : null}
        </div>
      )}

      {tab === 'option' && (
        <div>
          <label>S<input value={S} onChange={(e) => setS(e.target.value)} style={{ ...inp, width: 70 }} /></label>
          <label>K<input value={K} onChange={(e) => setK(e.target.value)} style={{ ...inp, width: 70 }} /></label>
          <label>T(年)<input value={T} onChange={(e) => setT(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label>r<input value={r} onChange={(e) => setR(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label>σ<input value={sigma} onChange={(e) => setSigma(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label>类型<select value={opt} onChange={(e) => setOpt(e.target.value)} style={inp}><option value="call">call</option><option value="put">put</option></select></label>
          <div style={{ margin: '10px 0' }}>
            <button style={btn} disabled={loading} onClick={() => run(runOptionPrice, { S: +S, K: +K, T: +T, r: +r, sigma: +sigma, option: opt })}>BS 价格</button>{' '}
            <button style={{ ...btn, background: '#16a34a' }} disabled={loading} onClick={() => run(runOptionGreeks, { S: +S, K: +K, T: +T, r: +r, sigma: +sigma, option: opt })}>Greeks</button>{' '}
            <button style={{ ...btn, background: '#7c3aed' }} disabled={loading} onClick={() => run(runOptionIV, { price: +mktPrice, S: +S, K: +K, T: +T, r: +r, option: opt })}>隐含波动率</button>
          </div>
          <label style={{ fontSize: 12, color: '#6b7280' }}>市价（算 IV 用）<input value={mktPrice} onChange={(e) => setMktPrice(e.target.value)} style={{ ...inp, width: 70 }} /></label>
          {data ? <div><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {data.price !== undefined ? <Card label="BS 价格" value={data.price} color="#374151" /> : null}
            {data.implied_vol !== undefined ? <Card label="隐含波动率" value={data.implied_vol} color="#7c3aed" /> : null}
            {data.delta !== undefined ? <><Card label="Delta" value={data.delta} color="#16a34a" /><Card label="Gamma" value={data.gamma} color="#2563eb" /><Card label="Vega" value={data.vega} color="#2563eb" /><Card label="Theta" value={data.theta} color="#ca8a04" /><Card label="Rho" value={data.rho} color="#374151" /></> : null}
          </div></div> : null}
        </div>
      )}

      {tab === 'grid' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>价格序列 JSON</label>
          <textarea value={prices} onChange={(e) => setPrices(e.target.value)} rows={3} style={ta} />
          <label>下界<input value="90" id="glo" style={{ ...inp, width: 60 }} /></label>
          <label>上界<input value="120" id="ghi" style={{ ...inp, width: 60 }} /></label>
          <label>网格数<input value="10" id="gn" style={{ ...inp, width: 50 }} /></label>
          <div style={{ margin: '10px 0' }}>
            <button style={btn} disabled={loading} onClick={() => run(runGridBacktest, { prices: parse(prices), lower: +document.getElementById('glo').value, upper: +document.getElementById('ghi').value, n_grid: +document.getElementById('gn').value, lot: 1000, initial_cash: 1000000 })}>{loading ? '回测中…' : '网格回测'}</button>
          </div>
          {data ? <div><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <Card label="交易数" value={data.n_trades} color="#374151" /><Card label="收益" value={(data.total_return * 100).toFixed(1) + '%'} color={data.total_return >= 0 ? '#16a34a' : '#dc2626'} /><Card label="最大回撤" value={(data.max_drawdown * 100).toFixed(1) + '%'} color="#dc2626" /><Card label="期末权益" value={'¥' + data.final_equity.toLocaleString()} color="#2563eb" />
          </div><EquityChart curve={data.equity_curve} /></div> : null}
        </div>
      )}

      {tab === 'dca' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>价格序列 JSON</label>
          <textarea value={prices} onChange={(e) => setPrices(e.target.value)} rows={3} style={ta} />
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>日期 JSON（["2023-01-01",...]）</label>
          <textarea value={dates} onChange={(e) => setDates(e.target.value)} rows={2} style={ta} />
          <label>每期投入<input value="10000" id="dinv" style={{ ...inp, width: 80 }} /></label>
          <label>频率<select id="dfreq" style={inp}><option value="M">月</option><option value="W">周</option><option value="D">日</option></select></label>
          <div style={{ margin: '10px 0' }}>
            <button style={btn} disabled={loading} onClick={() => run(runDcaBacktest, { prices: parse(prices), dates: parse(dates), periodic_investment: +document.getElementById('dinv').value, freq: document.getElementById('dfreq').value })}>{loading ? '回测中…' : '定投回测'}</button>
          </div>
          {data ? <div><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <Card label="DCA收益" value={(data.dca_return * 100).toFixed(1) + '%'} color={data.dca_return >= 0 ? '#16a34a' : '#dc2626'} /><Card label="一次性收益" value={(data.lump_return * 100).toFixed(1) + '%'} color={data.lump_return >= 0 ? '#16a34a' : '#dc2626'} /><Card label="DCA-一次性" value={'¥' + data.dca_minus_lump.toLocaleString()} color="#2563eb" /><Card label="平均成本" value={data.dca_avg_cost} color="#374151" /><Card label="期数" value={data.n_periods} color="#374151" />
          </div></div> : null}
        </div>
      )}

      {tab === 'trend' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益矩阵 JSON（[[r_a1,r_b1,...],[...]]）</label>
          <textarea value={rmat} onChange={(e) => setRmat(e.target.value)} rows={3} style={ta} />
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>资产列表 JSON</label>
          <textarea value={assets} onChange={(e) => setAssets(e.target.value)} rows={2} style={ta} />
          <label>快均线<input value="3" id="fast" style={{ ...inp, width: 50 }} /></label>
          <label>慢均线<input value="8" id="slow" style={{ ...inp, width: 50 }} /></label>
          <label>再平衡<select id="mreb" style={inp}><option value="W">周</option><option value="M">月</option></select></label>
          <div style={{ margin: '10px 0' }}>
            <button style={btn} disabled={loading} onClick={() => run(runMultiTrend, { returns: parse(rmat), assets: parse(assets), fast: +document.getElementById('fast').value, slow: +document.getElementById('slow').value, rebalance: document.getElementById('mreb').value })}>{loading ? '回测中…' : '趋势跟随回测'}</button>
          </div>
          {data ? <div><div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <Card label="策略收益" value={(data.total_return * 100).toFixed(1) + '%'} color="#16a34a" /><Card label="基准收益" value={(data.benchmark_total_return * 100).toFixed(1) + '%'} color="#374151" /><Card label="超额" value={(data.excess_return * 100).toFixed(1) + '%'} color={data.excess_return >= 0 ? '#16a34a' : '#dc2626'} /><Card label="夏普" value={data.sharpe} color="#2563eb" /><Card label="最大回撤" value={(data.max_drawdown * 100).toFixed(1) + '%'} color="#dc2626" /><Card label="再平衡" value={data.n_rebalances} color="#374151" />
          </div>
          <p style={{ fontSize: 12, color: '#6b7280' }}>最近看多：{data.weight_history?.slice(-1)[0]?.longs?.join(', ') || '无'}</p>
          </div> : null}
        </div>
      )}
    </div>
  )
}

function EquityChart({ curve }) {
  if (!curve || curve.length < 2) return null
  const w = 600, h = 120
  const mn = Math.min(...curve), mx = Math.max(...curve)
  const X = (i) => (i / (curve.length - 1)) * w
  const Y = (v) => h - ((v - mn) / (mx - mn || 1)) * h
  const path = curve.map((v, i) => `${i === 0 ? 'M' : 'L'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')
  return (<svg width={w} height={h} style={{ maxWidth: '100%', border: '1px solid #eee', borderRadius: 6 }}>
    <path d={path} fill="none" stroke="#2563eb" strokeWidth={1.5} />
  </svg>)
}
