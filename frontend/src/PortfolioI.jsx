import React, { useState } from 'react'
import {
  runPIBlackLitterman, runPIFactorPortfolio, runPIStressTest, runPIRebalance, runPIAggregate,
} from './api.js'

const btn = {
  padding: '6px 14px', borderRadius: 8, border: '1px solid #2f6df6',
  background: '#2f6df6', color: '#fff', cursor: 'pointer', fontSize: 13,
}
const tab = (a, label) => ({
  padding: '6px 12px', cursor: 'pointer', borderRadius: 8, border: 'none',
  background: a === label ? '#2f6df6' : '#eef1f6', color: a === label ? '#fff' : '#333', fontSize: 13,
})
const Card = ({ title, children }) => (
  <div style={{ background: '#fff', border: '1px solid #e6e9ef', borderRadius: 12, padding: 16, marginBottom: 14 }}>
    <div style={{ fontWeight: 600, marginBottom: 10, fontSize: 14 }}>{title}</div>
    {children}
  </div>
)
const KV = ({ data }) => {
  const flat = Object.entries(data).filter(([, v]) => typeof v === 'number' || typeof v === 'string')
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))', gap: 8 }}>
      {flat.map(([k, v]) => (
        <div key={k} style={{ background: '#f7f9fc', borderRadius: 8, padding: '8px 10px' }}>
          <div style={{ fontSize: 11, color: '#888' }}>{k}</div>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{typeof v === 'number' ? (Number.isInteger(v) ? v : (+v).toFixed(4)) : String(v)}</div>
        </div>
      ))}
    </div>
  )
}
const num = (id, val, ph) => (
  <input id={id} defaultValue={val} placeholder={ph} style={{ width: 90, padding: 6, marginRight: 6, borderRadius: 8, border: '1px solid #ccc' }} />
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }

export default function PortfolioI() {
  const [tabk, setTab] = useState('bl')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const run = async (fn, payload) => {
    setLoading(true); setErr(null)
    try { setRes(await fn(payload)) } catch (e) { setErr(jsonErr(e.message)) } finally { setLoading(false) }
  }

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>组合层面增强（V72–V76）</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>Black-Litterman · 因子组合构建 · 组合压力测试 · 带约束再平衡 · 多账户聚合</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['bl', 'Black-Litterman'], ['factor', '因子组合'], ['stress', '压力测试'], ['rebal', '约束再平衡'], ['agg', '多账户聚合']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'bl' && (
        <Card title="Black-Litterman 后验收益与权重">
          <p style={{ fontSize: 12, color: '#666' }}>cov: 协方差矩阵；下方对资产 0 设定一个看涨观点（q / 置信度）。</p>
          <textarea id="pif_cov" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[0.04, 0.01], [0.01, 0.03]])} />
          <div style={{ marginTop: 8 }}>
            {num('pif_vidx', 0, '观点资产idx')}{num('pif_q', 0.1, '观点q')}{num('pif_conf', 0.9, '置信度')}
            <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={() => run(runPIBlackLitterman, {
              cov: JSON.parse(document.getElementById('pif_cov').value),
              asset_names: ['股票', '债券'],
              views: [{ assets: [+document.getElementById('pif_vidx').value], q: +document.getElementById('pif_q').value, confidence: +document.getElementById('pif_conf').value }],
            })}>{loading ? '计算中…' : '融合观点'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ views_processed: res.views_processed }} />
            <div style={{ marginTop: 8 }}><b>均衡收益</b><pre style={pre}>{JSON.stringify(res.equilibrium_returns, null, 1)}</pre></div>
            <div style={{ marginTop: 8 }}><b>后验收益</b><pre style={pre}>{JSON.stringify(res.posterior_returns, null, 1)}</pre></div>
            <div style={{ marginTop: 8 }}><b>BL 权重</b><pre style={pre}>{JSON.stringify(res.bl_weights, null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'factor' && (
        <Card title="因子组合构建（主动权重倾斜 / 中性化）">
          <p style={{ fontSize: 12, color: '#666' }}>factor_exposures: (n×k) 暴露矩阵；target_bets: 目标因子暴露（留空=基准中性）。</p>
          <textarea id="pif_B" rows={3} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([[1.0, 0.2], [0.5, 0.8], [0.3, 0.4]])} />
          <textarea id="pif_tgt" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} placeholder="目标暴露，如 [1,0]（留空=中性）" />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => {
              const t = document.getElementById('pif_tgt').value.trim()
              run(runPIFactorPortfolio, {
                factor_exposures: JSON.parse(document.getElementById('pif_B').value),
                target_bets: t ? JSON.parse(t) : null,
                base_weights: [0.5, 0.3, 0.2],
              })
            }}>{loading ? '构建中…' : '构建组合'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ method: res.method, tracking_error: res.tracking_error }} />
            <div style={{ marginTop: 8 }}><b>新权重</b><pre style={pre}>{JSON.stringify(res.new_weights, null, 1)}</pre></div>
            <div style={{ marginTop: 8 }}><b>目标 vs 实际因子暴露</b><pre style={pre}>{JSON.stringify({ target: res.target_exposure, achieved: res.achieved_exposure }, null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {tabk === 'stress' && (
        <Card title="组合压力测试（情景冲击）">
          <p style={{ fontSize: 12, color: '#666' }}>weights + 资产名；情景：gfc_2008 / covid_2020 / rate_hike / inflation_spike / liquidity_crunch。</p>
          <textarea id="pif_w" rows={1} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.5, 0.2, 0.3])} />
          <textarea id="pif_n" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify(['股票A', '债券B', '黄金C'])} />
          <div style={{ marginTop: 8 }}>
            <select id="pif_scn" defaultValue="gfc_2008" style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
              <option value="gfc_2008">2008 金融危机</option>
              <option value="covid_2020">2020 疫情</option>
              <option value="rate_hike">加息</option>
              <option value="inflation_spike">通胀飙升</option>
              <option value="liquidity_crunch">流动性挤兑</option>
            </select>
            <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={() => run(runPIStressTest, {
              weights: JSON.parse(document.getElementById('pif_w').value),
              asset_names: JSON.parse(document.getElementById('pif_n').value),
              scenario: document.getElementById('pif_scn').value,
            })}>{loading ? '测算中…' : '压力测试'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ scenario: res.scenario, portfolio_pnl_pct: res.portfolio_pnl_pct, worst_asset: res.worst_asset, best_asset: res.best_asset }} />
          </div>}
        </Card>
      )}

      {tabk === 'rebal' && (
        <Card title="带约束再平衡（换手率/个股权重上限/不交易带）">
          <p style={{ fontSize: 12, color: '#666' }}>current/target 权重数组；可选 turnover_limit / max_weight / no_trade_band。</p>
          <textarea id="pif_cur" rows={1} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.5, 0.5, 0.0])} />
          <textarea id="pif_tgtw" rows={1} style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([0.0, 0.0, 1.0])} />
          <div style={{ marginTop: 8 }}>
            {num('pif_to', 0.4, '换手上限')}{num('pif_mw', 0.5, '权重上限')}{num('pif_ntb', 0.0, '不交易带')}
            <button style={{ ...btn, marginLeft: 8 }} disabled={loading} onClick={() => run(runPIRebalance, {
              current_weights: JSON.parse(document.getElementById('pif_cur').value),
              target_weights: JSON.parse(document.getElementById('pif_tgtw').value),
              turnover_limit: +document.getElementById('pif_to').value,
              max_weight: +document.getElementById('pif_mw').value,
              no_trade_band: +document.getElementById('pif_ntb').value,
            })}>{loading ? '再平衡中…' : '生成调仓单'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ turnover: res.turnover, constrained: res.constrained, n_trades: res.n_trades }} />
            <table style={{ width: '100%', marginTop: 8, borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>资产</th><th>当前</th><th>目标</th><th>调整后</th><th>Δ</th></tr></thead>
              <tbody>{res.trades.map((t) => (
                <tr key={t.index} style={{ borderTop: '1px solid #eee' }}>
                  <td>{t.index}</td><td>{t.current.toFixed(3)}</td><td>{t.target.toFixed(3)}</td><td>{t.adjusted.toFixed(3)}</td><td>{t.delta.toFixed(3)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>}
        </Card>
      )}

      {tabk === 'agg' && (
        <Card title="多账户聚合（统一组合视图）">
          <p style={{ fontSize: 12, color: '#666' }}>accounts: [{ '{' }"name", "positions":{ '{' }资产:市值{ '}' }, "cash"?{ '}' }]。</p>
          <textarea id="pif_acc" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} defaultValue={JSON.stringify([
            { name: '主账户', positions: { 股票A: 6000, 债券B: 4000 } },
            { name: '子账户', positions: [{ asset: '股票A', value: 2000 }, { asset: '黄金C', value: 3000 }] },
          ])} />
          <div style={{ marginTop: 8 }}>
            <button style={btn} disabled={loading} onClick={() => run(runPIAggregate, {
              accounts: JSON.parse(document.getElementById('pif_acc').value),
            })}>{loading ? '聚合中…' : '聚合账户'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ total_value: res.total_value, n_assets: res.n_assets, n_accounts: res.n_accounts, concentration_hhi: res.concentration_hhi }} />
            <div style={{ marginTop: 8 }}><b>前十大持仓</b><pre style={pre}>{JSON.stringify(res.top_positions, null, 1)}</pre></div>
            <div style={{ marginTop: 8 }}><b>账户占比</b><pre style={pre}>{JSON.stringify(res.account_weights, null, 1)}</pre></div>
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', marginTop: 10 }}>⚠ {err}</div>}
    </div>
  )
}

const pre = { background: '#f7f9fc', borderRadius: 8, padding: 10, fontSize: 12, overflowX: 'auto' }
