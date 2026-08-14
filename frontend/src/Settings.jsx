import { useCallback, useEffect, useState } from 'react'
import { getSettings, updateSettings, brokerGetConfig } from './api.js'

const VIEW_OPTIONS = [
  { value: 'home', label: '概览' },
  { value: 'editor', label: '工作流编辑器' },
  { value: 'chart', label: '行情图表' },
  { value: 'data', label: '数据更新' },
  { value: 'factor', label: '因子库' },
  { value: 'watch', label: '自选监控' },
  { value: 'trade', label: '模拟交易' },
  { value: 'sched', label: '调度中心' },
  { value: 'templates', label: '模板库' },
  { value: 'reports', label: '回测报告' },
]

const THEME_OPTIONS = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
]

const SOURCE_OPTIONS = [
  { value: 'fixture', label: '内置样例数据（fixture，无需凭证）' },
  { value: 'tushare', label: 'Tushare（需配置 token）' },
]

export default function Settings() {
  const [system, setSystem] = useState(null)
  const [prefs, setPrefs] = useState({ default_view: 'home', theme: 'light', preferred_data_source: 'fixture' })
  const [broker, setBroker] = useState(null)
  const [form, setForm] = useState(prefs)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    return Promise.all([
      getSettings().catch(() => null),
      brokerGetConfig().catch(() => null),
    ]).then(([s, b]) => {
      if (s) {
        setSystem(s.system)
        setPrefs(s.preferences)
        setForm(s.preferences)
      }
      if (b) setBroker(b)
    })
  }, [])

  useEffect(() => { load() }, [load])

  const save = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setMsg('')
    try {
      const res = await updateSettings(form)
      if (!res || res.error) throw new Error(res?.error || '保存失败')
      setPrefs(res.preferences)
      setMsg('偏好已保存')
    } catch (err) {
      setError(err.message || '保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="qf-templates" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="qf-templates-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2>设置</h2>
        <span className="qf-hint">系统信息（只读）· 用户偏好（按账户持久化）</span>
      </div>

      {error && <div className="qf-error">{error}</div>}
      {msg && <div className="qf-success">{msg}</div>}

      {/* 系统信息（只读） */}
      <div style={{ marginTop: 12, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>系统信息</div>
        <div className="qf-mcards" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
          <div className="qf-mcard"><div className="qf-mcard-value">{system?.version || '-'}</div><div className="qf-mcard-label">版本</div></div>
          <div className="qf-mcard"><div className="qf-mcard-value">{system?.market?.provider_mode || '-'}</div><div className="qf-mcard-label">行情数据源模式</div></div>
          <div className="qf-mcard"><div className="qf-mcard-value">{system?.market?.provider || '-'}</div><div className="qf-mcard-label">当前数据源</div></div>
          <div className="qf-mcard"><div className="qf-mcard-value">{system?.market?.cache_backend || '-'}</div><div className="qf-mcard-label">行情缓存后端</div></div>
          <div className="qf-mcard"><div className="qf-mcard-value">{broker?.broker || (system?.broker?.broker) || 'none'}</div><div className="qf-mcard-label">券商</div></div>
        </div>
        <div className="qf-hint" style={{ marginTop: 8 }}>
          数据源模式由环境变量 <code>QF_MARKET_PROVIDER</code> 决定（fixture / tushare）。切换真实数据源需在服务端配置对应凭证后重启；此处可在下方记录你的偏好。
        </div>
      </div>

      {/* 用户偏好 */}
      <form onSubmit={save} style={{ marginTop: 16, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>用户偏好</div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <label className="qf-prop-field" style={{ flex: '1 1 220px', marginBottom: 10 }}>
            <span className="qf-prop-label">默认进入视图</span>
            <select className="qf-name-input" value={form.default_view}
              onChange={(e) => setForm(f => ({ ...f, default_view: e.target.value }))}>
              {VIEW_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="qf-prop-field" style={{ flex: '1 1 220px', marginBottom: 10 }}>
            <span className="qf-prop-label">主题</span>
            <select className="qf-name-input" value={form.theme}
              onChange={(e) => setForm(f => ({ ...f, theme: e.target.value }))}>
              {THEME_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="qf-prop-field" style={{ flex: '1 1 220px', marginBottom: 10 }}>
            <span className="qf-prop-label">偏好数据源</span>
            <select className="qf-name-input" value={form.preferred_data_source}
              onChange={(e) => setForm(f => ({ ...f, preferred_data_source: e.target.value }))}>
              {SOURCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        </div>
        <button type="submit" className="qf-btn qf-btn-primary" disabled={busy}>
          {busy ? '保存中…' : '保存偏好'}
        </button>
        <div className="qf-hint" style={{ marginTop: 8 }}>
          保存后，下次登录将默认进入所选视图。「偏好数据源」仅记录你的意图，真实切换仍需服务端凭证。
        </div>
      </form>
    </div>
  )
}
