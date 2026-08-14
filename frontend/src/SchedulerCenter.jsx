import { useCallback, useEffect, useState } from 'react'
import {
  schedulerCenter,
  createSchedule,
  runSchedule,
  toggleSchedule,
  deleteSchedule,
  listWorkflows,
  fetchWorkflow,
  marketSyncNow,
  triggerAlertScheduler,
} from './api.js'

const fmtTime = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

const STATUS_COLOR = {
  success: '#16a34a', failed: '#e11d48', never_run: '#64748b', running: '#6366f1',
  submitted: '#6366f1', done: '#16a34a',
}

export default function SchedulerCenter() {
  const [center, setCenter] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const [runMsg, setRunMsg] = useState('')

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return schedulerCenter()
      .then(setCenter)
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // 新建计划表单
  const [showForm, setShowForm] = useState(false)
  const [workflows, setWorkflows] = useState([])
  const [form, setForm] = useState({
    name: '', workflowId: '', trigger_type: 'interval', minutes: 60, cron: '0 9 * * *', enabled: true,
  })

  const openForm = () => {
    setError('')
    setShowForm(true)
    listWorkflows().then((ws) => setWorkflows(ws || [])).catch(() => setWorkflows([]))
  }

  const onCreate = (e) => {
    e.preventDefault()
    if (!form.name.trim() || !form.workflowId) {
      setError('请填写计划名称并选择工作流')
      return
    }
    setError('')
    setBusyId('create')
    const cfg = form.trigger_type === 'interval'
      ? JSON.stringify({ minutes: Number(form.minutes) || 60 })
      : form.cron.trim()
    fetchWorkflow(form.workflowId)
      .then((wf) => {
        const payload = {
          nodes: wf.nodes || [],
          edges: wf.edges || [],
          workflow_name: wf.name || form.name,
        }
        return createSchedule({
          name: form.name.trim(),
          trigger_type: form.trigger_type,
          trigger_cfg: cfg,
          payload,
          enabled: form.enabled,
        })
      })
      .then(() => { setShowForm(false); setForm({ name: '', workflowId: '', trigger_type: 'interval', minutes: 60, cron: '0 9 * * *', enabled: true }); return refresh() })
      .catch((e) => setError(`创建失败: ${e.message}`))
      .finally(() => setBusyId(''))
  }

  const onRun = (id) => {
    setBusyId(id)
    setRunMsg('')
    runSchedule(id)
      .then((r) => { setRunMsg(`已触发计划 ${id}：run_id=${r.run_id}（${r.status}）`); refresh() })
      .catch((e) => setError(`触发失败: ${e.message}`))
      .finally(() => setBusyId(''))
  }
  const onToggle = (s) => { setBusyId(s.id); toggleSchedule(s.id, !s.enabled).then(refresh).catch((e) => setError(e.message)).finally(() => setBusyId('')) }
  const onDelete = (id) => { setBusyId(id); deleteSchedule(id).then(refresh).catch((e) => setError(e.message)).finally(() => setBusyId('')) }

  const onSync = () => {
    setBusyId('sync')
    marketSyncNow().then(refresh).catch((e) => setError(e.message)).finally(() => setBusyId(''))
  }
  const onEval = () => {
    setBusyId('eval')
    triggerAlertScheduler().then(refresh).catch((e) => setError(e.message)).finally(() => setBusyId(''))
  }

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>调度中心（V5.2）</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="qf-btn" onClick={refresh} disabled={loading}>刷新</button>
          <button className="qf-btn qf-btn-primary" onClick={openForm}>新建计划</button>
        </div>
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        集中查看与手动触发所有定时任务：系统自动任务（行情同步、预警巡检）与自定义工作流定时计划。
      </div>

      {error && <div className="qf-error">{error}</div>}
      {runMsg && <div className="qf-success">{runMsg}</div>}

      {loading && !center && <div className="qf-busy">加载中…</div>}

      {center && (
        <>
          {/* 系统自动任务 */}
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', margin: '8px 0' }}>系统自动任务</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            <div className="qf-mcard" style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div className="qf-mcard-label">行情自动同步</div>
                <div className="qf-mcard-value" style={{ fontSize: 13, color: STATUS_COLOR[center.data_sync?.status] || '#334155' }}>
                  {center.data_sync?.status || '—'} ｜ 库内 K 线 {center.data_sync?.stored_bars ?? 0}
                </div>
                <div className="qf-hint" style={{ fontSize: 12 }}>
                  上次 {fmtTime(center.data_sync?.finished_at)} ｜ 写入 {center.data_sync?.bars_written ?? 0}
                </div>
              </div>
              <button className="qf-btn qf-btn-primary" onClick={onSync} disabled={busyId === 'sync'}>立即同步</button>
            </div>
            <div className="qf-mcard" style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div className="qf-mcard-label">预警自动巡检</div>
                <div className="qf-mcard-value" style={{ fontSize: 13, color: center.alert_eval?.running ? '#16a34a' : '#64748b' }}>
                  {center.alert_eval?.running ? `每 ${center.alert_eval?.interval_minutes} 分钟` : (center.alert_eval?.disabled ? '已停用' : '未运行')}
                </div>
                <div className="qf-hint" style={{ fontSize: 12 }}>
                  上次 {fmtTime(center.alert_eval?.last_run_at)} ｜ 下次 ~{fmtTime(center.alert_eval?.next_run_at)}
                </div>
              </div>
              <button className="qf-btn qf-btn-primary" onClick={onEval} disabled={busyId === 'eval'}>立即巡检</button>
            </div>
          </div>

          {/* 工作流定时计划 */}
          <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', margin: '18px 0 8px' }}>
            工作流定时计划（{center.workflow_schedules?.length || 0}）
          </div>

          {center.workflow_schedules?.length === 0 && (
            <div className="qf-hint">暂无自定义定时计划。点击「新建计划」把某个工作流设为定时运行。</div>
          )}

          {center.workflow_schedules?.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table className="qf-table">
                <thead>
                  <tr><th>名称</th><th>触发</th><th>状态</th><th>上次运行</th><th>下次运行</th><th>运行结果</th><th>操作</th></tr>
                </thead>
                <tbody>
                  {center.workflow_schedules.map((s) => (
                    <tr key={s.id}>
                      <td>{s.name}</td>
                      <td>
                        {s.trigger_type === 'cron'
                          ? `cron ${s.trigger_cfg}`
                          : `每 ${JSON.parse(s.trigger_cfg).minutes} 分钟`}
                      </td>
                      <td>{s.enabled ? <span className="qf-up">启用</span> : <span className="qf-hint">停用</span>}</td>
                      <td className="qf-hint">{fmtTime(s.last_run_at)}</td>
                      <td className="qf-hint">{fmtTime(s.next_run_at)}</td>
                      <td style={{ color: STATUS_COLOR[s.last_run_status] || '#334155' }}>{s.last_run_status || '—'}</td>
                      <td>
                        <button className="qf-btn qf-btn-sm" onClick={() => onRun(s.id)} disabled={busyId === s.id}>触发</button>
                        <button className="qf-btn qf-btn-sm" onClick={() => onToggle(s)} disabled={busyId === s.id}>{s.enabled ? '停用' : '启用'}</button>
                        <button className="qf-btn qf-btn-sm" onClick={() => onDelete(s.id)} disabled={busyId === s.id}>删除</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {showForm && (
            <form onSubmit={onCreate} style={{ marginTop: 18, border: '1px solid var(--border)', borderRadius: 10, padding: 16, background: '#fff' }}>
              <div style={{ fontWeight: 600, marginBottom: 10 }}>新建定时计划</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, maxWidth: 720 }}>
                <label className="qf-field"><span>计划名称</span><input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="如 每日开盘回测" /></label>
                <label className="qf-field"><span>选择工作流</span>
                  <select value={form.workflowId} onChange={(e) => set('workflowId', e.target.value)}>
                    <option value="">— 请选择 —</option>
                    {(workflows || []).map((w) => <option key={w.id} value={w.id}>{w.name || w.id}</option>)}
                  </select>
                </label>
                <label className="qf-field"><span>触发类型</span>
                  <select value={form.trigger_type} onChange={(e) => set('trigger_type', e.target.value)}>
                    <option value="interval">固定间隔</option>
                    <option value="cron">Cron</option>
                  </select>
                </label>
                {form.trigger_type === 'interval' ? (
                  <label className="qf-field"><span>间隔（分钟）</span>
                    <input type="number" value={form.minutes} onChange={(e) => set('minutes', e.target.value)} />
                  </label>
                ) : (
                  <label className="qf-field"><span>Cron 表达式</span>
                    <input value={form.cron} onChange={(e) => set('cron', e.target.value)} placeholder="0 9 * * *" />
                  </label>
                )}
                <label className="qf-field" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} /> 启用
                </label>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button className="qf-btn qf-btn-primary" type="submit" disabled={busyId === 'create'}>创建</button>
                <button className="qf-btn" type="button" onClick={() => setShowForm(false)}>取消</button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  )
}
