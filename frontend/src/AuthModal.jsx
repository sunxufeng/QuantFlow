import { useState } from 'react'
import { login, register, setToken } from './api.js'

export default function AuthModal({ onClose, onAuthed }) {
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
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="qf-modal-mask" onClick={onClose}>
      <div className="qf-modal" onClick={(e) => e.stopPropagation()}>
        <div className="qf-modal-head">
          <h3>{mode === 'login' ? '登录 QuantFlow' : '注册 QuantFlow'}</h3>
          <button className="qf-btn qf-btn-sm" onClick={onClose}>×</button>
        </div>
        <div className="qf-tabs">
          <button
            className={`qf-tab ${mode === 'login' ? 'qf-tab-active' : ''}`}
            onClick={() => { setMode('login'); setError('') }}
          >
            登录
          </button>
          <button
            className={`qf-tab ${mode === 'register' ? 'qf-tab-active' : ''}`}
            onClick={() => { setMode('register'); setError('') }}
          >
            注册
          </button>
        </div>
        <form className="qf-modal-body" onSubmit={submit}>
          <label className="qf-field">
            用户名
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              placeholder="3-32 位字母/数字/下划线"
              minLength={3}
              maxLength={32}
              required
            />
          </label>
          <label className="qf-field">
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === 'register' ? '至少 6 位' : '请输入密码'}
              minLength={6}
              required
            />
          </label>
          {error && <div className="qf-error">{error}</div>}
          {mode === 'register' && (
            <div className="qf-hint">首个注册用户将成为管理员（admin）。</div>
          )}
          <button className="qf-btn qf-btn-primary qf-modal-submit" disabled={busy}>
            {busy ? '提交中…' : mode === 'login' ? '登录' : '注册'}
          </button>
        </form>
      </div>
    </div>
  )
}
