import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useDataStore } from '@/stores/data'
import { useUiStore } from '@/stores/ui'

type NavItem = {
  to: string
  label: string
  badge?: string
}

const PRIMARY: NavItem[] = [
  { to: '/profiles', label: '环境管理' },
  { to: '/runtime', label: '实例监控' },
  { to: '/proxies', label: '代理中心' },
  { to: '/fingerprints', label: '指纹策略' },
]

const PHASE2: NavItem[] = [
  { to: '/addons', label: '插件中心', badge: '第二阶段' },
  { to: '/tasks', label: '任务中心', badge: '第二阶段' },
]

const SYSTEM: NavItem[] = [
  { to: '/browser', label: '浏览器版本' },
  { to: '/api', label: '本地接口 (Local API)' },
  { to: '/settings', label: '系统设置' },
]

function NavGroup({ items }: { items: NavItem[] }) {
  return (
    <div className="space-y-1">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all',
              isActive
                ? 'bg-teal-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-white',
            )
          }
        >
          <span className="flex-1">{item.label}</span>
          {item.badge ? (
            <span
              className={cn(
                'rounded-full px-2 py-0.5 text-xs font-semibold',
                item.badge.includes('阶段')
                  ? 'text-slate-500'
                  : 'bg-teal-500/20 text-teal-300',
              )}
            >
              {item.badge}
            </span>
          ) : null}
        </NavLink>
      ))}
    </div>
  )
}

export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const settings = useDataStore((s) => s.settings)
  const running = useDataStore((s) =>
    s.profiles.filter(
      (p) => !p.deletedAt && (p.status === 'running' || p.status === 'api'),
    ).length,
  )

  if (collapsed) {
    return (
      <aside className="flex w-16 flex-col justify-between border-r border-slate-800 bg-slate-900 text-slate-300">
        <div className="flex h-16 items-center justify-center border-b border-slate-800">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-500 text-sm font-bold text-slate-950">
            CF
          </div>
        </div>
      </aside>
    )
  }

  return (
    <aside className="flex w-64 flex-shrink-0 flex-col justify-between border-r border-slate-800 bg-slate-900 text-slate-300">
      <div>
        <div className="flex h-16 items-center gap-3 border-b border-slate-800 px-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-teal-500 text-lg font-bold text-slate-950">
            CF
          </div>
          <div>
            <h1 className="text-sm font-bold leading-none tracking-wide text-white">
              Camoufox 控制台
            </h1>
            <span className="mt-1 inline-block text-xs text-teal-400">指纹浏览器系统</span>
          </div>
        </div>

        <nav className="mt-6 space-y-1 px-4">
          <NavGroup
            items={PRIMARY.map((item) =>
              item.to === '/runtime' && running > 0
                ? { ...item, badge: `${running} 运行` }
                : item,
            )}
          />
          <div className="my-4 h-px bg-slate-800" />
          <NavGroup items={PHASE2} />
          <div className="my-4 h-px bg-slate-800" />
          <NavGroup items={SYSTEM} />
        </nav>
      </div>

      <div className="border-t border-slate-800 p-4 text-xs">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-slate-500">接口服务 (API)</span>
          <span
            className={cn(
              'flex items-center gap-1.5',
              settings.apiRunning ? 'text-teal-400' : 'text-slate-500',
            )}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                settings.apiRunning ? 'animate-pulse bg-teal-400' : 'bg-slate-600',
              )}
            />
            {settings.apiRunning ? `运行中 :${settings.apiPort}` : '已停止'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-500">Camoufox 版本</span>
          <span className="font-mono text-slate-400">{settings.camoufoxVersion}</span>
        </div>
      </div>
    </aside>
  )
}
