import { useState } from 'react'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { useDataStore } from '@/stores/data'

export function ProfileGroupsPage() {
  const groups = useDataStore((s) => s.groups)
  const tags = useDataStore((s) => s.tags)
  const profiles = useDataStore((s) => s.profiles)
  const addGroup = useDataStore((s) => s.addGroup)
  const renameGroup = useDataStore((s) => s.renameGroup)
  const removeGroup = useDataStore((s) => s.removeGroup)
  const addTag = useDataStore((s) => s.addTag)
  const removeTag = useDataStore((s) => s.removeTag)

  const [groupName, setGroupName] = useState('')
  const [tagName, setTagName] = useState('')
  const [tagColor, setTagColor] = useState('#0d9488')

  const active = profiles.filter((p) => !p.deletedAt)
  const groupCount = (id: string) => active.filter((p) => p.groupId === id).length
  const tagCount = (name: string) => active.filter((p) => p.tags.includes(name)).length

  return (
    <>
      <TopBar title="分组标签管理器" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="分组数" value={`${groups.length}`} />
          <SummaryCard label="标签数" value={`${tags.length}`} accent />
          <SummaryCard label="环境数" value={`${active.length}`} />
          <SummaryCard label="未分类" value={`${active.filter((p) => !p.groupId).length}`} />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="mb-4 text-sm font-bold">分组</h3>
            <div className="mb-4 flex gap-2">
              <Input
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder="新分组名称"
              />
              <Button
                onClick={() => {
                  if (!groupName.trim()) return
                  void addGroup(groupName.trim()).then(() => setGroupName(''))
                }}
              >
                添加
              </Button>
            </div>
            <ul className="space-y-2">
              {groups.map((g) => (
                <li
                  key={g.id}
                  className="flex items-center gap-2 rounded-lg border border-slate-100 px-3 py-2"
                >
                  <Input
                    className="flex-1"
                    value={g.name}
                    onChange={(e) => renameGroup(g.id, e.target.value)}
                  />
                  <span className="text-[10px] text-slate-400">{groupCount(g.id)} 环境</span>
                  <Button variant="danger" onClick={() => void removeGroup(g.id)}>
                    删除
                  </Button>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="mb-4 text-sm font-bold">标签</h3>
            <div className="mb-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
              <Field label="名称">
                <Input value={tagName} onChange={(e) => setTagName(e.target.value)} />
              </Field>
              <Field label="颜色">
                <Input
                  type="color"
                  value={tagColor}
                  onChange={(e) => setTagColor(e.target.value)}
                  className="h-10 w-14 p-1"
                />
              </Field>
              <div className="flex items-end">
                <Button
                  onClick={() => {
                    if (!tagName.trim()) return
                    void addTag(tagName.trim(), tagColor).then(() => setTagName(''))
                  }}
                >
                  添加
                </Button>
              </div>
            </div>
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="pb-2">名称</th>
                  <th className="pb-2">色值</th>
                  <th className="pb-2">引用</th>
                  <th className="pb-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {tags.map((t) => (
                  <tr key={t.id} className="border-t border-slate-100">
                    <td className="py-2">
                      <span
                        className="mr-2 inline-block h-2 w-2 rounded-full"
                        style={{ background: t.color }}
                      />
                      {t.name}
                    </td>
                    <td className="py-2 font-mono text-slate-500">{t.color}</td>
                    <td className="py-2">{tagCount(t.name)}</td>
                    <td className="py-2 text-right">
                      <Button variant="danger" onClick={() => void removeTag(t.id)}>
                        删除
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Button
              variant="secondary"
              className="mt-4"
              onClick={() => {
                void (async () => {
                  const zero = tags.filter((t) => tagCount(t.name) === 0)
                  await Promise.all(zero.map((t) => removeTag(t.id)))
                })()
              }}
            >
              清理 0 引用标签
            </Button>
          </section>
        </div>
      </main>
    </>
  )
}
