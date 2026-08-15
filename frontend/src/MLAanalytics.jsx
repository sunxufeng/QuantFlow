import React, { useState } from 'react'
import {
  runMlPredict, runMlCluster, runMlAnomaly, runMlImportance, runMlFeatures,
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
const KV = ({ data }) => (
  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 8 }}>
    {Object.entries(data).map(([k, v]) => (
      <div key={k} style={{ background: '#f7f9fc', borderRadius: 8, padding: '8px 10px' }}>
        <div style={{ fontSize: 11, color: '#888' }}>{k}</div>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v)}</div>
      </div>
    ))}
  </div>
)
const jsonErr = (e) => { try { return JSON.parse(e)?.detail || e } catch { return e } }

export default function MLAanalytics() {
  const [tabk, setTab] = useState('predict')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const run = async (fn, payload) => {
    setLoading(true); setErr(null)
    try { setRes(await fn(payload)) } catch (e) { setErr(jsonErr(e.message)) } finally { setLoading(false) }
  }
  const parse = (s) => JSON.parse(s)

  return (
    <div style={{ padding: 18, maxWidth: 1080 }}>
      <h2 style={{ margin: '0 0 4px' }}>ML 量化分析</h2>
      <p style={{ color: '#888', marginTop: 0, fontSize: 13 }}>收益预测 · 聚类选股 · 异常检测 · 特征重要性 · 特征工程</p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['predict', '收益预测'], ['cluster', '聚类选股'], ['anomaly', '异常检测'], ['importance', '特征重要性'], ['features', '特征工程']].map(([k, l]) => (
          <button key={k} style={tab(tabk, k)} onClick={() => { setTab(k); setRes(null); setErr(null) }}>{l}</button>
        ))}
      </div>

      {tabk === 'predict' && (
        <Card title="收益预测（OLS / Ridge / Lasso 基线）">
          <p style={{ fontSize: 12, color: '#666' }}>features: JSON 矩阵 [[...],...]；targets: 收益率数组。按时间顺序切分训练/测试，返回样本外 R²、IC、系数。</p>
          <textarea id="mpf" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} placeholder='[[0.1,0.2],[0.3,0.4],...]' />
          <input id="mpt" style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} placeholder='targets: [0.01,0.02,...]' />
          <div style={{ marginTop: 8 }}>
            <select id="mpm" defaultValue="ridge" style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
              <option value="ols">OLS</option><option value="ridge">Ridge</option><option value="lasso">Lasso</option>
            </select>
            <button style={{ ...btn, marginLeft: 10 }} disabled={loading} onClick={() => run(runMlPredict, {
              features: parse(document.getElementById('mpf').value), targets: parse(document.getElementById('mpt').value), method: document.getElementById('mpm').value,
            })}>{loading ? '计算中…' : '预测'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ method: res.method, n_train: res.n_train, n_test: res.n_test, train_r2: res.train_r2, test_r2: res.test_r2, test_ic: res.test_ic, nonzero: res.nonzero_coef }} />
            <div style={{ marginTop: 10, fontSize: 12, color: '#666' }}>系数：{res.feature_names.map((f, i) => `${f}=${res.coefficients[i].toFixed(3)}`).join('  ')}</div>
          </div>}
        </Card>
      )}

      {tabk === 'cluster' && (
        <Card title="聚类选股（KMeans）">
          <p style={{ fontSize: 12, color: '#666' }}>features: JSON 矩阵；names: 标的名数组（可选）；n_clusters: 簇数。</p>
          <textarea id="mcf" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} placeholder='[[...],[...],...]' />
          <input id="mcn" style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} placeholder='names: ["A","B",...] (可选)' />
          <div style={{ marginTop: 8 }}>
            <input id="mck" defaultValue={3} style={{ width: 60, padding: 6, borderRadius: 8, border: '1px solid #ccc' }} />
            <span style={{ fontSize: 12, color: '#666', margin: '0 8px' }}>簇数</span>
            <button style={{ ...btn, marginLeft: 4 }} disabled={loading} onClick={() => {
              const f = parse(document.getElementById('mcf').value)
              const ns = document.getElementById('mcn').value.trim()
              run(runMlCluster, { features: f, names: ns ? parse(ns) : undefined, n_clusters: +document.getElementById('mck').value })
            }}>{loading ? '计算中…' : '聚类'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_clusters: res.n_clusters, inertia: res.inertia, representatives: res.representatives.join(', ') }} />
            {Object.entries(res.clusters).map(([c, v]) => (
              <div key={c} style={{ marginTop: 8, fontSize: 13 }}>
                <b>簇 {c}</b>（{v.size} 只，代表 <b>{v.representative}</b>）：{v.members.join('、')}
              </div>
            ))}
          </div>}
        </Card>
      )}

      {tabk === 'anomaly' && (
        <Card title="异常检测（Z-score / 稳健Z / Isolation Forest）">
          <p style={{ fontSize: 12, color: '#666' }}>series: 收益率数组；method 三选一；threshold 仅对 zscore/robust 生效。</p>
          <textarea id="maf" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} placeholder='[0.01,-0.3,0.02,...]' />
          <div style={{ marginTop: 8 }}>
            <select id="mam" defaultValue="zscore" style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
              <option value="zscore">Z-score</option><option value="robust">稳健Z</option><option value="isolation">Isolation Forest</option>
            </select>
            <input id="math" defaultValue={3.0} style={{ width: 70, padding: 6, marginLeft: 8, borderRadius: 8, border: '1px solid #ccc' }} />
            <span style={{ fontSize: 12, color: '#666', margin: '0 6px' }}>阈值</span>
            <button style={{ ...btn, marginLeft: 4 }} disabled={loading} onClick={() => run(runMlAnomaly, {
              series: parse(document.getElementById('maf').value), method: document.getElementById('mam').value, threshold: +document.getElementById('math').value,
            })}>{loading ? '检测中…' : '检测'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ method: res.method, n_anomalies: res.n_anomalies }} />
            <div style={{ marginTop: 8, fontSize: 13 }}>异常点索引：{res.anomaly_indices.join(', ') || '无'}</div>
            {res.anomaly_dates && <div style={{ fontSize: 13, color: '#c0392b' }}>异常日期：{res.anomaly_dates.join(', ')}</div>}
          </div>}
        </Card>
      )}

      {tabk === 'importance' && (
        <Card title="特征重要性（排列重要性 / 相关性）">
          <p style={{ fontSize: 12, color: '#666' }}>features + targets；method: permutation 或 correlation。</p>
          <textarea id="mif" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} placeholder='features JSON 矩阵' />
          <input id="mit" style={{ width: '100%', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} placeholder='targets: [...]' />
          <div style={{ marginTop: 8 }}>
            <select id="mim" defaultValue="permutation" style={{ padding: 6, borderRadius: 8, border: '1px solid #ccc' }}>
              <option value="permutation">排列重要性</option><option value="correlation">相关性</option>
            </select>
            <button style={{ ...btn, marginLeft: 10 }} disabled={loading} onClick={() => run(runMlImportance, {
              features: parse(document.getElementById('mif').value), targets: parse(document.getElementById('mit').value), method: document.getElementById('mim').value,
            })}>{loading ? '计算中…' : '计算'}</button>
          </div>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ method: res.method, base_r2: res.base_r2 }} />
            <table style={{ width: '100%', marginTop: 10, borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ textAlign: 'left', color: '#888' }}><th>特征</th><th>重要性</th><th>相对</th></tr></thead>
              <tbody>
                {res.ranked.map((r) => (
                  <tr key={r.feature} style={{ borderTop: '1px solid #eee' }}>
                    <td>{r.feature}</td><td>{r.importance.toFixed(4)}</td><td>{(r.relative * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>}
        </Card>
      )}

      {tabk === 'features' && (
        <Card title="特征工程（价格 → 特征矩阵）">
          <p style={{ fontSize: 12, color: '#666' }}>prices: 价格序列（长度 ≥ 30）；自动生成对数收益/多窗口波动率/动量/RSI/乖离Z。</p>
          <textarea id="mgf" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12 }} placeholder='[100,101,99,...]' />
          <button style={{ ...btn, marginTop: 8 }} disabled={loading} onClick={() => run(runMlFeatures, { prices: parse(document.getElementById('mgf').value) })}>{loading ? '构造中…' : '构造特征'}</button>
          {res && <div style={{ marginTop: 12 }}>
            <KV data={{ n_features: res.n_features, n_samples: res.n_samples }} />
            <div style={{ marginTop: 8, fontSize: 13 }}>特征：{res.feature_names.join('、')}</div>
            <div style={{ marginTop: 6, fontSize: 12, color: '#666' }}>样本数：{res.n_samples} × {res.n_features}（矩阵已返回，可用于上方预测/重要性）</div>
          </div>}
        </Card>
      )}

      {err && <div style={{ color: '#c0392b', marginTop: 10 }}>⚠ {err}</div>}
    </div>
  )
}
