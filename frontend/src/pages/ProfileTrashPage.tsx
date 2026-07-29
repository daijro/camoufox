import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { useDataStore } from '@/stores/data'

export function ProfileTrashPage() {
  const profiles = useDataStore((s) => s.profiles)
  const groups = useDataStore((s) => s.groups)
  const restore = useDataStore((s) => s.restore)
  const purge = useDataStore((s) => s.purge)
  const purgeAll = useDataStore((s) => s.purgeAll)

  const [selected, setSelected] = useState<string[]>([])
  const [q, setQ] = useState('')

  const trash = useMemo(
    () =>
      profiles.filter(
        (p) =>
          !!p.deletedAt &&
          (!q.trim() ||
            p.name.toLowerCase().includes(q.toLowerCase()) ||
            p.note.toLowerCase().includes(q.toLowerCase())),
      ),
    [profiles, q],
  )

  const disk = trash.reduce((sum, p) => sum + p.diskMb, 0)
  const groupName = (id: string | null) =>
    groups.find((g) => g.id === id)?.name ?? '未分类'

  return (
    <>
      <TopBar title="环境回收站" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="待清理" value={`${trash.length} 个`} />
          <SummaryCard label="可释放空间" value={`${disk} MB`} accent />
          <SummaryCard
            label="今日新增"
            value={`${trash.filter((p) => p.deletedAt?.startsWith(new Date().toISOString().slice(0, 10))).length}`}
          />
          <SummaryCard label="策略" value="软删除" hint="可恢复 / 彻底删除" />
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索名称 / 备注…"
            className="w-72 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
          />
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={selected.length === 0}
              onClick={() => {
                selected.forEach((id) => restore(id))
                setSelected([])
              }}
            >
              批量恢复
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (confirm('彻底清空回收站？不可恢复。')) purgeAll()
              }}
            >
              一键清空
            </Button>
            <Link
              to="/profiles"
              className="inline-flex items-center rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              返回列表
            </Link>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-4">
                  <input
                    type="checkbox"
                    checked={trash.length > 0 && selected.length === trash.length}
                    onChange={() =>
                      setSelected(
                        selected.length === trash.length ? [] : trash.map((p) => p.id),
                      )
                    }
                  />
                </th>
                <th className="p-4">名称</th>
                <th className="p-4">原分组</th>
                <th className="p-4">删除时间</th>
                <th className="p-4">路径 / 大小</th>
                <th className="p-4 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {trash.length === 0 ? (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-slate-400">
                    回收站为空
                  </td>
                </tr>
              ) : (
                trash.map((p) => (
                  <tr key={p.id} className="border-t border-slate-100">
                    <td className="p-4">
                      <input
                        type="checkbox"
                        checked={selected.includes(p.id)}
                        onChange={() =>
                          setSelected((prev) =>
                            prev.includes(p.id)
                              ? prev.filter((x) => x !== p.id)
                              : [...prev, p.id],
                          )
                        }
                      />
                    </td>
                    <td className="p-4">
                      <div className="font-semibold text-slate-800">{p.name}</div>
                      <div className="text-[10px] text-slate-400">{p.note || '—'}</div>
                    </td>
                    <td className="p-4">{groupName(p.groupId)}</td>
                    <td className="p-4 font-mono text-slate-500">{p.deletedAt}</td>
                    <td className="p-4">
                      <div className="max-w-xs truncate font-mono text-[10px] text-slate-500">
                        {p.profilePath}
                      </div>
                      <div className="text-slate-400">{p.diskMb} MB</div>
                    </td>
                    <td className="space-x-1 p-4 text-right">
                      <Button variant="secondary" onClick={() => restore(p.id)}>
                        恢复
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => {
                          if (confirm('彻底删除该环境？')) purge(p.id)
                        }}
                      >
                        彻底删除
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>
    </>
  )
}
