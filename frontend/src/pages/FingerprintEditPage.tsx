import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select } from '@/components/ui/Form'
import { cn } from '@/lib/utils'
import { isRemoteMode } from '@/lib/api'
import * as remote from '@/services/remote'
import { useDataStore } from '@/stores/data'
import type { OsChoice } from '@/types/console'

type Cat = 'basic' | 'screen' | 'geo' | 'seed'

const CATS: { id: Cat; label: string }[] = [
  { id: 'basic', label: '基础' },
  { id: 'screen', label: '屏幕' },
  { id: 'geo', label: '地理 · WebRTC' },
  { id: 'seed', label: 'Seed' },
]

function parseCfg(raw: string | null | undefined): Record<string, unknown> {
  if (!raw) return {}
  try {
    const o = JSON.parse(raw)
    return o && typeof o === 'object' && !Array.isArray(o) ? o : {}
  } catch {
    return {}
  }
}

function num(v: unknown, fallback: number): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}

export function FingerprintEditPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const templates = useDataStore((s) => s.templates)
  const sampleTemplate = useDataStore((s) => s.sampleTemplate)
  const refreshTemplates = useDataStore((s) => s.refreshTemplates)
  const tpl = templates.find((t) => t.id === id)

  const [cat, setCat] = useState<Cat>('basic')
  const [os, setOs] = useState<OsChoice>('windows')
  const [alignGeo, setAlignGeo] = useState(true)
  const [webrtc, setWebrtc] = useState<'follow' | 'disable'>('follow')
  const [usePreset, setUsePreset] = useState(false)
  const [cfg, setCfg] = useState<Record<string, unknown>>({})
  const [width, setWidth] = useState(1920)
  const [height, setHeight] = useState(1080)
  const [dpr, setDpr] = useState(1)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [seedMode, setSeedMode] = useState<'fixed' | 'random'>('fixed')

  useEffect(() => {
    if (isRemoteMode()) void refreshTemplates()
  }, [refreshTemplates])

  useEffect(() => {
    if (!tpl) return
    setOs((tpl.os as OsChoice) || 'windows')
    setAlignGeo(tpl.alignGeo)
    setWebrtc(tpl.webrtc === 'disable' ? 'disable' : 'follow')
    setUsePreset(tpl.usePreset)
    const parsed = parseCfg(tpl.configJson)
    setCfg(parsed)
    setWidth(num(parsed['screen.width'] ?? parsed['window.outerWidth'], 1920))
    setHeight(num(parsed['screen.height'] ?? parsed['window.outerHeight'], 1080))
    setDpr(num(parsed['window.devicePixelRatio'], 1))
    setSeedMode(tpl.hasConfig ? 'fixed' : 'random')
  }, [tpl?.id, tpl?.configJson, tpl?.os, tpl?.alignGeo, tpl?.webrtc, tpl?.usePreset, tpl?.hasConfig])

  const preview = useMemo(() => {
    const next = { ...cfg }
    next['screen.width'] = width
    next['screen.height'] = height
    next['window.outerWidth'] = width
    next['window.outerHeight'] = height
    next['window.devicePixelRatio'] = dpr
    return next
  }, [cfg, width, height, dpr])

  const previewJson = useMemo(
    () => JSON.stringify(preview, null, 2),
    [preview],
  )

  const ua = String(preview['navigator.userAgent'] ?? '')

  if (!tpl) {
    return (
      <>
        <TopBar title="指纹编辑器" />
        <main className="flex-1 p-8">
          <p className="text-sm text-slate-500">模板不存在。</p>
          <Link to="/fingerprints" className="mt-4 inline-block text-sm text-teal-600">
            返回列表
          </Link>
        </main>
      </>
    )
  }

  const readOnly = tpl.kind === 'system'

  const applyLocalScreen = () => {
    setCfg((c) => ({
      ...c,
      'screen.width': width,
      'screen.height': height,
      'window.outerWidth': width,
      'window.outerHeight': height,
      'window.devicePixelRatio': dpr,
    }))
  }

  const save = async () => {
    if (readOnly) {
      setMsg('系统模板只读，请先复制为自定义模板')
      return
    }
    if (!isRemoteMode()) {
      setMsg('本地 mock 模式请配置 VITE_API_BASE')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      applyLocalScreen()
      const body = {
        os,
        alignGeo,
        webrtc,
        usePreset,
        configJson: JSON.stringify({
          ...cfg,
          'screen.width': width,
          'screen.height': height,
          'window.outerWidth': width,
          'window.outerHeight': height,
          'window.devicePixelRatio': dpr,
        }),
      }
      const t = await remote.remotePatchTemplate(tpl.id, body)
      useDataStore.setState((s) => ({
        templates: s.templates.map((x) => (x.id === t.id ? t : x)),
      }))
      setMsg('已保存')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const resample = async (preset: boolean) => {
    if (readOnly) {
      setMsg('系统模板请先「复制后编辑」')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      if (isRemoteMode()) {
        await remote.remotePatchTemplate(tpl.id, { usePreset: preset, os })
        await sampleTemplate(tpl.id)
        await refreshTemplates()
        setSeedMode('fixed')
        setMsg(preset ? '已从预设采样并固化' : '已随机生成并固化')
      } else {
        setMsg('本地 mock 不支持采样')
      }
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(previewJson)
      setMsg('已复制 JSON')
    } catch {
      setMsg('复制失败')
    }
  }

  return (
    <>
      <TopBar title={`指纹编辑 · ${tpl.name}`} />
      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <Link to="/fingerprints" className="text-teal-600 hover:underline">
              ← 模板列表
            </Link>
            <span>
              {tpl.kind === 'system' ? '系统预设（只读）' : '自定义'}
              {tpl.hasConfig ? ' · 已固化' : ' · 未固化'}
            </span>
          </div>
          <div className="flex gap-2">
            {readOnly ? (
              <Button
                variant="secondary"
                onClick={() => {
                  void useDataStore
                    .getState()
                    .copyTemplate(tpl.id)
                    .then(() => {
                      const list = useDataStore.getState().templates
                      const last = list[list.length - 1]
                      if (last) navigate(`/fingerprints/${last.id}/edit`)
                    })
                }}
              >
                复制后编辑
              </Button>
            ) : (
              <Button disabled={busy} onClick={() => void save()}>
                保存
              </Button>
            )}
          </div>
        </div>

        {msg ? (
          <p className="border-b border-slate-100 bg-slate-50 px-6 py-2 text-xs text-slate-600">
            {msg}
          </p>
        ) : null}

        <div className="flex min-h-0 flex-1 overflow-hidden">
          <aside className="w-44 flex-shrink-0 space-y-1 overflow-y-auto border-r border-slate-200 bg-white p-3">
            {CATS.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setCat(c.id)}
                className={cn(
                  'block w-full rounded-lg px-3 py-2 text-left text-xs font-medium',
                  cat === c.id
                    ? 'bg-teal-50 text-teal-700'
                    : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                {c.label}
              </button>
            ))}
          </aside>

          <section className="flex-1 space-y-4 overflow-y-auto p-6">
            {cat === 'basic' ? (
              <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="text-sm font-bold">基础</h3>
                <Field label="操作系统">
                  <Select
                    value={os}
                    disabled={readOnly}
                    onChange={(e) => setOs(e.target.value as OsChoice)}
                  >
                    <option value="windows">Windows</option>
                    <option value="macos">macOS</option>
                    <option value="linux">Linux</option>
                  </Select>
                </Field>
                <Field label="User-Agent（只读）">
                  <Input value={ua || '（采样后显示）'} readOnly />
                </Field>
              </div>
            ) : null}

            {cat === 'screen' ? (
              <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="text-sm font-bold">屏幕</h3>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label="宽度">
                    <Input
                      type="number"
                      value={width}
                      disabled={readOnly}
                      onChange={(e) => setWidth(Number(e.target.value) || 0)}
                    />
                  </Field>
                  <Field label="高度">
                    <Input
                      type="number"
                      value={height}
                      disabled={readOnly}
                      onChange={(e) => setHeight(Number(e.target.value) || 0)}
                    />
                  </Field>
                  <Field label="DPR">
                    <Input
                      type="number"
                      step="0.25"
                      value={dpr}
                      disabled={readOnly}
                      onChange={(e) => setDpr(Number(e.target.value) || 1)}
                    />
                  </Field>
                </div>
              </div>
            ) : null}

            {cat === 'geo' ? (
              <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="text-sm font-bold">地理 · WebRTC</h3>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={alignGeo}
                    disabled={readOnly}
                    onChange={(e) => setAlignGeo(e.target.checked)}
                  />
                  时区/语言跟随代理（alignGeo）
                </label>
                <Field label="WebRTC">
                  <Select
                    value={webrtc}
                    disabled={readOnly}
                    onChange={(e) =>
                      setWebrtc(e.target.value === 'disable' ? 'disable' : 'follow')
                    }
                  >
                    <option value="follow">跟随代理 IP</option>
                    <option value="disable">禁用</option>
                  </Select>
                </Field>
              </div>
            ) : null}

            {cat === 'seed' ? (
              <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h3 className="text-sm font-bold">Seed</h3>
                <p className="text-xs text-slate-500">
                  固定模式：模板内固化 canvas/audio 等 seed；随机模式说明为启动时再采样（本页编辑以固化为准）。
                </p>
                <div className="flex gap-2">
                  <Button
                    variant={seedMode === 'fixed' ? 'primary' : 'secondary'}
                    disabled={readOnly}
                    onClick={() => setSeedMode('fixed')}
                  >
                    固定存模板
                  </Button>
                  <Button
                    variant={seedMode === 'random' ? 'primary' : 'secondary'}
                    disabled={readOnly}
                    onClick={() => setSeedMode('random')}
                  >
                    每次随机（说明）
                  </Button>
                </div>
                <Field label="canvas:seed">
                  <Input value={String(preview['canvas:seed'] ?? '—')} readOnly />
                </Field>
                <Field label="audio:seed">
                  <Input value={String(preview['audio:seed'] ?? '—')} readOnly />
                </Field>
                <Button
                  variant="secondary"
                  disabled={readOnly || busy}
                  onClick={() => void resample(false)}
                >
                  重新采样 Seed
                </Button>
              </div>
            ) : null}
          </section>

          <aside className="flex w-[360px] flex-shrink-0 flex-col border-l border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <h3 className="text-xs font-bold text-slate-700">camoucfg 预览</h3>
              <Button variant="ghost" onClick={() => void copyJson()}>
                复制
              </Button>
            </div>
            <pre className="flex-1 overflow-auto p-4 font-mono text-[10px] leading-relaxed text-slate-600">
              {previewJson || '{}'}
            </pre>
            <div className="space-y-2 border-t border-slate-200 p-4">
              <Button
                className="w-full"
                variant="secondary"
                disabled={readOnly || busy}
                onClick={() => void resample(false)}
              >
                随机生成
              </Button>
              <Button
                className="w-full"
                disabled={readOnly || busy}
                onClick={() => void resample(true)}
              >
                从预设采样
              </Button>
            </div>
          </aside>
        </div>
      </main>
    </>
  )
}
