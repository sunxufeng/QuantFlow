import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  factorLibraryList,
  factorLibraryCreate,
  factorLibraryUpdate,
  factorLibraryDelete,
  factorAnalyze,
} from './api.js'

const EMPTY = { name: '', expression: '', category: '自定义', description: '', params: {} }

function FactorForm({ initial, onSubmit, onCancel, busy }) {
  const [form, setForm] = useState(initial)
  const [paramsText, setParamsText] = useState(
    initial.params ? JSON.stringify(initial.params) : '{}',
  )
  const [err, setErr] = useState('')

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submit = (e) => {
    e.preventDefault()
    let params = {}
    try {
      params = paramsText.trim() ? JSON.parse(paramsText) : {}
    } catch {
      setErr('参数需为合法 JSON 对象')
      return
    }
    onSubmit({ ...form, params }, setErr)
  }

  return (
    <div className="qf-modal-mask" onClick={onCancel}>
      <div className="qf-modal" onClick={(e) => e.stopPropagation()}>
        <div className="qf-modal-head">
          <h3>{initial.id ? '编辑因子' : '新建因子'}</h3>
          <button className="qf-btn qf-btn-sm" onClick={onCancel}>×</button>
        </div>
        <div className="qf-modal-body">
          <form className="qf-prop-form" onSubmit={submit}>
            <div className="qf-prop-field">
              <label className="qf-prop-label">名称</label>
              <input
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="如 20日动量"
                required
              />
            </div>
            <div className="qf-prop-field">
              <label className="qf-prop-label">类别</label>
              <input
                value={form.category}
                onChange={(e) => set('category', e.target.value)}
                placeholder="动量 / 反转 / 风险 / 自定义"
              />
            </div>
            <div className="qf-prop-field">
              <label className="qf-prop-label">表达式（pandas）</label>
              <input
                value={form.expression}
                onChange={(e) => set('expression', e.target.value)}
                placeholder="close.pct_change(20)"
                required
              />
            </div>
            <div className="qf-prop-field">
              <label className="qf-prop-label">说明</label>
              <input
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="因子含义"
              />
            </div>
            <div className="qf-prop-field">
              <label className="qf-prop-label">附加参数（JSON）</label>
              <input
                value={paramsText}
                onChange={(e) => setParamsText(e.target.value)}
                placeholder='{"period": 20}'
              />
            </div>
            {err && <div className="qf-inline-error">{err}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="qf-btn" onClick={onCancel}>取消</button>
              <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
                {busy ? '保存中…' : '保存'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

function IcChart({ series }) {
  const W = 560
  const H = 130
  const pad = 8
  const vals = series.map((p) => Number(p.ic) || 0)
  const lo = Math.min(-0.05, ...vals)
  const hi = Math.max(0.05, ...vals)
  const span = hi - lo || 1
  const stepX = series.length > 1 ? (W - pad * 2) / (series.length - 1) : 0
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  const zeroY = y(0)
  const path = series
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * stepX).toFixed(1)},${y(Number(p.ic) || 0).toFixed(1)}`)
    .join(' ')
  const mean = vals.reduce((a, b) => a + b, 0) / (vals.length || 1)
  return (
    <div className="qf-an-block">
      <div className="qf-an-title">IC 时间序列（共 {series.length} 期）</div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 130 }}>
        <line x1={pad} y1={zeroY} x2={W - pad} y2={zeroY} stroke="#cbd5e1" strokeWidth="1" strokeDasharray="3 3" />
        <path d={path} fill="none" stroke="#2563eb" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <line x1={pad} y1={y(mean)} x2={W - pad} y2={y(mean)} stroke="#dc2626" strokeWidth="1" strokeDasharray="4 2" />
      </svg>
      <div className="qf-hint">红线为 IC 均值 {mean.toFixed(4)}</div>
    </div>
  )
}

function DecayChart({ decay }) {
  const W = 560
  const H = 120
  const pad = 8
  const items = decay.filter((d) => d.ic != null)
  if (!items.length) return null
  const vals = items.map((d) => Number(d.ic))
  const lo = Math.min(0, ...vals)
  const hi = Math.max(0, ...vals)
  const span = hi - lo || 1
  const bw = (W - pad * 2) / items.length
  const y = (v) => H - pad - ((v - lo) / span) * (H - pad * 2)
  return (
    <div className="qf-an-block">
      <div className="qf-an-title">IC 衰减（滞后 L 期）</div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: 120 }}>
        {items.map((d, i) => {
          const v = Number(d.ic)
          const x = pad + i * bw
          const top = y(Math.max(v, 0))
          const bottom = y(Math.min(v, 0))
          return (
            <g key={d.lag}>
              <rect x={x + 2} y={top} width={bw - 4} height={Math.max(1, bottom - top)} fill={v >= 0 ? '#15803d' : '#dc2626'} />
              <text x={x + bw / 2} y={H - 1} fill="#64748b" fontSize="9" textAnchor="middle">L{d.lag}</text>
            </g>
          )
        })}
        <line x1={pad} y1={y(0)} x2={W - pad} y2={y(0)} stroke="#cbd5e1" strokeWidth="1" />
      </svg>
    </div>
  )
}

function AnalyzePanel({ factor, onClose }) {
  const [symbols, setSymbols] = useState('TEST.STOCK,TEST.BANK')
  const [start, setStart] = useState('2024-01-01')
  const [end, setEnd] = useState('2024-02-01')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState(null)

  const run = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setReport(null)
    try {
      const res = await factorAnalyze({
        symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
        start,
        end,
        expression: factor.expression,
        factor: 'factor',
        forward_return: 'fwd_return',
      })
      setReport(res.report)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="qf-modal-mask" onClick={onClose}>
      <div className="qf-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 620 }}>
        <div className="qf-modal-head">
          <h3>因子分析 · {factor.name}</h3>
          <button className="qf-btn qf-btn-sm" onClick={onClose}>×</button>
        </div>
        <div className="qf-modal-body">
          <form className="qf-prop-form" onSubmit={run}>
            <div className="qf-prop-field">
              <label className="qf-prop-label">标的（逗号分隔）</label>
              <input value={symbols} onChange={(e) => setSymbols(e.target.value)} />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <div className="qf-prop-field" style={{ flex: 1 }}>
                <label className="qf-prop-label">开始</label>
                <input value={start} onChange={(e) => setStart(e.target.value)} />
              </div>
              <div className="qf-prop-field" style={{ flex: 1 }}>
                <label className="qf-prop-label">结束</label>
                <input value={end} onChange={(e) => setEnd(e.target.value)} />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="qf-btn" onClick={onClose}>关闭</button>
              <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
                {busy ? '分析中…' : '运行分析'}
              </button>
            </div>
          </form>
          {error && <div className="qf-error">{error}</div>}
          {report && (
            <div style={{ marginTop: 12 }}>
              <div className="qf-mcards">
                <div className="qf-mcard">
                  <div className="qf-mcard-label">IC 均值</div>
                  <div className="qf-mcard-value">{report.ic?.mean?.toFixed?.(4) ?? '-'}</div>
                </div>
                <div className="qf-mcard">
                  <div className="qf-mcard-label">ICIR</div>
                  <div className="qf-mcard-value">{report.ic?.ir?.toFixed?.(4) ?? '-'}</div>
                </div>
                <div className="qf-mcard">
                  <div className="qf-mcard-label">IC&gt;0 占比</div>
                  <div className="qf-mcard-value">{((report.ic?.pct_positive ?? 0) * 100).toFixed?.(1) ?? '-'}%</div>
                </div>
                <div className="qf-mcard">
                  <div className="qf-mcard-label">多空收益</div>
                  <div className="qf-mcard-value">
                    {report.quantile_returns?.long_short?.toFixed?.(4) ?? '-'}
                  </div>
                </div>
              </div>

              {report.ic?.series?.length > 1 && (
                <IcChart series={report.ic.series} />
              )}
              {report.ic_decay?.length > 0 && (
                <DecayChart decay={report.ic_decay} />
              )}

              {report.quantile_returns?.by_quantile && (
                <div className="qf-hint" style={{ marginTop: 8 }}>
                  分层收益（q1 最低 → q{report.n_quantiles} 最高）：
                  {Object.entries(report.quantile_returns.by_quantile).map(([q, v]) => (
                    <span key={q} style={{ marginLeft: 6 }}>
                      {q}: {v != null ? v.toFixed(4) : '-'}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function FactorLibrary() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [category, setCategory] = useState('')
  const [editing, setEditing] = useState(null) // null | 'new' | factor
  const [busyForm, setBusyForm] = useState(false)
  const [analyzing, setAnalyzing] = useState(null)

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return factorLibraryList(category)
      .then((res) => setItems(res.items || []))
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [category])

  useEffect(() => { refresh() }, [refresh])

  const categories = useMemo(() => {
    const set = new Set(items.map((f) => f.category).filter(Boolean))
    return ['', ...Array.from(set)]
  }, [items])

  const onDelete = async (fac) => {
    if (!window.confirm(`确认删除因子「${fac.name}」？`)) return
    try {
      await factorLibraryDelete(fac.id)
      await refresh()
    } catch (e) {
      setError(`删除失败: ${e.message}`)
    }
  }

  const onSubmitForm = async (payload, setErr) => {
    setBusyForm(true)
    try {
      if (editing && editing.id) {
        await factorLibraryUpdate(editing.id, payload)
      } else {
        await factorLibraryCreate(payload)
      }
      setEditing(null)
      await refresh()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusyForm(false)
    }
  }

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>因子库（N3）</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            className="qf-name-input"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            aria-label="按类别筛选"
            style={{ width: 140 }}
          >
            {categories.map((c) => (
              <option key={c || '__all'} value={c}>{c || '全部类别'}</option>
            ))}
          </select>
          <button className="qf-btn qf-btn-primary" onClick={() => setEditing(EMPTY)}>＋ 新建因子</button>
        </div>
      </div>
      {error && <div className="qf-error">{error}</div>}
      {loading && <div className="qf-busy">加载中…</div>}
      {!loading && items.length === 0 && (
        <div className="qf-hint">暂无因子，点击「新建因子」添加，或重启服务加载内置因子。</div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12, marginTop: 12 }}>
        {items.map((fac) => (
          <div key={fac.id} className="qf-mcard" style={{ alignItems: 'stretch' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div className="qf-mcard-label">{fac.category}</div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                {fac.owner_id ? (
                  <span className="qf-run-pill" style={{ fontSize: 10, background: '#e0f2fe', color: '#0369a1' }}>自定义</span>
                ) : (
                  <span className="qf-run-pill" style={{ fontSize: 10, background: '#dcfce7', color: '#15803d' }}>内置</span>
                )}
                <div className="qf-run-pill" style={{ fontSize: 10 }}>{fac.id.slice(0, 10)}</div>
              </div>
            </div>
            <div className="qf-mcard-value" style={{ fontSize: 14 }}>{fac.name}</div>
            <div className="qf-hint" style={{ wordBreak: 'break-all' }}>{fac.expression}</div>
            {fac.description && <div className="qf-hint">{fac.description}</div>}
            <div style={{ display: 'flex', gap: 6, marginTop: 8, justifyContent: 'flex-end' }}>
              <button className="qf-btn qf-btn-sm" onClick={() => setAnalyzing(fac)}>分析</button>
              <button className="qf-btn qf-btn-sm" onClick={() => setEditing(fac)}>编辑</button>
              <button className="qf-btn qf-btn-sm" onClick={() => onDelete(fac)}>删除</button>
            </div>
          </div>
        ))}
      </div>
      {editing && (
        <FactorForm
          initial={editing}
          onSubmit={onSubmitForm}
          onCancel={() => setEditing(null)}
          busy={busyForm}
        />
      )}
      {analyzing && <AnalyzePanel factor={analyzing} onClose={() => setAnalyzing(null)} />}
    </div>
  )
}
