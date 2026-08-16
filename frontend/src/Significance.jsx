import React, { useState } from 'react'
import {
  runDeflatedSharpe, runProbabilisticSharpe, runStrategyCapacity, runRegimeStats, runStrategyDiversification,
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

export default function Significance() {
  const [tabk, setTab] = useState('deflated')
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
      <h2 style={{ margin: '0 0 4px' }}>策略评估与显著性（V92–V96）</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>Deflated Sharpe · 概率Sharpe · 策略容量 · 状态条件收益 · 策略分散度</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['deflated', 'Deflated SR'], ['psr', '概率Sharpe'], ['cap', '策略容量'], ['regime', '状态收益'], ['div', '策略分散']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'deflated' && (
        <Card title="V92 Deflated Sharpe Ratio（多次检验修正）">
          <p style={{ fontSize: 12, color: '#666' }}>sharpe / n_obs 必填；n_trials 为历史检验次数（越多越严格）。</p>
          {num('si_sr', 1.5, 'sharpe')}
          {num('si_n', 250, 'n_obs')}
          {num('si_nt', 100, 'n_trials')}
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runDeflatedSharpe, {
              sharpe: +document.getElementById('si_sr').value, n_obs: +document.getElementById('si_n').value,
              n_trials: +document.getElementById('si_nt').value,
            })}>{loading ? '计算…' : '计算 Deflated SR'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ deflated_sharpe: res.deflated_sharpe, expected_max_sr: res.expected_max_sr, p_lucky: res.p_lucky, sr_se: res.sr_se }} />
          </div>}
        </Card>
      )}

      {tabk === 'psr' && (
        <Card title="V93 Probabilistic Sharpe Ratio（夏普≥目标的概率）">
          <p style={{ fontSize: 12, color: '#666' }}>PSR = Φ(z)，z 由夏普、样本数、偏度、峰度、目标夏普计算。</p>
          {num('si_psr_sr', 1.5, 'sharpe')}
          {num('si_psr_n', 250, 'n_obs')}
          {num('si_psr_t', 0.5, 'target')}
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runProbabilisticSharpe, {
              sharpe: +document.getElementById('si_psr_sr').value, n_obs: +document.getElementById('si_psr_n').value,
              target_sr: +document.getElementById('si_psr_t').value,
            })}>{loading ? '计算…' : '计算 PSR'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ prob: res.prob, z: res.z, sr_se: res.sr_se }} />
          </div>}
        </Card>
      )}

      {tabk === 'cap' && (
        <Card title="V94 策略容量估计（流动性 / 冲击）">
          <p style={{ fontSize: 12, color: '#666' }}>adv=日均成交额(元)；participation=参与率；annual_turnover=年化换手。</p>
          {num('si_adv', 1e8, 'adv')}
          {num('si_par', 0.1, 'part')}
          {num('si_at', 2.0, 'turnover')}
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runStrategyCapacity, {
              adv: +document.getElementById('si_adv').value, participation: +document.getElementById('si_par').value,
              annual_turnover: +document.getElementById('si_at').value,
            })}>{loading ? '计算…' : '估计容量'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ daily_tradable: res.daily_tradable, annual_tradable: res.annual_tradable, capacity: res.capacity, impact_cost_at_capacity: res.impact_cost_at_capacity }} />
          </div>}
        </Card>
      )}

      {tabk === 'regime' && (
        <Card title="V95 状态条件收益统计（按市场状态拆分）">
          <p style={{ fontSize: 12, color: '#666' }}>returns 与 regime_labels 等长；标签示例 bull/bear。</p>
          {ta('si_r', JSON.stringify(Array.from({ length: 40 }, (_, i) => +(0.001 + (i % 2 ? 0.004 : -0.002) + (Math.random() - 0.5) * 0.01).toFixed(5))), 3)}
          {ta('si_l', JSON.stringify(Array.from({ length: 40 }, (_, i) => (i % 2 ? 'bull' : 'bear'))), 2)}
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runRegimeStats, {
              returns: val('si_r'), regime_labels: val('si_l'),
            })}>{loading ? '计算…' : '拆分统计'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <div style={{ marginTop: 8 }}><b>各状态</b> <pre style={pre}>{JSON.stringify(res.per_regime, null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'div' && (
        <Card title="V96 策略分散度（相关系数 + 有效策略数）">
          <p style={{ fontSize: 12, color: '#666' }}>equity_curves：策略名 → 权益曲线。</p>
          {ta('si_ec', JSON.stringify({ "动量": [1, 1.02, 0.99, 1.05, 1.03], "价值": [1, 0.98, 1.01, 0.97, 1.02] }), 3)}
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runStrategyDiversification, {
              equity_curves: val('si_ec'),
            })}>{loading ? '计算…' : '计算分散度'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ avg_correlation: res.avg_correlation, effective_strategies: res.effective_strategies }} />
            <div style={{ marginTop: 8 }}><b>相关矩阵</b> <pre style={pre}>{JSON.stringify(res.correlation_matrix.map((r) => r.map((v) => +v.toFixed(3))))}</pre></div>
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', background: '#fdecea', padding: 10, borderRadius: 8, marginTop: 10 }}>请求失败：{err}</div>}
    </div>
  )
}
