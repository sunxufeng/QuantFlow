import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'
import WorkflowNode from './WorkflowNode.jsx'
import Palette from './Palette.jsx'
import PropertyPanel from './PropertyPanel.jsx'
import ChartView from './ChartView.jsx'
import Monitoring from './Monitoring.jsx'
import FactorLibrary from './FactorLibrary.jsx'
import Notifications from './Notifications.jsx'
import LLMAssistant from './LLMAssistant.jsx'
import LLMSettings from './LLMSettings.jsx'
import Templates from './Templates.jsx'
import AuthModal from './AuthModal.jsx'
import BacktestResultView from './BacktestResultView.jsx'
import BacktestReports from './BacktestReports.jsx'
import BrokerSettings from './BrokerSettings.jsx'
import LoginScreen from './LoginScreen.jsx'
import { useGraphHistory } from './useHistory.js'
import {
  clearToken,
  createProject,
  createWorkflow,
  deleteProject,
  deleteWorkflow,
  exportWorkflow,
  fetchNodes,
  fetchProjects,
  fetchWorkflow,
  fetchWorkflows,
  fetchWorkflowVersions,
  createWorkflowVersion,
  restoreWorkflowVersion,
  getMe,
  getToken,
  importWorkflow,
  listRuns,
  runWsUrl,
  submitRun,
  updateWorkflow,
  validateWorkflow,
} from './api.js'

const nodeTypes = { qf: WorkflowNode }

function ResultPanel({ result, error, busy, runStatus, onClose }) {
  return (
    <div className="qf-result">
      <div className="qf-result-head">
        <h3>运行结果</h3>
        {onClose && <button className="qf-btn qf-btn-sm" onClick={onClose}>×</button>}
      </div>
      {busy && <div className="qf-busy">提交中…</div>}
      {error && <div className="qf-error">{error}</div>}
      {runStatus && (
        <div className="qf-run-meta">
          状态 <b className={`qf-run-${runStatus}`}>{runStatus}</b>
        </div>
      )}
      {result && result.nodes?.length ? (
        <table className="qf-state-table">
          <thead>
            <tr><th>节点</th><th>状态</th><th>耗时(ms)</th><th>输出</th><th>错误</th></tr>
          </thead>
          <tbody>
            {result.nodes.map((n) => (
              <tr key={n.node_id}>
                <td>{n.node_id}</td>
                <td className={`qf-run-${n.status}`}>{n.status}</td>
                <td>{n.duration_ms}</td>
                <td className="qf-cell-out">
                  {n.outputs && n.outputs.attribution ? (
                    <BacktestResultView outputs={n.outputs} />
                  ) : n.outputs ? (
                    Object.entries(n.outputs).map(([k, v]) => (
                      <div key={k}>{k} = {v && v.__type__ === 'table' ? `table(${v.rows.length}行)` : JSON.stringify(v)}</div>
                    ))
                  ) : ''}
                </td>
                <td>{n.error || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : runStatus && (
        <div className="qf-busy">运行中… 节点状态实时更新到画布</div>
      )}
    </div>
  )
}

function RunsPanel({ runs, activeRunId, onSelectRun, onRefresh }) {
  return (
    <div className="qf-runs">
      <div className="qf-result-head">
        <h3>运行记录</h3>
        <button className="qf-btn qf-btn-sm" onClick={onRefresh}>刷新</button>
      </div>
      {runs.length === 0 && <div className="qf-prop-hint">暂无运行记录</div>}
      {runs.map((r) => (
        <div
          key={r.run_id}
          className={`qf-run-item ${r.run_id === activeRunId ? 'qf-run-item-active' : ''}`}
          onClick={() => onSelectRun(r.run_id)}
        >
          <span className={`qf-run-dot qf-run-${r.status}`} />
          <div className="qf-run-item-body">
            <div className="qf-run-item-name">{r.workflow_name || r.run_id.slice(0, 8)}</div>
            <div className="qf-run-item-meta">
              {r.status} · {new Date(r.started_at).toLocaleTimeString()}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function VersionHistoryModal({ workflowId, onClose, onRestore, setError }) {
  const [versions, setVersions] = useState([])
  const [busy, setBusy] = useState(false)
  const [label, setLabel] = useState('')
  const [error, setLocalError] = useState('')

  const load = useCallback(() => {
    setBusy(true)
    setLocalError('')
    fetchWorkflowVersions(workflowId)
      .then(setVersions)
      .catch((e) => setLocalError(`加载版本历史失败: ${e.message}`))
      .finally(() => setBusy(false))
  }, [workflowId])

  useEffect(() => { load() }, [load])

  const onSnapshot = useCallback(async () => {
    setBusy(true)
    setLocalError('')
    try {
      await createWorkflowVersion(workflowId, label.trim() || undefined)
      setLabel('')
      await load()
    } catch (e) {
      setLocalError(`保存版本失败: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }, [workflowId, label, load])

  const onDoRestore = useCallback(async (version) => {
    if (!window.confirm(`恢复到版本 v${version}？当前画布与工作流将被该版本覆盖。`)) return
    setBusy(true)
    setLocalError('')
    try {
      const restored = await restoreWorkflowVersion(workflowId, version)
      onRestore(restored)
      onClose()
    } catch (e) {
      setLocalError(`恢复失败: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }, [workflowId, onClose, onRestore])

  return (
    <div className="qf-modal-mask" onClick={onClose}>
      <div className="qf-modal" onClick={(e) => e.stopPropagation()} style={{ width: 460 }}>
        <div className="qf-modal-head">
          <h3>版本历史</h3>
          <button className="qf-btn qf-btn-sm" onClick={onClose}>×</button>
        </div>
        <div className="qf-modal-body">
          {error && <div className="qf-error">{error}</div>}
          {localError && <div className="qf-error">{localError}</div>}
          {busy && versions.length === 0 && <div className="qf-busy">加载中…</div>}
          {!busy && versions.length === 0 && (
            <div className="qf-prop-hint">暂无版本快照。编辑后点击「保存当前为新版本」即可创建。</div>
          )}
          <div className="qf-ver-list">
            {versions.map((v) => (
              <div className="qf-ver-item" key={v.id}>
                <div className="qf-ver-main">
                  <span className="qf-ver-label">{v.label}</span>
                  <span className="qf-ver-meta">
                    v{v.version} · {v.node_count} 节点 / {v.edge_count} 连线 · {new Date(v.saved_at).toLocaleString()}
                  </span>
                </div>
                <button className="qf-btn qf-btn-sm" disabled={busy} onClick={() => onDoRestore(v.version)}>恢复</button>
              </div>
            ))}
          </div>
          <div className="qf-ver-save">
            <input
              className="qf-name-input"
              placeholder="版本备注（可选）"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              style={{ flex: 1 }}
            />
            <button className="qf-btn qf-btn-primary" disabled={busy} onClick={onSnapshot}>保存当前为新版本</button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Canvas({ projectId, pendingTemplate, onTemplateConsumed }) {
  const [specs, setSpecs] = useState([])
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedId, setSelectedId] = useState(null)
  const [runNodeStates, setRunNodeStates] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [savedWorkflows, setSavedWorkflows] = useState([])
  const [workflowId, setWorkflowId] = useState('')
  const [workflowName, setWorkflowName] = useState('Untitled workflow')
  const [runId, setRunId] = useState('')
  const [runStatus, setRunStatus] = useState('')
  const [runs, setRuns] = useState([])
  const [rightTab, setRightTab] = useState('props')
  const [versionsOpen, setVersionsOpen] = useState(false)
  const rf = useReactFlow()
  const idRef = useRef(0)
  const importRef = useRef(null)

  const { canUndo, canRedo, undo, redo, clearHistory } = useGraphHistory(nodes, edges, setNodes, setEdges)

  const specOf = useCallback(
    (type) => specs.find((s) => s.node_type === type),
    [specs],
  )

  const applyWorkflow = useCallback((workflow) => {
    const restoredNodes = workflow.nodes.map((node, index) => {
      const spec = specOf(node.node_type)
      if (!spec) throw new Error(`节点类型不可用: ${node.node_type}`)
      return {
        id: node.id,
        type: 'qf',
        position: node.position || { x: 80 + index * 220, y: 120 },
        data: { nodeType: node.node_type, spec, params: node.params || {} },
      }
    })
    setNodes(restoredNodes)
    setEdges(workflow.edges.map((edge) => ({
      id: edge.id || `${edge.source}-${edge.source_port}-${edge.target}-${edge.target_port}`,
      source: edge.source,
      sourceHandle: edge.source_port,
      target: edge.target,
      targetHandle: edge.target_port,
    })))
    const maxSuffix = restoredNodes.reduce((max, node) => {
      const m = node.id.match(/-(\d+)$/)
      return m ? Math.max(max, Number(m[1])) : max
    }, restoredNodes.length)
    idRef.current = Math.max(idRef.current, maxSuffix)
    setRunNodeStates({})
    setRunId('')
    setRunStatus('')
    setResult(null)
    setError('')
    clearHistory()
  }, [clearHistory, setEdges, setNodes, specOf])

  const refreshWorkflows = useCallback(() => {
    return fetchWorkflows(projectId).then(setSavedWorkflows)
  }, [projectId])

  const refreshRuns = useCallback(() => {
    return listRuns().then((r) => setRuns(r.items || []))
  }, [])

  useEffect(() => {
    fetchNodes().then((list) => {
      setSpecs(list)
      if (list.length) addNode(list.find((s) => s.node_type === 'data.constant'), { x: 60, y: 120 })
    }).catch((e) => setError(`节点库加载失败: ${e.message}`))
    refreshWorkflows().catch((e) => setError(`工作流列表加载失败: ${e.message}`))
    refreshRuns().catch(() => {})
  }, [])

  // 切换项目时刷新工作流列表
  useEffect(() => {
    refreshWorkflows().catch(() => {})
  }, [projectId, refreshWorkflows])

  // 模板库加载：节点规格就绪后再 apply，避免「节点类型不可用」
  useEffect(() => {
    if (!pendingTemplate) return
    if (!specs.length) return
    try {
      applyWorkflow(pendingTemplate)
      setSelectedId(null)
      setError('')
    } catch (e) {
      setError(`模板加载失败: ${e.message}`)
    } finally {
      onTemplateConsumed?.()
    }
  }, [pendingTemplate, specs, applyWorkflow, onTemplateConsumed, setSelectedId])

  const addNode = useCallback((spec, position) => {
    const id = `${spec.node_type}-${++idRef.current}`
    const params = {}
    for (const p of spec.params) params[p.name] = p.default
    setNodes((nds) => [...nds, {
      id,
      type: 'qf',
      position,
      data: { nodeType: spec.node_type, spec, params },
    }])
    return id
  }, [setNodes])

  const patchNodeParams = useCallback((id, patch) => {
    setNodes((nds) => nds.map((n) => (
      n.id === id ? { ...n, data: { ...n.data, params: { ...n.data.params, ...patch } } } : n
    )))
  }, [setNodes])

  const removeNode = useCallback((id) => {
    setNodes((nds) => nds.filter((n) => n.id !== id))
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id))
    setSelectedId((cur) => (cur === id ? null : cur))
  }, [setEdges, setNodes])

  // ---- 连接：类型校验 + 去重 + 防自环 ----
  const onConnect = useCallback((conn) => {
    if (conn.source === conn.target) {
      setError('不能连接节点自身')
      return
    }
    const srcSpec = specOf(nodes.find((n) => n.id === conn.source)?.data?.nodeType)
    const dstSpec = specOf(nodes.find((n) => n.id === conn.target)?.data?.nodeType)
    const srcPort = srcSpec?.outputs.find((p) => p.name === conn.sourceHandle)
    const dstPort = dstSpec?.inputs.find((p) => p.name === conn.targetHandle)
    if (srcPort && dstPort && srcPort.type !== dstPort.type && srcPort.type !== 'any' && dstPort.type !== 'any') {
      setError(`端口类型不匹配：${srcPort.name}(${srcPort.type}) → ${dstPort.name}(${dstPort.type})`)
      return
    }
    const dup = edges.some((e) =>
      e.source === conn.source && e.sourceHandle === conn.sourceHandle &&
      e.target === conn.target && e.targetHandle === conn.targetHandle)
    if (dup) return
    setError('')
    setEdges((eds) => addEdge({ ...conn, type: 'default' }, eds))
  }, [edges, nodes, setEdges, specOf])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/qf-type')
    if (!type) return
    const spec = specOf(type)
    if (!spec) return
    const pos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    addNode(spec, pos)
  }, [specOf, addNode, rf])

  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  // ---- 键盘快捷键：撤销/重做/删除 ----
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo() }
      else if (mod && e.shiftKey && (e.key === 'z' || e.key === 'Z')) { e.preventDefault(); redo() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [undo, redo])

  const buildWorkflow = useCallback(() => ({
    nodes: nodes.map((n) => ({
      id: n.id,
      node_type: n.data.nodeType,
      params: n.data.params,
      position: n.position,
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      source_port: e.sourceHandle,
      target: e.target,
      target_port: e.targetHandle,
    })),
  }), [nodes, edges])

  const onSave = useCallback(async () => {
    const payload = {
      name: workflowName.trim() || 'Untitled workflow',
      description: '',
      project_id: projectId || undefined,
      ...buildWorkflow(),
    }
    setBusy(true)
    setError('')
    try {
      const saved = workflowId
        ? await updateWorkflow(workflowId, payload)
        : await createWorkflow(payload)
      setWorkflowId(saved.id)
      setWorkflowName(saved.name)
      await refreshWorkflows()
    } catch (err) {
      setError(`保存失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [buildWorkflow, projectId, refreshWorkflows, workflowId, workflowName])

  const onLoad = useCallback(async (id) => {
    if (!id) return
    setBusy(true)
    try {
      const workflow = await fetchWorkflow(id)
      applyWorkflow(workflow)
      setWorkflowId(workflow.id)
      setWorkflowName(workflow.name)
    } catch (err) {
      setError(`加载失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [applyWorkflow])

  const onDeleteWorkflow = useCallback(async (id) => {
    const wf = savedWorkflows.find((w) => w.id === id)
    if (!wf) return
    if (!window.confirm(`确认删除工作流「${wf.name}」？此操作不可恢复。`)) return
    setBusy(true)
    try {
      await deleteWorkflow(id)
      if (workflowId === id) {
        setWorkflowId('')
        setWorkflowName('Untitled workflow')
      }
      await refreshWorkflows()
    } catch (err) {
      setError(`删除失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [refreshWorkflows, savedWorkflows, workflowId])

  const onExport = useCallback(async () => {
    if (!workflowId) { setError('请先保存工作流，再导出 JSON'); return }
    try {
      const workflow = await exportWorkflow(workflowId)
      const blob = new Blob([JSON.stringify(workflow, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${workflow.name.replace(/[^a-zA-Z0-9_-]+/g, '_') || 'workflow'}.json`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(`导出失败: ${err.message}`)
    }
  }, [workflowId])

  const onImport = useCallback(async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const payload = JSON.parse(await file.text())
      const imported = await importWorkflow(payload)
      applyWorkflow(imported)
      setWorkflowId(imported.id)
      setWorkflowName(imported.name)
      await refreshWorkflows()
    } catch (err) {
      setError(`导入失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [applyWorkflow, refreshWorkflows])

  const onRestoreVersion = useCallback(async (restored) => {
    applyWorkflow(restored)
    setWorkflowId(restored.id)
    setWorkflowName(restored.name)
    await refreshWorkflows()
  }, [applyWorkflow, refreshWorkflows])

  const onNew = useCallback(() => {
    setNodes([])
    setEdges([])
    setWorkflowId('')
    setWorkflowName('Untitled workflow')
    setRunNodeStates({})
    setRunId('')
    setRunStatus('')
    setResult(null)
    setError('')
    setSelectedId(null)
    clearHistory()
  }, [clearHistory, setEdges, setNodes])

  // ---- 异步运行 + WebSocket 实时状态 ----
  const onRun = useCallback(async () => {
    setError('')
    setResult(null)
    const wf = buildWorkflow()
    try {
      const v = await validateWorkflow(wf)
      if (!v.valid) {
        setError(`校验失败: ${v.errors.join('; ')}`)
        return
      }
      setBusy(true)
      setRunNodeStates({})
      setRunStatus('running')
      const { run_id } = await submitRun({
        nodes: wf.nodes,
        edges: wf.edges,
        workflow_id: workflowId || undefined,
        workflow_name: workflowName,
      })
      setRunId(run_id)
      setRightTab('result')
      refreshRuns().catch(() => {})
    } catch (err) {
      setRunStatus('')
      setError(`运行失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [buildWorkflow, refreshRuns, workflowId, workflowName])

  // WebSocket 订阅
  useEffect(() => {
    if (!runId) return
    let ws = null
    let closed = false
    let retry = 0

    const applyNodeEvent = (nid, payload) => {
      setRunNodeStates((prev) => ({ ...prev, [nid]: { ...(prev[nid] || {}), ...payload } }))
    }

    const connect = () => {
      try {
        ws = new WebSocket(runWsUrl(runId))
      } catch {
        return
      }
      ws.onmessage = (ev) => {
        let msg
        try { msg = JSON.parse(ev.data) } catch { return }
        if (msg.kind === 'snapshot') {
          const record = msg.payload
          setRunStatus(record.status)
          const states = {}
          for (const [nid, st] of Object.entries(record.nodes || {})) states[nid] = st
          setRunNodeStates(states)
        } else if (msg.kind === 'node_running' || msg.kind === 'node_succeeded' || msg.kind === 'node_failed' || msg.kind === 'node_blocked') {
          applyNodeEvent(msg.node_id, msg.payload)
        } else if (msg.kind === 'run_succeeded' || msg.kind === 'run_failed') {
          setRunStatus(msg.payload?.status || msg.kind)
          refreshRuns().catch(() => {})
        }
      }
      ws.onerror = () => { /* 网络层错误，交给 onclose 重连 */ }
      ws.onclose = () => {
        if (closed) return
        retry += 1
        if (retry <= 10) setTimeout(connect, 1500)
      }
    }
    connect()
    return () => { closed = true; if (ws) ws.close() }
  }, [runId, refreshRuns])

  // 运行状态 → 画布展示节点（派生数据，不进撤销历史）
  const displayNodes = useMemo(() => nodes.map((n) => ({
    ...n,
    data: {
      ...n.data,
      status: runNodeStates[n.id]?.status || 'pending',
      outputs: runNodeStates[n.id]?.outputs || null,
    },
  })), [nodes, runNodeStates])

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedId) || null,
    [nodes, selectedId],
  )

  const onNodeClick = useCallback((_, node) => {
    setSelectedId(node.id)
    setRightTab('props')
  }, [])

  const onPaneClick = useCallback(() => {
    setSelectedId(null)
  }, [])

  const onNodesDelete = useCallback((deleted) => {
    const ids = new Set(deleted.map((d) => d.id))
    setEdges((eds) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)))
    setRunNodeStates((prev) => {
      const next = { ...prev }
      for (const id of ids) delete next[id]
      return next
    })
    setSelectedId((cur) => (ids.has(cur) ? null : cur))
  }, [setEdges])

  const autoConnectDemo = useCallback(() => {
    setNodes([]); setEdges([])
    clearHistory()
    const c = addNode(specOf('data.constant'), { x: 60, y: 160 })
    const a = addNode(specOf('math.add'), { x: 320, y: 120 })
    const m = addNode(specOf('math.multiply'), { x: 580, y: 160 })
    patchNodeParams(c, { value: 8 })
    setEdges([
      { id: 'e1', source: c, sourceHandle: 'value', target: a, targetHandle: 'a' },
      { id: 'e2', source: c, sourceHandle: 'value', target: a, targetHandle: 'b' },
      { id: 'e3', source: a, sourceHandle: 'result', target: m, targetHandle: 'a' },
      { id: 'e4', source: c, sourceHandle: 'value', target: m, targetHandle: 'b' },
    ])
  }, [addNode, clearHistory, patchNodeParams, setEdges, setNodes, specOf])

  return (
    <div className="qf-layout">
      <Palette specs={specs} onAddNode={addNode} />

      <div className="qf-center">
        <div className="qf-toolbar">
          <input
            className="qf-name-input"
            value={workflowName}
            onChange={(e) => setWorkflowName(e.target.value)}
            aria-label="工作流名称"
            style={{ width: 180 }}
          />
          <select value={workflowId} onChange={(e) => onLoad(e.target.value)} disabled={busy} aria-label="已保存工作流">
            <option value="">选择已保存工作流</option>
            {savedWorkflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>{workflow.name} · v{workflow.version}</option>
            ))}
          </select>
          <button className="qf-btn" onClick={onNew} disabled={busy}>新建</button>
          <button className="qf-btn" onClick={onSave} disabled={busy}>保存</button>
          <button className="qf-btn" onClick={() => onDeleteWorkflow(workflowId)} disabled={busy || !workflowId} title="删除当前工作流">删除</button>
          <button className="qf-btn" onClick={() => importRef.current?.click()} disabled={busy}>导入 JSON</button>
          <button className="qf-btn" onClick={onExport} disabled={busy || !workflowId}>导出 JSON</button>
          <button className="qf-btn" onClick={() => setVersionsOpen(true)} disabled={busy || !workflowId} title="工作流版本历史">版本历史</button>
          <span className="qf-toolbar-sep" />
          <button className="qf-btn" onClick={undo} disabled={!canUndo} title="撤销 (Ctrl+Z)">↶</button>
          <button className="qf-btn" onClick={redo} disabled={!canRedo} title="重做 (Ctrl+Shift+Z)">↷</button>
          <span className="qf-toolbar-sep" />
          <button className="qf-btn" onClick={autoConnectDemo}>示例</button>
          <button className="qf-btn qf-btn-primary" onClick={onRun} disabled={busy}>
            {busy ? '提交中…' : '运行'}
          </button>
          {runStatus && <span className={`qf-run-pill qf-run-${runStatus}`}>{runStatus}</span>}
          <input ref={importRef} type="file" accept="application/json,.json" hidden onChange={onImport} />
        </div>

        <div className="qf-canvas-wrap">
          <ReactFlow
            nodes={displayNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onNodesDelete={onNodesDelete}
            fitView
          >
            <Background gap={16} />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>
      </div>

      <div className="qf-side">
        <div className="qf-tabs">
          <button className={`qf-tab ${rightTab === 'props' ? 'qf-tab-active' : ''}`} onClick={() => setRightTab('props')}>
            属性
          </button>
          <button className={`qf-tab ${rightTab === 'result' ? 'qf-tab-active' : ''}`} onClick={() => setRightTab('result')}>
            运行结果
          </button>
          <button className={`qf-tab ${rightTab === 'runs' ? 'qf-tab-active' : ''}`} onClick={() => setRightTab('runs')}>
            运行记录
          </button>
        </div>
        <div className="qf-side-body">
          {rightTab === 'props' && (
            <PropertyPanel node={selectedNode} onChange={patchNodeParams} />
          )}
          {rightTab === 'result' && (
            <ResultPanel
              result={result}
              error={error}
              busy={busy}
              runStatus={runStatus}
              onClose={() => setRunStatus('')}
            />
          )}
          {rightTab === 'runs' && (
            <RunsPanel
              runs={runs}
              activeRunId={runId}
              onSelectRun={(id) => setRunId(id)}
              onRefresh={() => refreshRuns().catch(() => {})}
            />
          )}
        </div>
      </div>
      {versionsOpen && (
        <VersionHistoryModal
          workflowId={workflowId}
          onClose={() => setVersionsOpen(false)}
          onRestore={onRestoreVersion}
          setError={setError}
        />
      )}
    </div>
  )
}

export default function App() {
  const [view, setView] = useState('editor')
  const [user, setUser] = useState(null)
  const [authOpen, setAuthOpen] = useState(false)
  const [projects, setProjects] = useState([])
  const [projectId, setProjectId] = useState('')
  const [pendingTemplate, setPendingTemplate] = useState(null)

  // 启动时若已有令牌则恢复会话
  useEffect(() => {
    if (getToken()) {
      getMe().then(setUser).catch(() => clearToken())
    }
  }, [])

  // 登录后加载项目列表
  const refreshProjects = useCallback(() => {
    if (!getToken()) {
      setProjects([])
      setProjectId('')
      return
    }
    fetchProjects()
      .then((list) => {
        setProjects(list || [])
        setProjectId((cur) => (cur && (list || []).some((p) => p.id === cur) ? cur : ''))
      })
      .catch(() => setProjects([]))
  }, [])

  useEffect(() => {
    refreshProjects()
  }, [user, refreshProjects])

  const handleAuthed = () => {
    getMe().then(setUser).catch(() => {})
    refreshProjects()
  }

  const handleLogout = () => {
    clearToken()
    setUser(null)
    setProjects([])
    setProjectId('')
  }

  // 登录态失效（后端返回 401）→ 回到登录页
  useEffect(() => {
    const onUnauthorized = () => {
      clearToken()
      setUser(null)
      setProjects([])
      setProjectId('')
    }
    window.addEventListener('qf:unauthorized', onUnauthorized)
    return () => window.removeEventListener('qf:unauthorized', onUnauthorized)
  }, [])

  const handleCreateProject = () => {
    const name = window.prompt('新项目名称：')
    if (!name || !name.trim()) return
    createProject(name.trim())
      .then((p) => {
        setProjects((prev) => [...prev, p])
        setProjectId(p.id)
      })
      .catch((e) => window.alert(`创建项目失败: ${e.message}`))
  }

  const handleDeleteProject = () => {
    if (!projectId) return
    const p = projects.find((x) => x.id === projectId)
    if (!p) return
    if (!window.confirm(`确认删除项目「${p.name}」？项目内工作流将失去归属（不删除工作流）。`)) return
    deleteProject(projectId)
      .then(() => {
        setProjects((prev) => prev.filter((x) => x.id !== projectId))
        setProjectId('')
      })
      .catch((e) => window.alert(`删除项目失败: ${e.message}`))
  }

  // 登录门禁（V1.7）：未登录只渲染登录/注册页，不暴露任何业务内容
  if (!user) {
    return <LoginScreen onAuthed={handleAuthed} />
  }

  return (
    <ReactFlowProvider>
      <div className="qf-topbar">
        <span className="qf-logo">⚡ QuantFlow</span>
        <span className="qf-sub">量化工作流平台 · M4 业务能力</span>
        <nav className="qf-nav">
          <button
            className={`qf-nav-btn ${view === 'editor' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('editor')}
          >
            工作流编辑器
          </button>
          <button
            className={`qf-nav-btn ${view === 'chart' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('chart')}
          >
            行情图表
          </button>
          <button
            className={`qf-nav-btn ${view === 'monitor' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('monitor')}
          >
            系统监控
          </button>
          <button
            className={`qf-nav-btn ${view === 'factor' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('factor')}
          >
            因子库
          </button>
          <button
            className={`qf-nav-btn ${view === 'notify' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('notify')}
          >
            通知渠道
          </button>
          <button
            className={`qf-nav-btn ${view === 'llm' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('llm')}
          >
            LLM 助手
          </button>
          <button
            className={`qf-nav-btn ${view === 'settings' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('settings')}
          >
            LLM 配置
          </button>
          <button
            className={`qf-nav-btn ${view === 'templates' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('templates')}
          >
            模板库
          </button>
          <button
            className={`qf-nav-btn ${view === 'reports' ? 'qf-nav-active' : ''}`}
            onClick={() => setView('reports')}
          >
            回测报告
          </button>
          {user?.role === 'admin' && (
            <button
              className={`qf-nav-btn ${view === 'broker' ? 'qf-nav-active' : ''}`}
              onClick={() => setView('broker')}
            >
              券商设置
            </button>
          )}
        </nav>
        <div className="qf-topbar-right">
          {user && (
            <>
              <select
                className="qf-project-select"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                aria-label="切换项目"
                title="切换项目"
              >
                <option value="">未分组（全局）</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}（{p.member_count} 人）
                  </option>
                ))}
              </select>
              <button className="qf-btn qf-btn-sm" onClick={handleCreateProject} title="新建项目">＋ 项目</button>
              <button className="qf-btn qf-btn-sm" onClick={handleDeleteProject} disabled={!projectId} title="删除当前项目">🗑</button>
              <span className="qf-user-chip" title={`${user.username} · ${user.role}`}>
                {user.username}
                <em>{user.role === 'admin' ? '管理员' : user.role}</em>
              </span>
              <button className="qf-btn qf-btn-sm" onClick={handleLogout}>退出</button>
            </>
          )}
          {!user && (
            <button className="qf-btn qf-btn-sm" onClick={() => setAuthOpen(true)}>登录 / 注册</button>
          )}
        </div>
      </div>
      {view === 'editor' && (
        <Canvas
          projectId={projectId}
          pendingTemplate={pendingTemplate}
          onTemplateConsumed={() => setPendingTemplate(null)}
        />
      )}
      {view === 'chart' && <ChartView />}
      {view === 'monitor' && <Monitoring />}
      {view === 'factor' && <FactorLibrary />}
      {view === 'notify' && <Notifications />}
      {view === 'llm' && <LLMAssistant />}
      {view === 'settings' && <LLMSettings />}
      {view === 'templates' && (
        <Templates
          onApply={(tpl) => {
            setPendingTemplate(tpl)
            setView('editor')
          }}
        />
      )}
      {view === 'reports' && <BacktestReports />}
      {view === 'broker' && <BrokerSettings />}
      {authOpen && (
        <AuthModal onClose={() => setAuthOpen(false)} onAuthed={handleAuthed} />
      )}
    </ReactFlowProvider>
  )
}
