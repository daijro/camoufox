import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Drawer({
  open,
  title,
  onClose,
  children,
  widthClass = 'w-[420px]',
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  widthClass?: string
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        className="absolute inset-0 bg-slate-900/30"
        aria-label="关闭抽屉"
        onClick={onClose}
      />
      <aside
        className={cn(
          'relative z-10 flex h-full flex-col border-l border-slate-200 bg-white shadow-xl',
          widthClass,
        )}
      >
        <div className="flex h-14 items-center justify-between border-b border-slate-200 px-5">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
          >
            关闭
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  )
}
