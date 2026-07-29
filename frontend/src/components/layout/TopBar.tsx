import { isRemoteMode } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

type TopBarProps = {
  title?: string
  runningCount?: number
  totalCount?: number
}

export function TopBar({
  title = '环境管理中心',
  runningCount = 0,
  totalCount = 0,
}: TopBarProps) {
  const searchQuery = useUiStore((s) => s.searchQuery)
  const setSearchQuery = useUiStore((s) => s.setSearchQuery)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const remote = isRemoteMode()

  return (
    <header className="z-20 flex h-16 flex-shrink-0 items-center justify-between border-b border-slate-200 bg-white px-8">
      <div className="flex items-center gap-6">
        <button
          type="button"
          onClick={toggleSidebar}
          className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-50"
        >
          侧栏
        </button>
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        <div className="relative w-80">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索环境名、代理 IP、标签…"
            className="w-full rounded-lg border border-transparent bg-slate-100 py-1.5 pl-3 pr-4 text-sm placeholder:text-slate-400 focus:border-teal-500 focus:bg-white focus:outline-none"
          />
        </div>
      </div>

      <div className="flex items-center gap-4 text-xs text-slate-500">
        <span>
          运行中{' '}
          <strong className="font-semibold text-teal-600">{runningCount}</strong>
          {' / '}
          总计 <strong className="font-semibold text-slate-700">{totalCount}</strong>
        </span>
        <span
          className={
            remote
              ? 'rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 font-medium text-indigo-700'
              : 'rounded-lg border border-teal-200 bg-teal-50 px-2.5 py-1 font-medium text-teal-700'
          }
        >
          {remote ? 'API 模式' : 'Mock 模式'}
        </span>
      </div>
    </header>
  )
}
