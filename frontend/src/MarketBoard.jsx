import { useCallback, useEffect, useRef, useState } from 'react'
import { getWatchlist, addWatchlist, removeWatchlist, getQuotes } from './api.js'

// 模拟实时跳动：在最新价基础上做小幅随机游走（合成数据环境，无真实行情推送）
function jitter(price) {
  if (price == null) return price
  const drift = (Math.random() - 0.5) * 0.004 // ±0.2%
  return Math.round(price * (1 + drift) * 1000) / 1000
}

export default function MarketBoard() {
  const [symbols, setSymbols] = useState([])
  const [quotes, setQuotes] = useState({})
  const [error, setError] = useState('')
  const [input, setInput] = useState('')
  const [live, setLive] = useState(true)
  const timer = useRef(null)

  const refreshList = useCallback(() => {
    return getWatchlist()
      .then((r) => setSymbols(r.items || []))
      .catch((e) => setError(`加载自选失败: ${e.message}`))
  }, [])

  const refreshQuotes = useCallback(() => {
    if (symbols.length === 0) {
      setQuotes({})
      return
    }
    getQuotes(symbols.join(','))
      .then((r) => {
        const map = {}
        for (const q of r.items || []) map[q.symbol] = q
        setQuotes((prev) => {
          // 以服务端快照为基准，叠加客户端模拟跳动
          const next = {}
          for (const sym of symbols) {
            const base = map[sym]
            if (!base || base.error) {
              next[sym] = base || { symbol: sym, error: '无行情' }
              continue
            }
            const tick = prev[sym]?.tick != null ? jitter(prev[sym].tick) : base.last
            next[sym] = { ...base, tick, tick_up: tick >= (prev[sym]?.tick ?? base.last) }
          }
          return next
        })
      })
      .catch((e) => setError(`行情获取失败: ${e.message}`))
  }, [symbols])

  useEffect(() => { refreshList() }, [refreshList])
  useEffect(() => { refreshQuotes() }, [refreshQuotes])

  useEffect(() => {
    if (!live) return
    timer.current = setInterval(refreshQuotes, 2000)
    return () => clearInterval(timer.current)
  }, [live, refreshQuotes])

  const add = (e) => {
    e.preventDefault()
    const s = input.trim().toUpperCase()
    if (!s) return
    addWatchlist(s).then(refreshList).then(refreshQuotes).catch((e) => setError(e.message))
    setInput('')
  }
  const remove = (sym) => removeWatchlist(sym).then(refreshList).catch((e) => setError(e.message))

  return (
    <div className="qf-monitor" style={{ padding: 16 }}>
      <div className="qf-result-head">
        <h3>行情看板 / 自选股监控（V2.4）</h3>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> 模拟实时跳动
        </label>
      </div>
      <div className="qf-hint" style={{ marginBottom: 12 }}>
        管理自选标的并查看行情快照；开启「模拟实时跳动」后每 2 秒基于最新价做小幅随机游走（合成数据环境，无真实推送）。
      </div>

      {error && <div className="qf-error">{error}</div>}

      <form onSubmit={add} style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="添加标的，如 TEST.STOCK"
          style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)' }}
        />
        <button className="qf-btn qf-btn-primary" type="submit">添加自选</button>
      </form>

      {symbols.length === 0 && <div className="qf-hint">自选股为空，添加标的后查看行情。</div>}

      {symbols.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="qf-table">
            <thead>
              <tr>
                <th>标的</th><th>日期</th><th>最新价</th><th>模拟价</th><th>当日涨跌</th>
                <th>今开</th><th>最高</th><th>最低</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {symbols.map((sym) => {
                const q = quotes[sym] || {}
                const up = q.change_pct != null && q.change_pct >= 0
                const tickUp = q.tick_up
                return (
                  <tr key={sym}>
                    <td>{sym}</td>
                    <td className="qf-hint">{q.date || '-'}</td>
                    <td>{q.last != null ? Number(q.last).toFixed(3) : '-'}</td>
                    <td style={{ fontWeight: 600, color: tickUp ? '#15803d' : '#b91c1c' }}>
                      {q.tick != null ? Number(q.tick).toFixed(3) : '-'}
                    </td>
                    <td className={up ? 'qf-up' : 'qf-down'}>
                      {q.change_pct != null ? `${(q.change_pct).toFixed(2)}%` : '-'}
                    </td>
                    <td>{q.open != null ? Number(q.open).toFixed(3) : '-'}</td>
                    <td>{q.high != null ? Number(q.high).toFixed(3) : '-'}</td>
                    <td>{q.low != null ? Number(q.low).toFixed(3) : '-'}</td>
                    <td><button className="qf-btn qf-btn-sm" onClick={() => remove(sym)}>移除</button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
