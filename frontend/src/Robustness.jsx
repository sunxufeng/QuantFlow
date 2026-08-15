import React, { useState } from 'react'
import { runRobustness } from './api.js'

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{ flex: '1 1 150px', minWidth: 150, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: '12px 14px' }}>
      <div style={{ fontSize: 12, color: '#8a94a6' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: color || '#1f2733', marginTop: 4 }}>{value ?? '—'}</div>
      {sub && <div style={{ fontSize: 11, color: '#aab2c0', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export default function Robustness() {
  const [strategy, setStrategy] = useState('ma_cross')
  const [paramA, setParamA] = useState('fast')
  const [paramAValues, setParamAValues] = useState('3,5,8')
  const [paramB, setParamB] = useState('slow')
  const [paramBValues, setParamBValues] = useState('15,20,30')
  const [symbols, setSymbols] = useState('TEST.STOCK')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-12-31')
  const [nFolds, setNFolds] = useState(5)
  const [metric, setMetric] = useState('total_return')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [data, setData] = useState(null)

  async function run() {
    setLoading(true); setErr('')
    try {
      const grid = {
        [paramA]: paramAValues.split(',').map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n)),
        [paramB]: paramBValues.split(',').map((s) => Number(s.trim())).filter((n) => !Number.isNaN(n)),
      }
      const payload = {
        strategy,
        grid,
        symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
        start, end,
        n_folds: Number(nFolds),
        metric,
      }
      const res = await runRobustness(payload)
      setData(res)
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  const summary = data?.summary || {}
  const consensus = summary.consensus_optimal
  const gbest = summary.global_optimal
  const opa = data?.param_a, opb = data?.param_b

  return (
    <div style={{ padding: 18 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20 }}>参数最优区间稳健性 <span style={{ fontSize: 12, color: '#b0b8c4' }}>V17 · 无凭证</span></h2>
      <p style={{ color: '#8a94a6', fontSize: 13, marginTop: 0 }}>
        grid × walk-forward 联动：每折在训练区间重算参数网格找到样本内最优，再在样本外验证其表现；汇总「共识最优参数」及其稳定度、与全局单点最优的一致性。
      </p>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', background: '#fafbfc', border: '1px solid #eceef1', borderRadius: 10, padding: 14 }}>
        <label style={{ fontSize: 12, color: '#6b7382' }}>策略<br />
          <input value={strategy} onChange={(e) => setStrategy(e.target.value)} style={{ width: 120, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} />
        </label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>参数A名<br /><input value={paramA} onChange={(e) => setParamA(e.target.value)} style={{ width: 90, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>A取值<br /><input value={paramAValues} onChange={(e) => setParamAValues(e.target.value)} style={{ width: 130, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>参数B名<br /><input value={paramB} onChange={(e) => setParamB(e.target.value)} style={{ width: 90, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>B取值<br /><input value={paramBValues} onChange={(e) => setParamBValues(e.target.value)} style={{ width: 130, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>标的<br /><input value={symbols} onChange={(e) => setSymbols(e.target.value)} style={{ width: 140, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>起始<br /><input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={{ padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>结束<br /><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={{ padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>折数<br /><input type="number" value={nFolds} min={2} max={20} onChange={(e) => setNFolds(e.target.value)} style={{ width: 60, padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }} /></label>
        <label style={{ fontSize: 12, color: '#6b7382' }}>指标<br />
          <select value={metric} onChange={(e) => setMetric(e.target.value)} style={{ padding: 6, border: '1px solid #dfe3e8', borderRadius: 6 }}>
            {['total_return', 'annual_return', 'sharpe', 'max_drawdown', 'win_rate', 'final_value'].map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <button onClick={run} disabled={loading} style={{ padding: '8px 18px', background: '#3b6cf6', color: '#fff', border: 'none', borderRadius: 8, fontWeight: 600, cursor: 'pointer' }}>
          {loading ? '分析中…' : '运行分析'}
        </button>
      </div>
      {err && <div style={{ color: '#d23', marginTop: 10 }}>错误：{err}</div>}

      {data && (
        <>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
            <StatCard label="样本外折数" value={summary.n_oos_folds} />
            <StatCard
              label="共识最优"
              value={consensus ? `${opa}=${consensus.param_a}, ${opb}=${consensus.param_b}` : '—'}
              sub={consensus ? `稳定度 ${(consensus.stability_ratio * 100).toFixed(0)}%` : ''}
              color="#1a9c5b"
            />
            <StatCard
              label="与全局最优一致"
              value={summary.consistent_with_global ? '是' : '否'}
              sub={gbest ? `全局: ${opa}=${gbest.param_a}, ${opb}=${gbest.param_b}` : ''}
              color={summary.consistent_with_global ? '#1a9c5b' : '#d23'}
            />
            <StatCard label="样本外均值(折内最优)" value={summary.mean_oos_fold_best} sub={metric} />
            <StatCard label="样本外均值(全局最优)" value={summary.mean_oos_global_best} sub={metric} />
            <StatCard label="折内最优样本外胜率" value={summary.oos_fold_best_positive_rate} />
          </div>

          <div style={{ marginTop: 16, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: 14, overflowX: 'auto' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#1f2733', marginBottom: 8 }}>逐折最优参数与样本外表现</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ color: '#8a94a6', textAlign: 'right' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>样本外区间</th>
                  <th style={{ padding: '6px 8px' }}>{opa}(最优)</th>
                  <th style={{ padding: '6px 8px' }}>{opb}(最优)</th>
                  <th style={{ padding: '6px 8px' }}>样本内值</th>
                  <th style={{ padding: '6px 8px' }}>样本外指标</th>
                </tr>
              </thead>
              <tbody>
                {data.folds.map((f, i) => (
                  <tr key={i} style={{ borderTop: '1px solid #f2f4f7', textAlign: 'right' }}>
                    <td style={{ textAlign: 'left', padding: '6px 8px' }}>{f.test_period.start} ~ {f.test_period.end}</td>
                    <td style={{ padding: '6px 8px' }}>{f.best_param_a ?? '—'}</td>
                    <td style={{ padding: '6px 8px' }}>{f.best_param_b ?? '—'}</td>
                    <td style={{ padding: '6px 8px' }}>{f.best_value_in_sample ?? '—'}</td>
                    <td style={{ padding: '6px 8px', color: (f.oos_metric || 0) >= 0 ? '#1a9c5b' : '#d23', fontWeight: 600 }}>{f.oos_metric ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {summary.param_frequency && summary.param_frequency.length > 0 && (
            <div style={{ marginTop: 16, background: '#fff', border: '1px solid #eceef1', borderRadius: 10, padding: 14, overflowX: 'auto' }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#1f2733', marginBottom: 8 }}>最优参数组合出现频次（稳定度）</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ color: '#8a94a6', textAlign: 'right' }}>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>{opa}</th>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>{opb}</th>
                    <th style={{ padding: '6px 8px' }}>折数</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.param_frequency.map((p, i) => (
                    <tr key={i} style={{ borderTop: '1px solid #f2f4f7', textAlign: 'right', background: i === 0 ? '#f5f8ff' : 'transparent' }}>
                      <td style={{ textAlign: 'left', padding: '6px 8px' }}>{p.param_a}</td>
                      <td style={{ textAlign: 'left', padding: '6px 8px' }}>{p.param_b}</td>
                      <td style={{ padding: '6px 8px', fontWeight: i === 0 ? 700 : 400 }}>{p.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
