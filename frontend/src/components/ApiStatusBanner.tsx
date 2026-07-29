import { useEffect } from 'react'
import { isRemoteMode } from '@/lib/api'
import { useDataStore } from '@/stores/data'

export function ApiStatusBanner() {
  const hydrateError = useDataStore((s) => s.hydrateError)
  const hydrating = useDataStore((s) => s.hydrating)
  const hydrateFromApi = useDataStore((s) => s.hydrateFromApi)
  const setHydrateError = useDataStore((s) => s.setHydrateError)

  if (!isRemoteMode()) return null
  if (hydrating) {
    return (
      <div className="border-b border-indigo-100 bg-indigo-50 px-4 py-2 text-center text-xs text-indigo-700">
        正在从 Local API 同步数据…
      </div>
    )
  }
  if (!hydrateError) return null
  return (
    <div className="flex items-center justify-center gap-3 border-b border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
      <span>{hydrateError}</span>
      <button
        type="button"
        className="rounded border border-rose-300 px-2 py-0.5 font-semibold hover:bg-rose-100"
        onClick={() => void hydrateFromApi()}
      >
        重试
      </button>
      <button
        type="button"
        className="text-rose-500 underline"
        onClick={() => setHydrateError(null)}
      >
        关闭
      </button>
    </div>
  )
}

/** Boot hydrate when VITE_API_BASE is set; poll runtime so closed browsers update UI. */
export function useApiHydrate() {
  const hydrateFromApi = useDataStore((s) => s.hydrateFromApi)
  const refreshRuntime = useDataStore((s) => s.refreshRuntime)
  useEffect(() => {
    if (!isRemoteMode()) return
    void hydrateFromApi()
    const t = window.setInterval(() => void refreshRuntime(), 5000)
    return () => window.clearInterval(t)
  }, [hydrateFromApi, refreshRuntime])
}
