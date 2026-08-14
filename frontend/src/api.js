const BASE = '/api'
const TOKEN_KEY = 'qf_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

async function request(path, options = {}) {
  const token = getToken()
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!resp.ok) {
    let detail = await resp.text()
    try { detail = JSON.parse(detail).detail || detail } catch { /* keep text */ }
    // 登录态失效（非认证接口返回 401）→ 清除令牌并通知应用回到登录页
    if (resp.status === 401 && !path.startsWith('/auth/')) {
      clearToken()
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('qf:unauthorized'))
      }
    }
    const err = new Error(`HTTP ${resp.status}: ${String(detail).slice(0, 300)}`)
    err.status = resp.status
    throw err
  }
  if (resp.status === 204) return null
  return resp.json()
}

// ---- 认证（M4-1）----
export const register = (username, password) => request('/auth/register', {
  method: 'POST',
  body: JSON.stringify({ username, password }),
})
export const login = (username, password) => request('/auth/login', {
  method: 'POST',
  body: JSON.stringify({ username, password }),
})
export const getMe = () => request('/auth/me')

// ---- 项目（M4-2）----
export const fetchProjects = () => request('/projects')
export const createProject = (name, description = '') => request('/projects', {
  method: 'POST',
  body: JSON.stringify({ name, description }),
})
export const deleteProject = (id) => request(`/projects/${id}`, { method: 'DELETE' })
export const fetchMembers = (projectId) => request(`/projects/${projectId}/members`)
export const addMember = (projectId, username, role) => request(`/projects/${projectId}/members`, {
  method: 'POST',
  body: JSON.stringify({ username, role }),
})
export const removeMember = (projectId, userId) => request(`/projects/${projectId}/members/${userId}`, { method: 'DELETE' })

// ---- 日志 / 监控（M4-3 / M4-4）----
export const fetchLogs = ({ level, keyword, limit = 100 } = {}) => {
  const qs = new URLSearchParams()
  if (level) qs.set('level', level)
  if (keyword) qs.set('keyword', keyword)
  qs.set('limit', String(limit))
  return request(`/logs?${qs.toString()}`)
}
export const fetchOverview = () => request('/monitoring/overview')

// ---- 节点 / 工作流 ----
export const fetchNodes = () => request('/nodes')
export const fetchWorkflows = (projectId, scope = 'all') => {
  const qs = new URLSearchParams()
  if (projectId) qs.set('project_id', projectId)
  if (scope !== 'all') qs.set('scope', scope)
  const query = qs.toString()
  return request(`/workflows${query ? `?${query}` : ''}`)
}
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
export const fetchWorkflowVersions = (id) => request(`/workflows/${id}/versions`)
export const createWorkflowVersion = (id, label) => request(`/workflows/${id}/versions`, {
  method: 'POST',
  body: JSON.stringify(label ? { label } : {}),
})
export const restoreWorkflowVersion = (id, version) => request(
  `/workflows/${id}/versions/${version}/restore`,
  { method: 'POST' },
)
export const validateWorkflow = (workflow) => request('/workflows/validate', {
  method: 'POST',
  body: JSON.stringify(workflow),
})
export const runWorkflow = (workflow) => request('/workflows/run', {
  method: 'POST',
  body: JSON.stringify(workflow),
})

// ---- 内置示例工作流模板库（V1.1 遗留项 / V1.3 扩展）----
export const listTemplates = () => request('/workflows/templates')

// ---- M2 异步运行 + WebSocket ----
export const submitRun = (payload) => request('/runs', {
  method: 'POST',
  body: JSON.stringify(payload),
})
export const getRun = (runId) => request(`/runs/${runId}`)
export const listRuns = (limit = 30) => request(`/runs?limit=${limit}`)

export function runWsUrl(runId) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = getToken()
  return `${proto}//${location.host}/api/ws/runs/${runId}${token ? `?token=${encodeURIComponent(token)}` : ''}`
}

// ---- 行情 ----
export const fetchInstruments = () => request('/market/instruments')
export const fetchBars = (symbol, start, end) => request(
  `/market/bars?symbol=${encodeURIComponent(symbol)}&as_table=false${start ? `&start=${start}` : ''}${end ? `&end=${end}` : ''}`,
)
export const marketSyncStatus = () => request('/market/sync/status')
export const marketSyncNow = () => request('/market/sync', { method: 'POST' })

// ---- 回测报告中心（V1.6）----
export const backtestReports = () => request('/backtest/reports')
export const backtestReport = (runId) => request(`/backtest/reports/${runId}`)
export const backtestStrategies = () => request('/backtest/strategies')
export const runBacktest = (payload) => request('/backtest/run', { method: 'POST', body: JSON.stringify(payload) })
export const optimizeBacktest = (payload) => request('/backtest/optimize', { method: 'POST', body: JSON.stringify(payload) })

// ---- 因子库 CRUD（V1.1 N3）----
export const factorLibraryList = (category) => request(
  `/factors/library${category ? `?category=${encodeURIComponent(category)}` : ''}`,
)
export const factorLibraryCreate = (factor) => request('/factors/library', {
  method: 'POST',
  body: JSON.stringify(factor),
})
export const factorLibraryUpdate = (id, factor) => request(`/factors/library/${id}`, {
  method: 'PUT',
  body: JSON.stringify(factor),
})
export const factorLibraryDelete = (id) => request(`/factors/library/${id}`, {
  method: 'DELETE',
})
export const factorAnalyze = (payload) => request('/factors/analyze', {
  method: 'POST',
  body: JSON.stringify(payload),
})

// ---- 通知渠道配置（V1.1 N5）----
export const notificationsList = () => request('/notifications')
export const notificationsCreate = (channel) => request('/notifications', {
  method: 'POST',
  body: JSON.stringify(channel),
})
export const notificationsDelete = (id) => request(`/notifications/${id}`, {
  method: 'DELETE',
})
export const notificationsTest = (id) => request(`/notifications/${id}/test`, {
  method: 'POST',
})

// ---- LLM 策略助手（V1.1 N1）----
export const llmStatus = () => request('/llm/status')
export const llmAssist = (payload) => request('/llm/assist', {
  method: 'POST',
  body: JSON.stringify(payload),
})

// ---- LLM 自定义配置（V1.4 配置页）----
export const llmGetConfig = () => request('/llm/config')
export const llmSaveConfig = (cfg) => request('/llm/config', {
  method: 'PUT',
  body: JSON.stringify(cfg),
})
export const llmTestConfig = (cfg) => request('/llm/config/test', {
  // cfg 可选：不传则测当前已保存配置
  method: 'POST',
  body: JSON.stringify(cfg || {}),
})

// ---- 券商凭证配置（V1.7 设置页）----
export const brokerGetConfig = () => request('/settings/broker')
export const brokerSaveConfig = (cfg) => request('/settings/broker', {
  method: 'PUT',
  body: JSON.stringify(cfg),
})
export const brokerTestConfig = (cfg) => request('/settings/broker/test', {
  // cfg 可选：不传则测当前已保存配置
  method: 'POST',
  body: JSON.stringify(cfg || {}),
})
