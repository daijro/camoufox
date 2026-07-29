import { cn } from '@/lib/utils'
import type { ProfileStatus } from '@/types/console'

export const STATUS_LABEL: Record<ProfileStatus, string> = {
  idle: '未启动',
  starting: '启动中',
  running: '运行中',
  error: '运行异常',
  api: 'API 控制中',
}

const STATUS_STYLE: Record<ProfileStatus, string> = {
  idle: 'bg-slate-100 text-slate-600',
  starting: 'bg-amber-50 text-amber-700 animate-pulse',
  running: 'bg-teal-50 text-teal-700',
  error: 'bg-rose-50 text-rose-700',
  api: 'bg-indigo-50 text-indigo-700',
}

export function StatusBadge({ status }: { status: ProfileStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium',
        STATUS_STYLE[status],
      )}
    >
      {(status === 'running' || status === 'api') && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {STATUS_LABEL[status]}
    </span>
  )
}
