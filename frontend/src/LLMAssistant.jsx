import { useCallback, useEffect, useRef, useState } from 'react'
import { llmStatus, llmAssist } from './api.js'

export default function LLMAssistant() {
  const [status, setStatus] = useState(null)
  const [messages, setMessages] = useState([
    { role: 'assistant', content: '你好，我是 QuantFlow 策略助手。描述你的需求（如「写一个均线金叉策略」），我来给建议。' },
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [system, setSystem] = useState('')
  const endRef = useRef(null)

  const refreshStatus = useCallback(() => {
    llmStatus().then(setStatus).catch(() => {})
  }, [])

  useEffect(() => { refreshStatus() }, [refreshStatus])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (e) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || busy) return
    setError('')
    setBusy(true)
    const history = messages
      .filter((m) => m.role !== 'assistant' || true)
      .map((m) => ({ role: m.role, content: m.content }))
    setMessages((ms) => [...ms, { role: 'user', content: text }])
    setInput('')
    try {
      const res = await llmAssist({
        prompt: text,
        system: system.trim() || undefined,
        history,
      })
      setMessages((ms) => [...ms, { role: 'assistant', content: res.text }])
    } catch (err) {
      setError(err.message)
      setMessages((ms) => [...ms, { role: 'assistant', content: `⚠️ 调用失败：${err.message}` }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="qf-monitor" style={{ padding: 16, maxWidth: 820, margin: '0 auto' }}>
      <div className="qf-result-head">
        <h3>LLM 策略助手（N1）</h3>
        {status && (
          <span className={`qf-run-pill ${status.configured ? 'qf-run-succeeded' : 'qf-run-running'}`}>
            {status.provider}{status.configured ? '（已配置真实模型）' : '（Mock 演示）'}
          </span>
        )}
      </div>
      {status && !status.configured && (
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          当前为 Mock 演示模式。启用真实大模型：部署环境设置
          <code> QF_LLM_PROVIDER=openai</code> 与 <code>QF_LLM_API_KEY</code>（可选
          <code> QF_LLM_BASE_URL / QF_LLM_MODEL</code>）。
        </div>
      )}
      {error && <div className="qf-error">{error}</div>}
      <div
        style={{
          background: '#fff',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 12,
          minHeight: 320,
          maxHeight: 480,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
              background: m.role === 'user' ? 'var(--primary)' : '#f1f5f9',
              color: m.role === 'user' ? '#fff' : '#0f172a',
              padding: '8px 12px',
              borderRadius: 12,
              maxWidth: '80%',
              whiteSpace: 'pre-wrap',
              fontSize: 13,
            }}
          >
            {m.content}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="qf-prop-form" style={{ marginTop: 10 }} onSubmit={send}>
        <div className="qf-prop-field">
          <label className="qf-prop-label">系统提示（可选，覆盖默认角色）</label>
          <input
            value={system}
            onChange={(e) => setSystem(e.target.value)}
            placeholder="如：你是一名专注量价的资深量化研究员"
          />
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="qf-name-input"
            style={{ flex: 1 }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="描述你的策略需求…"
            disabled={busy}
          />
          <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
            {busy ? '思考中…' : '发送'}
          </button>
        </div>
      </form>
    </div>
  )
}
