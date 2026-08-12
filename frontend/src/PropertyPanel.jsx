import { useMemo } from 'react'

function ParamField({ param, value, onChange }) {
  const common = {
    value: value ?? param.default ?? '',
    onChange: (e) => onChange(param.name, e.target.value),
  }
  let control
  if (param.type === 'boolean') {
    control = (
      <input
        type="checkbox"
        checked={!!value}
        onChange={(e) => onChange(param.name, e.target.checked)}
      />
    )
  } else if (param.options?.length) {
    control = (
      <select {...common}>
        {param.options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  } else if (param.type === 'number') {
    control = (
      <input
        type="number"
        step={param.step || 'any'}
        min={param.min}
        max={param.max}
        {...common}
        placeholder={param.description}
      />
    )
  } else {
    control = (
      <input type="text" {...common} placeholder={param.description} />
    )
  }
  return (
    <label className="qf-prop-field">
      <span className="qf-prop-label" title={`${param.name} (${param.type})`}>
        {param.label || param.name}
        {param.required && <em className="qf-prop-required">*</em>}
      </span>
      {control}
      {param.description && <span className="qf-prop-hint">{param.description}</span>}
    </label>
  )
}

function PortList({ title, ports }) {
  if (!ports?.length) return null
  return (
    <div className="qf-prop-ports">
      <div className="qf-prop-ports-title">{title}</div>
      {ports.map((p) => (
        <span key={p.name} className={`qf-port-chip qf-port-${p.type}`}>
          {p.name} <em>{p.type}</em>
        </span>
      ))}
    </div>
  )
}

export default function PropertyPanel({ node, onChange }) {
  const { spec, params, status, outputs } = node?.data || {}

  const valueSummary = useMemo(() => {
    if (!outputs || !Object.keys(outputs).length) return null
    return Object.entries(outputs)
  }, [outputs])

  if (!node) {
    return (
      <div className="qf-prop">
        <h3>属性</h3>
        <div className="qf-prop-empty">点击画布节点查看 / 编辑属性</div>
      </div>
    )
  }

  return (
    <div className="qf-prop">
      <div className="qf-prop-head">
        <h3>属性</h3>
        <span className={`qf-node-status qf-st-${status || 'pending'}`} />
      </div>
      <div className="qf-prop-title">
        {spec.label}
        <span className="qf-prop-type">{spec.node_type}</span>
      </div>
      <p className="qf-prop-desc">{spec.description}</p>

      <PortList title="输入端口" ports={spec.inputs} />
      <PortList title="输出端口" ports={spec.outputs} />

      <div className="qf-prop-section">参数</div>
      {spec.params?.length ? (
        <div className="qf-prop-form">
          {spec.params.map((p) => (
            <ParamField
              key={p.name}
              param={p}
              value={params?.[p.name]}
              onChange={(name, val) => onChange(node.id, { [name]: val })}
            />
          ))}
        </div>
      ) : (
        <div className="qf-prop-hint">该节点无参数</div>
      )}

      {valueSummary && (
        <>
          <div className="qf-prop-section">运行输出</div>
          <div className="qf-prop-outputs">
            {valueSummary.map(([k, v]) => (
              <div key={k} className="qf-output-row">
                <span className="qf-output-name">{k}</span>
                {v && v.__type__ === 'table'
                  ? <span>table({v.rows.length} 行 × {v.columns.length} 列)</span>
                  : <span className="qf-output-value">{JSON.stringify(v)}</span>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
