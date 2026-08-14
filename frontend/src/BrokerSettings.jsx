import { useCallback, useEffect, useState } from 'react'
import { brokerGetConfig, brokerSaveConfig, brokerTestConfig } from './api.js'

const BROKERS = [
  { value: 'none', label: '未配置（暂不接入实盘）' },
  { value: 'simulated', label: '模拟盘（无需凭证，本地撮合）' },
  { value: 'universal', label: '通用券商（OpenAPI 兼容）' },
  { value: 'easytrade', label: 'EasyTrade 类柜台' },
  { value: 'xuntou', label: '迅投 / QMT 类柜台' },
]

export default function BrokerSettings() {
  const [cfg, setCfg] = useState({
    broker: 'none',
    api_key: '',
    api_secret: '',
    base_url: '',
    account_id: '',
  })
  const [loaded, setLoaded] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [savedAt, setSavedAt] = useState('')
  const [test, setTest] = useState(null) // {ok, broker, configured, detail, status}

  const refresh = useCallback(() => {
    setBusy(true)
    brokerGetConfig()
      .then((c) => {
        setCfg({
          broker: c.broker || 'none',
          api_key: '', // 不回显明文 key，仅提示是否已配置
          api_secret: '',
          base_url: c.base_url || '',
          account_id: '',
        })
        setLoaded(true)
        setError('')
      })
      .catch((e) => setError(`加载配置失败: ${e.message}`))
      .finally(() => setBusy(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const set = (patch) => {
    setCfg((c) => ({ ...c, ...patch }))
    setDirty(true)
    setTest(null)
  }

  const onSave = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await brokerSaveConfig({
        broker: cfg.broker,
        api_key: cfg.api_key,
        api_secret: cfg.api_secret,
        base_url: cfg.base_url,
        account_id: cfg.account_id,
      })
      setSavedAt(new Date().toLocaleString())
      setDirty(false)
      setCfg((c) => ({ ...c, api_key: '', api_secret: '' }))
    } catch (err) {
      setError(`保存失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const onTest = async () => {
    setBusy(true)
    setError('')
    setTest(null)
    try {
      const res = await brokerTestConfig({
        broker: cfg.broker,
        api_key: cfg.api_key,
        api_secret: cfg.api_secret,
        base_url: cfg.base_url,
        account_id: cfg.account_id,
      })
      setTest(res)
    } catch (err) {
      setError(`测试失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const isReal = cfg.broker !== 'none' && cfg.broker !== 'simulated'

  return (
    <div className="qf-monitor" style={{ padding: 16, maxWidth: 760, margin: '0 auto' }}>
      <div className="qf-result-head">
        <h3>券商凭证配置（V1.7）</h3>
        {savedAt && <span className="qf-run-pill qf-run-succeeded">已保存 {savedAt}</span>}
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        配置券商凭证后，实盘网关（LiveExecutionGateway）将自动读取此处设置；凭证申请中也可先保存，
        不影响其余功能开发。配置持久化到服务端数据库，敏感字段 GET 接口返回脱敏值。
      </div>
      {error && <div className="qf-error" style={{ marginBottom: 10 }}>{error}</div>}

      <form className="qf-prop-form" onSubmit={onSave}>
        <div className="qf-prop-field">
          <label className="qf-prop-label">券商类型</label>
          <select value={cfg.broker} onChange={(e) => set({ broker: e.target.value })}>
            {BROKERS.map((b) => (
              <option key={b.value} value={b.value}>{b.label}</option>
            ))}
          </select>
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">API Key</label>
          <input
            type="password"
            value={cfg.api_key}
            onChange={(e) => set({ api_key: e.target.value })}
            placeholder={loaded ? '（已配置，留空则保持不变）' : '申请中…'}
            autoComplete="new-password"
          />
          <span className="qf-prop-hint">仅本地持久化，GET 接口返回脱敏值（****尾4位）。</span>
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">API Secret</label>
          <input
            type="password"
            value={cfg.api_secret}
            onChange={(e) => set({ api_secret: e.target.value })}
            placeholder={loaded ? '（已配置，留空则保持不变）' : '申请中…'}
            autoComplete="new-password"
          />
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">Base URL（实盘柜台地址）</label>
          <input
            value={cfg.base_url}
            disabled={!isReal}
            onChange={(e) => set({ base_url: e.target.value })}
            placeholder="https://api.broker.example/v1"
          />
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">资金账户 ID</label>
          <input
            value={cfg.account_id}
            disabled={!isReal}
            onChange={(e) => set({ account_id: e.target.value })}
            placeholder="如 99887766"
          />
          <span className="qf-prop-hint">真实券商类型下需填写 Base URL 与账户 ID。</span>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy || !dirty}>
            {busy ? '处理中…' : '保存配置'}
          </button>
          <button type="button" className="qf-btn" onClick={onTest} disabled={busy}>
            测试连接
          </button>
          {dirty && <span className="qf-prop-hint" style={{ alignSelf: 'center' }}>有未保存的修改</span>}
        </div>
      </form>

      {test && (
        <div
          style={{
            marginTop: 14,
            padding: 12,
            borderRadius: 8,
            border: `1px solid ${test.ok ? 'var(--ok, #22c55e)' : 'var(--err, #ef4444)'}`,
            background: test.ok ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {test.ok ? '✅ 连通成功' : '❌ 不可用'} · {test.broker}
            {test.status ? ` (HTTP ${test.status})` : ''}
          </div>
          <div style={{ fontSize: 12 }}>{test.detail}</div>
        </div>
      )}
    </div>
  )
}
