import { cn } from '@/lib/utils'

export function SummaryCard({
  label,
  value,
  accent,
  danger,
  hint,
}: {
  label: string
  value: string
  accent?: boolean
  danger?: boolean
  hint?: string
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <span className="text-xs font-medium text-slate-400">{label}</span>
      <h3
        className={cn(
          'mt-1 text-2xl font-bold',
          danger ? 'text-rose-600' : accent ? 'text-teal-600' : 'text-slate-800',
        )}
      >
        {value}
      </h3>
      {hint ? <p className="mt-1 text-[10px] text-slate-400">{hint}</p> : null}
    </div>
  )
}
