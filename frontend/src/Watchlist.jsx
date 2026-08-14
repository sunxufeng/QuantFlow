import { useCallback, useEffect, useState } from 'react'
import {
  watchlistMonitor,
  addWatchlist,
  removeWatchlist,
  createAlert,
  deleteAlert,
  toggleAlert,
  triggerAlertScheduler,
  alertSchedulerStatus,
} from './api.js'

const METRICS = [
  ['price', '最新价'],
  ['daily_change_pct', '当日涨跌幅(%)'],
]
const OPERATORS = ['>', '<', '>=', '<=', 'cross_above', 'cross_below']

const fmtTime = (epoch) => {
  if (!epoch) return '—'
  const d = new Date(epoch * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export default function Watchlist() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [input, setInput] = useState('')
  const [sched, setSched] = useState(null)
  const [evalResult, setEvalResult] = useState(null)
  const [addingFor, setAddingFor] = useState(null) // symbol currently adding alert for
  const [form, setForm] = useState({
    metric: 'price',
    operator: '>',
    threshold: '',
    cooldown_minutes: 60,
  })

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return watchlistMonitor()
      .then((r) => setItems(r.items || []))
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])
  useEffect(() => {
    alertSchedulerStatus().then(setSched).catch(() => setSched(null))
  }, [])

  const onAdd = (e) => {
    e.preventDefault()
    const s = input.trim().toUpperCase()
    if (!s) return
    addWatchlist(s).then(refresh).catch((e) => setError(e.message))
    setInput('')
  }

  const onRemove = (sym) => removeWatchlist(sym).then(refresh).catch((e) => setError(e.message))

  const openAdd = (sym) => {
    setAddingFor(sym)
    setForm({ metric: 'price', operator: '>', threshold: '', cooldown_minutes: 60 })
    setError('')
  }

  const submitAlert = (e) => {
    e.preventDefault()
    const th = parseFloat(form.threshold)
    if (Number.isNaN(th)) {
      setError('请填写数值阈值')
      return
    }
    const name = `${addingFor} ${form.operator} ${form.metric === 'price' ? th : th + '%'}`
    createAlert({
      name,
      symbol: addingFor,
      metric: form.metric,
      operator: form.operator,
      threshold: th,
      cooldown_minutes: Number(form.cooldown_minutes) || 60,
    })
      .then(() => { setAddingFor(null); return refresh() })
      .catch((e) => setError(`创建失败: ${e.message}`))
  }

  const onDelete = (id) => deleteAlert(id).then(refresh).catch((e) => setError(e.message))
  const onToggle = (rule) =>
    toggleAlert(rule.id, { enabled: !rule.enabled }).then(refresh).catch((e) => setError(e.message))

  const runEval = () => {
    setError('')
    setEvalResult(null)
    triggerAlertScheduler()
      .then((r) => {
        setEvalResult(r)
        setSched((s) => (s ? { ...s, last_run_at: r.last_run_at } : s))
        refresh()
      })
      .catch((e) => setError(`巡检失败: ${e.message}`))
  }

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>自选股监控 + 价格预警（V5.1）</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {sched && (
            <span className="qf-badge" title="每 N 分钟自动评估一次启用中的规则">
              {sched.running ? `自动巡检·${sched.interval_minutes}分钟` : (sched.disabled ? '自动巡检·已停用' : '自动巡检·未运行')}
            </span>
          )}
          {sched && sched.running && (
            <span className="qf-hint" style={{ fontSize: 12 }}>
              上次 {fmtTime(sched.last_run_at)}
            </span>
          )}
          <button className="qf-btn qf-btn-primary" onClick={runEval}>立即评估</button>
          <button className="qf-btn" onClick={refresh}>刷新</button>
        </div>
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        管理自选标的并查看实时行情快照；点击「添加预警」为某标的绑定价格规则，满足条件时通过通知渠道推送。自选股与预警规则均持久化（SQLite）。
      </div>

      {error && <div className="qf-error">{error}</div>}

      {evalResult && (
        <div className="qf-an-block" style={{ marginBottom: 16 }}>
          <div className="qf-an-title">
            评估结果 · 评估 {evalResult.evaluated} 条 · 触发通知 {evalResult.notified} 条
          </div>
          <div className="qf-hint">
            {(evalResult.results || []).map((r) => `${r.name}: ${r.triggered ? (r.notified ? '已通知' : '触发中(冷却)') : '未触发'}${r.value != null ? ` (值=${r.value})` : ''}`).join(' ｜ ')}
          </div>
        </div>
      )}

      <form onSubmit={onAdd} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="添加自选标的，如 TEST.STOCK"
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}
        />
        <button className="qf-btn qf-btn-primary" type="submit">添加自选</button>
      </form>

      {loading && <div className="qf-busy">加载中…</div>}
      {!loading && items.length === 0 && <div className="qf-hint">自选股为空，添加标的后即可监控并设置价格预警。</div>}

      {items.map((it) => {
        const up = it.quote?.change_pct != null && it.quote.change_pct >= 0
        return (
          <div key={it.symbol} style={{ border: '1px solid var(--border)', borderRadius: 10, marginBottom: 14, overflow: 'hidden' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 14, padding: '12px 14px', background: '#f8fafc' }}>
              <strong style={{ fontSize: 15 }}>{it.symbol}</strong>
              {it.quote ? (
                <>
                  <span style={{ fontSize: 15, fontWeight: 700 }}>{Number(it.quote.last).toFixed(3)}</span>
                  <span className={up ? 'qf-up' : 'qf-down'}>
                    {it.quote.change_pct != null ? `${it.quote.change_pct.toFixed(2)}%` : '-'}
                  </span>
                  <span className="qf-hint">{it.quote.date}</span>
                </>
              ) : (
                <span className="qf-hint">无行情数据</span>
              )}
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                <button className="qf-btn qf-btn-sm" onClick={() => openAdd(it.symbol)}>添加预警</button>
                <button className="qf-btn qf-btn-sm" onClick={() => onRemove(it.symbol)}>移除</button>
              </span>
            </div>

            {addingFor === it.symbol && (
              <form onSubmit={submitAlert} style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, padding: 12, background: '#fff' }}>
                <label className="qf-field"><span>指标</span>
                  <select value={form.metric} onChange={(e) => set('metric', e.target.value)}>
                    {METRICS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </label>
                <label className="qf-field"><span>算子</span>
                  <select value={form.operator} onChange={(e) => set('operator', e.target.value)}>
                    {OPERATORS.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                </label>
                <label className="qf-field"><span>阈值</span>
                  <input value={form.threshold} onChange={(e) => set('threshold', e.target.value)} placeholder="如 1700" />
                </label>
                <label className="qf-field"><span>冷却(分钟)</span>
                  <input type="number" value={form.cooldown_minutes} onChange={(e) => set('cooldown_minutes', e.target.value)} />
                </label>
                <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8 }}>
                  <button className="qf-btn qf-btn-primary" type="submit">保存预警</button>
                  <button className="qf-btn" type="button" onClick={() => setAddingFor(null)}>取消</button>
                </div>
              </form>
            )}

            <div style={{ padding: '4px 14px 12px', background: '#fff' }}>
              {it.alerts.length === 0 ? (
                <div className="qf-hint" style={{ padding: '6px 0' }}>该标的暂无预警规则。</div>
              ) : (
                <table className="qf-table">
                  <thead>
                    <tr><th>名称</th><th>指标</th><th>条件</th><th>阈值</th><th>冷却</th><th>状态</th><th>触发次数</th><th>上次触发</th><th>操作</th></tr>
                  </thead>
                  <tbody>
                    {it.alerts.map((r) => (
                      <tr key={r.id}>
                        <td>{r.name}</td>
                        <td>{r.metric}</td>
                        <td>{r.operator}</td>
                        <td>{r.threshold}</td>
                        <td>{r.cooldown_minutes}m</td>
                        <td>{r.enabled ? <span className="qf-up">启用</span> : <span className="qf-hint">停用</span>}</td>
                        <td>{r.trigger_count}</td>
                        <td className="qf-hint">{fmtTime(r.last_triggered)}</td>
                        <td>
                          <button className="qf-btn qf-btn-sm" onClick={() => onToggle(r)}>{r.enabled ? '停用' : '启用'}</button>
                          <button className="qf-btn qf-btn-sm" onClick={() => onDelete(r.id)}>删除</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
