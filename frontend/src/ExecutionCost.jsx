import React, { useState } from 'react'
import {
  runExecCost, runExecImpact, runExecTwap, runExecVwap, runExecSlippage,
} from './api.js'

const btn = {
  padding: '6px 14px', borderRadius: 8, border: '1px solid #2f6df6',
  background: '#2f6df6', color: '#fff', cursor: 'pointer', fontSize: 13,
}
const tab = (a, label) => ({
  padding: '6px 12px', cursor: 'pointer', borderRadius: 8, border: 'none',
  background: a === label ? '#2f6df6' : '#eef1f6', color: a === label ? '#fff' : '#333', fontSize: 13,
})
const Card = ({ title, children }) => (
  <div style={{ background: '#fff', border: '1px solid #e6e9ef', borderRadius: 12, padding: 16, marginBottom: 14 }}>
    <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 14 }}>{title}</div>
    {children}
  </div>
)
const KV = ({ data }) => (
  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 8 }}>
    {Object.entries(data).map(([k, v]) => (
      <div key={k} style={{ background: '#f7f9fc', borderRadius: 8, padding: '8px 10px' }}>
        <div style={{ fontSize: 11, color: '#888' }}>{k}</div>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v)}</div>
      </div>
    ))}
  </div>
)
const num = (id, val, ph) => (
  <input id={id} defaultValue={val} placeholder={ph} style={{ width: 110, padding: 6, marginRight: 6, borderRadius: 8, border: '1px solid #ccc' }} />
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }

export default function ExecutionCost() {
  const [tabk, setTab] = useState('cost')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const run = async (fn, payload) => {
    setLoading(true); setErr(null)
    try { setRes(await fn(payload)) } catch (e) { setErr(jsonErr(e.message)) } finally { setLoading(false) }
  }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>执行成本与最优执行</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>交易成本模型 · 市场冲击 · TWAP 切片 · VWAP 切片 · 滑点归因</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['cost', '交易成本'], ['impact', '市场冲击'], ['twap', 'TWAP'], ['vwap', 'VWAP'], ['slippage', '滑点归因']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'cost' && (
        <Card title="交易成本模型（佣金/印花税/规费）">
          <p style={{ fontSize: 12, color: '#666' }}>trades: JSON 数组 [{ '{' }"price":10,"shares":1000,"side":"buy"{ '}' }, ...]</p>
          <textarea id="ecf" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue='[{"price":10,"shares":1000,"side":"buy"},{"price":11,"shares":500,"side":"sell"}]' />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runExecCost, { trades: JSON.parse(document.getElementById('ecf').value) })}>{loading ? '计算中…' : '计算成本'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_trades: res.n_trades, total_notional: res.total_notional, total_cost: res.total_cost, total_cost_pct: res.total_cost_pct }} />
            <div style={{ marginTop: 8, fontSize: 13, color: '#666' }}>组成：佣金 {res.components.commission} / 印花税 {res.components.stamp_tax} / 规费 {res.components.regulator_fee} / 固定 {res.components.fixed}</div>
            {res.details.map((d, i) => (
              <div key={i} style={{ fontSize: 12, marginTop: 4 }}>#{i + 1} {d.side} {d.shares}@{d.price} → 成本 {d.cost} ({(d.cost_pct * 100).toFixed(3)}%)</div>
            ))}
          </div>}
        </Card>
      )}

      {tabk === 'impact' && (
        <Card title="市场冲击模型（平方根法）">
          <div style={{ marginTop: 4 }}>
            {num('eis', 50000, 'shares')}{num('eip', 20, 'price')}{num('eadv', 1000000, 'ADV')}{num('ev', 0.02, 'volatility')}{num('ep', 0.1, 'participation')}
          </div>
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runExecImpact, {
              shares: +document.getElementById('eis').value, price: +document.getElementById('eip').value,
              adv: +document.getElementById('eadv').value, volatility: +document.getElementById('ev').value,
              participation: +document.getElementById('ep').value,
            })}>{loading ? '计算中…' : '估算冲击'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ turnover: res.turnover, temp_impact_pct: res.temporary_impact_pct, perm_impact_pct: res.permanent_impact_pct, impact_cost: res.impact_cost, liquidation_days: res.liquidation_days }} />
          </div>}
        </Card>
      )}

      {tabk === 'twap' && (
        <Card title="TWAP 切片（均匀切分）">
          <div style={{ marginTop: 4 }}>
            {num('tq', 1000, 'parent_qty')}{num('tn', 5, 'n_slices')}{num('ti', 60, 'interval_sec')}
          </div>
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runExecTwap, {
              parent_qty: +document.getElementById('tq').value, n_slices: +document.getElementById('tn').value, interval_seconds: +document.getElementById('ti').value,
            })}>{loading ? '计算中…' : '生成切片'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_slices: res.n_slices, avg_slice_qty: res.avg_slice_qty, total_seconds: res.total_seconds }} />
            <table style={{ width: '100%', marginTop: 8, borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>段</th><th>数量</th><th>起(s)</th><th>止(s)</th></tr></thead>
              <tbody>{res.children.map((c) => (<tr key={c.slice} style={{ borderTop: '1px solid #eee' }}><td>{c.slice}</td><td>{c.qty}</td><td>{c.start_sec}</td><td>{c.end_sec}</td></tr>))}</tbody>
            </table>
          </div>}
        </Card>
      )}

      {tabk === 'vwap' && (
        <Card title="VWAP 切片（按成交量分布）">
          <p style={{ fontSize: 12, color: '#666' }}>volume_profile 可选（长度=n_slices）；缺省 U 型。默认按等权重 profile 演示。</p>
          <div style={{ marginTop: 4 }}>
            {num('vq', 600, 'parent_qty')}{num('vn', 6, 'n_slices')}
          </div>
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runExecVwap, {
              parent_qty: +document.getElementById('vq').value, n_slices: +document.getElementById('vn').value,
            })}>{loading ? '计算中…' : '生成切片'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_slices: res.n_slices }} />
            <table style={{ width: '100%', marginTop: 8, borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>段</th><th>权重</th><th>数量</th></tr></thead>
              <tbody>{res.children.map((c) => (<tr key={c.slice} style={{ borderTop: '1px solid #eee' }}><td>{c.slice}</td><td>{(c.weight * 100).toFixed(1)}%</td><td>{c.qty}</td></tr>))}</tbody>
            </table>
          </div>}
        </Card>
      )}

      {tabk === 'slippage' && (
        <Card title="滑点归因（择时 / 冲击 / 费用）">
          <div style={{ marginTop: 4 }}>
            {num('sa', 100, 'arrival_mid')}{num('sf', 100.2, 'fill_price')}{num('ss', 1000, 'shares')}{num('sfe', 3, 'fee_bps')}{num('si', 10, 'impact_bps')}
          </div>
          <div style={{ marginTop: 8 }}>
            <select id="ssd" defaultValue="buy" style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
              <option value="buy">买入</option><option value="sell">卖出</option>
            </select>
            <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={() => run(runExecSlippage, {
              arrival_mid: +document.getElementById('sa').value, fill_price: +document.getElementById('sf').value,
              side: document.getElementById('ssd').value, shares: +document.getElementById('ss').value,
              fee_bps: +document.getElementById('sfe').value, impact_bps: +document.getElementById('si').value,
            })}>{loading ? '计算中…' : '归因'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ total_slippage_bps: res.total_slippage_bps, timing_bps: res.timing_bps, impact_bps: res.impact_bps, fee_bps: res.fee_bps, residual_bps: res.residual_bps }} />
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', marginTop: 10 }}>⚠ {err}</div>}
    </div>
  )
}
