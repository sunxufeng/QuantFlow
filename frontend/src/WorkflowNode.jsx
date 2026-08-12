import { memo } from 'react'
import { Handle, Position } from 'reactflow'

const STATUS_COLOR = {
  pending: '#8a94a6',
  running: '#f59e0b',
  succeeded: '#22c55e',
  failed: '#ef4444',
  blocked: '#9ca3af',
}

function PortHandles({ ports, side, type }) {
  const n = Math.max(ports.length, 1)
  return ports.map((p, i) => (
    <Handle
      key={p.name}
      id={p.name}
      type={type}
      position={side}
      style={{ top: `${((i + 0.5) / n) * 100}%`, background: '#6366f1' }}
      data-port-type={p.type}
    />
  ))
}

function ParamField({ spec, value, onChange }) {
  const common = {
    value: value ?? spec.default ?? '',
    onChange: (e) => onChange(spec.name, e.target.value),
  }
  if (spec.type === 'boolean') {
    return (
      <label className="qf-param">
        <input
          type="checkbox"
          checked={!!value}
          onChange={(e) => onChange(spec.name, e.target.checked)}
        />
        <span>{spec.label}</span>
      </label>
    )
  }
  if (spec.options?.length) {
    return (
      <label className="qf-param">
        <span>{spec.label}</span>
        <select {...common}>
          {spec.options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      </label>
    )
  }
  return (
    <label className="qf-param">
      <span>{spec.label}</span>
      <input
        type={spec.type === 'number' ? 'number' : 'text'}
        {...common}
        placeholder={spec.description}
      />
    </label>
  )
}

function OutputValue({ value }) {
  if (value && value.__type__ === 'table') {
    const { columns, rows } = value
    return (
      <div className="qf-table-preview">
        <table>
          <thead>
            <tr>{columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {rows.slice(0, 3).map((r, i) => (
              <tr key={i}>
                {columns.map((c) => <td key={c}>{String(r[c] ?? '')}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  return <div className="qf-output-value">{JSON.stringify(value)}</div>
}

function WorkflowNode({ data, selected }) {
  const spec = data.spec
  return (
    <div className={`qf-node ${selected ? 'qf-node-selected' : ''}`}>
      <PortHandles ports={spec.inputs} side={Position.Left} type="target" />
      <div className="qf-node-header" style={{ borderColor: STATUS_COLOR[data.status] || '#cbd5e1' }}>
        <span className="qf-node-title">{spec.label}</span>
        <span className={`qf-node-status qf-st-${data.status || 'pending'}`} />
      </div>
      <div className="qf-node-cat">{spec.category}</div>
      <div className="qf-node-body">
        {spec.params.map((p) => (
          <ParamField key={p.name} spec={p} value={data.params[p.name]} onChange={data.onChange} />
        ))}
        {data.outputs && Object.keys(data.outputs).length > 0 && (
          <div className="qf-node-outputs">
            {Object.entries(data.outputs).map(([k, v]) => (
              <div key={k} className="qf-output-row">
                <span className="qf-output-name">{k}</span>
                <OutputValue value={v} />
              </div>
            ))}
          </div>
        )}
      </div>
      <PortHandles ports={spec.outputs} side={Position.Right} type="source" />
    </div>
  )
}

export default memo(WorkflowNode)
