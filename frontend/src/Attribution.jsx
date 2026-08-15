import { useState } from 'react'
import { runAttribution } from './api.js'

const EXAMPLES = {
  brinson: {
    method: 'brinson',
    name: '行业配置归因',
    groups: [
      { name: '科技', portfolio_weight: 0.6, benchmark_weight: 0.5, portfolio_return: 0.12, benchmark_return: 0.10 },
      { name: '金融', portfolio_weight: 0.4, benchmark_weight: 0.5, portfolio_return: 0.05, benchmark_return: 0.07 }
    ]
  },
  factor: {
    method: 'factor',
    name: '因子归因',
    factors: [
      { name: '市场', exposure: 1.1, factor_return: 0.08 },
      { name: '规模', exposure: 0.3, factor_return: 0.02 },
      { name: '价值', exposure: -0.2, factor_return: 0.015 }
    ],
    specific_return: 0.01
  },
  holdings: {
    method: 'holdings',
    name: '持仓贡献',
    holdings: [
      { symbol: 'AAPL', weight: 0.4, return_: 0.10 },
      { symbol: 'MSFT', weight: 0.35, return_: 0.06 },
      { symbol: 'BABA', weight: 0.25, return_: -0.04 }
    ]
  }
}

function StatCard({ label, value, hint, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '10px 12px', minWidth: 130 }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
      {hint ? <div style={{ fontSize: 11, color: '#9ca3af' }}>{hint}</div> : null}
    </div>
  )
}

function BarChart({ rows, labelKey, valueKey }) {
  if (!rows || rows.length === 0) return null
  const w = 720, h = 200, pad = 40
  const vals = rows.map((r) => r[valueKey] || 0)
  const max = Math.max(...vals, 0.0001)
  const min = Math.min(...vals, -0.0001)
  const scale = (max - min) || 1
  const n = rows.length
  const bw = (w - 2 * pad) / n
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`}>
      <line x1={pad} y1={pad} x2={w - pad} y2={pad} stroke="#eee" />
      {rows.map((r, i) => {
        const v = r[valueKey] || 0
        const x = pad + i * bw + bw * 0.2
        const bwv = bw * 0.6
        const y0 = pad + (0 - min) / scale * (h - 2 * pad)
        const y = pad + (v - min) / scale * (h - 2 * pad)
        const top = Math.min(y, y0)
        const hgt = Math.abs(y - y0) || 1
        const col = v >= 0 ? '#16a34a' : '#dc2626'
        return (
          <g key={i}>
            <rect x={x} y={top} width={bwv} height={hgt} fill={col} />
            <text x={x + bwv / 2} y={h - 8} fontSize="11" fill="#6b7280" textAnchor="middle">
              {String(r[labelKey]).slice(0, 6)}
            </text>
            <text x={x + bwv / 2} y={top - 4} fontSize="10" fill={col} textAnchor="middle">
              {(v * 100).toFixed(2)}%
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export default function Attribution() {
  const [method, setMethod] = useState('brinson')
  const [text, setText] = useState(JSON.stringify(EXAMPLES.brinson, null, 2))
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const loadExample = () => setText(JSON.stringify(EXAMPLES[method], null, 2))

  const run = async () => {
    setErr('')
    let payload
    try {
      payload = JSON.parse(text)
    } catch (e) {
      setErr('JSON 解析失败：' + e.message)
      return
    }
    if (!payload.method) payload.method = method
    setLoading(true)
    try {
      const res = await runAttribution(payload)
      setData(res)
    } catch (e) {
      setErr(e?.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const pct = (x) => (x == null ? '—' : (x * 100).toFixed(2) + '%')

  return (
    <div style={{ padding: 20, maxWidth: 980 }}>
      <h2 style={{ margin: '0 0 4px' }}>绩效归因增强 <span style={{ fontSize: 12, color: '#9ca3af' }}>V27</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>将组合收益拆解到板块（Brinson）、因子或持仓层面，定位收益来源。</p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        {['brinson', 'factor', 'holdings'].map((m) => (
          <button key={m} onClick={() => setMethod(m)} style={{
            padding: '6px 14px', borderRadius: 6, cursor: 'pointer',
            border: '1px solid ' + (method === m ? '#2563eb' : '#d1d5db'),
            background: method === m ? '#2563eb' : '#fff', color: method === m ? '#fff' : '#374151'
          }}>{m === 'brinson' ? 'Brinson 板块' : m === 'factor' ? '因子归因' : '持仓贡献'}</button>
        ))}
        <button onClick={loadExample} style={{ padding: '6px 12px', borderRadius: 6, border: '1px solid #d1d5db', background: '#f9fafb', cursor: 'pointer' }}>填入示例</button>
      </div>

      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} style={{
        width: '100%', fontFamily: 'monospace', fontSize: 13, padding: 10, border: '1px solid #d1d5db', borderRadius: 8
      }} />

      <div style={{ margin: '10px 0' }}>
        <button onClick={run} disabled={loading} style={{
          padding: '8px 20px', borderRadius: 6, background: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer'
        }}>{loading ? '计算中…' : '运行归因'}</button>
      </div>
      {err ? <div style={{ color: '#dc2626', marginBottom: 10 }}>{err}</div> : null}

      {data ? (
        <div>
          {data.method === 'brinson' && (
            <>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                <StatCard label="组合收益" value={pct(data.portfolio_return)} />
                <StatCard label="基准收益" value={pct(data.benchmark_return)} />
                <StatCard label="主动收益" value={pct(data.active_return)} tone={data.active_return >= 0 ? 'good' : 'bad'} />
                <StatCard label="配置效应" value={pct(data.total_allocation)} tone={data.total_allocation >= 0 ? 'good' : 'bad'} />
                <StatCard label="选股效应" value={pct(data.total_selection)} tone={data.total_selection >= 0 ? 'good' : 'bad'} />
                <StatCard label="交互效应" value={pct(data.total_interaction)} tone={data.total_interaction >= 0 ? 'good' : 'bad'} />
              </div>
              <BarChart rows={data.groups} labelKey="name" valueKey="total" />
              <table style={tbl}>
                <thead><tr>{['板块', '组合权重', '基准权重', '组合收益', '基准收益', '配置', '选股', '交互', '合计'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                <tbody>
                  {data.groups.map((g, i) => (
                    <tr key={i}>
                      <td style={td}>{g.name}</td>
                      <td style={td}>{pct(g.portfolio_weight)}</td>
                      <td style={td}>{pct(g.benchmark_weight)}</td>
                      <td style={td}>{pct(g.portfolio_return)}</td>
                      <td style={td}>{pct(g.benchmark_return)}</td>
                      <td style={td}>{pct(g.allocation)}</td>
                      <td style={td}>{pct(g.selection)}</td>
                      <td style={td}>{pct(g.interaction)}</td>
                      <td style={td}>{pct(g.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ fontSize: 12, color: data.checksum_ok ? '#16a34a' : '#dc2626', marginTop: 6 }}>
                {data.checksum_ok ? '✓ 效应之和 = 主动收益（校验通过）' : '⚠ 效应之和与主动收益不一致'}
              </div>
            </>
          )}

          {data.method === 'factor' && (
            <>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                <StatCard label="因子可解释" value={pct(data.explained_return)} />
                <StatCard label="特异性(α)" value={pct(data.specific_return)} />
                <StatCard label="总收益" value={pct(data.total_return)} />
                <StatCard label="可解释比例 R²" value={data.r_squared == null ? '—' : (data.r_squared * 100).toFixed(1) + '%'} />
              </div>
              <BarChart rows={data.factors} labelKey="name" valueKey="contribution" />
              <table style={tbl}>
                <thead><tr>{['因子', '暴露 β', '因子收益', '贡献'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                <tbody>
                  {data.factors.map((f, i) => (
                    <tr key={i}>
                      <td style={td}>{f.name}</td>
                      <td style={td}>{f.exposure}</td>
                      <td style={td}>{pct(f.factor_return)}</td>
                      <td style={td}>{pct(f.contribution)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {data.method === 'holdings' && (
            <>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                <StatCard label="组合总收益" value={pct(data.total_return)} tone={data.total_return >= 0 ? 'good' : 'bad'} />
              </div>
              <BarChart rows={data.holdings} labelKey="symbol" valueKey="contribution" />
              <table style={tbl}>
                <thead><tr>{['标的', '权重', '贡献', '累计贡献', '累计占比'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                <tbody>
                  {data.holdings.map((hh, i) => (
                    <tr key={i}>
                      <td style={td}>{hh.symbol}</td>
                      <td style={td}>{pct(hh.weight)}</td>
                      <td style={td}>{pct(hh.contribution)}</td>
                      <td style={td}>{pct(hh.cumulative)}</td>
                      <td style={td}>{hh.cumulative_pct == null ? '—' : (hh.cumulative_pct * 100).toFixed(1) + '%'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}

const tbl = { width: '100%', borderCollapse: 'collapse', marginTop: 8, fontSize: 13 }
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '2px solid #e5e7eb', color: '#374151' }
const td = { padding: '6px 8px', borderBottom: '1px solid #f0f0f0' }
