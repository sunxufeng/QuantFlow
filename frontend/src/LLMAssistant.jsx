import { useCallback, useEffect, useRef, useState } from 'react'
import { llmStatus, llmAssist, batchGenerateCompare } from './api.js'

export default function LLMAssistant() {
  const [status, setStatus] = useState(null)
  const [messages, setMessages] = useState([
    { role: 'assistant', content: '你好，我是 QuantFlow 策略助手。描述你的需求（如「写一个均线金叉策略」），我来给建议。' },
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [system, setSystem] = useState('')

  // V3.4 批量生成对比
  const [batchText, setBatchText] = useState('动量因子策略，用 TEST.STOCK\n均线金叉策略，用 TEST.BANK\n期货多空策略，用 TEST.FUTURE')
  const [batchUseLlm, setBatchUseLlm] = useState(true)
  const [batchResult, setBatchResult] = useState(null)
  const [batchBusy, setBatchBusy] = useState(false)
  const [batchError, setBatchError] = useState('')

  const runBatch = useCallback(async () => {
    setBatchError('')
    const prompts = batchText.split('\n').map((s) => s.trim()).filter(Boolean)
    if (prompts.length === 0) {
      setBatchError('请至少输入一个策略描述（每行一个）')
      return
    }
    setBatchBusy(true)
    try {
      const res = await batchGenerateCompare({ prompts, use_llm: batchUseLlm })
      setBatchResult(res)
    } catch (err) {
      setBatchError(err.message)
    } finally {
      setBatchBusy(false)
    }
  }, [batchText, batchUseLlm])

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
      {status && status.routing && status.chain && (
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          多模型路由（按序 fallback）：
          {status.chain.map((c, i) => (
            <span key={i} style={{ marginLeft: i === 0 ? 6 : 4 }}>
              {i > 0 && <span style={{ color: '#94a3b8' }}> → </span>}
              <b>{c.name}</b>
              <span className="qf-hint">:{c.model}</span>
              <span style={{ color: c.configured ? '#16a34a' : '#94a3b8' }}>
                {c.configured ? ' ✓' : ' ✗'}
              </span>
            </span>
          ))}
        </div>
      )}
      {status && !status.configured && (
        <div className="qf-hint" style={{ marginBottom: 8 }}>
          当前为 Mock 演示模式。启用真实大模型：前往顶部导航
          <b>「LLM 配置」</b> 填写 Base URL / API Key / 模型后保存并测试即可，无需改环境变量。
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

      {/* V3.4 批量生成并对比回测 */}
      <div style={{ marginTop: 18, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
        <div className="qf-result-head">
          <h3>批量生成对比（V3.4）</h3>
          <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              type="checkbox"
              checked={batchUseLlm}
              onChange={(e) => setBatchUseLlm(e.target.checked)}
            />
            使用 LLM 生成
          </label>
        </div>
        <p className="qf-hint" style={{ marginBottom: 8 }}>
          每行一个策略描述（最多 5 条），一键生成并运行回测，下方对比净值曲线与绩效指标。
        </p>
        <textarea
          value={batchText}
          onChange={(e) => setBatchText(e.target.value)}
          rows={3}
          style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0', fontFamily: 'inherit' }}
        />
        <div style={{ marginTop: 8 }}>
          <button className="qf-btn qf-btn-primary" onClick={runBatch} disabled={batchBusy}>
            {batchBusy ? '生成并回测中…' : '批量生成并对比'}
          </button>
        </div>
        {batchError && <div className="qf-error" style={{ marginTop: 8 }}>{batchError}</div>}

        {batchResult && (
          <BatchCompare result={batchResult} />
        )}
      </div>
    </div>
  )
}

// 批量对比渲染：归一化净值叠加 + 绩效指标表
function BatchCompare({ result }) {
  const items = (result.items || []).filter((it) => it.ok)
  if (items.length === 0) {
    const errs = (result.items || []).filter((it) => !it.ok)
    return (
      <div className="qf-hint" style={{ marginTop: 10 }}>
        无可用结果{errs.length ? `（${errs.map((e) => e.error).join('；')}）` : ''}
      </div>
    )
  }
  const metricKeys = Array.from(
    new Set(items.flatMap((it) => Object.keys(it.metrics || {})))
  )
  const W = 520
  const H = 180
  const allPts = items.flatMap((it) => it.curve_pct || [])
  const maxPct = Math.max(0.01, ...allPts.map((p) => p.pct))
  const minPct = Math.min(0, ...allPts.map((p) => p.pct))
  const span = Math.max(0.01, maxPct - minPct)
  const colors = ['#22c55e', '#38bdf8', '#f59e0b', '#a78bfa', '#ef4444']
  const xOf = (i, n) => (n <= 1 ? 0 : (i / (n - 1)) * (W - 40)) + 20
  const yOf = (pct) => H - 20 - ((pct - minPct) / span) * (H - 40)

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
        <div className="qf-reports-title" style={{ fontSize: 13, marginBottom: 8 }}>归一化净值曲线（累计收益率 %）</div>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }}>
          <line x1="20" y1={H - 20} x2={W - 20} y2={H - 20} stroke="#cbd5e1" strokeWidth="1" />
          <line x1="20" y1={yOf(0)} x2={W - 20} y2={yOf(0)} stroke="#94a3b8" strokeWidth="1" strokeDasharray="4 3" />
          {items.map((it, idx) => {
            const pts = it.curve_pct || []
            const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i, pts.length)} ${yOf(p.pct)}`).join(' ')
            return (
              <path key={idx} d={d} fill="none" stroke={colors[idx % colors.length]} strokeWidth="2" />
            )
          })}
        </svg>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 6 }}>
          {items.map((it, idx) => (
            <span key={idx} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 10, height: 10, background: colors[idx % colors.length], borderRadius: 2, display: 'inline-block' }} />
              {it.name || it.prompt}
            </span>
          ))}
        </div>
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12, marginTop: 10, overflowX: 'auto' }}>
        <table className="qf-table" style={{ width: '100%' }}>
          <thead>
            <tr>
              <th>指标</th>
              {items.map((it, idx) => (
                <th key={idx}>{it.name || it.prompt}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((k) => (
              <tr key={k}>
                <td style={{ fontWeight: 600 }}>{k}</td>
                {items.map((it, idx) => (
                  <td key={idx} style={{ fontVariantNumeric: 'tabular-nums' }}>{fmt(it.metrics[k])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function fmt(v) {
  if (v == null) return '—'
  if (typeof v === 'number') return Number(v).toFixed(4)
  return String(v)
}
