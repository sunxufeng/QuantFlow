import { useState } from 'react'
import { runVarCvar, runVarBacktest, runDrawdown, runTailRisk, runLiquidity, runConcentration } from './api.js'

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6 }
const btn = { padding: '8px 16px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
const tabBtn = (active) => ({ padding: '6px 10px', borderRadius: 6, border: '1px solid #d1d5db', background: active ? '#2563eb' : '#fff', color: active ? '#fff' : '#374151', cursor: 'pointer', marginRight: 6 })
const S_RET = JSON.stringify([0.012, -0.008, 0.015, -0.02, 0.005, -0.011, 0.018, -0.006, 0.009, -0.014, 0.022, -0.017, 0.003, 0.01, -0.019, 0.013, -0.009, 0.006, -0.016, 0.011], null, 0)

function Card({ label, value, color }) {
  return (<div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 14px', textAlign: 'center', minWidth: 110 }}>
    <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div><div style={{ fontSize: 18, fontWeight: 800, color }}>{value}</div></div>)
}

export default function RiskAnalytics() {
  const [tab, setTab] = useState('var')
  const [ret, setRet] = useState(S_RET)
  const [retB, setRetB] = useState(S_RET)
  const [conf, setConf] = useState('0.95')
  const [method, setMethod] = useState('historical')
  const [alpha, setAlpha] = useState('0.05')
  const [positions, setPositions] = useState(JSON.stringify({ A: { quantity: 100000, price: 10 }, B: { quantity: 50000, price: 20 } }, null, 0))
  const [adv, setAdv] = useState(JSON.stringify({ A: 1000000, A_vol: 200000, B: 2000000, B_vol: 300000 }, null, 0))
  const [weights, setWeights] = useState(JSON.stringify({ A: 0.4, B: 0.3, C: 0.2, D: 0.1 }, null, 0))
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const parse = (s) => { try { return JSON.parse(s) } catch (e) { throw new Error('JSON 解析失败：' + e.message) } }
  const run = async (fn, payload) => { setErr(''); setLoading(true); try { setData(await fn(payload)) } catch (e) { setErr(e?.message || '请求失败') } finally { setLoading(false) } }

  const tabs = [
    { k: 'var', label: 'V42 VaR/CVaR' }, { k: 'varbt', label: 'V42 VaR回测' }, { k: 'dd', label: 'V43 回撤归因' },
    { k: 'tail', label: 'V44 尾部相关' }, { k: 'liq', label: 'V45 流动性' }, { k: 'conc', label: 'V46 集中度' },
  ]
  const ta = { width: '100%', maxWidth: 640, marginTop: 4, fontFamily: 'monospace', padding: 6, border: '1px solid #d1d5db', borderRadius: 6 }

  return (
    <div style={{ padding: 20, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>风险分析 <span style={{ fontSize: 12, color: '#9ca3af' }}>V42–V46</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>VaR/CVaR 与回测、回撤归因、尾部相关、流动性冲击、持仓集中度。</p>
      <div style={{ marginBottom: 10 }}>{tabs.map((t) => <button key={t.k} style={tabBtn(tab === t.k)} onClick={() => setTab(t.k)}>{t.label}</button>)}</div>
      <button style={{ ...btn, background: '#6b7280', marginBottom: 8 }} onClick={() => { setRet(S_RET); setRetB(S_RET) }}>载入示例</button>
      {err ? <div style={{ color: '#dc2626', marginBottom: 8 }}>{err}</div> : null}

      {(tab === 'var' || tab === 'varbt' || tab === 'dd') && (
        <div>
          <label>置信度<input value={conf} onChange={(e) => setConf(e.target.value)} style={{ ...inp, width: 70 }} /></label>
          {tab === 'var' ? <label>方法<select value={method} onChange={(e) => setMethod(e.target.value)} style={inp}><option value="historical">历史</option><option value="parametric">参数</option><option value="montecarlo">蒙特卡洛</option></select></label> : null}
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益序列 JSON（[r1, r2, ...]）</label>
          <textarea value={ret} onChange={(e) => setRet(e.target.value)} rows={4} style={ta} />
          <div style={{ margin: '10px 0' }}>
            <button style={btn} disabled={loading} onClick={() => { const r = parse(ret); tab === 'var' ? run(runVarCvar, { returns: r, confidence: parseFloat(conf), method }) : tab === 'varbt' ? run(runVarBacktest, { returns: r, confidence: parseFloat(conf), method }) : run(runDrawdown, { returns: r }) }}>{loading ? '计算中…' : '运行'}</button>
          </div>
          {data && tab === 'var' ? <div style={{ display: 'flex', gap: 12 }}>
            <Card label="VaR" value={(data.var_pct).toFixed(2) + '%'} color="#dc2626" /><Card label="CVaR" value={(data.cvar_pct).toFixed(2) + '%'} color="#dc2626" /><Card label="方法" value={data.method} color="#374151" /></div> : null}
          {data && tab === 'varbt' ? <div style={{ display: 'flex', gap: 12 }}>
            <Card label="击穿数" value={data.breaches} color="#dc2626" /><Card label="期望" value={data.expected_breaches} color="#374151" /><Card label="覆盖" value={data.coverage} color="#2563eb" /><Card label="通过" value={data.passed ? '是' : '否'} color={data.passed ? '#16a34a' : '#dc2626'} /></div> : null}
          {data && tab === 'dd' ? <div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="最大回撤" value={(data.max_drawdown * 100).toFixed(2) + '%'} color="#dc2626" /><Card label="区间数" value={data.n_episodes} color="#374151" /><Card label="当前回撤" value={(data.current_drawdown * 100).toFixed(2) + '%'} color="#374151" /></div>
            {data.worst_episodes?.map((e, i) => <p key={i} style={{ fontSize: 12 }}>最差段#{i + 1}：深度 {(e.depth * 100).toFixed(1)}% · 持续 {e.duration} 期 · 最差单日 {(e.worst_single_day * 100).toFixed(1)}%</p>)}</div> : null}
        </div>
      )}

      {tab === 'tail' && (
        <div>
          <label>alpha<input value={alpha} onChange={(e) => setAlpha(e.target.value)} style={{ ...inp, width: 60 }} /></label>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益序列 A JSON</label>
          <textarea value={ret} onChange={(e) => setRet(e.target.value)} rows={3} style={ta} />
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>收益序列 B JSON</label>
          <textarea value={retB} onChange={(e) => setRetB(e.target.value)} rows={3} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runTailRisk, { returns_a: parse(ret), returns_b: parse(retB), alpha: parseFloat(alpha) })}>{loading ? '计算中…' : '计算尾部相关'}</button></div>
          {data ? <div style={{ display: 'flex', gap: 12 }}>
            <Card label="下尾相依" value={data.lower_tail_dependence} color="#dc2626" /><Card label="上尾相依" value={data.upper_tail_dependence} color="#2563eb" /><Card label="正常相关" value={data.normal_correlation} color="#374151" /><Card label="下跌相关" value={data.downside_correlation} color="#7c3aed" /></div> : null}
        </div>
      )}

      {tab === 'liq' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>持仓 JSON（{"{资产:{quantity,price}}"}）</label>
          <textarea value={positions} onChange={(e) => setPositions(e.target.value)} rows={3} style={ta} />
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>ADV JSON（{"{资产:日均额, 资产_vol:日均量}"}）</label>
          <textarea value={adv} onChange={(e) => setAdv(e.target.value)} rows={3} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runLiquidity, { positions: parse(positions), adv: parse(adv) })}>{loading ? '计算中…' : '计算流动性'}</button></div>
          {data ? <div><div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
            <Card label="总市值" value={'¥' + data.total_market_value.toLocaleString()} color="#374151" /><Card label="总冲击成本" value={'¥' + data.total_impact_cost.toLocaleString()} color="#dc2626" /><Card label="冲击占比" value={(data.total_impact_pct * 100).toFixed(2) + '%'} color="#dc2626" /></div>
            {data.positions.map((p) => <p key={p.asset} style={{ fontSize: 12 }}>{p.asset}：冲击 {(p.impact_cost_pct * 100).toFixed(2)}% · 变现 {p.liquidation_days ?? 'N/A'} 天</p>)}</div> : null}
        </div>
      )}

      {tab === 'conc' && (
        <div>
          <label style={{ display: 'block', fontSize: 12, color: '#6b7280', marginTop: 6 }}>权重 JSON（{"{资产:权重}"}）</label>
          <textarea value={weights} onChange={(e) => setWeights(e.target.value)} rows={3} style={ta} />
          <div style={{ margin: '10px 0' }}><button style={btn} disabled={loading} onClick={() => run(runConcentration, { weights: parse(weights) })}>{loading ? '计算中…' : '计算集中度'}</button></div>
          {data ? <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <Card label="HHI" value={data.hhi} color="#dc2626" /><Card label="有效持仓" value={data.effective_n} color="#2563eb" /><Card label="Top1" value={(data.top1 * 100).toFixed(0) + '%'} color="#374151" /><Card label="Top3" value={(data.top3 * 100).toFixed(0) + '%'} color="#374151" /><Card label="熵" value={data.entropy} color="#374151" /></div> : null}
        </div>
      )}
    </div>
  )
}
