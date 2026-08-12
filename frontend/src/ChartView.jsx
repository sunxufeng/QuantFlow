import { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, CandlestickSeries, HistogramSeries, ColorType } from 'lightweight-charts'
import { fetchBars, fetchInstruments } from './api.js'

const DEFAULT_SYMBOL = 'TEST.STOCK'

function toChartData(bars) {
  return bars.map((b) => ({
    time: b.date,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }))
}

function toVolumeData(bars) {
  return bars.map((b) => ({
    time: b.date,
    value: b.volume,
    color: b.close >= b.open ? 'rgba(38,166,154,0.4)' : 'rgba(239,83,80,0.4)',
  }))
}

export default function ChartView() {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleRef = useRef(null)
  const volumeRef = useRef(null)
  const [instruments, setInstruments] = useState([])
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL)
  const [bars, setBars] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [meta, setMeta] = useState(null)

  // 初始化图表（一次）
  useEffect(() => {
    if (!containerRef.current || chartRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#475569',
        fontFamily: '-apple-system, "PingFang SC", sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(226,232,240,0.5)' },
        horzLines: { color: 'rgba(226,232,240,0.5)' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: '#e2e8f0' },
      timeScale: { borderColor: '#e2e8f0', rightOffset: 6, barSpacing: 8 },
      autoSize: true,
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350',
      borderUpColor: '#26a69a', borderDownColor: '#ef5350',
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    })
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    chartRef.current = chart
    candleRef.current = candle
    volumeRef.current = volume
    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      volumeRef.current = null
    }
  }, [])

  useEffect(() => {
    fetchInstruments()
      .then((res) => {
        const items = res.items || []
        setInstruments(items)
        if (items.length && !items.some((i) => i.symbol === symbol)) {
          setSymbol(items[0].symbol)
        }
      })
      .catch((e) => setError(`标的列表加载失败: ${e.message}`))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadBars = (sym) => {
    setBusy(true)
    setError('')
    fetchBars(sym)
      .then((res) => {
        setBars(res.bars || [])
        setMeta({ symbol: res.symbol, count: res.count, source: res.bars?.[0]?.source })
        if (candleRef.current) {
          candleRef.current.setData(toChartData(res.bars || []))
          volumeRef.current.setData(toVolumeData(res.bars || []))
          chartRef.current.timeScale().fitContent()
        }
      })
      .catch((e) => setError(`行情加载失败: ${e.message}`))
      .finally(() => setBusy(false))
  }

  useEffect(() => {
    if (symbol) loadBars(symbol)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol])

  const last = useMemo(() => bars[bars.length - 1], [bars])

  const change = last && bars.length > 1 ? ((last.close - bars[bars.length - 2].close) / bars[bars.length - 2].close) * 100 : null

  return (
    <div className="qf-chart-view">
      <div className="qf-chart-toolbar">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          disabled={busy}
          aria-label="选择标的"
        >
          {instruments.length === 0 && <option value={DEFAULT_SYMBOL}>TEST.STOCK</option>}
          {instruments.map((inst) => (
            <option key={inst.symbol} value={inst.symbol}>
              {inst.name} · {inst.symbol}（{inst.market === 'fund' ? '基金' : inst.exchange || inst.market}）
            </option>
          ))}
        </select>
        <button className="qf-btn" onClick={() => loadBars(symbol)} disabled={busy}>
          {busy ? '加载中…' : '刷新'}
        </button>
        {meta && (
          <span className="qf-chart-meta">
            {meta.symbol} · {meta.count} 根日线{meta.source ? ` · ${meta.source}` : ''}
          </span>
        )}
      </div>
      {error && <div className="qf-error">{error}</div>}
      <div className="qf-chart-last">
        {last && (
          <span className="qf-chart-price">
            {last.close.toFixed(2)}
            <em className={change >= 0 ? 'qf-up' : 'qf-down'}>
              {change >= 0 ? '+' : ''}{change.toFixed(2)}%
            </em>
          </span>
        )}
      </div>
      <div className="qf-chart-wrap" ref={containerRef} />
    </div>
  )
}
