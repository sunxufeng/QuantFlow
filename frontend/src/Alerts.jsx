import { useCallback, useEffect, useState } from 'react'
import { listAlerts, createAlert, deleteAlert, toggleAlert, evaluateAlerts } from './api.js'

const METRICS = [
  ['price', '最新价'],
  ['daily_change_pct', '当日涨跌幅(%)'],
]
const OPERATORS = ['>', '<', '>=', '<=', 'cross_above', 'cross_below']

export default function Alerts() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [evalResult, setEvalResult] = useState(null)
  const [form, setForm] = useState({
    name: '',
    symbol: 'TEST.STOCK',
    metric: 'price',
    operator: '>',
    threshold: '',
    cooldown_minutes: 60,
  })

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return listAlerts()
      .then((r) => setItems(r.items || []))
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const submit = (e) => {
    e.preventDefault()
    setError('')
    const th = parseFloat(form.threshold)
    if (!form.name.trim() || !form.symbol.trim() || Number.isNaN(th)) {
      setError('请填写规则名称、标的与数值阈值')
      return
    }
    createAlert({
      name: form.name.trim(),
      symbol: form.symbol.trim(),
      metric: form.metric,
      operator: form.operator,
      threshold: th,
      cooldown_minutes: Number(form.cooldown_minutes) || 60,
    })
      .then(() => refresh())
      .catch((e) => setError(`创建失败: ${e.message}`))
  }

  const remove = (id) => deleteAlert(id).then(refresh).catch((e) => setError(e.message))
  const toggle = (rule) => toggleAlert(rule.id, { enabled: !rule.enabled }).then(refresh).catch((e) => setError(e.message))

  const runEval = () => {
    setError('')
    setEvalResult(null)
    evaluateAlerts()
      .then(setEvalResult)
      .catch((e) => setError(`评估失败: ${e.message}`))
  }

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>预警规则引擎（V2.3）</h3>
        <button className="qf-btn qf-btn-primary" onClick={runEval}>立即检查</button>
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        定义「标的 + 指标 + 算子 + 阈值」规则，满足条件时通过已配置的通知渠道（飞书/Webhook/邮件）推送，并带冷却去重。
      </div>

      {error && <div className="qf-error">{error}</div>}

      <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, maxWidth: 820, marginBottom: 16 }}>
        <label className="qf-field"><span>名称</span><input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="如 茅台价监控" /></label>
        <label className="qf-field"><span>标的</span><input value={form.symbol} onChange={(e) => set('symbol', e.target.value)} /></label>
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
        <label className="qf-field"><span>阈值</span><input value={form.threshold} onChange={(e) => set('threshold', e.target.value)} placeholder="如 1700" /></label>
        <label className="qf-field"><span>冷却(分钟)</span><input type="number" value={form.cooldown_minutes} onChange={(e) => set('cooldown_minutes', e.target.value)} /></label>
        <div style={{ gridColumn: '1 / -1' }}>
          <button className="qf-btn qf-btn-primary" type="submit">新增规则</button>
        </div>
      </form>

      {evalResult && (
        <div className="qf-an-block" style={{ marginBottom: 16 }}>
          <div className="qf-an-title">
            评估结果 · 评估 {evalResult.evaluated} 条 · 触发通知 {evalResult.notified} 条
          </div>
          <div className="qf-hint">
            {evalResult.results.map((r) => `${r.name}: ${r.triggered ? (r.notified ? '已通知' : '触发中(冷却)') : '未触发'}${r.value != null ? ` (值=${r.value})` : ''}`).join(' ｜ ')}
          </div>
        </div>
      )}

      {loading && <div className="qf-busy">加载中…</div>}
      {!loading && items.length === 0 && <div className="qf-hint">暂无预警规则。</div>}

      {items.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="qf-table">
            <thead>
              <tr><th>名称</th><th>标的</th><th>指标</th><th>条件</th><th>阈值</th><th>冷却</th><th>状态</th><th>触发次数</th><th>操作</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td>{r.symbol}</td>
                  <td>{r.metric}</td>
                  <td>{r.operator}</td>
                  <td>{r.threshold}</td>
                  <td>{r.cooldown_minutes}m</td>
                  <td>{r.enabled ? <span className="qf-up">启用</span> : <span className="qf-hint">停用</span>}</td>
                  <td>{r.trigger_count}</td>
                  <td>
                    <button className="qf-btn qf-btn-sm" onClick={() => toggle(r)}>{r.enabled ? '停用' : '启用'}</button>
                    <button className="qf-btn qf-btn-sm" onClick={() => remove(r.id)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
