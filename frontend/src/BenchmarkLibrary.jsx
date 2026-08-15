import { useEffect, useState } from 'react'
import { listBenchmarks, saveBenchmark, deleteBenchmark, runBenchmarkCompare } from './api.js'

const inp = { padding: '8px 10px', border: '1px solid #d1d5db', borderRadius: 6 }

function Stat({ label, value, tone }) {
  const color = tone === 'good' ? '#16a34a' : tone === 'bad' ? '#dc2626' : '#1f2937'
  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px' }}>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
    </div>
  )
}

export default function BenchmarkLibrary() {
  const [items, setItems] = useState([])
  const [name, setName] = useState('')
  const [symbols, setSymbols] = useState('CSI300, CSI500')
  const [weights, setWeights] = useState('')
  const [runId, setRunId] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const refresh = async () => {
    try {
      const d = await listBenchmarks()
      setItems(d.items || [])
    } catch (e) {
      setErr(e?.message || '读取失败')
    }
  }

  useEffect(() => { refresh() }, [])

  const save = async () => {
    setErr('')
    if (!name.trim()) { setErr('请填写基准名称'); return }
    const syms = symbols.split(',').map((s) => s.trim()).filter(Boolean)
    const w = weights ? weights.split(',').map((x) => parseFloat(x.trim())).filter((n) => !isNaN(n)) : null
    if (!syms.length) { setErr('请至少填写一个标的'); return }
    try {
      await saveBenchmark({ name: name.trim(), symbols: syms, weights: w })
      setName(''); setWeights('')
      await refresh()
    } catch (e) {
      setErr(e?.message || '保存失败')
    }
  }

  const del = async (id) => {
    try { await deleteBenchmark(id); await refresh() } catch (e) { setErr(e?.message || '删除失败') }
  }

  const compare = async (bench) => {
    setErr('')
    if (!runId.trim()) { setErr('请填写用于对比的回测 run_id'); return }
    setLoading(true)
    try {
      const def = { name: bench.name }
      if (bench.symbols && bench.symbols.length) {
        def.symbols = bench.symbols
        if (bench.weights) def.weights = bench.weights
      } else if (bench.values) {
        def.values = bench.values
      }
      const res = await runBenchmarkCompare({ run_id: runId.trim(), benchmarks: [def] })
      setResult({ bench: bench.name, res })
    } catch (e) {
      setErr(e?.message || '对比失败')
    } finally {
      setLoading(false)
    }
  }

  const rel = result?.res?.composite_relative || {}

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>基准自选库 <span style={{ fontSize: 12, color: '#16a34a' }}>V26</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        保存自定义基准（标的篮子或显式序列）到本地，便于在「基准对比」场景中一键复用，无需重复填写。
      </p>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <input placeholder="基准名称" value={name} onChange={(e) => setName(e.target.value)} style={{ ...inp, width: 180 }} />
        <input placeholder="标的逗号分隔" value={symbols} onChange={(e) => setSymbols(e.target.value)} style={{ ...inp, width: 220 }} />
        <input placeholder="权重逗号分隔(可选,等权)" value={weights} onChange={(e) => setWeights(e.target.value)} style={{ ...inp, width: 200 }} />
        <button onClick={save}
          style={{ padding: '8px 16px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
          保存基准
        </button>
      </div>

      {err ? <div style={{ color: '#dc2626' }}>{err}</div> : null}

      <h3 style={{ fontSize: 14 }}>已保存基准（{items.length}）</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 16 }}>
        <thead>
          <tr style={{ color: '#6b7280', textAlign: 'right' }}>
            <th style={{ textAlign: 'left' }}>名称</th>
            <th style={{ textAlign: 'left' }}>类型</th>
            <th style={{ textAlign: 'left' }}>标的 / 权重</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.bench_id} style={{ borderTop: '1px solid #f1f5f9' }}>
              <td>{b.name}</td>
              <td>{b.mode === 'explicit' ? '显式序列' : '标的篮子'}</td>
              <td>{b.symbols ? `${b.symbols.join(', ')}${b.weights ? ' / ' + b.weights.join(',') : ''}` : '—'}</td>
              <td>
                <button onClick={() => compare(b)}
                  style={{ marginRight: 8, padding: '4px 10px', border: '1px solid #2563eb', color: '#2563eb', background: '#fff', borderRadius: 6, cursor: 'pointer' }}>
                  对比
                </button>
                <button onClick={() => del(b.bench_id)}
                  style={{ padding: '4px 10px', border: '1px solid #dc2626', color: '#dc2626', background: '#fff', borderRadius: 6, cursor: 'pointer' }}>
                  删除
                </button>
              </td>
            </tr>
          ))}
          {!items.length ? (
            <tr><td colSpan={4} style={{ color: '#9ca3af', padding: '8px 0' }}>暂无保存的基准</td></tr>
          ) : null}
        </tbody>
      </table>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <input placeholder="用于对比的回测 run_id" value={runId} onChange={(e) => setRunId(e.target.value)} style={{ ...inp, width: 280 }} />
        <span style={{ fontSize: 12, color: '#9ca3af' }}>点上方「对比」按钮，用选中基准对比该回测</span>
        {loading ? <span style={{ color: '#2563eb' }}>对比中…</span> : null}
      </div>

      {result ? (
        <div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
            <Stat label="超额收益" value={rel.excess_return == null ? '—' : `${(rel.excess_return * 100).toFixed(2)}%`} tone={(rel.excess_return || 0) >= 0 ? 'good' : 'bad'} />
            <Stat label="Beta" value={rel.beta == null ? '—' : rel.beta.toFixed(3)} />
            <Stat label="Alpha" value={rel.alpha == null ? '—' : `${(rel.alpha * 100).toFixed(2)}%`} tone={(rel.alpha || 0) >= 0 ? 'good' : 'bad'} />
            <Stat label="跟踪误差" value={rel.tracking_error == null ? '—' : `${(rel.tracking_error * 100).toFixed(2)}%`} />
            <Stat label="信息比率" value={rel.information_ratio == null ? '—' : rel.information_ratio.toFixed(3)} />
          </div>
          {(result.res.benchmarks || []).map((bm, i) => (
            <div key={i} style={{ fontSize: 12, color: '#6b7280' }}>
              基准「{bm.name}」权重 {bm.weight} · 收益 {(bm.curve?.[bm.curve.length - 1]?.value || 0).toFixed(0)}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
