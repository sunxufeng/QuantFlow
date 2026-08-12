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
import {
  createWorkflow,
  exportWorkflow,
  fetchNodes,
  fetchWorkflow,
  fetchWorkflows,
  importWorkflow,
  runWorkflow,
  updateWorkflow,
  validateWorkflow,
} from './api.js'

const nodeTypes = { qf: WorkflowNode }

function Palette({ specs, onAddNode }) {
  const groups = useMemo(() => {
    const map = {}
    for (const s of specs) (map[s.category] ||= []).push(s)
    return map
  }, [specs])

  return (
    <div className="qf-palette">
      <h3>节点库</h3>
      {Object.entries(groups).map(([cat, list]) => (
        <div key={cat} className="qf-palette-group">
          <div className="qf-palette-cat">{cat}</div>
          {list.map((s) => (
            <div
              key={s.node_type}
              className="qf-palette-item"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/qf-type', s.node_type)
                e.dataTransfer.effectAllowed = 'move'
              }}
              onClick={() => onAddNode(s, { x: 120 + Math.random() * 200, y: 120 + Math.random() * 200 })}
            >
              {s.label}
              <span className="qf-palette-desc">{s.description}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function ResultPanel({ result, error, busy }) {
  return (
    <div className="qf-result">
      <h3>运行结果</h3>
      {busy && <div className="qf-busy">运行中…</div>}
      {error && <div className="qf-error">{error}</div>}
      {result && !error && (
        <>
          <div className="qf-run-meta">
            状态 <b className={`qf-run-${result.status}`}>{result.status}</b> · 耗时{' '}
            {result.duration_ms}ms · run_id {result.run_id}
          </div>
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
                  <td className="qf-cell-out">{n.outputs ? Object.entries(n.outputs).map(([k, v]) => (
                    <div key={k}>{k} = {v && v.__type__ === 'table' ? `table(${v.rows.length}行)` : JSON.stringify(v)}</div>
                  )) : ''}</td>
                  <td>{n.error || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

function Canvas() {
  const [specs, setSpecs] = useState([])
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [savedWorkflows, setSavedWorkflows] = useState([])
  const [workflowId, setWorkflowId] = useState('')
  const [workflowName, setWorkflowName] = useState('Untitled workflow')
  const rf = useReactFlow()
  const idRef = useRef(0)
  const importRef = useRef(null)

  const refreshWorkflows = useCallback(() => {
    return fetchWorkflows().then(setSavedWorkflows)
  }, [])

  useEffect(() => {
    fetchNodes().then((list) => {
      setSpecs(list)
      if (list.length) addNode(list.find((s) => s.node_type === 'data.constant'), { x: 60, y: 120 })
    }).catch((e) => setError(`节点库加载失败: ${e.message}`))
    refreshWorkflows().catch((e) => setError(`工作流列表加载失败: ${e.message}`))
  }, [])

  const specOf = useCallback(
    (type) => specs.find((s) => s.node_type === type),
    [specs],
  )

  const addNode = useCallback((spec, position) => {
    const id = `${spec.node_type}-${++idRef.current}`
    const params = {}
    for (const p of spec.params) {
      params[p.name] = p.default
    }
    setNodes((nds) => [
      ...nds,
      {
        id,
        type: 'qf',
        position,
        data: { nodeType: spec.node_type, spec, params, status: 'pending', outputs: null },
      },
    ])
    // 默认把上游最后一个节点的第一个输出接过来（快速演示）
    return id
  }, [setNodes])

  const patchNode = useCallback((id, patch) => {
    setNodes((nds) => nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)))
  }, [setNodes])

  const onConnect = useCallback((conn) => {
    setEdges((eds) => addEdge({ ...conn, type: 'default' }, eds))
  }, [setEdges])

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

  const buildWorkflow = useCallback(() => {
    return {
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
    }
  }, [nodes, edges])

  const applyWorkflow = useCallback((workflow) => {
    const restoredNodes = workflow.nodes.map((node, index) => {
      const spec = specOf(node.node_type)
      if (!spec) throw new Error(`节点类型不可用: ${node.node_type}`)
      return {
        id: node.id,
        type: 'qf',
        position: node.position || { x: 80 + index * 220, y: 120 },
        data: {
          nodeType: node.node_type,
          spec,
          params: node.params || {},
          status: 'pending',
          outputs: null,
        },
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
    const maxNodeSuffix = restoredNodes.reduce((max, node) => {
      const match = node.id.match(/-(\d+)$/)
      return match ? Math.max(max, Number(match[1])) : max
    }, restoredNodes.length)
    idRef.current = Math.max(idRef.current, maxNodeSuffix)
    setResult(null)
    setError('')
  }, [setEdges, setNodes, specOf])

  const onSave = useCallback(async () => {
    const payload = { name: workflowName.trim() || 'Untitled workflow', description: '', ...buildWorkflow() }
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
  }, [buildWorkflow, refreshWorkflows, workflowId, workflowName])

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

  const onExport = useCallback(async () => {
    if (!workflowId) {
      setError('请先保存工作流，再导出 JSON')
      return
    }
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

  const onNew = useCallback(() => {
    setNodes([])
    setEdges([])
    setWorkflowId('')
    setWorkflowName('Untitled workflow')
    setResult(null)
    setError('')
  }, [setEdges, setNodes])

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
      nodes.forEach((n) => patchNode(n.id, { status: 'pending', outputs: null }))
      const r = await runWorkflow(wf)
      setResult(r)
      const byId = Object.fromEntries(r.nodes.map((s) => [s.node_id, s]))
      nodes.forEach((n) => {
        const st = byId[n.id]
        if (st) patchNode(n.id, { status: st.status, outputs: st.outputs || null })
      })
    } catch (err) {
      setError(`运行失败: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }, [buildWorkflow, nodes, patchNode])

  const autoConnectDemo = useCallback(() => {
    // 用示例节点搭一个最小闭环：常量 -> 加法 -> 乘法
    setNodes([]); setEdges([])
    const c = addNode(specOf('data.constant'), { x: 60, y: 160 })
    const a = addNode(specOf('math.add'), { x: 320, y: 120 })
    const m = addNode(specOf('math.multiply'), { x: 580, y: 160 })
    patchNode(c, { params: { value: 8 } })
    setEdges([
      { id: 'e1', source: c, sourceHandle: 'value', target: a, targetHandle: 'a' },
      { id: 'e2', source: c, sourceHandle: 'value', target: a, targetHandle: 'b' },
      { id: 'e3', source: a, sourceHandle: 'result', target: m, targetHandle: 'a' },
      { id: 'e4', source: c, sourceHandle: 'value', target: m, targetHandle: 'b' },
    ])
  }, [specOf, addNode, patchNode, setEdges, setNodes])

  return (
    <div className="qf-layout">
      <Palette specs={specs} onAddNode={addNode} />
      <div className="qf-canvas-wrap">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onDrop={onDrop}
          onDragOver={onDragOver}
          fitView
        >
          <Background gap={16} />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
      <div className="qf-side">
        <div className="qf-actions qf-workflow-actions">
          <input
            className="qf-name-input"
            value={workflowName}
            onChange={(event) => setWorkflowName(event.target.value)}
            aria-label="工作流名称"
          />
          <select value={workflowId} onChange={(event) => onLoad(event.target.value)} disabled={busy}>
            <option value="">选择已保存工作流</option>
            {savedWorkflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>{workflow.name} · v{workflow.version}</option>
            ))}
          </select>
          <button className="qf-btn" onClick={onNew} disabled={busy}>新建</button>
          <button className="qf-btn" onClick={onSave} disabled={busy}>保存</button>
          <button className="qf-btn" onClick={() => importRef.current?.click()} disabled={busy}>导入 JSON</button>
          <button className="qf-btn" onClick={onExport} disabled={busy || !workflowId}>导出 JSON</button>
          <input ref={importRef} type="file" accept="application/json,.json" hidden onChange={onImport} />
        </div>
        <div className="qf-actions">
          <button className="qf-btn" onClick={autoConnectDemo}>示例工作流</button>
          <button className="qf-btn qf-btn-primary" onClick={onRun} disabled={busy}>
            {busy ? '运行中…' : '运行'}
          </button>
        </div>
        <ResultPanel result={result} error={error} busy={busy} />
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <div className="qf-topbar">
        <span className="qf-logo">⚡ QuantFlow</span>
        <span className="qf-sub">量化工作流平台 · M1 原型</span>
      </div>
      <Canvas />
    </ReactFlowProvider>
  )
}
