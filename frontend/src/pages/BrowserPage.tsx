import { useCallback, useEffect, useState } from 'react'
import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { isRemoteMode } from '@/lib/api'
import { cn } from '@/lib/utils'
import * as remote from '@/services/remote'
import { useDataStore } from '@/stores/data'

type Installed = { version: string; path?: string | null; repo?: string | null }

export function BrowserPage() {
  const version = useDataStore((s) => s.settings.camoufoxVersion)
  const updateSettings = useDataStore((s) => s.updateSettings)
  const [active, setActive] = useState(version)
  const [installed, setInstalled] = useState<Installed[]>([])
  const [catalog, setCatalog] = useState<{ version: string; channel: string }[]>([])
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      if (isRemoteMode()) {
        const data = await remote.remoteBrowserVersions()
        setActive(data.active)
        setInstalled(data.installed ?? [])
        setCatalog(data.remote ?? [])
        setNote(data.note ?? '')
        updateSettings({ camoufoxVersion: data.active })
      } else {
        setActive(version)
        setInstalled([{ version }])
        setCatalog([
          { version: '152.0.4-beta.28', channel: 'beta' },
          { version: '150.0.2-beta.25', channel: 'beta' },
        ])
        setNote('本地 mock：无真实 multiversion')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [updateSettings, version])

  useEffect(() => {
    void load()
  }, [load])

  const setAsActive = async (ver: string) => {
    setBusy(true)
    setError('')
    try {
      if (isRemoteMode()) {
        const data = await remote.remoteBrowserSetActive(ver)
        setActive(data.active)
        setInstalled(data.installed ?? [])
        updateSettings({ camoufoxVersion: data.active })
      } else {
        setActive(ver)
        updateSettings({ camoufoxVersion: ver })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const rows = (() => {
    const map = new Map<string, { version: string; channel?: string; installed: boolean }>()
    for (const r of catalog) {
      map.set(r.version, { version: r.version, channel: r.channel, installed: false })
    }
    for (const i of installed) {
      const cur = map.get(i.version) ?? { version: i.version, installed: true }
      cur.installed = true
      map.set(i.version, cur)
    }
    if (!map.has(active)) {
      map.set(active, { version: active, installed: true })
    }
    return [...map.values()]
  })()

  return (
    <>
      <TopBar title="Camoufox 版本管理" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="Active" value={active} accent />
          <SummaryCard label="作用域" value="全局" hint="非 per-profile" />
          <SummaryCard label="已安装" value={`${installed.length}`} />
          <SummaryCard label="目录项" value={`${catalog.length}`} />
        </div>

        <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 text-xs text-amber-800">
          本页对接 <code>multiversion.list_installed / set_active</code>。在线下载请用 CLI
          （如 <code>camoufox fetch</code>），控制台不提供假安装。
          {note ? <p className="mt-2 opacity-80">{note}</p> : null}
        </div>

        {error ? <p className="text-sm text-rose-600">{error}</p> : null}

        <div className="flex justify-end">
          <Button variant="secondary" disabled={busy} onClick={() => void load()}>
            刷新已安装
          </Button>
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-4">版本</th>
                <th className="p-4">Channel</th>
                <th className="p-4">状态</th>
                <th className="p-4 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isActive = r.version === active
                return (
                  <tr key={r.version} className="border-t border-slate-100">
                    <td className="p-4 font-mono font-semibold">{r.version}</td>
                    <td className="p-4">{r.channel ?? '—'}</td>
                    <td className="p-4">
                      <span
                        className={cn(
                          'rounded px-2 py-0.5 text-[10px] font-medium',
                          isActive
                            ? 'bg-teal-50 text-teal-700'
                            : r.installed
                              ? 'bg-slate-100 text-slate-600'
                              : 'bg-slate-50 text-slate-400',
                        )}
                      >
                        {isActive ? 'Active' : r.installed ? '已安装' : '未安装'}
                      </span>
                    </td>
                    <td className="space-x-1 p-4 text-right">
                      {!r.installed ? (
                        <span className="text-[10px] text-slate-400">请用 CLI 安装</span>
                      ) : null}
                      {r.installed && !isActive ? (
                        <Button disabled={busy} onClick={() => void setAsActive(r.version)}>
                          设为 Active
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </main>
    </>
  )
}
