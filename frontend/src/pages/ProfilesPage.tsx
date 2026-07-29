import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Drawer } from '@/components/ui/Drawer'
import { Button } from '@/components/ui/Form'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { cn } from '@/lib/utils'
import { useDataStore } from '@/stores/data'
import { useUiStore } from '@/stores/ui'
import type { Profile, ProfileStatus } from '@/types/console'
import { countRunning } from '@/types/console'

function matchesQuery(p: Profile, q: string): boolean {
  if (!q.trim()) return true
  const s = q.toLowerCase()
  return (
    p.name.toLowerCase().includes(s) ||
    p.platform.toLowerCase().includes(s) ||
    (p.proxyLabel?.toLowerCase().includes(s) ?? false) ||
    p.note.toLowerCase().includes(s) ||
    p.tags.some((t) => t.toLowerCase().includes(s)) ||
    p.id.toLowerCase().includes(s)
  )
}

export function ProfilesPage() {
  const searchQuery = useUiStore((s) => s.searchQuery)
  const profiles = useDataStore((s) => s.profiles)
  const groups = useDataStore((s) => s.groups)
  const startProfile = useDataStore((s) => s.startProfile)
  const stopProfile = useDataStore((s) => s.stopProfile)
  const stopMany = useDataStore((s) => s.stopMany)
  const softDeleteMany = useDataStore((s) => s.softDeleteMany)
  const settings = useDataStore((s) => s.settings)

  const [groupFilter, setGroupFilter] = useState('all')
  const [tagFilter, setTagFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState<ProfileStatus | 'all'>('all')
  const [selected, setSelected] = useState<string[]>([])
  const [drawerId, setDrawerId] = useState<string | null>(null)

  const active = useMemo(
    () => profiles.filter((p) => !p.deletedAt),
    [profiles],
  )

  const allTags = useMemo(() => {
    const set = new Set<string>()
    active.forEach((p) => p.tags.forEach((t) => set.add(t)))
    return [...set]
  }, [active])

  const filtered = active.filter((p) => {
    if (!matchesQuery(p, searchQuery)) return false
    if (groupFilter !== 'all' && p.groupId !== groupFilter) return false
    if (tagFilter !== 'all' && !p.tags.includes(tagFilter)) return false
    if (statusFilter !== 'all' && p.status !== statusFilter) return false
    return true
  })

  const running = countRunning(active)
  const errors = active.filter((p) => p.status === 'error').length
  const drawer = active.find((p) => p.id === drawerId)
  const groupName = (id: string | null) =>
    groups.find((g) => g.id === id)?.name ?? '未分类'

  const toggleAll = () => {
    if (selected.length === filtered.length) setSelected([])
    else setSelected(filtered.map((p) => p.id))
  }

  const toggleOne = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  return (
    <>
      <TopBar title="环境管理中心" runningCount={running} totalCount={active.length} />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="环境总数" value={`${active.length} 个`} />
          <SummaryCard label="运行中" value={`${running} 个`} accent />
          <SummaryCard label="异常 / 失败" value={`${errors} 个`} danger />
          <SummaryCard
            label="Local API"
            value={`:${settings.apiPort}`}
            hint={settings.apiRunning ? '运行中' : '已停止'}
          />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap gap-2">
            <select
              value={groupFilter}
              onChange={(e) => setGroupFilter(e.target.value)}
              className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
            >
              <option value="all">全部分组</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            <select
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
            >
              <option value="all">所有标签</option>
              {allTags.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ProfileStatus | 'all')}
              className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
            >
              <option value="all">所有运行状态</option>
              <option value="idle">未启动</option>
              <option value="starting">启动中</option>
              <option value="running">运行中</option>
              <option value="api">API 控制中</option>
              <option value="error">运行异常</option>
            </select>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={selected.length === 0}
              onClick={() => void stopMany(selected)}
            >
              批量停止 ({selected.length})
            </Button>
            <Button
              variant="danger"
              disabled={selected.length === 0}
              onClick={() => {
                void softDeleteMany(selected).then(() => setSelected([]))
              }}
            >
              批量删除
            </Button>
            <Link
              to="/profiles/import"
              className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              批量导入
            </Link>
            <Link
              to="/profiles/groups"
              className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              分组标签
            </Link>
            <Link
              to="/profiles/trash"
              className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              回收站
            </Link>
            <Link
              to="/profiles/new"
              className="inline-flex items-center rounded-lg bg-teal-600 px-3 py-2 text-xs font-semibold text-white hover:bg-teal-700"
            >
              新建环境
            </Link>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
              <tr>
                <th className="p-4">
                  <input
                    type="checkbox"
                    checked={filtered.length > 0 && selected.length === filtered.length}
                    onChange={toggleAll}
                  />
                </th>
                <th className="p-4 font-medium">#</th>
                <th className="p-4 font-medium">环境名称</th>
                <th className="p-4 font-medium">平台</th>
                <th className="p-4 font-medium">分组</th>
                <th className="p-4 font-medium">代理</th>
                <th className="p-4 font-medium">指纹摘要</th>
                <th className="p-4 font-medium">状态</th>
                <th className="p-4 font-medium">最后启动</th>
                <th className="p-4 font-medium">标签</th>
                <th className="p-4 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-slate-400">
                    无匹配环境
                  </td>
                </tr>
              ) : (
                filtered.map((p, i) => (
                  <tr
                    key={p.id}
                    className={cn(
                      'border-t border-slate-100 hover:bg-slate-50',
                      drawerId === p.id && 'bg-teal-50/40',
                    )}
                  >
                    <td className="p-4">
                      <input
                        type="checkbox"
                        checked={selected.includes(p.id)}
                        onChange={() => toggleOne(p.id)}
                      />
                    </td>
                    <td className="p-4 font-mono text-slate-400">
                      {String(i + 1).padStart(2, '0')}
                    </td>
                    <td className="p-4">
                      <button
                        type="button"
                        className="text-left font-semibold text-slate-800 hover:text-teal-700"
                        onClick={() => setDrawerId(p.id)}
                      >
                        {p.name}
                      </button>
                      <div className="mt-0.5 text-[10px] text-slate-400">ID: {p.id}</div>
                    </td>
                    <td className="p-4 text-slate-600">{p.platform}</td>
                    <td className="p-4 text-slate-500">{groupName(p.groupId)}</td>
                    <td className="p-4 font-mono text-slate-600">
                      {p.proxyLabel ?? <span className="italic text-slate-400">直连</span>}
                    </td>
                    <td className="p-4">
                      <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-600">
                        {p.fingerprint}
                      </span>
                    </td>
                    <td className="p-4">
                      <StatusBadge status={p.status} />
                    </td>
                    <td className="p-4 font-mono text-slate-500">
                      {p.lastStartedAt ?? '—'}
                    </td>
                    <td className="p-4">
                      <div className="flex flex-wrap gap-1">
                        {p.tags.length === 0 ? (
                          <span className="text-slate-300">—</span>
                        ) : (
                          p.tags.map((t) => (
                            <span
                              key={t}
                              className="rounded border border-teal-100 bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-600"
                            >
                              {t}
                            </span>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="space-x-1.5 whitespace-nowrap p-4 text-right">
                      {p.status === 'starting' ? (
                        <Button variant="secondary" disabled>
                          启动中
                        </Button>
                      ) : p.status === 'running' || p.status === 'api' ? (
                        <Button variant="danger" onClick={() => void stopProfile(p.id)}>
                          {p.status === 'api' ? '强制断开' : '停止'}
                        </Button>
                      ) : (
                        <Button onClick={() => void startProfile(p.id)}>
                          {p.status === 'error' ? '重试' : '启动'}
                        </Button>
                      )}
                      <Link
                        to={`/profiles/${p.id}`}
                        className="inline-flex rounded-lg border border-slate-200 bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600"
                      >
                        详情
                      </Link>
                      <Button variant="ghost" onClick={() => setDrawerId(p.id)}>
                        快捷
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>

      <Drawer
        open={!!drawer}
        title={drawer ? `快捷管理 · ${drawer.name}` : ''}
        onClose={() => setDrawerId(null)}
      >
        {drawer ? (
          <div className="space-y-5 text-sm">
            <section className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                本地存储
              </h4>
              <p className="break-all font-mono text-xs text-slate-600">
                {drawer.profilePath}
              </p>
              <p className="text-xs text-slate-500">占用约 {drawer.diskMb} MB</p>
              <Button
                variant="secondary"
                onClick={() =>
                  useDataStore.getState().updateProfile(drawer.id, {
                    diskMb: Math.max(8, Math.floor(drawer.diskMb * 0.55)),
                    logs: [
                      ...drawer.logs,
                      {
                        at: new Date().toISOString().slice(0, 16).replace('T', ' '),
                        level: 'info',
                        message: '已清理缓存（保留 Cookie）',
                      },
                    ],
                  })
                }
              >
                一键清理缓存（保留 Cookie）
              </Button>
            </section>
            <section className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                代理 / GeoIP
              </h4>
              <p className="font-mono text-xs">{drawer.proxyLabel ?? '直连'}</p>
              <p className="text-xs text-slate-500">出口 / 时区：mock 未实测</p>
              <Button variant="secondary">重新测试代理</Button>
            </section>
            <section className="space-y-2">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                指纹配置（只读）
              </h4>
              <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 font-mono text-[10px] text-teal-200">
                {JSON.stringify(
                  {
                    strategy: drawer.fingerprintStrategy,
                    os: drawer.os,
                    alignGeo: drawer.alignGeoWithProxy,
                    summary: drawer.fingerprint,
                  },
                  null,
                  2,
                )}
              </pre>
              <Link to="/fingerprints" className="text-xs font-medium text-teal-600">
                前往指纹策略模板 →
              </Link>
            </section>
            <Link
              to={`/profiles/${drawer.id}`}
              className="inline-flex w-full justify-center rounded-lg bg-teal-600 px-3 py-2 text-xs font-semibold text-white"
            >
              打开完整详情
            </Link>
          </div>
        ) : null}
      </Drawer>
    </>
  )
}
