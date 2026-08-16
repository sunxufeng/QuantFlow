import React, { useState } from 'react'
import {
  runOptionPayoff, runDeltaHedge, runPortfolioInsurance, runPortfolioGreeks, runVolSurface,
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
const KV = ({ data }) => {
  const flat = Object.entries(data).filter(([, v]) => typeof v === 'number' || typeof v === 'string')
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))', gap: 8 }}>
      {flat.map(([k, v]) => (
        <div key={k} style={{ background: '#f7f9fc', borderRadius: 8, padding: '8px 10px' }}>
          <div style={{ fontSize: 11, color: '#888' }}>{k}</div>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{typeof v === 'number' ? (Number.isInteger(v) ? v : (+v).toFixed(4)) : String(v)}</div>
        </div>
      ))}
    </div>
  )
}
const num = (id, val, ph) => (
  <input id={id} defaultValue={val} placeholder={ph} style={{ width: 90, padding: 6, marginRight: 6, borderRadius: 8, border: '1px solid #ccc' }} />
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }
const pre = { background: '#f7f9fc', borderRadius: 8, padding: 10, fontSize: 12, overflowX: 'auto' }
const ta = (id, val, rows) => (
  <textarea id={id} rows={rows} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={val} />
)

export default function Derivatives() {
  const [tabk, setTab] = useState('payoff')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const run = async (fn, payload) => {
    setLoading(true); setErr(null)
    try { setRes(await fn(payload)) } catch (e) { setErr(jsonErr(e.message)) } finally { setLoading(false) }
  }
  const val = (id) => JSON.parse(document.getElementById(id).value)

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>衍生品策略与对冲（V82–V86）</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>期权盈亏图 · Delta对冲 · 组合保险 · 组合Greeks · 波动率曲面</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['payoff', '期权盈亏图'], ['hedge', 'Delta对冲'], ['insure', '组合保险'], ['greeks', '组合Greeks'], ['surface', '波动率曲面']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'payoff' && (
        <Card title="V82 期权盈亏图（多腿组合到期损益）">
          <p style={{ fontSize: 12, color: '#666' }}>legs: type / side(long or short) / strike / premium / qty。spot 采样区间 [spot_min, spot_max]。</p>
          {ta('dv_legs', JSON.stringify([
            { type: 'call', side: 'long', strike: 100, premium: 5, qty: 1 },
            { type: 'call', side: 'short', strike: 110, premium: 2, qty: 1 },
          ]), 4)}
          <div style={{ marginTop: 8 }}>
            {num('dv_smin', 90, 'spot_min')}
            {num('dv_smax', 120, 'spot_max')}
            <button style={btn} disabled={loading} onClick={() => run(runOptionPayoff, {
              legs: val('dv_legs'), spot_min: +document.getElementById('dv_smin').value, spot_max: +document.getElementById('dv_smax').value,
            })}>{loading ? '计算中…' : '生成盈亏图'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ max_profit: res.max_profit, max_loss: res.max_loss, n_breakeven: res.breakeven.length }} />
            <div style={{ marginTop: 8 }}><b>盈亏平衡点</b> <pre style={pre}>{JSON.stringify(res.breakeven)}</pre></div>
            <div style={{ marginTop: 8 }}><b>损益曲线（spot, pnl）</b> <pre style={pre}>{JSON.stringify(res.spots.map((s, i) => [+s.toFixed(1), +res.pnl[i].toFixed(2)]))}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'hedge' && (
        <Card title="V83 Delta 对冲模拟（空头期权动态对冲）">
          <p style={{ fontSize: 12, color: '#666' }}>给定标的现货路径 path（含 S0），对空头期权按 BS delta 动态对冲，输出对冲损益与误差。</p>
          {ta('dv_path', JSON.stringify([100, 102, 99, 101, 98, 103, 100, 105, 97, 101, 104]), 3)}
          <div style={{ marginTop: 8 }}>
            {num('dv_K', 100, 'strike')}
            {num('dv_sig', 0.2, 'sigma')}
            {num('dv_T', 1.0, 'T')}
            <button style={btn} disabled={loading} onClick={() => run(runDeltaHedge, {
              path: val('dv_path'), strike: +document.getElementById('dv_K').value,
              sigma: +document.getElementById('dv_sig').value, T: +document.getElementById('dv_T').value,
            })}>{loading ? '模拟中…' : '模拟对冲'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ hedge_pnl: res.hedge_pnl, option_payoff: res.option_payoff, hedge_error: res.hedge_error, n_rebalances: res.n_rebalances }} />
          </div>}
        </Card>
      )}

      {tabk === 'insure' && (
        <Card title="V84 组合保险（保护看跌 / 领口 / CPPI）">
          <p style={{ fontSize: 12, color: '#666' }}>risky_path：全仓风险资产时的组合价值路径（首点 V0）。method: put / collar / cppi。</p>
          {ta('dv_risk', JSON.stringify([100, 95, 88, 92, 80, 85, 96]), 2)}
          <div style={{ marginTop: 8 }}>
            {num('dv_floor', 0.8, 'floor')}
            {num('dv_mult', 3.0, 'cppi_m')}
            <button style={btn} disabled={loading} onClick={() => run(runPortfolioInsurance, {
              risky_path: val('dv_risk'), floor: +document.getElementById('dv_floor').value,
              cppi_multiplier: +document.getElementById('dv_mult').value, method: 'cppi',
            })}>{loading ? '计算中…' : '运行CPPI'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ method: res.method, floor_value: res.floor_value, min_value: res.min_value, n_breaches: res.n_breaches }} />
            <div style={{ marginTop: 8 }}><b>保险价值路径</b> <pre style={pre}>{JSON.stringify(res.insured_value.map((v) => +v.toFixed(2)))}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'greeks' && (
        <Card title="V85 组合 Greeks 聚合">
          <p style={{ fontSize: 12, color: '#666' }}>positions: type / strike / t / sigma / qty / side。按 BS 聚合为净希腊字母。</p>
          {ta('dv_pos', JSON.stringify([
            { type: 'call', strike: 100, t: 1.0, sigma: 0.2, qty: 1, side: 'long' },
            { type: 'put', strike: 100, t: 1.0, sigma: 0.2, qty: 1, side: 'short' },
          ]), 4)}
          <div style={{ marginTop: 8 }}>
            {num('dv_spot', 100, 'spot')}
            <button style={btn} disabled={loading} onClick={() => run(runPortfolioGreeks, {
              positions: val('dv_pos'), spot: +document.getElementById('dv_spot').value,
            })}>{loading ? '计算中…' : '聚合Greeks'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ delta: res.delta, gamma: res.gamma, vega: res.vega, theta: res.theta, rho: res.rho }} />
          </div>}
        </Card>
      )}

      {tabk === 'surface' && (
        <Card title="V86 隐含波动率曲面（ATM 期限结构 + 偏度）">
          <p style={{ fontSize: 12, color: '#666' }}>iv 矩阵：行=strikes，列=maturities。抽 ATM 期限结构与各期限偏度(col[0]-col[-1])。</p>
          {ta('dv_strike', JSON.stringify([90, 100, 110]), 1)}
          {ta('dv_mat', JSON.stringify([0.25, 0.5, 1.0]), 1)}
          {ta('dv_iv', JSON.stringify([[0.22, 0.21, 0.20], [0.20, 0.19, 0.18], [0.18, 0.17, 0.16]]), 3)}
          <div style={{ marginTop: 8 }}>
            {num('dv_ivspot', 100, 'spot')}
            <button style={btn} disabled={loading} onClick={() => run(runVolSurface, {
              strikes: val('dv_strike'), maturities: val('dv_mat'), iv: val('dv_iv'),
              spot: +document.getElementById('dv_ivspot').value,
            })}>{loading ? '计算中…' : '构建曲面'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ spot: res.spot }} />
            <div style={{ marginTop: 8 }}><b>ATM 期限结构</b> <pre style={pre}>{JSON.stringify(res.atm_term_structure)}</pre></div>
            <div style={{ marginTop: 8 }}><b>各期限偏度</b> <pre style={pre}>{JSON.stringify(res.skew_by_maturity)}</pre></div>
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', background: '#fdecea', padding: 10, borderRadius: 8, marginTop: 10 }}>请求失败：{err}</div>}
    </div>
  )
}
