import { useCallback, useEffect, useMemo, useState } from 'react'
import { factorScoringCatalog, factorScore } from './api.js'

const DEFAULT_SYMBOLS = 'TEST.STOCK, TEST.BANK, TEST.FUND, TEST.FUTURE'

function parseSymbols(text) {
  return Array.from(
    new Set(
      (text || '')
        .split(/[,，\s]+/)
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean),
    ),
  )
}

// 综合分分值区间映射到 0~100% 的条形宽度（rank 百分位天然在 0~1）
function barWidth(norm) {
  if (norm == null) return 0
  return Math.max(0, Math.min(1, norm)) * 100
}

export default function Factors() {
  const [catalog, setCatalog] = useState([])
  const [symbolsText, setSymbolsText] = useState(DEFAULT_SYMBOLS)
  const [sel, setSel] = useState({}) // name -> {checked, direction, weight}
  const [method, setMethod] = useState('rank')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    factorScoringCatalog()
      .then((r) => {
        const items = r.items || []
        setCatalog(items)
        const init = {}
        for (const f of items) {
          init[f.name] = { checked: true, direction: f.direction, weight: 1 }
        }
        setSel(init)
      })
      .catch((e) => setError(`因子目录加载失败: ${e.message}`))
  }, [])

  const run = useCallback(() => {
    setError('')
    const symbols = parseSymbols(symbolsText)
    if (symbols.length === 0) {
      setError('请至少输入一个标的代码')
      return
    }
    const factors = Object.entries(sel)
      .filter(([, v]) => v.checked)
      .map(([name, v]) => ({ name, direction: v.direction, weight: Number(v.weight) || 1 }))
    if (factors.length === 0) {
      setError('请至少选择一个因子')
      return
    }
    setBusy(true)
    factorScore({ symbols, factors, method })
      .then((r) => setResult(r))
      .catch((e) => setError(`评分失败: ${e.message}`))
      .finally(() => setBusy(false))
  }, [symbolsText, sel, method])

  const toggleAll = (checked) =>
    setSel((prev) => {
      const next = {}
      for (const k of Object.keys(prev)) next[k] = { ...prev[k], checked }
      return next
    })

  const factorCols = useMemo(() => (result?.factors || []).map((f) => f.name), [result])

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h2>因子评分与排序</h2>
        <span className="qf-hint" style={{ marginLeft: 8 }}>
          V2.5 · 横截面因子打分（综合分越高越优）
        </span>
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {/* 左：配置 */}
        <div style={{ flex: '1 1 320px', minWidth: 300 }}>
          <div className="qf-field" style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              标的（逗号分隔）
            </label>
            <textarea
              value={symbolsText}
              onChange={(e) => setSymbolsText(e.target.value)}
              rows={2}
              style={{
                width: '100%',
                padding: '6px 10px',
                borderRadius: 6,
                border: '1px solid var(--border)',
                background: '#0b1220',
                color: '#e2e8f0',
                fontFamily: 'inherit',
              }}
            />
          </div>

          <div className="qf-field" style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <label style={{ fontSize: 13 }}>因子（勾选参与评分）</label>
              <span>
                <button className="qf-btn qf-btn-sm" onClick={() => toggleAll(true)}>全选</button>{' '}
                <button className="qf-btn qf-btn-sm" onClick={() => toggleAll(false)}>清空</button>
              </span>
            </div>
            <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8, maxHeight: 320, overflowY: 'auto' }}>
              {catalog.length === 0 && <div className="qf-hint">加载中…</div>}
              {catalog.map((f) => {
                const s = sel[f.name] || { checked: false, direction: f.direction, weight: 1 }
                return (
                  <div key={f.name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 13 }}>
                    <input
                      type="checkbox"
                      checked={s.checked}
                      onChange={(e) =>
                        setSel((p) => ({ ...p, [f.name]: { ...p[f.name], checked: e.target.checked } }))
                      }
                    />
                    <span style={{ flex: 1 }}>
                      <b>{f.name}</b>
                      <span className="qf-hint" style={{ marginLeft: 6 }}>{f.description}</span>
                    </span>
                    <select
                      value={s.direction}
                      onChange={(e) =>
                        setSel((p) => ({
                          ...p,
                          [f.name]: { ...p[f.name], direction: Number(e.target.value) },
                        }))
                      }
                      style={{ background: '#0b1220', color: '#e2e8f0', border: '1px solid var(--border)', borderRadius: 4 }}
                    >
                      <option value={1}>高配</option>
                      <option value={-1}>低配</option>
                    </select>
                    <input
                      type="number"
                      step="0.5"
                      min="0"
                      value={s.weight}
                      onChange={(e) =>
                        setSel((p) => ({
                          ...p,
                          [f.name]: { ...p[f.name], weight: e.target.value },
                        }))
                      }
                      style={{ width: 56, background: '#0b1220', color: '#e2e8f0', border: '1px solid var(--border)', borderRadius: 4 }}
                      title="权重"
                    />
                  </div>
                )
              })}
            </div>
          </div>

          <div className="qf-field" style={{ marginBottom: 12, fontSize: 13 }}>
            <label style={{ marginRight: 12 }}>
              <input type="radio" checked={method === 'rank'} onChange={() => setMethod('rank')} /> 百分位排名
            </label>
            <label>
              <input type="radio" checked={method === 'zscore'} onChange={() => setMethod('zscore')} /> Z-Score
            </label>
          </div>

          <button className="qf-btn qf-btn-primary" onClick={run} disabled={busy}>
            {busy ? '评分中…' : '运行评分'}
          </button>
          {error && <div className="qf-error" style={{ marginTop: 10 }}>{error}</div>}
        </div>

        {/* 右：结果 */}
        <div style={{ flex: '2 1 480px', minWidth: 360 }}>
          {!result && !error && (
            <div className="qf-hint">配置标的与因子后点击「运行评分」，结果按综合分降序排列。</div>
          )}
          {result && (
            <>
              <div className="qf-hint" style={{ marginBottom: 8 }}>
                标准化方法：{result.method === 'rank' ? '百分位排名' : 'Z-Score'} · 共 {result.scores.length} 个标的
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="qf-table" style={{ width: '100%' }}>
                  <thead>
                    <tr>
                      <th>排名</th>
                      <th>标的</th>
                      <th>综合分</th>
                      {factorCols.map((name) => (
                        <th key={name}>{name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.scores.map((row) => (
                      <tr key={row.symbol}>
                        <td>{row.rank}</td>
                        <td style={{ fontWeight: 600 }}>{row.symbol}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <div style={{ flex: 1, height: 8, background: '#1e293b', borderRadius: 4, overflow: 'hidden' }}>
                              <div
                                style={{
                                  width: `${barWidth(row.composite)}%`,
                                  height: '100%',
                                  background: 'linear-gradient(90deg,#22c55e,#15803d)',
                                }}
                              />
                            </div>
                            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{row.composite.toFixed(3)}</span>
                          </div>
                        </td>
                        {factorCols.map((name) => {
                          const norm = row.normalized?.[name]
                          const raw = row.factors?.[name]
                          return (
                            <td key={name}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <div style={{ flex: 1, height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
                                  <div
                                    style={{
                                      width: `${barWidth(norm)}%`,
                                      height: '100%',
                                      background: '#38bdf8',
                                    }}
                                  />
                                </div>
                                <span className="qf-hint" style={{ fontVariantNumeric: 'tabular-nums' }}>
                                  {raw == null ? '—' : Number(raw).toFixed(3)}
                                </span>
                              </div>
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
