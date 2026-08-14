import { useCallback, useEffect, useMemo, useState } from 'react'
import { factorScoringCatalog, factorScore, factorResearchMatrix, factorResearchIc, factorResearchRanking, multifactorBacktest } from './api.js'

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

// 相关系数 -> 单元格背景色（正蓝负红，强度随 |r|）
function corrColor(r) {
  if (r == null) return 'transparent'
  const a = Math.min(1, Math.abs(r)) * 0.85 + 0.05
  const rgb = r >= 0 ? '56,189,248' : '239,68,68'
  return `rgba(${rgb},${a.toFixed(2)})`
}

function corrText(r) {
  if (r == null) return '#94a3b8'
  return Math.abs(r) > 0.5 ? '#fff' : '#0f172a'
}

// IC 时序小条形图
function IcSpark({ series }) {
  if (!series || !series.length) return <span className="qf-hint">样本不足</span>
  const max = Math.max(0.3, ...series.map((x) => Math.abs(x)))
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 28 }}>
      {series.map((v, i) => {
        const h = (Math.abs(v) / max) * 26
        return (
          <div
            key={i}
            title={`第${i + 1}期 IC=${v.toFixed(3)}`}
            style={{
              width: 5,
              height: `${Math.max(2, h)}px`,
              background: v >= 0 ? '#22c55e' : '#ef4444',
              borderRadius: 1,
            }}
          />
        )
      })}
    </div>
  )
}

export default function Factors() {
  const [tab, setTab] = useState('score')
  const [catalog, setCatalog] = useState([])
  const [symbolsText, setSymbolsText] = useState(DEFAULT_SYMBOLS)
  const [sel, setSel] = useState({}) // name -> {checked, direction, weight}
  const [method, setMethod] = useState('rank')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // 研究态
  const [win, setWin] = useState(10)
  const [matrix, setMatrix] = useState(null)
  const [ic, setIc] = useState(null)
  const [researchBusy, setResearchBusy] = useState(false)
  const [researchError, setResearchError] = useState('')

  // 排行榜态
  const [rankMetric, setRankMetric] = useState('mean_ic')
  const [rankOrder, setRankOrder] = useState('desc')
  const [ranking, setRanking] = useState(null)
  const [rankingBusy, setRankingBusy] = useState(false)
  const [rankingError, setRankingError] = useState('')

  // 多因子组合回测闭环（V4.2）
  const [mfSymbol, setMfSymbol] = useState('TEST.STOCK')
  const [mfStart, setMfStart] = useState('2024-01-01')
  const [mfEnd, setMfEnd] = useState('2024-04-01')
  const [mfThreshold, setMfThreshold] = useState(0)
  const [mfFactors, setMfFactors] = useState([
    { name: '动量', expression: 'close/close.shift(1)-1', weight: 1 },
    { name: '均值回归', expression: '(close-open)/open', weight: 1 },
    { name: '量能', expression: 'log(volume)', weight: 0.5 },
  ])
  const [mfResult, setMfResult] = useState(null)
  const [mfBusy, setMfBusy] = useState(false)
  const [mfError, setMfError] = useState('')

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

  const runResearch = useCallback(() => {
    setResearchError('')
    const symbols = parseSymbols(symbolsText)
    if (symbols.length === 0) {
      setResearchError('请至少输入一个标的代码')
      return
    }
    setResearchBusy(true)
    const params = { symbols: symbols.join(','), window: win, start: '2000-01-01', end: '2100-01-01' }
    Promise.all([factorResearchMatrix(params), factorResearchIc(params)])
      .then(([m, i]) => {
        setMatrix(m)
        setIc(i)
      })
      .catch((e) => setResearchError(`研究失败: ${e.message}`))
      .finally(() => setResearchBusy(false))
  }, [symbolsText, win])

  // 切到研究页自动跑一次
  useEffect(() => {
    if (tab === 'research' && !matrix && !researchBusy) {
      runResearch()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const runRanking = useCallback(() => {
    setRankingError('')
    const symbols = parseSymbols(symbolsText)
    if (symbols.length === 0) {
      setRankingError('请至少输入一个标的代码')
      return
    }
    setRankingBusy(true)
    const params = {
      symbols: symbols.join(','),
      window: win,
      start: '2000-01-01',
      end: '2100-01-01',
      metric: rankMetric,
      order: rankOrder,
    }
    factorResearchRanking(params)
      .then((r) => setRanking(r))
      .catch((e) => setRankingError(`排行榜计算失败: ${e.message}`))
      .finally(() => setRankingBusy(false))
  }, [symbolsText, win, rankMetric, rankOrder])

  // 切到排行榜页自动跑一次
  useEffect(() => {
    if (tab === 'ranking' && !ranking && !rankingBusy) {
      runRanking()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const toggleAll = (checked) =>
    setSel((prev) => {
      const next = {}
      for (const k of Object.keys(prev)) next[k] = { ...prev[k], checked }
      return next
    })

  const runMultifactor = useCallback(() => {
    setMfError('')
    const factors = mfFactors
      .map((f) => ({ name: f.name.trim(), expression: f.expression.trim(), weight: Number(f.weight) || 0 }))
      .filter((f) => f.name && f.expression)
    if (factors.length === 0) {
      setMfError('请至少填写一个因子（名称 + 表达式）')
      return
    }
    setMfBusy(true)
    setMfResult(null)
    multifactorBacktest({
      symbol: mfSymbol.trim().toUpperCase(),
      factors,
      start: mfStart,
      end: mfEnd,
      threshold: mfThreshold,
    })
      .then((r) => setMfResult(r))
      .catch((e) => setMfError(`组合回测失败: ${e.message}`))
      .finally(() => setMfBusy(false))
  }, [mfSymbol, mfStart, mfEnd, mfThreshold, mfFactors])

  const factorCols = useMemo(() => (result?.factors || []).map((f) => f.name), [result])

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h2>因子库</h2>
        <span className="qf-hint" style={{ marginLeft: 8 }}>
          V2.5 因子评分 · V2.9 因子研究
        </span>
      </div>

      <div className="qf-reports-tabs" style={{ marginBottom: 14 }}>
        <button
          className={`qf-reports-tab ${tab === 'score' ? 'qf-reports-tab-active' : ''}`}
          onClick={() => setTab('score')}
        >
          因子评分
        </button>
        <button
          className={`qf-reports-tab ${tab === 'research' ? 'qf-reports-tab-active' : ''}`}
          onClick={() => setTab('research')}
        >
          因子研究
        </button>
        <button
          className={`qf-reports-tab ${tab === 'ranking' ? 'qf-reports-tab-active' : ''}`}
          onClick={() => setTab('ranking')}
        >
          因子排行榜
        </button>
        <button
          className={`qf-reports-tab ${tab === 'multi' ? 'qf-reports-tab-active' : ''}`}
          onClick={() => setTab('multi')}
        >
          多因子组合(V4.2)
        </button>
      </div>

      {tab === 'score' && (
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
      )}

      {tab === 'research' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 320px', minWidth: 260 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>标的（逗号分隔）</label>
              <textarea
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                rows={1}
                style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0', fontFamily: 'inherit' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>窗口</label>
              <input
                type="number"
                min="3"
                max="20"
                value={win}
                onChange={(e) => setWin(Number(e.target.value) || 10)}
                style={{ width: 80, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }}
              />
            </div>
            <button className="qf-btn qf-btn-primary" onClick={runResearch} disabled={researchBusy}>
              {researchBusy ? '计算中…' : '运行研究'}
            </button>
          </div>
          {researchError && <div className="qf-error">{researchError}</div>}

          {/* 相关性矩阵 */}
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
            <div className="qf-reports-title" style={{ fontSize: 14, marginBottom: 8 }}>
              因子相关性矩阵
              {matrix && <span className="qf-hint" style={{ marginLeft: 8 }}>（{matrix.dates_count} 期截面合并）</span>}
            </div>
            {matrix ? (
              <div style={{ overflowX: 'auto' }}>
                <table className="qf-table" style={{ width: 'auto' }}>
                  <thead>
                    <tr>
                      <th></th>
                      {matrix.factors.map((f) => (
                        <th key={f}>{f}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.factors.map((rowF, i) => (
                      <tr key={rowF}>
                        <td style={{ fontWeight: 600 }}>{rowF}</td>
                        {matrix.factors.map((colF, j) => {
                          const v = matrix.matrix[i][j]
                          return (
                            <td
                              key={colF}
                              style={{
                                textAlign: 'center',
                                background: corrColor(v),
                                color: corrText(v),
                                fontVariantNumeric: 'tabular-nums',
                                fontWeight: 600,
                              }}
                            >
                              {v == null ? '—' : v.toFixed(2)}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="qf-hint">点击「运行研究」生成因子相关性矩阵。</div>
            )}
          </div>

          {/* IC / IR */}
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
            <div className="qf-reports-title" style={{ fontSize: 14, marginBottom: 8 }}>
              因子 IC / IR 分析
              {ic && <span className="qf-hint" style={{ marginLeft: 8 }}>（下期收益 {ic.forward_days} 日，{ic.dates_count} 期）</span>}
            </div>
            {ic ? (
              <div style={{ overflowX: 'auto' }}>
                <table className="qf-table" style={{ width: '100%' }}>
                  <thead>
                    <tr>
                      <th>因子</th>
                      <th>均值 IC</th>
                      <th>IC 标准差</th>
                      <th>IR</th>
                      <th>IC&gt;0 占比</th>
                      <th>样本数</th>
                      <th>IC 时序</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ic.factors.map((f) => {
                      const r = ic.results[f]
                      const enough = r.observations && r.observations > 0
                      return (
                        <tr key={f}>
                          <td style={{ fontWeight: 600 }}>{f}</td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{r.mean_ic == null ? '—' : r.mean_ic.toFixed(3)}</td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{r.std_ic == null ? '—' : r.std_ic.toFixed(3)}</td>
                          <td
                            style={{
                              fontVariantNumeric: 'tabular-nums',
                              fontWeight: 600,
                              color: !enough ? '#94a3b8' : r.ir >= 0 ? '#16a34a' : '#dc2626',
                            }}
                          >
                            {r.ir == null ? '—' : r.ir.toFixed(3)}
                          </td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{r.ic_positive_ratio == null ? '—' : `${(r.ic_positive_ratio * 100).toFixed(0)}%`}</td>
                          <td>{r.observations}</td>
                          <td><IcSpark series={r.ic_series} /></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="qf-hint">点击「运行研究」生成 IC / IR 分析。</div>
            )}
            <div className="qf-hint" style={{ marginTop: 8 }}>
              说明：IC 为因子值与下期收益的秩相关；IR=均值IC/标准差IC，绝对值越大越稳定；IC&gt;0 占比越高代表选股方向越一致。样本不足（如 volume_trend 需 20 日窗口）会标记为「样本不足」。
            </div>
          </div>
        </div>
      )}

      {tab === 'ranking' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 320px', minWidth: 260 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>标的（逗号分隔）</label>
              <textarea
                value={symbolsText}
                onChange={(e) => setSymbolsText(e.target.value)}
                rows={1}
                style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0', fontFamily: 'inherit' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>排序指标</label>
              <select
                value={rankMetric}
                onChange={(e) => setRankMetric(e.target.value)}
                style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }}
              >
                <option value="mean_ic">均值 IC</option>
                <option value="ir">IR（信息比率）</option>
                <option value="ic_positive_ratio">IC&gt;0 占比</option>
                <option value="std_ic">IC 标准差（越小越稳）</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>方向</label>
              <select
                value={rankOrder}
                onChange={(e) => setRankOrder(e.target.value)}
                style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }}
              >
                <option value="desc">降序</option>
                <option value="asc">升序</option>
              </select>
            </div>
            <button className="qf-btn qf-btn-primary" onClick={runRanking} disabled={rankingBusy}>
              {rankingBusy ? '计算中…' : '刷新排行'}
            </button>
          </div>
          {rankingError && <div className="qf-error">{rankingError}</div>}

          <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
            <div className="qf-reports-title" style={{ fontSize: 14, marginBottom: 8 }}>
              因子排行榜
              {ranking && (
                <span className="qf-hint" style={{ marginLeft: 8 }}>
                  （按 {ranking.metric} {ranking.order === 'desc' ? '降序' : '升序'} · {ranking.dates_count} 期 · 下期收益 {ranking.forward_days} 日）
                </span>
              )}
            </div>
            {ranking ? (
              <div style={{ overflowX: 'auto' }}>
                <table className="qf-table" style={{ width: '100%' }}>
                  <thead>
                    <tr>
                      <th>排名</th>
                      <th>因子</th>
                      <th>方向</th>
                      <th>均值 IC</th>
                      <th>IR</th>
                      <th>IC&gt;0 占比</th>
                      <th>IC 标准差</th>
                      <th>样本数</th>
                      <th>IC 时序</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranking.ranked.map((r, i) => {
                      const enough = r.observations && r.observations > 0
                      return (
                        <tr key={r.factor}>
                          <td style={{ fontWeight: 700 }}>{i + 1}</td>
                          <td style={{ fontWeight: 600 }}>
                            {r.factor}
                            <div className="qf-hint" style={{ fontWeight: 400, fontSize: 11 }}>{r.description}</div>
                          </td>
                          <td>{r.direction === 1 ? '高配' : r.direction === -1 ? '低配' : '—'}</td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{r.mean_ic == null ? '—' : r.mean_ic.toFixed(3)}</td>
                          <td
                            style={{
                              fontVariantNumeric: 'tabular-nums',
                              fontWeight: 600,
                              color: !enough ? '#94a3b8' : r.ir >= 0 ? '#16a34a' : '#dc2626',
                            }}
                          >
                            {r.ir == null ? '—' : r.ir.toFixed(3)}
                          </td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{r.ic_positive_ratio == null ? '—' : `${(r.ic_positive_ratio * 100).toFixed(0)}%`}</td>
                          <td style={{ fontVariantNumeric: 'tabular-nums' }}>{r.std_ic == null ? '—' : r.std_ic.toFixed(3)}</td>
                          <td>{r.observations}</td>
                          <td><IcSpark series={r.ic_series} /></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="qf-hint">点击「刷新排行」生成因子排行榜。</div>
            )}
            <div className="qf-hint" style={{ marginTop: 8 }}>
              说明：排行榜打通 V2.8 回测排行与 V2.9 因子研究——按 IC/IR 对全部内置因子排序，便于优先选择选股能力稳定（IR 高、IC&gt;0 占比高）的因子。当前回测报告未记录所用因子，策略级联动为后续项。
            </div>
          </div>
        </div>
      )}

      {tab === 'multi' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 200px', minWidth: 160 }}>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>标的</label>
              <input
                value={mfSymbol}
                onChange={(e) => setMfSymbol(e.target.value)}
                style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>起始</label>
              <input value={mfStart} onChange={(e) => setMfStart(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }} />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>结束</label>
              <input value={mfEnd} onChange={(e) => setMfEnd(e.target.value)} style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }} />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>综合分阈值</label>
              <input type="number" step="0.1" value={mfThreshold} onChange={(e) => setMfThreshold(Number(e.target.value) || 0)} style={{ width: 90, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }} />
            </div>
            <button className="qf-btn qf-btn-primary" onClick={runMultifactor} disabled={mfBusy}>
              {mfBusy ? '回测中…' : '运行组合回测'}
            </button>
          </div>

          <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
            <div className="qf-reports-title" style={{ fontSize: 14, marginBottom: 8 }}>因子与权重</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {mfFactors.map((f, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <input
                    value={f.name}
                    onChange={(e) => setMfFactors((p) => p.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                    placeholder="因子名"
                    style={{ width: 120, padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }}
                  />
                  <input
                    value={f.expression}
                    onChange={(e) => setMfFactors((p) => p.map((x, j) => (j === i ? { ...x, expression: e.target.value } : x)))}
                    placeholder="表达式（仅用 open/high/low/close/volume）"
                    style={{ flex: 1, minWidth: 240, padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0', fontFamily: 'monospace', fontSize: 12 }}
                  />
                  <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                    权重
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      value={f.weight}
                      onChange={(e) => setMfFactors((p) => p.map((x, j) => (j === i ? { ...x, weight: Number(e.target.value) || 0 } : x)))}
                      style={{ width: 64, padding: '5px 8px', borderRadius: 6, border: '1px solid var(--border)', background: '#0b1220', color: '#e2e8f0' }}
                    />
                  </label>
                  <button className="qf-btn qf-btn-sm qf-btn-danger" onClick={() => setMfFactors((p) => p.filter((_, j) => j !== i))}>删</button>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 8 }}>
              <button className="qf-btn qf-btn-sm" onClick={() => setMfFactors((p) => [...p, { name: '', expression: '', weight: 1 }])}>+ 添加因子</button>
            </div>
          </div>

          {mfError && <div className="qf-error">{mfError}</div>}

          {mfResult && (
            <>
              <div className="qf-bt-cards">
                {[
                  ['总收益', pct(mfResult.metrics.total_return)],
                  ['年化收益', pct(mfResult.metrics.annual_return)],
                  ['夏普', num(mfResult.metrics.sharpe)],
                  ['最大回撤', pct(mfResult.metrics.max_drawdown)],
                  ['年化波动', pct(mfResult.metrics.attribution?.risk?.volatility)],
                  ['持仓暴露比', pct(mfResult.metrics.attribution?.curve?.exposure_ratio)],
                ].map(([k, v]) => (
                  <div key={k} className="qf-bt-card">
                    <div className="qf-bt-card-l">{k}</div>
                    <div className="qf-bt-card-v">{v}</div>
                  </div>
                ))}
              </div>

              <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: '#fff', padding: 12 }}>
                <div className="qf-reports-title" style={{ fontSize: 14, marginBottom: 8 }}>
                  综合分 / 仓位序列（{mfResult.composite_series.length} 个交易日）
                </div>
                <CompositeChart series={mfResult.composite_series} />
              </div>

              <div className="qf-hint">
                综合分 = 各因子列 winsorize + 全局 zscore 后按权重求和；综合分 &gt; 阈值则下一交易日满仓，否则空仓（无前视）。
                可把『因子排行榜』选出的高分因子表达式直接填入上方，完成研究→合成→回测闭环。
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function pct(v) {
  if (v == null) return '-'
  return `${(Number(v) * 100).toFixed(2)}%`
}
function num(v) {
  if (v == null) return '-'
  return Number(v).toFixed(3)
}

// 多因子综合分 + 仓位可视化
function CompositeChart({ series }) {
  if (!series || series.length === 0) return null
  const vals = series.map((s) => s.composite)
  const lo = Math.min(...vals, 0)
  const hi = Math.max(...vals, 0)
  const span = hi - lo || 1
  const w = 600
  const h = 160
  const step = w / Math.max(series.length - 1, 1)
  const y = (v) => h - ((v - lo) / span) * h
  const linePts = series.map((s, i) => `${i * step},${y(s.composite)}`).join(' ')
  const zeroY = y(0)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: 180 }}>
      <line x1="0" y1={zeroY} x2={w} y2={zeroY} stroke="#cbd5e1" strokeWidth="1" strokeDasharray="3 3" />
      <polyline points={linePts} fill="none" stroke="#6366f1" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      {series.map((s, i) =>
        s.position > 0 ? (
          <circle key={i} cx={i * step} cy={h - 6} r="3" fill="#15803d" />
        ) : (
          <circle key={i} cx={i * step} cy={h - 6} r="2" fill="#cbd5e1" />
        ),
      )}
    </svg>
  )
}
