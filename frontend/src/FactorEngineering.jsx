import { useState } from 'react'
import { runOrthogonalize, runOrthogonalizeAll, runFactorTiming, runFactorCrowding, runCombineFactors, runFactorTurnover } from './api.js'

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6 }
const btn = { padding: '8px 16px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
const tabBtn = (active) => ({ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: active ? '#2563eb' : '#fff', color: active ? '#fff' : '#374151', cursor: 'pointer', marginRight: 6 })
const SAMPLE = JSON.stringify({ mom: [0.01, -0.02, 0.015, -0.005, 0.02, -0.01, 0.012, -0.018, 0.009, 0.004], value: [0.008, 0.006, -0.004, 0.01, -0.007, 0.003, 0.005, -0.009, 0.002, 0.006], size: [-0.003, 0.004, 0.006, -0.002, 0.005, -0.004, 0.003, 0.001, -0.005, 0.002] }, null, 0)

function Card({ label, value, color }) {
  return (<div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 14px', textAlign: 'center', minWidth: 110 }}>
    <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div><div style={{ fontSize: 18, fontWeight: 800, color }}>{value}</div></div>)
}
function Sparkline({ values, min, max, color, zeroLine }) {
  const W = 600, H = 120
  if (!values || !values.length) return <div style={{ color: '#9ca3af' }}>无数据</div>
  const n = values.length
  const x = (i) => (i / (n - 1)) * W
  const y = (v) => H - ((v - min) / (max - min || 1)) * H
  const pts = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const baseY = zeroLine ? y(0) : H
  return (<svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 120, background: '#fafafa', border: '1px solid #eef2f7', borderRadius: 8 }}>
    {zeroLine ? <line x1={0} y1={baseY} x2={W} y2={baseY} stroke="#cbd5e1" strokeDasharray="4 4" /> : null}
    <polyline points={pts} fill="none" stroke={color} strokeWidth="2" /></svg>)
}

export default function FactorEngineering() {
  const [tab, setTab] = useState('ortho')
  const [json, setJson] = useState(SAMPLE)
  const [target, setTarget] = useState('mom')
  const [method, setMethod] = useState('equal')
  const [halflife, setHalflife] = useState('21')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const parse = () => {
    try { return JSON.parse(json) }
    catch (e) { throw new Error('JSON 解析失败：' + e.message) }
  }
  const run = async (fn, payload) => {
    setErr(''); setLoading(true)
    try { setData(await fn(payload)) }
    catch (e) { setErr(e?.message || '请求失败') }
    finally { setLoading(false) }
  }

  const tabs = [
    { k: 'ortho', label: 'V37 正交化' },
    { k: 'orthoAll', label: 'V37 全体正交' },
    { k: 'timing', label: 'V38 因子择时' },
    { k: 'crowd', label: 'V39 拥挤度' },
    { k: 'combine', label: 'V40 多因子合成' },
    { k: 'turn', label: 'V41 换手率' },
  ]

  return (
    <div style={{ padding: 20, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>因子工程深化 <span style={{ fontSize: 12, color: '#9ca3af' }}>V37–V41</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>因子正交化去冗余、波动率择时、拥挤度监测、多因子合成、换手率与稳定性。</p>
      <div style={{ marginBottom: 10 }}>{tabs.map((t) => <button key={t.k} style={tabBtn(tab === t.k)} onClick={() => setTab(t.k)}>{t.label}</button>)}</div>
      <button style={{ ...btn, background: '#6b7280', marginBottom: 8 }} onClick={() => setJson(SAMPLE)}>载入示例</button>
      {err ? <div style={{ color: '#dc2626', marginBottom: 8 }}>{err}</div> : null}

      {(tab === 'ortho' || tab === 'orthoAll') && (
        <div>
          {tab === 'ortho' ? <label>目标因子<input value={target} onChange={(e) => setTarget(e.target.value)} style={{ ...inp, width: 140 }} /></label> : null}
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>因子收益序列 JSON（{"{因子名: [收益...]}"}）</label>
          <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={5} style={{ ...inp, width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace' }} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => { const fr = parse(); tab === 'ortho' ? run(runOrthogonalize, { target, factor_returns: fr }) : run(runOrthogonalizeAll, { factor_returns: fr }) }}>{loading ? '计算中…' : '运行'}</button></div>
          {data ? <pre style={{ background: '#f8fafc', padding: 12, borderRadius: 8, fontSize: 12, overflowX: 'auto' }}>{JSON.stringify(data, null, 2)}</pre> : null}
        </div>
      )}

      {tab === 'timing' && (
        <div>
          <label>半衰期<input value={halflife} onChange={(e) => setHalflife(e.target.value)} style={{ ...inp, width: 70 }} /></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>因子收益序列 JSON（单因子 {"{名: [收益...]}"}）</label>
          <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={5} style={{ ...inp, width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace' }} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runFactorTiming, { factor_returns: parse(), halflife: parseInt(halflife, 10) || 21 })}>{loading ? '计算中…' : '运行择时'}</button></div>
          {data ? (<div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="静态夏普" value={data.static_sharpe} color="#374151" />
            <Card label="择时夏普" value={data.timed_sharpe} color={data.timed_sharpe >= data.static_sharpe ? '#16a34a' : '#dc2626'} />
            <Card label="平均权重" value={data.avg_weight} color="#2563eb" /></div>
            <Sparkline values={data.weights} min={Math.min(...data.weights)} max={Math.max(...data.weights)} color="#7c3aed" /></div>) : null}
        </div>
      )}

      {tab === 'crowd' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>因子收益序列 JSON（{"{名: [收益...]}"}）</label>
          <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={5} style={{ ...inp, width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace' }} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runFactorCrowding, { factor_returns: parse() })}>{loading ? '计算中…' : '计算拥挤度'}</button></div>
          {data ? (<div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="拥挤指数" value={data.crowding_index} color={data.crowding_index > 60 ? '#dc2626' : '#16a34a'} />
            <Card label="波动" value={data.volatility} color="#374151" />
            <Card label="最大回撤" value={data.max_drawdown} color="#dc2626" /></div>
            <p style={{ fontSize: 12, color: '#6b7280' }}>{data.interpretation}</p></div>) : null}
        </div>
      )}

      {tab === 'combine' && (
        <div>
          <label>合成方式
            <select value={method} onChange={(e) => setMethod(e.target.value)} style={inp}>
              <option value="equal">等权</option><option value="vol_inverse">逆波动</option><option value="orthogonal">正交</option><option value="custom">自定义</option>
            </select></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>因子收益序列 JSON（多因子 {"{名: [收益...]}"}）</label>
          <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={5} style={{ ...inp, width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace' }} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runCombineFactors, { factor_returns: parse(), method })}>{loading ? '计算中…' : '合成'}</button></div>
          {data ? (<div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="年化" value={(data.metrics.ann_return * 100).toFixed(1) + '%'} color="#16a34a" />
            <Card label="夏普" value={data.metrics.sharpe} color="#374151" />
            <Card label="最大回撤" value={(data.metrics.max_drawdown * 100).toFixed(1) + '%'} color="#dc2626" /></div>
            {data.weights ? <p style={{ fontSize: 12 }}>权重：{Object.entries(data.weights).map(([k, v]) => `${k}=${v}`).join(', ')}</p> : null}</div>) : null}
        </div>
      )}

      {tab === 'turn' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>因子值矩阵 JSON（资产→横截面序列 {"{资产: [值...]}"}）</label>
          <textarea value={json} onChange={(e) => setJson(e.target.value)} rows={5} style={{ ...inp, width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace' }} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runFactorTurnover, { factor_values: parse() })}>{loading ? '计算中…' : '计算换手率'}</button></div>
          {data ? (<div style={{ display: 'flex', gap: 12 }}>
            <Card label="平均换手率" value={data.avg_turnover} color="#374151" />
            <Card label="稳定性" value={data.stability} color="#2563eb" /></div>) : null}
        </div>
      )}
    </div>
  )
}
