import { useEffect, useState } from 'react'
import { getStressScenarios, runStressTest } from './api.js'

const ASSET_CLASSES = ['equity', 'bond', 'gold', 'cash', 'reit', 'em', 'commodity', 'oil', 'tech', 'growth', 'value']
const AC_LABELS = {
  equity: '股票', bond: '债券', gold: '黄金', cash: '现金', reit: '房地产', em: '新兴市场',
  commodity: '大宗商品', oil: '原油', tech: '科技股', growth: '成长股', value: '价值股',
}
const EXAMPLE_HOLDINGS = JSON.stringify([
  { symbol: 'AAPL', asset_class: 'tech', weight: 0.25 },
  { symbol: 'SP500', asset_class: 'equity', weight: 0.35 },
  { symbol: 'AGG', asset_class: 'bond', weight: 0.25 },
  { symbol: 'GLD', asset_class: 'gold', weight: 0.10 },
  { symbol: 'VNQ', asset_class: 'reit', weight: 0.05 },
], null, 2)

export default function StressTest() {
  const [scenarios, setScenarios] = useState([])
  const [selected, setSelected] = useState([])
  const [holdingsText, setHoldingsText] = useState(EXAMPLE_HOLDINGS)
  const [baseValue, setBaseValue] = useState('1000000')
  const [customText, setCustomText] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    getStressScenarios().then((r) => {
      setScenarios(r.scenarios || [])
      setSelected((r.scenarios || []).map((s) => s.name))
    }).catch(() => {})
  }, [])

  const toggle = (name) => setSelected((s) => s.includes(name) ? s.filter((x) => x !== name) : [...s, name])

  const run = async () => {
    setErr('')
    let holdings
    try { holdings = JSON.parse(holdingsText) } catch (e) { setErr('持仓 JSON 解析失败：' + e.message); return }
    let custom = null
    if (customText.trim()) {
      try { custom = JSON.parse(customText) } catch (e) { setErr('自定义冲击 JSON 解析失败：' + e.message); return }
    }
    const payload = { holdings, scenarios: selected, base_value: parseFloat(baseValue) || 1000000 }
    if (custom) payload.custom_shocks = custom
    setLoading(true)
    try {
      const res = await runStressTest(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const maxAbs = data ? Math.max(...data.scenarios.map((s) => Math.abs(s.impact_pct)), 0.0001) : 1

  return (
    <div style={{ padding: 20, maxWidth: 1040 }}>
      <h2 style={{ margin: '0 0 4px' }}>压力测试 / 情景分析 <span style={{ fontSize: 12, color: '#9ca3af' }}>V29</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>对持仓组合施加历史危机冲击或自定义冲击，计算组合损益影响并排序最脆弱情景。</p>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
        <label>组合基准市值<input value={baseValue} onChange={(e) => setBaseValue(e.target.value)} style={inp} /></label>
      </div>

      <h3 style={{ fontSize: 14, margin: '14px 0 6px' }}>预置历史情景（点击勾选）</h3>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        {scenarios.map((s) => {
          const on = selected.includes(s.name)
          return (
            <button key={s.name} type="button" onClick={() => toggle(s.name)}
              title={s.desc}
              style={{
                padding: '6px 12px', borderRadius: 16, cursor: 'pointer', fontSize: 12,
                border: '1px solid ' + (on ? '#2563eb' : '#d1d5db'),
                background: on ? '#eff6ff' : '#fff', color: on ? '#1d4ed8' : '#374151',
              }}>{s.name} · {s.year}</button>
          )
        })}
      </div>

      <h3 style={{ fontSize: 14, margin: '14px 0 6px' }}>持仓组合（JSON）</h3>
      <textarea value={holdingsText} onChange={(e) => setHoldingsText(e.target.value)} rows={9} style={ta} />

      <h3 style={{ fontSize: 14, margin: '14px 0 6px' }}>自定义冲击（可选 JSON：资产类别 或 标的代码 → 冲击收益率）</h3>
      <textarea value={customText} onChange={(e) => setCustomText(e.target.value)} rows={3} placeholder='{"equity": -0.2, "AAPL": -0.35}' style={ta} />

      <div style={{ margin: '12px 0' }}>
        <button onClick={run} disabled={loading} style={btn}>{loading ? '计算中…' : '运行压力测试'}</button>
      </div>
      {err ? <div style={{ color: '#dc2626', marginBottom: 10 }}>{err}</div> : null}

      {data ? (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
            <Card label="最差情景" value={data.summary.worst_scenario || '—'} color="#dc2626" />
            <Card label="最大跌幅" value={(data.summary.max_loss_pct * 100).toFixed(2) + '%'} color="#dc2626" />
            <Card label="平均冲击" value={(data.summary.mean_loss_pct * 100).toFixed(2) + '%'} color="#d97706" />
            <Card label="情景数" value={String(data.summary.n_scenarios)} color="#374151" />
          </div>

          <h3 style={{ fontSize: 14, margin: '6px 0' }}>情景影响排序（最差在前）</h3>
          <table style={tbl}>
            <thead><tr>{['情景', '年份', '冲击', '影响金额', '冲击后市值', '最拖后腿持仓'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
            <tbody>
              {data.scenarios.map((s) => (
                <tr key={s.name}>
                  <td style={{ ...td, fontWeight: 600 }}>{s.name}</td>
                  <td style={td}>{s.year ?? '—'}</td>
                  <td style={{ ...td, color: s.impact_pct < 0 ? '#dc2626' : '#16a34a', fontWeight: 700 }}>
                    {(s.impact_pct * 100).toFixed(2)}%
                  </td>
                  <td style={{ ...td, color: s.impact_value < 0 ? '#dc2626' : '#16a34a' }}>{fmt(s.impact_value)}</td>
                  <td style={td}>{fmt(s.post_value)}</td>
                  <td style={td}>{s.worst_holding ? `${s.worst_holding.symbol}（${AC_LABELS[s.worst_holding.asset_class] || s.worst_holding.asset_class} ${(s.worst_holding.contribution / (data.base_value || 1) * 100).toFixed(2)}%）` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 style={{ fontSize: 14, margin: '16px 0 6px' }}>冲击幅度可视化</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {data.scenarios.map((s) => {
              const pct = s.impact_pct
              const w = (Math.abs(pct) / maxAbs) * 100
              const color = pct < 0 ? '#dc2626' : '#16a34a'
              return (
                <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 150, fontSize: 12, textAlign: 'right', color: '#374151' }}>{s.name}</span>
                  <div style={{ flex: 1, background: '#f1f5f9', borderRadius: 4, height: 18, position: 'relative', overflow: 'hidden' }}>
                    <div style={{ width: w + '%', height: '100%', background: color, marginLeft: pct < 0 ? 'auto' : 0 }} />
                  </div>
                  <span style={{ width: 70, fontSize: 12, color, fontWeight: 700 }}>{(pct * 100).toFixed(2)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Card({ label, value, color }) {
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 16px', textAlign: 'center', minWidth: 130 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color }}>{value}</div>
    </div>
  )
}

function fmt(n) {
  if (n == null) return '—'
  return (n < 0 ? '-' : '') + '¥' + Math.abs(n).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

const inp = { marginLeft: 6, padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 6, width: 150 }
const ta = { width: '100%', fontFamily: 'monospace', fontSize: 13, padding: 10, border: '1px solid #d1d5db', borderRadius: 8 }
const tbl = { width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 13 }
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '2px solid #e5e7eb', color: '#374151' }
const td = { padding: '6px 8px', borderBottom: '1px solid #f0f0f0' }
const btn = { padding: '8px 20px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer' }
