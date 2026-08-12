import { useMemo, useState } from 'react'

function matches(query, s) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return (
    s.label?.toLowerCase().includes(q) ||
    s.node_type?.toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q)
  )
}

export default function Palette({ specs, onAddNode }) {
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState({})

  const groups = useMemo(() => {
    const map = {}
    for (const s of specs) {
      if (!matches(query, s)) continue
      ;(map[s.category] ||= []).push(s)
    }
    return map
  }, [specs, query])

  const total = Object.values(groups).reduce((n, l) => n + l.length, 0)

  return (
    <div className="qf-palette">
      <h3>节点库 <span className="qf-palette-count">{total} / {specs.length}</span></h3>
      <input
        className="qf-palette-search"
        type="search"
        placeholder="搜索节点…（名称/类型/说明）"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="搜索节点"
      />
      {Object.entries(groups).map(([cat, list]) => {
        const isCollapsed = !!collapsed[cat]
        return (
          <div key={cat} className="qf-palette-group">
            <div
              className="qf-palette-cat"
              onClick={() => setCollapsed((c) => ({ ...c, [cat]: !c[cat] }))}
              role="button"
            >
              <span className="qf-palette-caret">{isCollapsed ? '▸' : '▾'}</span>
              {cat} <span className="qf-palette-count">{list.length}</span>
            </div>
            {!isCollapsed && list.map((s) => (
              <div
                key={s.node_type}
                className="qf-palette-item"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('application/qf-type', s.node_type)
                  e.dataTransfer.effectAllowed = 'move'
                }}
                onClick={() => onAddNode(s, { x: 120 + Math.random() * 240, y: 120 + Math.random() * 240 })}
                title={s.node_type}
              >
                {s.label}
                <span className="qf-palette-desc">{s.description}</span>
                <span className="qf-palette-type">{s.node_type}</span>
              </div>
            ))}
          </div>
        )
      })}
      {total === 0 && <div className="qf-palette-empty">无匹配节点</div>}
    </div>
  )
}
