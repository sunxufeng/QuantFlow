import { useState } from 'react'

const navItems = [
  { key: 'home', label: '概览', abbr: '览' },
  { key: 'editor', label: '工作流编辑器', abbr: '工' },
  { key: 'chart', label: '行情图表', abbr: '行' },
  { key: 'data', label: '数据更新', abbr: '数' },
  { key: 'monitor', label: '系统监控', abbr: '系' },
  { key: 'factor', label: '因子库', abbr: '因' },
  { key: 'notify', label: '通知渠道', abbr: '通' },
  { key: 'llm', label: 'LLM 助手', abbr: '助' },
  { key: 'settings', label: 'LLM 配置', abbr: '配' },
  { key: 'templates', label: '模板库', abbr: '模' },
  { key: 'reports', label: '回测报告', abbr: '报' },
  { key: 'trade', label: '模拟交易', abbr: '易' },
  { key: 'broker', label: '券商设置', abbr: '券', adminOnly: true },
]

export default function Sidebar({
  collapsed,
  setCollapsed,
  view,
  setView,
  user,
  projects,
  projectId,
  setProjectId,
  onCreateProject,
  onDeleteProject,
  onLogout,
}) {
  const [showLogout, setShowLogout] = useState(false)

  return (
    <div
      className="qf-sidebar"
      style={{
        width: collapsed ? 56 : 180,
        transition: 'width .2s ease',
        background: '#0f172a',
        borderRight: '1px solid #1e293b',
        display: 'flex',
        flexDirection: 'column',
        color: '#e2e8f0',
        flexShrink: 0,
        overflow: 'hidden',
      }}
    >
      {/* header */}
      <div
        style={{
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: collapsed ? '0 8px' : '0 12px',
          borderBottom: '1px solid #1e293b',
        }}
      >
        {!collapsed && (
          <span style={{ fontWeight: 700, fontSize: 15, whiteSpace: 'nowrap' }}>
            ⚡ QuantFlow
          </span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? '展开' : '收起'}
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            border: 'none',
            background: 'rgba(255,255,255,.08)',
            color: '#e2e8f0',
            cursor: 'pointer',
            fontSize: 14,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {/* nav */}
      <nav style={{ flex: 1, overflowY: 'auto', padding: '8px 6px' }}>
        {navItems
          .filter((item) => !item.adminOnly || user?.role === 'admin')
          .map((item) => {
            const active = view === item.key
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setView(item.key)}
                title={item.label}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  gap: 10,
                  padding: collapsed ? '10px 0' : '10px 12px',
                  marginBottom: 4,
                  borderRadius: 8,
                  border: 'none',
                  background: active ? 'rgba(99,102,241,.25)' : 'transparent',
                  color: active ? '#fff' : '#94a3b8',
                  cursor: 'pointer',
                  fontSize: 13,
                  whiteSpace: 'nowrap',
                  transition: 'background .15s, color .15s',
                }}
                onMouseEnter={(e) => {
                  if (!active) e.currentTarget.style.background = 'rgba(255,255,255,.06)'
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.background = 'transparent'
                }}
              >
                <span
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 5,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: active ? '#6366f1' : 'rgba(255,255,255,.08)',
                    fontSize: 12,
                    fontWeight: 600,
                    flexShrink: 0,
                  }}
                >
                  {item.abbr}
                </span>
                {!collapsed && <span>{item.label}</span>}
              </button>
            )
          })}
      </nav>

      {/* footer: project & user */}
      <div style={{ borderTop: '1px solid #1e293b', padding: '10px 6px' }}>
        {!collapsed && (
          <>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <select
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                aria-label="切换项目"
                title="切换项目"
                style={{
                  flex: 1,
                  minWidth: 0,
                  padding: '5px 8px',
                  borderRadius: 6,
                  border: '1px solid #334155',
                  background: '#1e293b',
                  color: '#e2e8f0',
                  fontSize: 12,
                }}
              >
                <option value="">未分组（全局）</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}（{p.member_count} 人）
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={onCreateProject}
                title="新建项目"
                style={{
                  padding: '5px 8px',
                  borderRadius: 6,
                  border: '1px solid #334155',
                  background: '#1e293b',
                  color: '#e2e8f0',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                ＋
              </button>
              <button
                type="button"
                onClick={onDeleteProject}
                disabled={!projectId}
                title="删除当前项目"
                style={{
                  padding: '5px 8px',
                  borderRadius: 6,
                  border: '1px solid #334155',
                  background: '#1e293b',
                  color: '#e2e8f0',
                  cursor: projectId ? 'pointer' : 'not-allowed',
                  opacity: projectId ? 1 : 0.5,
                  fontSize: 12,
                }}
              >
                🗑
              </button>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 8,
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  color: '#94a3b8',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={`${user?.username} · ${user?.role}`}
              >
                {user?.username}
                <em style={{ fontStyle: 'normal', marginLeft: 4, color: '#6366f1' }}>
                  {user?.role === 'admin' ? '管理员' : user?.role}
                </em>
              </span>
              <button
                type="button"
                onClick={onLogout}
                style={{
                  padding: '4px 8px',
                  borderRadius: 6,
                  border: 'none',
                  background: 'rgba(239,68,68,.15)',
                  color: '#f87171',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                退出
              </button>
            </div>
          </>
        )}
        {collapsed && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
            <button
              type="button"
              onClick={onCreateProject}
              title="新建项目"
              style={{
                width: 32,
                height: 32,
                borderRadius: 6,
                border: '1px solid #334155',
                background: '#1e293b',
                color: '#e2e8f0',
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              ＋
            </button>
            <button
              type="button"
              onClick={() => setShowLogout((s) => !s)}
              title={user?.username}
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                border: 'none',
                background: 'rgba(99,102,241,.25)',
                color: '#e0e7ff',
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              {user?.username?.slice(0, 1).toUpperCase()}
            </button>
            {showLogout && (
              <button
                type="button"
                onClick={() => { setShowLogout(false); onLogout() }}
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: 6,
                  border: 'none',
                  background: 'rgba(239,68,68,.15)',
                  color: '#f87171',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                退
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
