import { useState } from 'react'
import { login, register, setToken } from './api.js'

// 全屏登录 / 注册页（V1.7 登录门禁）：未登录时应用只渲染此页。
export default function LoginScreen({ onAuthed }) {
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = mode === 'login'
        ? await login(username.trim(), password)
        : await register(username.trim(), password)
      setToken(res.token)
      onAuthed(res.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #0f172a 100%)',
        color: '#e2e8f0',
        padding: 16,
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: '100%',
          maxWidth: 360,
          background: 'rgba(15,23,42,0.85)',
          border: '1px solid #334155',
          borderRadius: 14,
          padding: 28,
          boxShadow: '0 12px 40px rgba(0,0,0,0.45)',
        }}
      >
        <div style={{ fontSize: 26, fontWeight: 700, marginBottom: 4 }}>
          ⚡ QuantFlow
        </div>
        <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 20 }}>
          量化工作流平台 · 请登录后使用
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          <button
            type="button"
            onClick={() => { setMode('login'); setError('') }}
            className={`qf-btn ${mode === 'login' ? 'qf-btn-primary' : ''}`}
            style={{ flex: 1 }}
          >
            登录
          </button>
          <button
            type="button"
            onClick={() => { setMode('register'); setError('') }}
            className={`qf-btn ${mode === 'register' ? 'qf-btn-primary' : ''}`}
            style={{ flex: 1 }}
          >
            注册
          </button>
        </div>

        <label className="qf-field" style={{ display: 'block', marginBottom: 12 }}>
          用户名
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            placeholder="3-32 位字母/数字/下划线"
            minLength={3}
            maxLength={32}
            required
            style={{ marginTop: 6 }}
          />
        </label>
        <label className="qf-field" style={{ display: 'block', marginBottom: 12 }}>
          密码
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === 'register' ? '至少 6 位' : '请输入密码'}
            minLength={6}
            required
            style={{ marginTop: 6 }}
          />
        </label>

        {error && <div className="qf-error" style={{ marginBottom: 10 }}>{error}</div>}
        {mode === 'register' && (
          <div className="qf-hint" style={{ marginBottom: 10 }}>
            首个注册用户将成为管理员（admin）。
          </div>
        )}

        <button
          type="submit"
          className="qf-btn qf-btn-primary"
          disabled={busy}
          style={{ width: '100%' }}
        >
          {busy ? '提交中…' : mode === 'login' ? '登录' : '注册'}
        </button>
      </form>
    </div>
  )
}
