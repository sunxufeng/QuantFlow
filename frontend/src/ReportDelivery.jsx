import React, { useEffect, useState } from 'react'
import {
  deliverReport, listDeliveryJobs, createDeliveryJob, deleteDeliveryJob,
  toggleDeliveryJob, runDeliveryJob, getDeliveryScheduler, startDeliveryScheduler,
  triggerDeliveryScheduler,
} from './api.js'

const btn = {
  padding: '6px 14px', borderRadius: 8, border: '1px solid #2f6df6',
  background: '#2f6df6', color: '#fff', cursor: 'pointer', fontSize: 13,
}
const Card = ({ title, children }) => (
  <div style={{ background: '#fff', border: '1px solid #e6e9ef', borderRadius: 12, padding: 16, marginBottom: 14 }}>
    <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 14 }}>{title}</div>
    {children}
  </div>
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }
const pre = { background: '#f7f9fc', borderRadius: 8, padding: 10, fontSize: 12, overflowX: 'auto' }

const TYPES = [
  ['performance', '综合绩效'],
  ['risk', '风险看板'],
  ['periodic', '周期报告'],
  ['consolidate', '综合报告'],
]
const SAMPLE_PARAMS = {
  performance: '{\n  "returns": [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.003, -0.005, 0.01, 0.008]\n}',
  risk: '{\n  "returns": [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.003, -0.005, 0.01, 0.008],\n  "weights": {"A": 0.6, "B": 0.4}\n}',
  periodic: '{\n  "returns": [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.003, -0.005, 0.01, 0.008],\n  "dates": ["2024-01-01","2024-01-02","2024-01-03","2024-01-04","2024-01-05","2024-01-06","2024-01-07","2024-01-08","2024-01-09","2024-01-10"],\n  "freq": "W"\n}',
  consolidate: '{\n  "returns": [0.01, -0.02, 0.015, 0.005, -0.01, 0.02, 0.003, -0.005, 0.01, 0.008]\n}',
}

export default function ReportDelivery() {
  const [jobs, setJobs] = useState([])
  const [sched, setSched] = useState(null)
  const [name, setName] = useState('')
  const [rtype, setRtype] = useState('performance')
  const [params, setParams] = useState(SAMPLE_PARAMS.performance)
  const [interval, setInterval_] = useState(60)
  const [msg, setMsg] = useState(null)
  const [deliverRes, setDeliverRes] = useState(null)
  const [deliverParams, setDeliverParams] = useState(SAMPLE_PARAMS.performance)
  const [deliverType, setDeliverType] = useState('performance')

  const loadJobs = async () => { try { setJobs(await listDeliveryJobs()) } catch {} }
  const loadSched = async () => { try { setSched(await getDeliveryScheduler()) } catch {} }
  useEffect(() => { loadJobs(); loadSched() }, [])

  const addJob = async () => {
    setMsg(null)
    try {
      const p = JSON.parse(params)
      await createDeliveryJob({ name: name || '未命名投递', report_type: rtype, params: p, interval_minutes: +interval })
      setMsg({ ok: true, text: '投递任务已添加' })
      setName(''); setParams(SAMPLE_PARAMS[rtype])
      await loadJobs()
    } catch (e) { setMsg({ ok: false, text: jsonErr(e.message) }) }
  }
  const remove = async (id) => { await deleteDeliveryJob(id); loadJobs() }
  const toggle = async (id, enabled) => { await toggleDeliveryJob(id, !enabled); loadJobs() }
  const runOne = async (id) => {
    try { const r = await runDeliveryJob(id); setMsg({ ok: r.status === 'delivered', text: `执行结果：${r.status}${r.sent != null ? `，已推送 ${r.sent} 渠道` : ''}` }) }
    catch (e) { setMsg({ ok: false, text: jsonErr(e.message) }) }
  }
  const doDeliver = async () => {
    setDeliverRes(null); setMsg(null)
    try {
      const p = JSON.parse(deliverParams)
      const r = await deliverReport({ report_type: deliverType, params: p })
      setDeliverRes(r)
    } catch (e) { setMsg({ ok: false, text: jsonErr(e.message) }) }
  }
  const startSched = async () => { await startDeliveryScheduler(); loadSched() }
  const triggerAll = async () => {
    try { const r = await triggerDeliveryScheduler(); setMsg({ ok: true, text: `自动投递触发：执行 ${r.executed} 个，已投递 ${r.delivered} 个` }) }
    catch (e) { setMsg({ ok: false, text: jsonErr(e.message) }) }
  }
  const onType = (t) => { setRtype(t); setParams(SAMPLE_PARAMS[t]) }
  const onDeliverType = (t) => { setDeliverType(t); setDeliverParams(SAMPLE_PARAMS[t]) }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>定时报告自动投递（V102）</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>
        定时生成绩效 / 风险 / 周期 / 综合报告并推送至「设置 → 通知渠道」已配置的飞书 / 邮件 / Webhook。
      </p>

      <Card title="立即投递一份报告（手动）">
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <select value={deliverType} onChange={(e) => onDeliverType(e.target.value)} style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
            {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <button style={btn} onClick={doDeliver}>生成并推送</button>
        </div>
        <textarea rows={4} value={deliverParams} onChange={(e) => setDeliverParams(e.target.value)}
          style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} />
        {deliverRes && (
          <div style={{ background: '#f7f9fc', borderRadius: 8, padding: 10, fontSize: 12, marginTop: 8 }}>
            已推送 {deliverRes.sent} 个渠道，指标 {deliverRes.metric_count} 项。
            <pre style={pre}>{JSON.stringify(deliverRes.metrics, null, 1)}</pre>
          </div>
        )}
      </Card>

      <Card title="投递任务管理">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
          <button style={{ ...btn, background: '#27ae60' }} onClick={addJob}>添加任务</button>
          <button style={{ ...btn, background: '#fff', color: '#2f6df6' }} disabled={sched?.running} onClick={startSched}>
            {sched?.running ? `自动投递运行中（${sched?.interval_minutes}分钟）` : '启动自动投递'}
          </button>
          <button style={{ ...btn, background: '#fff', color: '#2f6df6' }} onClick={triggerAll}>立即触发全部</button>
          {sched && <span style={{ fontSize: 12, color: '#888' }}>上次执行 {sched.last_executed ?? 0} 个</span>}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          <input placeholder="任务名称" value={name} onChange={(e) => setName(e.target.value)} style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc', width: 140 }} />
          <select value={rtype} onChange={(e) => onType(e.target.value)} style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
            {TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <input placeholder="间隔(分钟)" value={interval} onChange={(e) => setInterval_(e.target.value)} style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc', width: 90 }} />
        </div>
        <textarea placeholder="报告参数 JSON" rows={3} value={params} onChange={(e) => setParams(e.target.value)}
          style={{ width: '100%', fontFamily: 'monospace', fontSize: 12, marginBottom: 8 }} />
        {msg && <div style={{ color: msg.ok ? '#1e7e34' : '#c0392b', fontSize: 12, marginBottom: 8 }}>{msg.text}</div>}

        <div style={{ borderTop: '1px solid #eee', paddingTop: 8 }}>
          {jobs.length === 0 && <div style={{ fontSize: 12, color: '#999' }}>暂无投递任务</div>}
          {jobs.map((j) => (
            <div key={j.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0', borderBottom: '1px dashed #f0f0f0', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, fontSize: 13 }}>{j.name}</span>
              <span style={{ fontSize: 11, color: '#888' }}>{TYPES.find(([k]) => k === j.report_type)?.[1] || j.report_type}</span>
              <span style={{ fontSize: 11, color: '#888' }}>每 {j.interval_minutes} 分钟</span>
              <span style={{ fontSize: 11, color: j.enabled ? '#1e7e34' : '#999' }}>{j.enabled ? '启用' : '停用'}</span>
              <span style={{ fontSize: 11, color: '#888' }}>{j.last_run_status ? `上次:${j.last_run_status}` : '未执行'}</span>
              <span style={{ flex: 1 }} />
              <button style={{ ...btn, padding: '4px 10px', background: '#fff', color: '#2f6df6' }} onClick={() => runOne(j.id)}>执行</button>
              <button style={{ ...btn, padding: '4px 10px', background: '#fff', color: '#2f6df6' }} onClick={() => toggle(j.id, j.enabled)}>{j.enabled ? '停用' : '启用'}</button>
              <button style={{ ...btn, padding: '4px 10px', background: '#fff', color: '#c0392b', borderColor: '#c0392b' }} onClick={() => remove(j.id)}>删除</button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
