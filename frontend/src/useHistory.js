import { useCallback, useEffect, useRef, useState } from 'react'

const clone = (nodes, edges) => ({
  nodes: JSON.parse(JSON.stringify(nodes)),
  edges: JSON.parse(JSON.stringify(edges)),
})

const HISTORY_LIMIT = 60
const DEBOUNCE_MS = 400

/**
 * 基于图快照的撤销/重做。
 * - 对 nodes/edges 的任何变更做 debounce 快照入栈（连续拖拽/输入合并为一步）
 * - undo/redo 回放时通过 applyingRef 跳过再入栈
 */
export function useGraphHistory(nodes, edges, setNodes, setEdges) {
  const [past, setPast] = useState([])
  const [future, setFuture] = useState([])
  const applyingRef = useRef(false)
  const changedRef = useRef(false)

  useEffect(() => {
    if (applyingRef.current) return
    changedRef.current = true
    const timer = setTimeout(() => {
      if (!changedRef.current) return
      changedRef.current = false
      setPast((p) => [...p.slice(-(HISTORY_LIMIT - 1)), clone(nodes, edges)])
      setFuture([])
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [nodes, edges])

  const apply = useCallback((snapshot) => {
    applyingRef.current = true
    setNodes(snapshot.nodes)
    setEdges(snapshot.edges)
    requestAnimationFrame(() => { applyingRef.current = false })
  }, [setEdges, setNodes])

  const undo = useCallback(() => {
    setPast((p) => {
      if (!p.length) return p
      const prev = p[p.length - 1]
      setFuture((f) => [...f, clone(nodes, edges)])
      apply(prev)
      return p.slice(0, -1)
    })
  }, [apply, edges, nodes])

  const redo = useCallback(() => {
    setFuture((f) => {
      if (!f.length) return f
      const next = f[f.length - 1]
      setPast((p) => [...p, clone(nodes, edges)])
      apply(next)
      return f.slice(0, -1)
    })
  }, [apply, edges, nodes])

  const clearHistory = useCallback(() => {
    setPast([])
    setFuture([])
    changedRef.current = false
  }, [])

  return { canUndo: past.length > 0, canRedo: future.length > 0, undo, redo, clearHistory }
}
