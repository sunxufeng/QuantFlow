const BASE = '/api'

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const detail = await resp.text()
    throw new Error(`HTTP ${resp.status}: ${detail.slice(0, 300)}`)
  }
  if (resp.status === 204) return null
  return resp.json()
}

export const fetchNodes = () => request('/nodes')
export const fetchWorkflows = () => request('/workflows')
export const fetchWorkflow = (id) => request(`/workflows/${id}`)
export const createWorkflow = (workflow) => request('/workflows', {
  method: 'POST',
  body: JSON.stringify(workflow),
})
export const updateWorkflow = (id, workflow) => request(`/workflows/${id}`, {
  method: 'PUT',
  body: JSON.stringify(workflow),
})
export const deleteWorkflow = (id) => request(`/workflows/${id}`, { method: 'DELETE' })
export const importWorkflow = (workflow) => request('/workflows/import', {
  method: 'POST',
  body: JSON.stringify(workflow),
})
export const exportWorkflow = (id) => request(`/workflows/${id}/export`)
export const validateWorkflow = (workflow) => request('/workflows/validate', {
  method: 'POST',
  body: JSON.stringify(workflow),
})
export const runWorkflow = (workflow) => request('/workflows/run', {
  method: 'POST',
  body: JSON.stringify(workflow),
})

// ---- M2 异步运行 + WebSocket ----
export const submitRun = (payload) => request('/runs', {
  method: 'POST',
  body: JSON.stringify(payload),
})
export const getRun = (runId) => request(`/runs/${runId}`)
export const listRuns = (limit = 30) => request(`/runs?limit=${limit}`)

export function runWsUrl(runId) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/api/ws/runs/${runId}`
}

// ---- 行情 ----
export const fetchInstruments = () => request('/market/instruments')
export const fetchBars = (symbol, start, end) => request(
  `/market/bars?symbol=${encodeURIComponent(symbol)}&as_table=false${start ? `&start=${start}` : ''}${end ? `&end=${end}` : ''}`,
)
