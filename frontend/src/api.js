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
