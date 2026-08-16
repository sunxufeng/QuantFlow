import React, { useState } from 'react'
import {
  runReportPerformance, runReportCompare, runReportMulti, runReportPeriodic, runReportDashboard,
} from './api.js'
import ExportBar from './ExportBar.jsx'

const TAB_LABEL = { performance: '综合绩效', compare: '快照对比', multi: '多策略对比', periodic: '周期报告', dashboard: '风险看板' }

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
  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))', gap: 8 }}>
    {Object.entries(data).map(([k, v]) => (
      <div key={k} style={{ background: '#f7f9fc', borderRadius: 8, padding: '8px 10px' }}>
        <div style={{ fontSize: 11, color: '#888' }}>{k}</div>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v)}</div>
      </div>
    ))}
  </div>
)
const num = (id, val, ph) => (
  <input id={id} defaultValue={val} placeholder={ph} style={{ width: 90, padding: 6, marginRight: 6, borderRadius: 8, border: '1px solid #ccc' }} />
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }

export default function ReportsHub() {
  const [tabk, setTab] = useState('performance')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const run = async (fn, payload) => {
    setLoading(true); setErr(null)
    try { setRes(await fn(payload)) } catch (e) { setErr(jsonErr(e.message)) } finally { setLoading(false) }
  }
  const gen = (n, drift, vol, seed) => {
    let s = seed, out = []
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff }
    for (let i = 0; i < n; i++) out.push(+(drift + (rnd() - 0.5) * 2 * vol).toFixed(6))
    return out
  }

  // 把当前结果按 tab 转成可导出的章节结构（V95）。
  const buildSections = () => {
    if (!res) return []
    if (tabk === 'performance') {
      return [
        { title: '绩效', kv: res.performance },
        { title: '风险', kv: res.risk },
        ...(res.benchmark ? [{ title: '基准', kv: res.benchmark }] : []),
      ]
    }
    if (tabk === 'compare') {
      return [
        { title: '对比概览', kv: { n_metrics: res.n_metrics, improved_count: res.improved_count } },
        {
          title: '逐指标对比',
          columns: ['metric', res.name_a, res.name_b, 'delta', 'improved'],
          rows: res.comparisons.map((c) => ({
            metric: c.metric, [res.name_a]: c[res.name_a], [res.name_b]: c[res.name_b],
            delta: c.delta, improved: c.improved ? res.name_a : res.name_b,
          })),
        },
      ]
    }
    if (tabk === 'multi') {
      return [
        { title: '概览', kv: { n_strategies: res.n_strategies, ranking_by_sharpe: res.ranking_by_sharpe.join(' > ') } },
        {
          title: '各策略',
          columns: ['name', 'sharpe', 'ann_return', 'max_drawdown'],
          rows: res.rows.map((r) => ({
            name: r.name, sharpe: r.report.performance.sharpe,
            ann_return: r.report.performance.ann_return, max_drawdown: r.report.risk.max_drawdown,
          })),
        },
      ]
    }
    if (tabk === 'periodic') {
      return [
        { title: '概览', kv: { freq: res.freq, n_periods: res.n_periods, overall_sharpe: res.overall.sharpe } },
        {
          title: '分周期',
          columns: ['period', 'n', 'ann_return', 'ann_vol', 'sharpe'],
          rows: res.periods.map((p) => ({
            period: p.period, n: p.n, ann_return: p.ann_return, ann_vol: p.ann_vol, sharpe: p.sharpe,
          })),
        },
      ]
    }
    if (tabk === 'dashboard') {
      return [{ title: '风险看板', kv: res.dashboard }]
    }
    return []
  }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>报告与运维增强</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>综合绩效报告 · 快照对比 · 多策略对比 · 周期报告 · 风险看板</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['performance', '绩效报告'], ['compare', '快照对比'], ['multi', '多策略对比'], ['periodic', '周期报告'], ['dashboard', '风险看板']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'performance' && (
        <Card title="综合绩效报告（收益/风险/回撤/基准）">
          <p style={{ fontSize: 12, color: '#666' }}>returns: 收益率数组；可选 benchmark。单调用聚合 Sharpe/Sortino/最大回撤/VaR/CVaR/Beta/Alpha。</p>
          <textarea id="rpf" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify(gen(120, 0.0006, 0.01, 7))} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runReportPerformance, { returns: JSON.parse(document.getElementById('rpf').value) })}>{loading ? '生成中…' : '生成报告'}</button>
            <button style={{ ...btn, marginLeft: 8, background: '#fff', color: '#2f6df6' }} disabled={loading} onClick={() => run(runReportPerformance, { returns: JSON.parse(document.getElementById('rpf').value), benchmark: JSON.parse(JSON.stringify(gen(120, 0.0003, 0.01, 9))) })}>含基准</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={res.performance} />
            <div style={{ marginTop: 8 }}><b>风险</b></div>
            <KV data={res.risk} />
            {res.benchmark && <div style={{ marginTop: 8 }}><b>基准</b><KV data={res.benchmark} /></div>}
          </div>}
        </Card>
      )}

      {tabk === 'compare' && (
        <Card title="快照对比（两份报告逐指标 diff）">
          <p style={{ fontSize: 12, color: '#666' }}>先各生成一份报告，再对比。下方用两组随机序列自动对比 A vs B。</p>
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={async () => {
              const a = await runReportPerformance({ returns: gen(100, 0.0006, 0.01, 1) })
              const b = await runReportPerformance({ returns: gen(100, 0.0002, 0.015, 3) })
              run(runReportCompare, { report_a: a, report_b: b, name_a: '策略A', name_b: '策略B' })
            }}>{loading ? '对比中…' : '生成并对比'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_metrics: res.n_metrics, improved_count: res.improved_count }} />
            <table style={{ width: '100%', marginTop: 8, borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>指标</th><th>{res.name_a}</th><th>{res.name_b}</th><th>Δ</th><th>更优</th></tr></thead>
              <tbody>{res.comparisons.map((c) => (
                <tr key={c.metric} style={{ borderTop: '1px solid #eee' }}>
                  <td>{c.metric}</td><td>{c[res.name_a]}</td><td>{c[res.name_b]}</td><td>{c.delta}</td>
                  <td style={{ color: c.improved ? '#1a7f37' : '#c0392b' }}>{c.improved ? 'A' : 'B'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>}
        </Card>
      )}

      {tabk === 'multi' && (
        <Card title="多策略对比看板（按 Sharpe 排名）">
          <p style={{ fontSize: 12, color: '#666' }}>curves: { '{' }"名称": 收益率数组{ '}' }。</p>
          <textarea id="rmf" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify({ 稳健: gen(120, 0.0006, 0.008, 1), 进取: gen(120, 0.001, 0.014, 2), 保守: gen(120, 0.0003, 0.006, 3) })} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runReportMulti, { curves: JSON.parse(document.getElementById('rmf').value) })}>{loading ? '对比中…' : '多策略对比'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_strategies: res.n_strategies, ranking: res.ranking_by_sharpe.join(' > ') }} />
            {res.rows.map((row) => (
              <div key={row.name} style={{ marginTop: 6, fontSize: 13 }}>
                <b>{row.name}</b>：Sharpe {row.report.performance.sharpe} / 年化 {row.report.performance.ann_return} / 回撤 {row.report.risk.max_drawdown}
              </div>
            ))}
          </div>}
        </Card>
      )}

      {tabk === 'periodic' && (
        <Card title="周期报告（按月/季分组绩效）">
          <p style={{ fontSize: 12, color: '#666' } }>returns + dates（ISO 日期，长度一致）；freq: M/W/Q/Y。</p>
          <textarea id="rpdf" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify(gen(120, 0.0005, 0.01, 5))} />
          <textarea id="rpdd" rows={2} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={Array.from({ length: 120 }, (_, i) => { const d = new Date(2024, 0, 1); d.setDate(d.getDate() + i); return d.toISOString().slice(0, 10) }).join(',')} />
          <div style={{ marginTop: 8 }}>
            <select id="rpdq" defaultValue="M" style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}><option value="M">月</option><option value="Q">季</option><option value="W">周</option><option value="Y">年</option></select>
            <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={() => run(runReportPeriodic, {
              returns: JSON.parse(document.getElementById('rpdf').value),
              dates: document.getElementById('rpdd').value.split(','),
              freq: document.getElementById('rpdq').value,
            })}>{loading ? '生成中…' : '生成周期报告'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ freq: res.freq, n_periods: res.n_periods, overall_sharpe: res.overall.sharpe }} />
            <table style={{ width: '100%', marginTop: 8, borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>期</th><th>n</th><th>年化</th><th>波动</th><th>Sharpe</th></tr></thead>
              <tbody>{res.periods.map((p) => (
                <tr key={p.period} style={{ borderTop: '1px solid #eee' }}><td>{p.period}</td><td>{p.n}</td><td>{p.ann_return}</td><td>{p.ann_vol}</td><td>{p.sharpe}</td></tr>
              ))}</tbody>
            </table>
          </div>}
        </Card>
      )}

      {tabk === 'dashboard' && (
        <Card title="风险看板（聚合波动/回撤/VaR/Beta/集中度）">
          <div style={{ marginTop: 4 }}>
            {num('rdd', 120, 'n')}{num('rddr', 0.0006, 'drift')}{num('rddv', 0.01, 'vol')}
          </div>
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runReportDashboard, {
              returns: gen(+document.getElementById('rdd').value, +document.getElementById('rddr').value, +document.getElementById('rddv').value, 7),
              weights: { A: 0.4, B: 0.3, C: 0.3 },
              benchmark: gen(120, 0.0003, 0.01, 9),
            })}>{loading ? '聚合中…' : '生成看板'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={res.dashboard} />
          </div>}
        </Card>
      )}

      {res && (
        <ExportBar sections={buildSections()} baseName={`report_${tabk}`} title={`QuantFlow 报告 - ${TAB_LABEL[tabk]}`} />
      )}

      {err && <div style={{ color: '#c0392b', marginTop: 10 }}>⚠ {err}</div>}
    </div>
  )
}
