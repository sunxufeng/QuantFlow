import React, { useState } from 'react'
import {
  runDriftMonitor, runReturnQuality, runTrackingError, runSectorExposure, runRiskBudget,
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
  <input id={id} defaultValue={val} placeholder={ph} style={{ width: 80, padding: 6, marginRight: 6, borderRadius: 8, border: '1px solid #ccc' }} />
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }
const pre = { background: '#f7f9fc', borderRadius: 8, padding: 10, fontSize: 12, overflowX: 'auto' }
const ta = (id, val, rows) => (
  <textarea id={id} rows={rows} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={val} />
)

export default function MonitorAlert() {
  const [tabk, setTab] = useState('drift')
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
      <h2 style={{ margin: '0 0 4px' }}>组合监控与预警（V87–V91）</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>持仓偏离 · 收益质量 · 跟踪误差 · 行业敞口 · 风险预算（集中度/流动性见风险页）</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['drift', '持仓偏离'], ['rq', '收益质量'], ['te', '跟踪误差'], ['sector', '行业敞口'], ['budget', '风险预算']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'drift' && (
        <Card title="V87 持仓偏离监控（drift 超阈值 → 再平衡清单）">
          <p style={{ fontSize: 12, color: '#666' }}>weights / target 均须归一化为 1。</p>
          {ta('mo_w', JSON.stringify([0.4, 0.4, 0.2]), 1)}
          {ta('mo_t', JSON.stringify([0.33, 0.33, 0.34]), 1)}
          <div style={{ marginTop: 8 }}>
            {num('mo_th', 0.05, 'threshold')}
            <button style={btn} disabled={loading} onClick={() => run(runDriftMonitor, {
              weights: val('mo_w'), target: val('mo_t'), threshold: +document.getElementById('mo_th').value,
            })}>{loading ? '监控中…' : '检测偏离'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ max_drift: res.max_drift, n_flagged: res.n_flagged }} />
            <div style={{ marginTop: 8 }}><b>触发再平衡</b> <pre style={pre}>{JSON.stringify(res.trades)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'rq' && (
        <Card title="V88 收益质量监控（胜率 / 盈亏比 / 连胜连亏 / 偏度）">
          <p style={{ fontSize: 12, color: '#666' }}>returns：日收益序列。</p>
          {ta('mo_rq', JSON.stringify(Array.from({ length: 60 }, () => +(0.0008 + (Math.random() - 0.5) * 0.012).toFixed(5))), 4)}
          <div style={{ marginTop: 8 }}>
            {num('mo_hr', 0.45, 'hit_limit')}
            <button style={btn} disabled={loading} onClick={() => run(runReturnQuality, {
              returns: val('mo_rq'), hit_rate_limit: +document.getElementById('mo_hr').value,
            })}>{loading ? '监控中…' : '检测质量'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ hit_rate: res.hit_rate, payoff_ratio: res.payoff_ratio, max_win_streak: res.max_win_streak, max_loss_streak: res.max_loss_streak, skew: res.skew }} />
            <div style={{ marginTop: 8 }}><b>告警</b> <pre style={pre}>{JSON.stringify(res.breaches)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'te' && (
        <Card title="V89 跟踪误差监控（滚动 TE 超限告警）">
          <p style={{ fontSize: 12, color: '#666' }}>returns_port / returns_bench 等长，长度 ≥ window。</p>
          {ta('mo_rp', JSON.stringify(Array.from({ length: 60 }, (_, i) => +(0.0005 + (i > 40 ? 0.02 : 0) + (Math.random() - 0.5) * 0.01).toFixed(5))), 3)}
          {ta('mo_rb', JSON.stringify(Array.from({ length: 60 }, () => +(0.0005 + (Math.random() - 0.5) * 0.01).toFixed(5))), 3)}
          <div style={{ marginTop: 8 }}>
            {num('mo_win', 20, 'window')}
            {num('mo_tel', 0.05, 'limit')}
            <button style={btn} disabled={loading} onClick={() => run(runTrackingError, {
              returns_port: val('mo_rp'), returns_bench: val('mo_rb'),
              window: +document.getElementById('mo_win').value, limit: +document.getElementById('mo_tel').value,
            })}>{loading ? '监控中…' : '检测TE'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ mean_te: res.mean_te, max_te: res.max_te, n_breaches: res.n_breaches }} />
          </div>}
        </Card>
      )}

      {tabk === 'sector' && (
        <Card title="V90 行业敞口监控（分组权重 vs 上限）">
          <p style={{ fontSize: 12, color: '#666' }}>group_weights 合计须为 1。</p>
          {ta('mo_gw', JSON.stringify({ "金融": 0.7, "科技": 0.2, "消费": 0.1 }), 2)}
          <div style={{ marginTop: 8 }}>
            {num('mo_gl', 0.6, 'limit')}
            <button style={btn} disabled={loading} onClick={() => run(runSectorExposure, {
              group_weights: val('mo_gw'), limit: +document.getElementById('mo_gl').value,
            })}>{loading ? '监控中…' : '检测敞口'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ max_exposure: res.max_exposure, n_breaches: res.breaches.length }} />
            <div style={{ marginTop: 8 }}><b>超限分组</b> <pre style={pre}>{JSON.stringify(res.over_limit)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'budget' && (
        <Card title="V91 风险预算监控（边际风险贡献 vs 预算）">
          <p style={{ fontSize: 12, color: '#666' }}>weights 归一化为 1；cov 为 n×n。target_budget 可选。</p>
          {ta('mo_bw', JSON.stringify([0.5, 0.5]), 1)}
          {ta('mo_bc', JSON.stringify([[0.04, 0.01], [0.01, 0.02]]), 2)}
          {ta('mo_bb', JSON.stringify([0.5, 0.5]), 1)}
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runRiskBudget, {
              weights: val('mo_bw'), cov: val('mo_bc'), target_budget: val('mo_bb'),
            })}>{loading ? '监控中…' : '检测预算'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ max_deviation: res.max_deviation, n_breaches: res.breaches.length }} />
            <div style={{ marginTop: 8 }}><b>风险贡献占比</b> <pre style={pre}>{JSON.stringify(res.risk_contrib_pct.map((v) => +v.toFixed(4)))}</pre></div>
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', background: '#fdecea', padding: 10, borderRadius: 8, marginTop: 10 }}>请求失败：{err}</div>}
    </div>
  )
}
