import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { cn } from '@/lib/utils'
import { useDataStore } from '@/stores/data'
import type { OsChoice } from '@/types/console'

export function FingerprintsPage() {
  const navigate = useNavigate()
  const templates = useDataStore((s) => s.templates)
  const createTemplate = useDataStore((s) => s.createTemplate)
  const sampleTemplate = useDataStore((s) => s.sampleTemplate)
  const setDefaultTemplate = useDataStore((s) => s.setDefaultTemplate)
  const copyTemplate = useDataStore((s) => s.copyTemplate)
  const removeTemplate = useDataStore((s) => s.removeTemplate)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [os, setOs] = useState<OsChoice>('windows')
  const [usePreset, setUsePreset] = useState(false)

  const systemCount = templates.filter((t) => t.kind === 'system').length
  const customCount = templates.filter((t) => t.kind === 'custom').length
  const defaultName = useMemo(
    () => templates.find((t) => t.isDefault)?.name ?? '—',
    [templates],
  )

  const run = async (id: string, fn: () => Promise<void>) => {
    setBusy(id)
    setError('')
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <TopBar title="指纹策略模板" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="模板数" value={`${templates.length}`} />
          <SummaryCard label="系统预设" value={`${systemCount}`} accent />
          <SummaryCard label="自定义" value={`${customCount}`} />
          <SummaryCard label="默认策略" value={defaultName} />
        </div>

        <div className="rounded-xl border border-teal-100 bg-teal-50/60 p-4 text-xs text-teal-800">
          Camoufox 指纹在 C++ 层注入。自定义模板可「采样固化」后写入固定 config；启动时按
          template 注入，不再用 preset 顶替。
        </div>

        {error ? <p className="text-sm text-rose-600">{error}</p> : null}

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-bold">新建自定义模板</h3>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="名称">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="OS">
              <Select value={os} onChange={(e) => setOs(e.target.value as OsChoice)}>
                <option value="windows">Windows</option>
                <option value="macos">macOS</option>
                <option value="linux">Linux</option>
              </Select>
            </Field>
            <label className="flex items-center gap-2 pb-2 text-xs text-slate-600">
              <input
                type="checkbox"
                checked={usePreset}
                onChange={(e) => setUsePreset(e.target.checked)}
              />
              基于真实预设采样
            </label>
            <Button
              disabled={!name.trim() || busy === 'create'}
              onClick={() =>
                void run('create', async () => {
                  const t = await createTemplate({
                    name: name.trim(),
                    os,
                    usePreset,
                    alignGeo: true,
                    webrtc: 'follow',
                  })
                  setName('')
                  await sampleTemplate(t.id)
                })
              }
            >
              创建并采样
            </Button>
          </div>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          {templates.map((t) => (
            <article
              key={t.id}
              className={cn(
                'rounded-xl border bg-white p-5 shadow-sm',
                t.kind === 'system' ? 'border-teal-200' : 'border-slate-200',
                t.isDefault && 'ring-1 ring-teal-400',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-bold text-slate-800">
                    {t.name}
                    {t.isDefault ? (
                      <span className="ml-2 text-[10px] font-medium text-teal-600">默认</span>
                    ) : null}
                  </h3>
                  <p className="mt-1 text-xs text-slate-500">
                    {t.hasConfig
                      ? '已固化 config_json'
                      : t.usePreset
                        ? '启动时 fingerprint_preset'
                        : '每次启动自动生成'}
                  </p>
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                  {t.kind === 'system' ? '系统' : '自定义'}
                </span>
              </div>
              <p className="mt-3 text-[11px] text-slate-400">
                OS：{t.os} · WebRTC：{t.webrtc} · Geo：{t.alignGeo ? '跟随代理' : '关'}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {t.kind === 'custom' ? (
                  <Link
                    to={`/fingerprints/${t.id}/edit`}
                    className="inline-flex rounded-lg border border-slate-200 bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700"
                  >
                    编辑
                  </Link>
                ) : (
                  <Button
                    variant="secondary"
                    disabled={busy === t.id}
                    onClick={() =>
                      void run(t.id, async () => {
                        await copyTemplate(t.id)
                        const list = useDataStore.getState().templates
                        const last = list[list.length - 1]
                        if (last) navigate(`/fingerprints/${last.id}/edit`)
                      })
                    }
                  >
                    复制后编辑
                  </Button>
                )}
                <Button
                  variant="secondary"
                  disabled={busy === t.id || (t.kind === 'system' && t.id === 'tpl_auto')}
                  onClick={() => void run(t.id, () => sampleTemplate(t.id))}
                >
                  采样固化
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy === t.id || t.isDefault}
                  onClick={() => void run(t.id, () => setDefaultTemplate(t.id))}
                >
                  设为默认
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy === t.id}
                  onClick={() => void run(t.id, () => copyTemplate(t.id))}
                >
                  复制
                </Button>
                {t.kind === 'custom' ? (
                  <Button
                    variant="danger"
                    disabled={busy === t.id}
                    onClick={() => void run(t.id, () => removeTemplate(t.id))}
                  >
                    删除
                  </Button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </main>
    </>
  )
}
