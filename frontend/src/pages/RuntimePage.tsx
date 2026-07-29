import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/Form'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { isRemoteMode } from '@/lib/api'
import * as remote from '@/services/remote'
import { useDataStore } from '@/stores/data'

export function RuntimePage() {
  const profiles = useDataStore((s) => s.profiles)
  const settings = useDataStore((s) => s.settings)
  const stopProfile = useDataStore((s) => s.stopProfile)
  const stopMany = useDataStore((s) => s.stopMany)
  const refreshRuntime = useDataStore((s) => s.refreshRuntime)
  const updateSettings = useDataStore((s) => s.updateSettings)

  const [limit, setLimit] = useState(settings.maxConcurrency ?? 8)
  const [stats, setStats] = useState<{
    cpuPercent: number | null
    memoryUsedMb: number | null
    memoryTotalMb: number | null
    running: number
    maxConcurrency: number
  } | null>(null)
  const [runtimeExtras, setRuntimeExtras] = useState<
    Record<string, { cpuPercent?: number | null; memoryMb?: number | null }>
  >({})
  const [limitMsg, setLimitMsg] = useState('')

  const pullStats = useCallback(async () => {
    if (!isRemoteMode()) return
    try {
      const [s, rt] = await Promise.all([
        remote.remoteRuntimeStats(),
        remote.remoteListRuntime(),
      ])
      setStats(s)
      setLimit(s.maxConcurrency)
      const map: Record<string, { cpuPercent?: number | null; memoryMb?: number | null }> =
        {}
      for (const p of rt) {
        map[p.id] = { cpuPercent: p.cpuPercent, memoryMb: p.memoryMb }
      }
      setRuntimeExtras(map)
    } catch {
      /* keep */
    }
  }, [])

  useEffect(() => {
    if (!isRemoteMode()) return
    void refreshRuntime()
    void pullStats()
    const t = window.setInterval(() => {
      void refreshRuntime()
      void pullStats()
    }, 8000)
    return () => window.clearInterval(t)
  }, [refreshRuntime, pullStats])

  useEffect(() => {
    if (settings.maxConcurrency != null) setLimit(settings.maxConcurrency)
  }, [settings.maxConcurrency])

  const running = useMemo(
    () =>
      profiles.filter(
        (p) =>
          !p.deletedAt &&
          (p.status === 'running' || p.status === 'api' || p.status === 'starting'),
      ),
    [profiles],
  )

  const memLabel = useMemo(() => {
    if (!stats?.memoryUsedMb || !stats.memoryTotalMb) return '—'
    const used = (stats.memoryUsedMb / 1024).toFixed(1)
    const total = (stats.memoryTotalMb / 1024).toFixed(1)
    return `${used} / ${total} GB`
  }, [stats])

  const commitLimit = async (n: number) => {
    setLimit(n)
    setLimitMsg('')
    if (!isRemoteMode()) {
      updateSettings({ maxConcurrency: n })
      return
    }
    try {
      const s = await remote.remotePatchSettings({ maxConcurrency: n })
      updateSettings({ maxConcurrency: s.maxConcurrency ?? n })
      setStats((prev) =>
        prev
          ? { ...prev, maxConcurrency: s.maxConcurrency ?? n }
          : {
              cpuPercent: null,
              memoryUsedMb: null,
              memoryTotalMb: null,
              running: running.length,
              maxConcurrency: s.maxConcurrency ?? n,
            },
      )
      setLimitMsg(`并发上限已设为 ${s.maxConcurrency ?? n}`)
    } catch (e) {
      setLimitMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <TopBar
        title="实例运行监控台"
        runningCount={running.length}
        totalCount={profiles.filter((p) => !p.deletedAt).length}
      />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard
            label="运行实例"
            value={`${stats?.running ?? running.length}`}
            accent
          />
          <SummaryCard label="并发上限" value={`${stats?.maxConcurrency ?? limit}`} />
          <SummaryCard
            label="CPU"
            value={
              stats?.cpuPercent != null ? `${stats.cpuPercent.toFixed(0)}%` : '—'
            }
          />
          <SummaryCard label="内存" value={memLabel} />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <label className="flex items-center gap-3 text-xs text-slate-600">
            并发上限
            <input
              type="range"
              min={1}
              max={20}
              value={limit}
              onChange={(e) => void commitLimit(Number(e.target.value))}
              className="w-40"
            />
            <span className="font-mono">{limit}</span>
          </label>
          <div className="flex items-center gap-3">
            {limitMsg ? (
              <span className="text-xs text-slate-500">{limitMsg}</span>
            ) : null}
            <span className="flex items-center gap-1.5 text-xs text-teal-600">
              <span className="h-2 w-2 animate-pulse rounded-full bg-teal-500" />
              {isRemoteMode() ? '每 8s 同步 runtime + stats' : '本地 store'}
            </span>
            <Button
              variant="secondary"
              onClick={() => {
                void refreshRuntime()
                void pullStats()
              }}
            >
              立即刷新
            </Button>
            <Button
              variant="danger"
              disabled={running.length === 0}
              onClick={() => void stopMany(running.map((p) => p.id))}
            >
              全部停止
            </Button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {running.length === 0 ? (
            <p className="col-span-full text-center text-sm text-slate-400">
              当前无运行实例。可在{' '}
              <Link to="/profiles" className="text-teal-600">
                环境管理
              </Link>{' '}
              启动。
            </p>
          ) : (
            running.map((p) => {
              const extra = runtimeExtras[p.id]
              const mem = extra?.memoryMb ?? p.memoryMb
              const cpu = extra?.cpuPercent ?? p.cpuPercent
              return (
                <article
                  key={p.id}
                  className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-bold text-slate-800">{p.name}</h3>
                      <p className="mt-1 font-mono text-[10px] text-slate-400">
                        PID {p.pid ?? '—'}
                      </p>
                    </div>
                    <StatusBadge status={p.status} />
                  </div>
                  <dl className="mt-4 space-y-1.5 text-[11px] text-slate-500">
                    <div>
                      模式：{p.headless ? '无头' : '有头'}
                      {p.status === 'api' ? ' · API' : ''}
                    </div>
                    <div>启动：{p.lastStartedAt ?? '—'}</div>
                    <div>
                      资源：
                      {mem != null ? `${mem.toFixed(0)} MB` : '—'}
                      {cpu != null ? ` · CPU ${cpu.toFixed(0)}%` : ''}
                    </div>
                    <div className="truncate font-mono">WS：{p.wsEndpoint ?? '—'}</div>
                    <div>代理：{p.proxyLabel ?? '直连'}</div>
                  </dl>
                  <div className="mt-4 flex gap-2">
                    <Link
                      to={`/profiles/${p.id}`}
                      className="inline-flex rounded-lg border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700"
                    >
                      详情
                    </Link>
                    <Button variant="danger" onClick={() => void stopProfile(p.id)}>
                      强杀
                    </Button>
                  </div>
                </article>
              )
            })
          )}
        </div>
      </main>
    </>
  )
}
