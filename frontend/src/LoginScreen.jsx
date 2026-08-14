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
            style={{
              flex: 1,
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid',
              borderColor: mode === 'login' ? '#6366f1' : '#334155',
              background: mode === 'login' ? '#6366f1' : 'transparent',
              color: '#fff',
              fontSize: 14,
              cursor: 'pointer',
            }}
          >
            登录
          </button>
          <button
            type="button"
            onClick={() => { setMode('register'); setError('') }}
            style={{
              flex: 1,
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid',
              borderColor: mode === 'register' ? '#6366f1' : '#334155',
              background: mode === 'register' ? '#6366f1' : 'transparent',
              color: '#fff',
              fontSize: 14,
              cursor: 'pointer',
            }}
          >
            注册
          </button>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>
            用户名
          </label>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            placeholder="3-32 位字母/数字/下划线"
            minLength={3}
            maxLength={32}
            required
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '10px 12px',
              border: '1px solid #334155',
              borderRadius: 8,
              background: '#0f172a',
              color: '#e2e8f0',
              fontSize: 14,
              outline: 'none',
            }}
          />
        </div>
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6 }}>
            密码
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={mode === 'register' ? '至少 6 位' : '请输入密码'}
            minLength={6}
            required
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '10px 12px',
              border: '1px solid #334155',
              borderRadius: 8,
              background: '#0f172a',
              color: '#e2e8f0',
              fontSize: 14,
              outline: 'none',
            }}
          />
        </div>

        {error && <div className="qf-error" style={{ marginBottom: 10 }}>{error}</div>}
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 12, lineHeight: 1.5 }}>
          {mode === 'login'
            ? '系统没有预置管理员账号，首次使用请切换到“注册”；首个注册用户自动成为管理员。'
            : '首个注册用户将自动成为管理员（admin）。'}
        </div>

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
