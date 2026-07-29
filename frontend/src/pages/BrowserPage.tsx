import { useState } from 'react'
import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { useDataStore } from '@/stores/data'
import { cn } from '@/lib/utils'

const REMOTE = [
  { version: '152.0.4-beta.28', channel: 'beta', size: '98 MB' },
  { version: '150.0.2-beta.25', channel: 'beta', size: '96 MB' },
  { version: '135.0.1-beta.23', channel: 'beta', size: '94 MB' },
]

export function BrowserPage() {
  const version = useDataStore((s) => s.settings.camoufoxVersion)
  const updateSettings = useDataStore((s) => s.updateSettings)
  const [installed, setInstalled] = useState(REMOTE.map((r) => r.version === version))

  return (
    <>
      <TopBar title="Camoufox 版本管理" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="Active" value={version} accent />
          <SummaryCard label="作用域" value="全局" hint="非 per-profile" />
          <SummaryCard label="已安装" value={`${installed.filter(Boolean).length}`} />
          <SummaryCard label="远程列表" value={`${REMOTE.length}`} />
        </div>

        <div className="rounded-xl border border-amber-100 bg-amber-50 p-4 text-xs text-amber-800">
          Camoufox 内核版本为<strong>全局 Active</strong>（multiversion.set_active），不在单环境级别切换。
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-4">版本</th>
                <th className="p-4">Channel</th>
                <th className="p-4">大小</th>
                <th className="p-4">状态</th>
                <th className="p-4 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {REMOTE.map((r, i) => {
                const isActive = r.version === version
                const isInst = installed[i] || isActive
                return (
                  <tr key={r.version} className="border-t border-slate-100">
                    <td className="p-4 font-mono font-semibold">{r.version}</td>
                    <td className="p-4">{r.channel}</td>
                    <td className="p-4">{r.size}</td>
                    <td className="p-4">
                      <span
                        className={cn(
                          'rounded px-2 py-0.5 text-[10px] font-medium',
                          isActive
                            ? 'bg-teal-50 text-teal-700'
                            : isInst
                              ? 'bg-slate-100 text-slate-600'
                              : 'bg-slate-50 text-slate-400',
                        )}
                      >
                        {isActive ? 'Active' : isInst ? '已安装' : '未安装'}
                      </span>
                    </td>
                    <td className="space-x-1 p-4 text-right">
                      {!isInst ? (
                        <Button
                          variant="secondary"
                          onClick={() =>
                            setInstalled((prev) => {
                              const next = [...prev]
                              next[i] = true
                              return next
                            })
                          }
                        >
                          安装
                        </Button>
                      ) : null}
                      {isInst && !isActive ? (
                        <Button onClick={() => updateSettings({ camoufoxVersion: r.version })}>
                          设为 Active
                        </Button>
                      ) : null}
                      {isInst && !isActive ? (
                        <Button
                          variant="danger"
                          onClick={() =>
                            setInstalled((prev) => {
                              const next = [...prev]
                              next[i] = false
                              return next
                            })
                          }
                        >
                          卸载
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
