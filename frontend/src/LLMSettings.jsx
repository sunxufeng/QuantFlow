import { useCallback, useEffect, useState } from 'react'
import { llmGetConfig, llmSaveConfig, llmTestConfig } from './api.js'

const PROVIDERS = [
  { value: 'mock', label: 'Mock（演示模式，无需 Key）' },
  { value: 'openai', label: 'OpenAI 兼容（自定义大模型）' },
]

export default function LLMSettings() {
  const [cfg, setCfg] = useState({
    provider: 'mock',
    base_url: 'https://api.openai.com/v1',
    api_key: '',
    model: 'gpt-4o-mini',
    system_prompt: '',
    temperature: 0.2,
    max_tokens: 1024,
    timeout: 90,
    enabled: true,
  })
  const [loaded, setLoaded] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [savedAt, setSavedAt] = useState('')
  const [test, setTest] = useState(null) // {ok, provider, model, sample|error}

  const refresh = useCallback(() => {
    setBusy(true)
    llmGetConfig()
      .then((c) => {
        setCfg({
          provider: c.provider,
          base_url: c.base_url,
          api_key: '', // 不回显明文 key，仅提示是否已配置
          model: c.model,
          system_prompt: c.system_prompt || '',
          temperature: c.temperature,
          max_tokens: c.max_tokens,
          timeout: c.timeout,
          enabled: c.enabled,
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
      const payload = {
        provider: cfg.provider,
        base_url: cfg.base_url,
        // 仅当用户填写了新 key 才上传；空串表示保留现有 key
        api_key: cfg.api_key,
        model: cfg.model,
        system_prompt: cfg.system_prompt,
        temperature: Number(cfg.temperature),
        max_tokens: Number(cfg.max_tokens),
        timeout: Number(cfg.timeout),
        enabled: cfg.enabled,
      }
      const saved = await llmSaveConfig(payload)
      setSavedAt(new Date().toLocaleString())
      setDirty(false)
      // 不回显明文
      setCfg((c) => ({ ...c, api_key: '' }))
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
      // 用当前表单（含可能未保存的新 key）即时验证，不落库
      const res = await llmTestConfig({
        provider: cfg.provider,
        base_url: cfg.base_url,
        api_key: cfg.api_key,
        model: cfg.model,
        system_prompt: cfg.system_prompt,
        temperature: Number(cfg.temperature),
        max_tokens: Number(cfg.max_tokens),
        timeout: Number(cfg.timeout),
        enabled: cfg.enabled,
      })
      setTest(res)
    } catch (err) {
      setError(`测试失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const isOpenAI = cfg.provider === 'openai'

  return (
    <div className="qf-monitor" style={{ padding: 16, maxWidth: 760, margin: '0 auto' }}>
      <div className="qf-result-head">
        <h3>LLM 配置（V1.4）</h3>
        {savedAt && <span className="qf-run-pill qf-run-succeeded">已保存 {savedAt}</span>}
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        在此添加自定义大模型（OpenAI 兼容协议：DeepSeek / 通义 / 自建网关 / beaigo 等）。
        配置持久化到服务端数据库；保存后「LLM 助手」立即生效。
      </div>
      {error && <div className="qf-error" style={{ marginBottom: 10 }}>{error}</div>}

      <form className="qf-prop-form" onSubmit={onSave}>
        <div className="qf-prop-field">
          <label className="qf-prop-label">运行模式</label>
          <select value={cfg.provider} onChange={(e) => set({ provider: e.target.value })}>
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">
            启用
            <input
              type="checkbox"
              checked={cfg.enabled}
              onChange={(e) => set({ enabled: e.target.checked })}
              style={{ marginLeft: 8 }}
            />
            <span className="qf-prop-hint" style={{ marginLeft: 6 }}>
              （关闭则强制走 Mock 演示）
            </span>
          </label>
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">Base URL（兼容 /chat/completions）</label>
          <input
            value={cfg.base_url}
            disabled={!isOpenAI}
            onChange={(e) => set({ base_url: e.target.value })}
            placeholder="https://api.openai.com/v1"
          />
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">API Key</label>
          <input
            type="password"
            value={cfg.api_key}
            disabled={!isOpenAI}
            onChange={(e) => set({ api_key: e.target.value })}
            placeholder={loaded ? '（已配置，留空则保持不变）' : 'sk-...'}
            autoComplete="new-password"
          />
          <span className="qf-prop-hint">仅本地持久化，GET 接口返回脱敏值。</span>
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">模型名</label>
          <input
            value={cfg.model}
            disabled={!isOpenAI}
            onChange={(e) => set({ model: e.target.value })}
            placeholder="gpt-4o-mini"
          />
        </div>

        <div className="qf-prop-field">
          <label className="qf-prop-label">系统提示（可选，覆盖内置默认角色）</label>
          <textarea
            rows={3}
            value={cfg.system_prompt}
            onChange={(e) => set({ system_prompt: e.target.value })}
            placeholder="如：你是一名专注量价的资深量化研究员"
          />
        </div>

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 160 }}>
            <label className="qf-prop-label">温度</label>
            <input
              type="number"
              step="0.1"
              min="0"
              max="2"
              value={cfg.temperature}
              onChange={(e) => set({ temperature: e.target.value })}
            />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 160 }}>
            <label className="qf-prop-label">最大 Token</label>
            <input
              type="number"
              step="1"
              min="1"
              value={cfg.max_tokens}
              onChange={(e) => set({ max_tokens: e.target.value })}
            />
          </div>
          <div className="qf-prop-field" style={{ flex: 1, minWidth: 160 }}>
            <label className="qf-prop-label">超时（秒）</label>
            <input
              type="number"
              step="1"
              min="1"
              value={cfg.timeout}
              onChange={(e) => set({ timeout: e.target.value })}
            />
          </div>
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
            {test.ok ? '✅ 连通成功' : '❌ 连接失败'} · {test.provider} / {test.model}
          </div>
          {test.ok ? (
            <div style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>样例返回：{test.sample}</div>
          ) : (
            <div style={{ fontSize: 12, color: '#b91c1c' }}>{test.error}</div>
          )}
        </div>
      )}
    </div>
  )
}
