import { useCallback, useEffect, useState } from 'react'
import {
  notificationsList,
  notificationsCreate,
  notificationsDelete,
  notificationsTest,
} from './api.js'

const TYPE_LABELS = { webhook: 'Webhook', feishu: '飞书机器人', email: '邮件(SMTP)' }

function configSummary(type, config) {
  if (type === 'webhook') return config.url || '-'
  if (type === 'feishu') return config.webhook || '-'
  if (type === 'email') {
    const to = Array.isArray(config.to_addrs)
      ? config.to_addrs.join(', ')
      : (config.to_addrs || '-')
    return `${config.smtp_host || '?'}:${config.smtp_port || 465} → ${to}`
  }
  return '-'
}

function ChannelForm({ onSubmit, onCancel, busy }) {
  const [type, setType] = useState('webhook')
  const [name, setName] = useState('')
  const [cfg, setCfg] = useState({})
  const [err, setErr] = useState('')

  const set = (k, v) => setCfg((c) => ({ ...c, [k]: v }))

  const submit = (e) => {
    e.preventDefault()
    if (!name.trim()) {
      setErr('请填写名称')
      return
    }
    setErr('')
    onSubmit({ type, name: name.trim(), config: cfg }, setErr)
  }

  return (
    <div className="qf-modal-mask" onClick={onCancel}>
      <div className="qf-modal" onClick={(e) => e.stopPropagation()}>
        <div className="qf-modal-head">
          <h3>新增通知渠道</h3>
          <button className="qf-btn qf-btn-sm" onClick={onCancel}>×</button>
        </div>
        <div className="qf-modal-body">
          <form className="qf-prop-form" onSubmit={submit}>
            <div className="qf-prop-field">
              <label className="qf-prop-label">类型</label>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                <option value="webhook">Webhook（通用 JSON）</option>
                <option value="feishu">飞书自定义机器人</option>
                <option value="email">邮件（SMTP）</option>
              </select>
            </div>
            <div className="qf-prop-field">
              <label className="qf-prop-label">名称</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 运维告警" />
            </div>
            {type === 'webhook' && (
              <div className="qf-prop-field">
                <label className="qf-prop-label">URL</label>
                <input value={cfg.url || ''} onChange={(e) => set('url', e.target.value)} placeholder="https://..." />
              </div>
            )}
            {type === 'feishu' && (
              <>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">Webhook</label>
                  <input value={cfg.webhook || ''} onChange={(e) => set('webhook', e.target.value)} placeholder="https://open.feishu.cn/..." />
                </div>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">加签 Secret（可选）</label>
                  <input value={cfg.secret || ''} onChange={(e) => set('secret', e.target.value)} placeholder="可选" />
                </div>
              </>
            )}
            {type === 'email' && (
              <>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">SMTP 主机</label>
                  <input value={cfg.smtp_host || ''} onChange={(e) => set('smtp_host', e.target.value)} placeholder="smtp.example.com" />
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <div className="qf-prop-field" style={{ flex: 1 }}>
                    <label className="qf-prop-label">端口</label>
                    <input value={cfg.smtp_port || 465} onChange={(e) => set('smtp_port', e.target.value)} />
                  </div>
                  <div className="qf-prop-field" style={{ flex: 1 }}>
                    <label className="qf-prop-label">TLS</label>
                    <select value={cfg.use_tls === false ? 'false' : 'true'} onChange={(e) => set('use_tls', e.target.value === 'true')}>
                      <option value="true">SMTP_SSL (465)</option>
                      <option value="false">STARTTLS (587)</option>
                    </select>
                  </div>
                </div>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">用户名（可选）</label>
                  <input value={cfg.username || ''} onChange={(e) => set('username', e.target.value)} />
                </div>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">密码/授权码（可选）</label>
                  <input type="password" value={cfg.password || ''} onChange={(e) => set('password', e.target.value)} />
                </div>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">发件人（可选）</label>
                  <input value={cfg.from_addr || ''} onChange={(e) => set('from_addr', e.target.value)} placeholder="缺省用用户名" />
                </div>
                <div className="qf-prop-field">
                  <label className="qf-prop-label">收件人（逗号分隔）</label>
                  <input value={cfg.to_addrs || ''} onChange={(e) => set('to_addrs', e.target.value)} placeholder="a@x.com, b@x.com" />
                </div>
              </>
            )}
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

export default function Notifications() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busyForm, setBusyForm] = useState(false)
  const [adding, setAdding] = useState(false)
  const [testing, setTesting] = useState(null)

  const refresh = useCallback(() => {
    setLoading(true)
    setError('')
    return notificationsList()
      .then(setItems)
      .catch((e) => setError(`加载失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const onDelete = async (c) => {
    if (!window.confirm(`确认删除渠道「${c.name}」？`)) return
    try {
      await notificationsDelete(c.id)
      await refresh()
    } catch (e) {
      setError(`删除失败: ${e.message}`)
    }
  }

  const onTest = async (c) => {
    setTesting(c.id)
    setError('')
    try {
      await notificationsTest(c.id)
    } catch (e) {
      setError(`测试发送失败: ${e.message}`)
    } finally {
      setTesting(null)
    }
  }

  const onSubmitForm = async (payload, setErr) => {
    setBusyForm(true)
    setError('')
    try {
      await notificationsCreate(payload)
      setAdding(null)
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
        <h3>通知渠道（N5）</h3>
        <button className="qf-btn qf-btn-primary" onClick={() => setAdding(true)}>＋ 新增渠道</button>
      </div>
      {error && <div className="qf-error">{error}</div>}
      {loading && <div className="qf-busy">加载中…</div>}
      {!loading && items.length === 0 && (
        <div className="qf-hint">暂无渠道，点击「新增渠道」配置 Webhook / 飞书 / 邮件(SMTP)。</div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12, marginTop: 12 }}>
        {items.map((c) => (
          <div key={c.id} className="qf-mcard" style={{ alignItems: 'stretch' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div className="qf-mcard-label">{TYPE_LABELS[c.type] || c.type}</div>
              <div className="qf-run-pill" style={{ fontSize: 10 }}>{c.enabled ? '启用' : '停用'}</div>
            </div>
            <div className="qf-mcard-value" style={{ fontSize: 14 }}>{c.name}</div>
            <div className="qf-hint" style={{ wordBreak: 'break-all' }}>{configSummary(c.type, c.config)}</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 8, justifyContent: 'flex-end' }}>
              <button className="qf-btn qf-btn-sm" disabled={testing === c.id} onClick={() => onTest(c)}>
                {testing === c.id ? '发送中…' : '测试'}
              </button>
              <button className="qf-btn qf-btn-sm" onClick={() => onDelete(c)}>删除</button>
            </div>
          </div>
        ))}
      </div>
      {adding && (
        <ChannelForm onSubmit={onSubmitForm} onCancel={() => setAdding(null)} busy={busyForm} />
      )}
    </div>
  )
}
