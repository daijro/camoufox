import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import { cn } from '@/lib/utils'

export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-slate-600">{label}</span>
      {children}
      {hint ? <span className="block text-[10px] text-slate-400">{hint}</span> : null}
    </label>
  )
}

const control =
  'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-teal-500'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(control, props.className)} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(control, props.className)} />
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(control, 'min-h-[100px] font-mono text-xs', props.className)} />
}

export function Button({
  variant = 'primary',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
}) {
  const styles = {
    primary: 'bg-teal-600 text-white hover:bg-teal-700',
    secondary: 'border border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-200',
    danger: 'border border-rose-100 bg-rose-50 text-rose-700 hover:bg-rose-100',
    ghost: 'text-slate-500 hover:bg-slate-100',
  }
  return (
    <button
      type="button"
      {...props}
      className={cn(
        'inline-flex items-center justify-center rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-50',
        styles[variant],
        className,
      )}
    />
  )
}
