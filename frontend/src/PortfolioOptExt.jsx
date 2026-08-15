import { useState } from 'react'
import { runRiskParity, runMaxDiversification, runHRP, runRebalance, runStyleExposure } from './api.js'

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6 }
const btn = { padding: '8px 18px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
const tabBtn = (active) => ({ padding: '6px 12px', borderRadius: 6, border: '1px solid #d1d5db', background: active ? '#2563eb' : '#fff', color: active ? '#fff' : '#374151', cursor: 'pointer', marginRight: 6 })

function Card({ label, value, color }) {
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 14px', textAlign: 'center', minWidth: 110 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 800, color }}>{value}</div>
    </div>
  )
}

// 权重结果表格 + 条形
function WeightResult({ data, title }) {
  if (!data) return null
  const maxW = Math.max(...data.weights.map((w) => Math.abs(w.weight)), 0.0001)
  return (
    <div style={{ marginTop: 14 }}>
      <h3 style={{ fontSize: 14, margin: '6px 0' }}>{title}</h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', maxWidth: 560, fontSize: 13 }}>
        <thead><tr style={{ color: '#6b7280', textAlign: 'left' }}>
          <th style={{ padding: '4px 8px' }}>资产</th><th style={{ padding: '4px 8px' }}>权重</th>
          {data.risk_contributions ? <th style={{ padding: '4px 8px' }}>风险贡献</th> : null}
        </tr></thead>
        <tbody>
          {data.weights.map((w) => (
            <tr key={w.asset}>
              <td style={{ padding: '4px 8px' }}>{w.asset}</td>
              <td style={{ padding: '4px 8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 120, height: 10, background: '#eef2f7', borderRadius: 4 }}>
                    <div style={{ width: `${(Math.abs(w.weight) / maxW) * 100}%`, height: 10, background: w.weight >= 0 ? '#2563eb' : '#dc2626', borderRadius: 4 }} />
                  </div>
                  <span>{(w.weight * 100).toFixed(2)}%</span>
                </div>
              </td>
              {data.risk_contributions ? <td style={{ padding: '4px 8px' }}>{(data.risk_contributions[data.weights.indexOf(w)] * 100).toFixed(2)}%</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
      {data.diversification_ratio != null ? <p style={{ fontSize: 12, color: '#6b7280' }}>分散化比率 DR = {data.diversification_ratio.toFixed(4)}</p> : null}
    </div>
  )
}

export default function PortfolioOptExt() {
  const [tab, setTab] = useState('rp')
  const [universe, setUniverse] = useState('A1,A2,A3,A4,A5')
  const [start, setStart] = useState('2023-01-01')
  const [end, setEnd] = useState('2023-12-31')
  const [seed, setSeed] = useState('12345')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  // 再平衡
  const [curW, setCurW] = useState('A:0.5, B:0.3, C:0.2')
  const [tgtW, setTgtW] = useState('A:0.33, B:0.33, C:0.34')
  const [thr, setThr] = useState('0.0')
  const [baseVal, setBaseVal] = useState('1000000')
  const [reb, setReb] = useState(null)

  // 风格暴露
  const [styleW, setStyleW] = useState('A:0.6, B:0.4')
  const [styleBeta, setStyleBeta] = useState('A: value=1,growth=-0.5,size=0.2,momentum=0.3,vol=-0.1; B: value=-0.4,growth=0.8,size=-0.3,momentum=0.1,vol=0.5')
  const [styleRes, setStyleRes] = useState(null)

  const _optPayload = () => ({
    universe: universe.split(',').map((s) => s.trim()).filter(Boolean),
    start, end, seed: parseInt(seed, 10) || 12345,
  })

  const runOpt = async (fn) => {
    setErr(''); setLoading(true)
    try { setData(await fn(_optPayload())) }
    catch (e) { setErr(e?.message || '请求失败') }
    finally { setLoading(false) }
  }

  const parseWeightStr = (s) => {
    const out = {}
    s.split(',').forEach((p) => {
      const [k, v] = p.split(':')
      if (k && v != null) out[k.trim()] = parseFloat(v.trim())
    })
    return out
  }

  const runRebalance = async () => {
    setErr(''); setLoading(true)
    try {
      setReb(await runRebalance({
        current_weights: parseWeightStr(curW),
        target_weights: parseWeightStr(tgtW),
        threshold: parseFloat(thr) || 0,
        base_value: parseFloat(baseVal) || 1000000,
      }))
    } catch (e) { setErr(e?.message || '请求失败') }
    finally { setLoading(false) }
  }

  const runStyle = async () => {
    setErr(''); setLoading(true)
    try {
      const fb = {}
      styleBeta.split(';').forEach((p) => {
        const [asset, rest] = p.split(':')
        if (!asset || rest == null) return
        const betas = {}
        rest.split(',').forEach((kv) => {
          const [k, v] = kv.split('=')
          if (k && v != null) betas[k.trim()] = parseFloat(v.trim())
        })
        fb[asset.trim()] = betas
      })
      setStyleRes(await runStyleExposure({ weights: parseWeightStr(styleW), factor_betas: fb }))
    } catch (e) { setErr(e?.message || '请求失败') }
    finally { setLoading(false) }
  }

  const tabs = [
    { k: 'rp', label: 'V32 风险平价' },
    { k: 'md', label: 'V33 最大分散化' },
    { k: 'hrp', label: 'V34 层次风险平价' },
    { k: 'reb', label: 'V35 再平衡' },
    { k: 'style', label: 'V36 风格暴露' },
  ]

  return (
    <div style={{ padding: 20, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>组合优化增强 <span style={{ fontSize: 12, color: '#9ca3af' }}>V32–V36</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>风险驱动的组合构建与运营工具：风险平价 / 最大分散化 / 层次风险平价 / 再平衡引擎 / 风格因子暴露归因。</p>

      <div style={{ marginBottom: 12 }}>{tabs.map((t) => <button key={t.k} style={tabBtn(tab === t.k)} onClick={() => setTab(t.k)}>{t.label}</button>)}</div>
      {err ? <div style={{ color: '#dc2626', marginBottom: 10 }}>{err}</div> : null}

      {(tab === 'rp' || tab === 'md' || tab === 'hrp') && (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <label>股票池<input value={universe} onChange={(e) => setUniverse(e.target.value)} style={{ ...inp, width: 240 }} placeholder="逗号分隔" /></label>
            <label>起始<input value={start} onChange={(e) => setStart(e.target.value)} style={inp} /></label>
            <label>结束<input value={end} onChange={(e) => setEnd(e.target.value)} style={inp} /></label>
            <label>种子<input value={seed} onChange={(e) => setSeed(e.target.value)} style={{ ...inp, width: 80 }} /></label>
            <button style={btn} disabled={loading} onClick={() => runOpt(tab === 'rp' ? runRiskParity : tab === 'md' ? runMaxDiversification : runHRP)}>{loading ? '计算中…' : '计算权重'}</button>
          </div>
          <WeightResult data={data} title={tab === 'rp' ? '风险平价（ERC）权重' : tab === 'md' ? '最大分散化权重' : '层次风险平价（HRP）权重'} />
        </div>
      )}

      {tab === 'reb' && (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <label>当前权重<input value={curW} onChange={(e) => setCurW(e.target.value)} style={{ ...inp, width: 220 }} placeholder="A:0.5, B:0.3" /></label>
            <label>目标权重<input value={tgtW} onChange={(e) => setTgtW(e.target.value)} style={{ ...inp, width: 220 }} placeholder="A:0.33, B:0.33" /></label>
            <label>阈值<input value={thr} onChange={(e) => setThr(e.target.value)} style={{ ...inp, width: 60 }} /></label>
            <label>基准市值<input value={baseVal} onChange={(e) => setBaseVal(e.target.value)} style={{ ...inp, width: 100 }} /></label>
            <button style={btn} disabled={loading} onClick={runRebalance}>{loading ? '计算中…' : '生成调仓单'}</button>
          </div>
          {reb ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', gap: 12, marginBottom: 10 }}>
                <Card label="越界资产" value={reb.n_breached} color="#dc2626" />
                <Card label="总买入" value={'¥' + reb.summary.total_buy.toLocaleString()} color="#16a34a" />
                <Card label="总卖出" value={'¥' + reb.summary.total_sell.toLocaleString()} color="#dc2626" />
                <Card label="净现金" value={'¥' + reb.summary.net_cash.toLocaleString()} color="#374151" />
              </div>
              <table style={{ borderCollapse: 'collapse', width: '100%', maxWidth: 620, fontSize: 13 }}>
                <thead><tr style={{ color: '#6b7280', textAlign: 'left' }}>
                  <th style={{ padding: '4px 8px' }}>资产</th><th style={{ padding: '4px 8px' }}>方向</th><th style={{ padding: '4px 8px' }}>当前→目标</th><th style={{ padding: '4px 8px' }}>金额</th>
                </tr></thead>
                <tbody>
                  {reb.trades.map((t) => (
                    <tr key={t.asset}>
                      <td style={{ padding: '4px 8px' }}>{t.asset}</td>
                      <td style={{ padding: '4px 8px', color: t.side === 'buy' ? '#16a34a' : '#dc2626' }}>{t.side === 'buy' ? '买入' : '卖出'}</td>
                      <td style={{ padding: '4px 8px' }}>{(t.current_weight * 100).toFixed(1)}% → {(t.target_weight * 100).toFixed(1)}%</td>
                      <td style={{ padding: '4px 8px' }}>¥{Math.abs(t.trade_value).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      )}

      {tab === 'style' && (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <label>权重<input value={styleW} onChange={(e) => setStyleW(e.target.value)} style={{ ...inp, width: 200 }} placeholder="A:0.6, B:0.4" /></label>
            <button style={btn} disabled={loading} onClick={runStyle}>{loading ? '计算中…' : '计算暴露'}</button>
          </div>
          <label style={{ display: 'block', marginTop: 8, fontSize: 12, color: '#6b7280' }}>因子暴露 beta（资产: 因子=值, 用 ; 分隔）</label>
          <textarea value={styleBeta} onChange={(e) => setStyleBeta(e.target.value)} rows={3} style={{ ...inp, width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace' }} />
          {styleRes ? (
            <div style={{ marginTop: 12 }}>
              <h3 style={{ fontSize: 14, margin: '6px 0' }}>组合风格因子暴露</h3>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                {styleRes.factors.map((f) => <Card key={f} label={f} value={styleRes.portfolio_exposure[f].toFixed(3)} color={styleRes.portfolio_exposure[f] >= 0 ? '#2563eb' : '#dc2626'} />)}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
