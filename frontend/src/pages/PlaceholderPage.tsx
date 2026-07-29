import { Link } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'

type PlaceholderPageProps = {
  title: string
  description: string
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <>
      <TopBar title={title} />
      <main className="flex-1 overflow-y-auto p-8">
        <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <p className="mt-2 text-sm text-slate-500">{description}</p>
          <p className="mt-4 text-xs text-slate-400">
            本页为脚手架占位，后续按{' '}
            <code className="rounded bg-slate-100 px-1">原型/</code> HTML 细化实现。
          </p>
          <Link
            to="/profiles"
            className="mt-6 inline-flex rounded-lg bg-teal-600 px-4 py-2 text-xs font-semibold text-white hover:bg-teal-700"
          >
            返回环境管理
          </Link>
        </div>
      </main>
    </>
  )
}
