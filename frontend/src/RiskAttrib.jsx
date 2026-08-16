import React, { useState } from 'react'
import {
  runFactorRisk, runFactorReturn, runComponentVar, runRiskTree, runTailMetrics,
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

export default function RiskAttrib() {
  const [tabk, setTab] = useState('frisk')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const run = async (fn, payload) => {
    setLoading(true); setErr(null)
    try { setRes(await fn(payload)) } catch (e) { setErr(jsonErr(e.message)) } finally { setLoading(false) }
  }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>风险归因与因子风险模型（V77–V81）</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>因子风险分解 · 因子收益归因 · 成分VaR · 风险分解树 · 尾部风险指标</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['frisk', '因子风险'], ['fret', '收益归因'], ['cvar', '成分VaR'], ['tree', '风险树'], ['tail', '尾部指标']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'frisk' && (
        <Card title="V77 因子风险分解（因子风险 + 特异性风险）">
          <p style={{ fontSize: 12, color: '#666' }}>weights / factor_exposures(B) / factor_cov(F)。总方差 = 因子方差 + 特异性方差。</p>
          <textarea id="ra_B" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[1.0, 0.2], [0.5, 0.8], [0.3, 0.4], [0.9, 0.1]])} />
          <textarea id="ra_F" rows={2} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[0.04, 0.01], [0.01, 0.02]])} />
          <textarea id="ra_w" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.25, 0.25, 0.25, 0.25])} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runFactorRisk, {
              weights: JSON.parse(document.getElementById('ra_w').value),
              factor_exposures: JSON.parse(document.getElementById('ra_B').value),
              factor_cov: JSON.parse(document.getElementById('ra_F').value),
              factor_names: ['Mkt', 'Val'],
            })}>{loading ? '分解中…' : '分解风险'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ total_variance: res.total_variance, factor_variance: res.factor_variance, specific_variance: res.specific_variance, pct_factor: res.pct_factor }} />
            <div style={{ marginTop: 8 }}><b>各因子风险贡献</b><pre style={pre}>{JSON.stringify(Object.fromEntries(res.factor_names.map((n, i) => [n, res.factor_contrib[i]])), null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'fret' && (
        <Card title="V78 因子收益归因">
          <p style={{ fontSize: 12, color: '#666' }}>weights / factor_exposures(B) / factor_returns(T×k)。把组合收益拆到各因子。</p>
          <textarea id="raf_B" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[1.0, 0.2], [0.5, 0.8], [0.3, 0.4]])} />
          <textarea id="raf_Fr" rows={3} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[0.01, 0.0], [0.0, 0.02], [0.005, 0.01]])} />
          <textarea id="raf_w" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.5, 0.3, 0.2])} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runFactorReturn, {
              weights: JSON.parse(document.getElementById('raf_w').value),
              factor_exposures: JSON.parse(document.getElementById('raf_B').value),
              factor_returns: JSON.parse(document.getElementById('raf_Fr').value),
              factor_names: ['Mkt', 'Val'],
            })}>{loading ? '归因中…' : '收益归因'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ total_return: res.total_return, specific_contrib: res.specific_contrib, n_periods: res.n_periods }} />
            <div style={{ marginTop: 8 }}><b>各因子收益贡献</b><pre style={pre}>{JSON.stringify(Object.fromEntries(res.factor_names.map((n, i) => [n, res.factor_contrib[i]])), null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'cvar' && (
        <Card title="V79 成分 VaR（Euler 分配）">
          <p style={{ fontSize: 12, color: '#666' }}>returns(T×n) + weights。成分 VaR 之和 = 组合 CVaR。</p>
          <textarea id="rac_R" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[0.01, 0.005, -0.003], [-0.02, 0.01, 0.004], [0.008, -0.01, 0.002]])} />
          <textarea id="rac_w" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.4, 0.35, 0.25])} />
          <div style={{ marginTop: 8 }}>
            {num('rac_a', 0.05, 'alpha')}
            <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={() => run(runComponentVar, {
              returns: JSON.parse(document.getElementById('rac_R').value),
              weights: JSON.parse(document.getElementById('rac_w').value),
              alpha: +document.getElementById('rac_a').value,
            })}>{loading ? '计算中…' : '成分 VaR'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ portfolio_var: res.portfolio_var, portfolio_cvar: res.portfolio_cvar, alpha: res.alpha }} />
            <div style={{ marginTop: 8 }}><b>各资产成分 VaR</b><pre style={pre}>{JSON.stringify(res.component_var.map((v) => +v.toFixed(5)), null, 1)}</pre></div>
            <div style={{ marginTop: 8 }}><b>各资产边际 VaR</b><pre style={pre}>{JSON.stringify(res.marginal_var.map((v) => +v.toFixed(5)), null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'tree' && (
        <Card title="V80 风险分解树（按分组聚合风险贡献）">
          <p style={{ fontSize: 12, color: '#666' }}>weights / cov / groups（资产分组标签）。单资产风险贡献按组汇总。</p>
          <textarea id="rat_w" rows={1} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.25, 0.25, 0.25, 0.25])} />
          <textarea id="rat_g" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify(['金融', '金融', '科技', '科技'])} />
          <textarea id="rat_C" rows={3} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[0.04, 0.01, 0.0, 0.0], [0.01, 0.03, 0.0, 0.0], [0.0, 0.0, 0.05, 0.02], [0.0, 0.0, 0.02, 0.04]])} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runRiskTree, {
              weights: JSON.parse(document.getElementById('rat_w').value),
              groups: JSON.parse(document.getElementById('rat_g').value),
              cov: JSON.parse(document.getElementById('rat_C').value),
              asset_names: ['A', 'B', 'C', 'D'],
            })}>{loading ? '聚合中…' : '风险分解树'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ total_variance: res.total_variance, n_assets: res.n_assets }} />
            <div style={{ marginTop: 8 }}><b>按组风险贡献</b><pre style={pre}>{JSON.stringify(res.by_group, null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'tail' && (
        <Card title="V81 尾部风险指标快照">
          <p style={{ fontSize: 12, color: '#666' }}>returns: 收益率数组。Sortino / 下行偏差 / Calmar / Omega / 尾部比率 / CVaR。</p>
          <textarea id="ratl_r" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.01, -0.02, 0.008, -0.005, 0.012, 0.003, -0.01, 0.006])} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runTailMetrics, {
              returns: JSON.parse(document.getElementById('ratl_r').value),
            })}>{loading ? '测算中…' : '尾部指标'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n: res.n, ann_return: res.ann_return, ann_vol: res.ann_vol, downside_deviation: res.downside_deviation, sortino: res.sortino, max_drawdown: res.max_drawdown, calmar: res.calmar, omega: res.omega, var: res.var, cvar: res.cvar, tail_ratio: res.tail_ratio }} />
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', marginTop: 10 }}>⚠ {err}</div>}
    </div>
  )
}
