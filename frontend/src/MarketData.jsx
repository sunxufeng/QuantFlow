import { useCallback, useEffect, useRef, useState } from 'react'
import { uploadMarket, listUploaded, deleteUploaded, marketCache } from './api.js'

const SAMPLE = `date,open,high,low,close,volume
2024-01-02,100.0,102.0,99.0,101.5,1200000
2024-01-03,101.5,103.0,100.5,102.8,1350000
2024-01-04,102.8,104.2,101.0,101.2,1100000
2024-01-05,101.2,101.8,99.5,100.3,980000`

export default function MarketData() {
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [csv, setCsv] = useState('')
  const [items, setItems] = useState([])
  const [provider, setProvider] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const fileRef = useRef(null)

  const load = useCallback(() => {
    return Promise.all([
      listUploaded().catch(() => ({ items: [] })),
      marketCache().catch(() => null),
    ]).then(([up, cache]) => {
      setItems(up.items || [])
      setProvider(cache)
    })
  }, [])

  useEffect(() => { load() }, [load])

  const onFile = async (e) => {
    const f = e.target.files && e.target.files[0]
    if (!f) return
    const text = await f.text()
    setCsv(text)
    if (!symbol) setSymbol(f.name.replace(/\.[^.]+$/, '').toUpperCase())
  }

  const submit = async () => {
    setBusy(true); setError(''); setMsg('')
    const sym = symbol.trim().toUpperCase()
    if (!sym) { setError('请填写标的代码'); setBusy(false); return }
    if (!csv.trim()) { setError('请粘贴或上传 CSV 行情'); setBusy(false); return }
    try {
      const res = await uploadMarket({ symbol: sym, name: name.trim(), csv })
      setMsg(`已导入 ${res.count} 条 ${res.symbol}（${res.first_date} ~ ${res.last_date}），可直接用于回测与行情快照`)
      setCsv(''); setName('')
      if (!symbol) setSymbol('')
      await load()
    } catch (err) {
      setError(err.message)
    } finally { setBusy(false) }
  }

  const remove = async (s) => {
    if (!window.confirm(`确认删除已导入的行情 ${s}？`)) return
    setBusy(true)
    try {
      await deleteUploaded(s)
      await load()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="qf-templates" style={{ height: '100%', overflowY: 'auto' }}>
      <div className="qf-templates-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2>行情导入</h2>
        <span className="qf-hint">
          数据源模式：{provider ? provider.provider_mode : '加载中'}（
          {provider?.provider === 'fixture' ? '合成行情' : provider?.provider}）
        </span>
      </div>

      {error && <div className="qf-error">{error}</div>}
      {msg && <div className="qf-success">{msg}</div>}

      <div style={{ marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>
            上传自定义行情（OHLCV）
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <label className="qf-prop-field" style={{ margin: 0, flex: 1 }}>
              <span className="qf-prop-label">标的代码</span>
              <input className="qf-name-input" value={symbol}
                onChange={(e) => setSymbol(e.target.value)} placeholder="如 MY.AAPL / 600519.SH" />
            </label>
            <label className="qf-prop-field" style={{ margin: 0, flex: 1 }}>
              <span className="qf-prop-label">名称（可选）</span>
              <input className="qf-name-input" value={name}
                onChange={(e) => setName(e.target.value)} placeholder="如 我的自定义标的" />
            </label>
          </div>

          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span className="qf-prop-label">CSV 文本（含表头，兼容 Yahoo 导出）</span>
              <button type="button" className="qf-btn qf-btn-sm" onClick={() => setCsv(SAMPLE)}>填充示例</button>
            </div>
            <textarea className="qf-name-input" value={csv}
              onChange={(e) => setCsv(e.target.value)}
              rows={8} style={{ width: '100%', fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12 }}
              placeholder="date,open,high,low,close,volume&#10;2024-01-02,..." />
          </div>

          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <input ref={fileRef} type="file" accept=".csv,.txt" onChange={onFile}
              style={{ fontSize: 12, flex: 1 }} />
          </div>

          <button type="button" className="qf-btn qf-btn-primary" onClick={submit} disabled={busy} style={{ width: '100%' }}>
            {busy ? '导入中…' : '导入并落库'}
          </button>
          <div className="qf-hint" style={{ marginTop: 8 }}>
            导入后行情写入本地库（source=upload），回测 / 行情快照 / 模拟交易可直接引用该标的，
            全程无需外部数据源凭证。当前为合成行情模式，真实行情需在服务端配置 Tushare token。
          </div>
        </div>

        <div style={{ flex: '1 1 360px', minWidth: 320, border: '1px solid var(--border)', borderRadius: 10, padding: 14, background: '#fff' }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', marginBottom: 10 }}>
            已导入标的（{items.length}）
          </div>
          {items.length === 0 && <div className="qf-prop-hint">暂无导入数据，左侧粘贴 CSV 即可导入。</div>}
          {items.length > 0 && (
            <table className="qf-state-table">
              <thead><tr><th>标的</th><th>条数</th><th>区间</th><th>操作</th></tr></thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.symbol}>
                    <td>{it.symbol}</td>
                    <td>{it.count}</td>
                    <td className="qf-hint">{it.first_date} ~ {it.last_date}</td>
                    <td>
                      <button className="qf-btn qf-btn-sm" onClick={() => remove(it.symbol)} disabled={busy}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {provider && (
            <div className="qf-hint" style={{ marginTop: 10 }}>
              数据源快照：模式 {provider.provider_mode} · 缓存后端 {provider.cache_backend} ·
              库中总 K 线 {provider.total_bars} · TTL {provider.cache_ttl_seconds}s
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
