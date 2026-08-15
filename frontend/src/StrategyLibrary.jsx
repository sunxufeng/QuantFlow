import { useEffect, useState } from 'react'
import { backtestStrategies } from './api.js'

const DEFAULT_PARAMS = {
  buy_hold: { shares: 0 },
  ma_cross: { fast: 5, slow: 20 },
  fund_dingtou: { amount: 1000 },
  fund_value_avg: { amount: 1000 },
  futures_ma_cross: { fast: 5, slow: 20, contracts: 1 },
  momentum: { lookback: 20, threshold: 0.0 },
  mean_reversion: { window: 20, k: 2.0 },
  rsi: { period: 14, oversold: 30, overbought: 70 },
  bollinger: { window: 20, num_std: 2.0 },
}

export default function StrategyLibrary() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    backtestStrategies().then((d) => setItems(d.items || [])).finally(() => setLoading(false))
  }, [])

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ margin: '0 0 4px' }}>策略库 <span style={{ fontSize: 12, color: '#16a34a' }}>V19</span></h2>
      <p style={{ color: '#6b7280', marginTop: 0, fontSize: 13 }}>
        内置回测策略清单（含 V19 新增 动量 / 均值回归 / RSI / 布林带）。默认参数可直接用于 POST /backtest/run。
      </p>
      {loading ? <div>加载中…</div> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {items.map((s) => (
            <div key={s.name} style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 14 }}>
              <div style={{ fontWeight: 700, fontSize: 15, color: '#1f2937' }}>{s.name}</div>
              <div style={{ fontSize: 13, color: '#4b5563', margin: '6px 0' }}>{s.description || '—'}</div>
              <div style={{ fontSize: 12, color: '#6b7280' }}>
                默认参数：<code style={{ background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 }}>
                  {JSON.stringify(DEFAULT_PARAMS[s.name] || {})}
                </code>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
