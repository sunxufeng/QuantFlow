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
// ---- V3.0 AI 策略工作台：自然语言生成工作流 ----
export const generateWorkflow = (prompt, useLlm = true) =>
  request('/workflows/generate', {
    method: 'POST',
    body: JSON.stringify({ prompt, use_llm: useLlm }),
  })
// ---- V3.4 批量生成并对比回测 ----
export const batchGenerateCompare = (payload) =>
  request('/workflows/batch-generate-compare', {
    method: 'POST',
    body: JSON.stringify(payload),
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

// ---- 个人工作流模板库（V3.1 模板市场）----
export const listMyTemplates = () => request('/workflows/templates/mine')
export const saveTemplate = (payload) => request('/workflows/templates', {
  method: 'POST',
  body: JSON.stringify(payload),
})
export const deleteTemplate = (id) => request(`/workflows/templates/${id}`, {
  method: 'DELETE',
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
// ---- V5.0 行情缓存 / 数据源管理 ----
export const marketCache = () => request('/market/cache')
export const marketRefresh = (payload = {}) =>
  request('/market/cache/refresh', { method: 'POST', body: JSON.stringify(payload) })
// ---- V5.1 自选股监控 + 价格预警 ----
export const watchlistMonitor = () => request('/market/watchlist/monitor')

// ---- 回测报告中心（V1.6）----
export const backtestReports = () => request('/backtest/reports')
export const backtestReport = (runId) => request(`/backtest/reports/${runId}`)
// ---- 回测对比与排行榜（V2.8）----
export const backtestCompare = (ids) =>
  request(`/backtest/compare?ids=${encodeURIComponent(ids.join(','))}`)
export const backtestLeaderboard = (metric = 'sharpe', order = 'desc') =>
  request(`/backtest/leaderboard?metric=${metric}&order=${order}`)
export const exportBacktestReport = async (runId, format = 'csv') => {
  const token = getToken()
  const resp = await fetch(`${BASE}/backtest/reports/${runId}/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`)
  }
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `backtest_${runId}.${format}`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// ---- 预警规则引擎（V2.3）----
export const listAlerts = () => request('/alerts')
export const createAlert = (payload) => request('/alerts', { method: 'POST', body: JSON.stringify(payload) })
export const deleteAlert = (id) => request(`/alerts/${id}`, { method: 'DELETE' })
export const toggleAlert = (id, payload) => request(`/alerts/${id}/toggle`, { method: 'POST', body: JSON.stringify(payload) })
export const evaluateAlerts = () => request('/alerts/evaluate', { method: 'POST' })
export const alertSchedulerStatus = () => request('/alerts/scheduler')
export const triggerAlertScheduler = () => request('/alerts/scheduler/trigger', { method: 'POST' })
// ---- V5.2 调度中心 ----
export const schedulerCenter = () => request('/schedules/center')
export const listSchedules = () => request('/schedules')
export const createSchedule = (payload) =>
  request('/schedules', { method: 'POST', body: JSON.stringify(payload) })
export const runSchedule = (id) => request(`/schedules/${id}/run`, { method: 'POST' })
export const toggleSchedule = (id, enabled) =>
  request(`/schedules/${id}/toggle`, { method: 'POST', body: JSON.stringify({ enabled }) })
export const deleteSchedule = (id) => request(`/schedules/${id}`, { method: 'DELETE' })
export const listWorkflows = (scope = 'all') =>
  request(`/workflows?scope=${scope}`)

// ---- 自选股监控 / 行情看板（V2.4）----
export const getWatchlist = () => request('/market/watchlist')
export const addWatchlist = (symbol) => request(`/market/watchlist?symbol=${encodeURIComponent(symbol)}`, { method: 'POST' })
export const removeWatchlist = (symbol) => request(`/market/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' })
export const getQuotes = (symbols) => request(`/market/quotes?symbols=${encodeURIComponent(symbols)}`)
export const backtestStrategies = () => request('/backtest/strategies')
export const runBacktest = (payload) => request('/backtest/run', { method: 'POST', body: JSON.stringify(payload) })
export const optimizeBacktest = (payload) => request('/backtest/optimize', { method: 'POST', body: JSON.stringify(payload) })
export const runPortfolioBacktest = (payload) => request('/backtest/portfolio', { method: 'POST', body: JSON.stringify(payload) })
export const runSensitivity = (payload) => request('/backtest/sensitivity', { method: 'POST', body: JSON.stringify(payload) })
export const runMonteCarlo = (payload) => request('/backtest/montecarlo', { method: 'POST', body: JSON.stringify(payload) })
export const runSensitivityGrid = (payload) => request('/backtest/sensitivity-grid', { method: 'POST', body: JSON.stringify(payload) })
export const runWalkForward = (payload) => request('/backtest/walkforward', { method: 'POST', body: JSON.stringify(payload) })
export const runBenchmarkCompare = (payload) => request('/backtest/benchmark-compare', { method: 'POST', body: JSON.stringify(payload) })
export const listBenchmarks = () => request('/backtest/benchmarks')
export const saveBenchmark = (payload) => request('/backtest/benchmarks', { method: 'POST', body: JSON.stringify(payload) })
export const deleteBenchmark = (benchId) => request(`/backtest/benchmarks/${benchId}`, { method: 'DELETE' })
export const runFactorDecay = (payload) => request('/backtest/factor-decay', { method: 'POST', body: JSON.stringify(payload) })
export const runRobustness = (payload) => request('/backtest/robustness', { method: 'POST', body: JSON.stringify(payload) })
export const runBenchmarkWeighted = (payload) => request('/backtest/benchmark-weighted', { method: 'POST', body: JSON.stringify(payload) })
export const runMetricsExtended = (payload) => request('/backtest/metrics-extended', { method: 'POST', body: JSON.stringify(payload) })
export const genSynthetic = (payload) => request('/backtest/market/synthetic', { method: 'POST', body: JSON.stringify(payload) })
export const runSyntheticBacktest = (payload) => request('/backtest/synthetic-run', { method: 'POST', body: JSON.stringify(payload) })
export const runForwardSim = (payload) => request('/backtest/forward-sim', { method: 'POST', body: JSON.stringify(payload) })
export const runSeasonality = (payload) => request('/backtest/seasonality', { method: 'POST', body: JSON.stringify(payload) })
export const runPortfolioOptimize = (payload) => request('/backtest/portfolio-optimize', { method: 'POST', body: JSON.stringify(payload) })
export const runTradeAnalysis = (payload) => request('/backtest/trade-analysis', { method: 'POST', body: JSON.stringify(payload) })
export const runAttribution = (payload) => request('/backtest/performance-attribution', { method: 'POST', body: JSON.stringify(payload) })
export const runDataQuality = (payload) => request('/backtest/data-quality', { method: 'POST', body: JSON.stringify(payload) })
export const getStressScenarios = () => request('/backtest/stress-scenarios')
export const runStressTest = (payload) => request('/backtest/stress-test', { method: 'POST', body: JSON.stringify(payload) })
export const getFactorBacktestCatalog = () => request('/factors/backtest/catalog')
export const runFactorBacktest = (payload) => request('/factors/backtest', { method: 'POST', body: JSON.stringify(payload) })

// ---- 组合优化增强（V32–V36）----
const _portOpt = (path, payload) => request(`/portfolio/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runRiskParity = (payload) => _portOpt('risk-parity', payload)
export const runMaxDiversification = (payload) => _portOpt('max-diversification', payload)
export const runHRP = (payload) => _portOpt('hrp', payload)
export const runRebalance = (payload) => _portOpt('rebalance', payload)
export const runStyleExposure = (payload) => _portOpt('style-exposure', payload)

// ---- 因子工程深化（V37–V41）----
const _facEng = (path, payload) => request(`/factors/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runOrthogonalize = (payload) => _facEng('orthogonalize', payload)
export const runOrthogonalizeAll = (payload) => _facEng('orthogonalize-all', payload)
export const runFactorTiming = (payload) => _facEng('timing', payload)
export const runFactorCrowding = (payload) => _facEng('crowding', payload)
export const runCombineFactors = (payload) => _facEng('combine', payload)
export const runFactorTurnover = (payload) => _facEng('turnover', payload)

// ---- 风险分析（V42–V46）----
const _risk = (path, payload) => request(`/risk/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runVarCvar = (payload) => _risk('var', payload)
export const runVarBacktest = (payload) => _risk('var-backtest', payload)
export const runDrawdown = (payload) => _risk('drawdown', payload)
export const runTailRisk = (payload) => _risk('tail', payload)
export const runLiquidity = (payload) => _risk('liquidity', payload)
export const runConcentration = (payload) => _risk('concentration', payload)
export const getLivePositions = () => request('/trading/live/positions')

// ---- 市场状态与择时（V47–V51）----
const _mkt = (path, payload) => request(`/market/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runRegime = (payload) => _mkt('regime', payload)
export const runVolForecast = (payload) => _mkt('vol-forecast', payload)
export const runSectorRotation = (payload) => _mkt('sector-rotation', payload)
export const runCorrelationNetwork = (payload) => _mkt('correlation-network', payload)
export const runEtfRotation = (payload) => _mkt('etf-rotation', payload)

// ---- 策略库扩展（V52–V56）----
const _stx = (path, payload) => request(`/strategy/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runPairsCoint = (payload) => _stx('pairs-coint', payload)
export const runPairsBacktest = (payload) => _stx('pairs-backtest', payload)
export const runOptionPrice = (payload) => _stx('option-price', payload)
export const runOptionGreeks = (payload) => _stx('option-greeks', payload)
export const runOptionIV = (payload) => _stx('option-implied-vol', payload)
export const runGridBacktest = (payload) => _stx('grid-backtest', payload)
export const runDcaBacktest = (payload) => _stx('dca-backtest', payload)
export const runMultiTrend = (payload) => _stx('multi-trend', payload)
export const getLiveFills = () => request('/trading/live/fills')

// ---- ML 量化分析（V57–V61）----
const _ml = (path, payload) => request(`/ml/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runMlPredict = (payload) => _ml('predict', payload)
export const runMlCluster = (payload) => _ml('cluster', payload)
export const runMlAnomaly = (payload) => _ml('anomaly', payload)
export const runMlImportance = (payload) => _ml('importance', payload)
export const runMlFeatures = (payload) => _ml('features', payload)

// ---- 执行成本与最优执行（V62–V66）----
const _exec = (path, payload) => request(`/execution/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runExecCost = (payload) => _exec('cost', payload)
export const runExecImpact = (payload) => _exec('impact', payload)
export const runExecTwap = (payload) => _exec('twap', payload)
export const runExecVwap = (payload) => _exec('vwap', payload)
export const runExecSlippage = (payload) => _exec('slippage', payload)

// ---- 报告与运维增强（V67–V71）----
const _rep = (path, payload) => request(`/reports/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runReportPerformance = (payload) => _rep('performance', payload)
export const runReportCompare = (payload) => _rep('compare', payload)
export const runReportMulti = (payload) => _rep('multi-compare', payload)
export const runReportPeriodic = (payload) => _rep('periodic', payload)
export const runReportDashboard = (payload) => _rep('dashboard', payload)

// ---- 组合层面增强（V72–V76）----
const _pi = (path, payload) => request(`/portfolioi/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runPIBlackLitterman = (payload) => _pi('black-litterman', payload)
export const runPIFactorPortfolio = (payload) => _pi('factor-portfolio', payload)
export const runPIStressTest = (payload) => _pi('stress-test', payload)
export const runPIRebalance = (payload) => _pi('rebalance', payload)
export const runPIAggregate = (payload) => _pi('aggregate', payload)

// ---- 风险归因与因子风险模型（V77–V81）----
const _ra = (path, payload) => request(`/riskattr/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runFactorRisk = (payload) => _ra('factor-risk', payload)
export const runFactorReturn = (payload) => _ra('factor-return', payload)
export const runComponentVar = (payload) => _ra('component-var', payload)
export const runRiskTree = (payload) => _ra('risk-tree', payload)
export const runTailMetrics = (payload) => _ra('tail', payload)

// ---- 衍生品策略与对冲（V82–V86）----
const _deriv = (path, payload) => request(`/deriv/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runOptionPayoff = (payload) => _deriv('payoff', payload)
export const runDeltaHedge = (payload) => _deriv('delta-hedge', payload)
export const runPortfolioInsurance = (payload) => _deriv('insurance', payload)
export const runPortfolioGreeks = (payload) => _deriv('portfolio-greeks', payload)
export const runVolSurface = (payload) => _deriv('vol-surface', payload)

// ---- 组合监控与预警（V87–V91）----
const _mon = (path, payload) => request(`/monalert/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runDriftMonitor = (payload) => _mon('drift', payload)
export const runReturnQuality = (payload) => _mon('return-quality', payload)
export const runTrackingError = (payload) => _mon('tracking-error', payload)
export const runSectorExposure = (payload) => _mon('sector-exposure', payload)
export const runRiskBudget = (payload) => _mon('risk-budget', payload)

// ---- 策略评估与显著性（V92–V96）----
const _sig = (path, payload) => request(`/sig/${path}`, { method: 'POST', body: JSON.stringify(payload) })
export const runDeflatedSharpe = (payload) => _sig('deflated-sharpe', payload)
export const runProbabilisticSharpe = (payload) => _sig('probabilistic-sharpe', payload)
export const runStrategyCapacity = (payload) => _sig('capacity', payload)
export const runRegimeStats = (payload) => _sig('regime-stats', payload)
export const runStrategyDiversification = (payload) => _sig('diversification', payload)

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

// ---- V2.5 因子评分 ----
export const factorScoringCatalog = () => request('/factors/scoring/catalog')
export const factorScore = (payload) => request('/factors/scoring/score', {
  method: 'POST',
  body: JSON.stringify(payload),
})
// ---- 因子研究（V2.9）：相关性矩阵 + IC/IR ----
export const factorResearchMatrix = (params = {}) =>
  request(`/factors/research/matrix?${new URLSearchParams(params).toString()}`)
export const factorResearchIc = (params = {}) =>
  request(`/factors/research/ic?${new URLSearchParams(params).toString()}`)
// ---- 因子排行榜（V3.2）：按 IC/IR 排序 ----
export const factorResearchRanking = (params = {}) =>
  request(`/factors/research/ranking?${new URLSearchParams(params).toString()}`)

// ---- 多因子组合回测闭环（V4.2）----
export const multifactorBacktest = (payload) =>
  request('/factors/research/multifactor', { method: 'POST', body: JSON.stringify(payload) })

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

// ---- V6.1 系统设置 + 用户偏好 ----
export const getSettings = () => request('/settings')
export const updateSettings = (prefs = {}) => request('/settings', {
  method: 'PUT',
  body: JSON.stringify(prefs),
})

// ---- V7.0 投研工作区总览快照 ----
export const fetchWorkspace = () => request('/workspace')

// ---- V6.2 批量导出中心 ----
export const exportData = (resource, format = 'json') =>
  fetch(`/api/export?resource=${encodeURIComponent(resource)}&format=${encodeURIComponent(format)}`, {
    headers: { Authorization: `Bearer ${getToken() || ''}` },
  })

// ---- V7.1 用户行情导入 ----
export const uploadMarket = (payload) => request('/market/upload', {
  method: 'POST',
  body: JSON.stringify(payload),
})
export const listUploaded = () => request('/market/uploaded')
export const deleteUploaded = (symbol) => request(`/market/uploaded/${encodeURIComponent(symbol)}`, {
  method: 'DELETE',
})

// ---- V8.0 公共模板市场 ----
export const templateMarket = () => request('/workflows/templates/market')
export const shareTemplate = (id, publicFlag) => request(`/workflows/templates/${id}/share`, {
  method: 'POST',
  body: JSON.stringify({ public: publicFlag }),
})

// ---- V9.0 回测实验追踪（标签 / 备注）----
export const patchReport = (runId, payload) => request(`/backtest/reports/${runId}`, {
  method: 'PATCH',
  body: JSON.stringify(payload),
})
export const reportTags = () => request('/backtest/tags')
export const reportFactors = (runId) => request(`/backtest/reports/${runId}/factors`)

// ---- V10.0 模拟交易（paper trading，无真实券商）----
export const tradingMode = () => request('/trading/mode')
export const tradingLiveStatus = () => request('/trading/live/status')
export const tradingAccount = () => request('/trading/account')
export const tradingSummary = () => request('/trading/summary')
export const tradingAnalytics = () => request('/trading/analytics')
export const tradingPositions = () => request('/trading/positions')
export const tradingOrders = (status = '') =>
  request(`/trading/orders${status ? `?status=${status}` : ''}`)
export const placeTradingOrder = (payload) => request('/trading/orders', {
  method: 'POST',
  body: JSON.stringify(payload),
})
export const cancelTradingOrder = (id) => request(`/trading/orders/${id}/cancel`, {
  method: 'POST',
})
export const simulateTrading = (priceOverrides = {}) => request('/trading/simulate', {
  method: 'POST',
  body: JSON.stringify({ price_overrides: priceOverrides }),
})
export const resetTrading = (initialCash = null) => request('/trading/reset', {
  method: 'DELETE',
  body: JSON.stringify(initialCash != null ? { initial_cash: initialCash } : {}),
})

