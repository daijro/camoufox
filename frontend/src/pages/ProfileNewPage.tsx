import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select, Textarea } from '@/components/ui/Form'
import { cn } from '@/lib/utils'
import { useDataStore } from '@/stores/data'
import type {
  FingerprintStrategy,
  OsChoice,
  ProxyProtocol,
} from '@/types/console'
import { fingerprintSummary } from '@/types/console'

type ProxyMode = 'none' | 'library' | 'new'

export function ProfileNewPage() {
  const navigate = useNavigate()
  const groups = useDataStore((s) => s.groups)
  const proxies = useDataStore((s) => s.proxies)
  const tags = useDataStore((s) => s.tags)
  const templates = useDataStore((s) => s.templates)
  const createProfile = useDataStore((s) => s.createProfile)
  const startProfile = useDataStore((s) => s.startProfile)
  const addGroup = useDataStore((s) => s.addGroup)
  const addProxy = useDataStore((s) => s.addProxy)

  const defaultTpl = templates.find((t) => t.isDefault)
  const customTemplates = templates.filter((t) => t.kind === 'custom' || t.hasConfig)

  const [name, setName] = useState('')
  const [platform, setPlatform] = useState('')
  const [groupId, setGroupId] = useState<string>('')
  const [newGroupName, setNewGroupName] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [proxyMode, setProxyMode] = useState<ProxyMode>('none')
  const [proxyId, setProxyId] = useState('')
  const [newProxy, setNewProxy] = useState({
    protocol: 'socks5' as ProxyProtocol,
    host: '',
    port: '1080',
    username: '',
    password: '',
    alias: '',
  })
  const [strategy, setStrategy] = useState<FingerprintStrategy>(
    defaultTpl && defaultTpl.id !== 'tpl_auto'
      ? defaultTpl.usePreset
        ? 'preset'
        : defaultTpl.kind === 'custom' || defaultTpl.hasConfig
          ? 'template'
          : 'auto'
      : 'auto',
  )
  const [templateId, setTemplateId] = useState(
    defaultTpl && (defaultTpl.kind === 'custom' || defaultTpl.hasConfig)
      ? defaultTpl.id
      : '',
  )
  const [os, setOs] = useState<OsChoice>('windows')
  const [alignGeo, setAlignGeo] = useState(true)
  const [cookiesJson, setCookiesJson] = useState('[]')
  const [startUrl, setStartUrl] = useState('')
  const [error, setError] = useState('')

  const strategyLabel = useMemo(() => {
    if (strategy === 'auto') return '自动随机 (BrowserForge)'
    if (strategy === 'preset') return '真实设备预设采样'
    return '已保存模板'
  }, [strategy])

  const toggleTag = (t: string) => {
    setSelectedTags((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    )
  }

  const save = async (andStart: boolean) => {
    if (!name.trim()) {
      setError('请填写环境名称')
      return
    }
    try {
      const parsed = JSON.parse(cookiesJson || '[]')
      if (!Array.isArray(parsed)) throw new Error('Cookie 须为 JSON 数组')
    } catch {
      setError('Cookie JSON 格式无效')
      return
    }

    try {
      let resolvedProxyId: string | null = null
      let proxyLabel: string | null = null
      if (proxyMode === 'library') {
        const px = proxies.find((p) => p.id === proxyId)
        if (!px) {
          setError('请选择代理')
          return
        }
        resolvedProxyId = px.id
        proxyLabel = `${px.protocol}://${px.host}:***`
      } else if (proxyMode === 'new') {
        if (!newProxy.host || !newProxy.port) {
          setError('请填写新建代理主机与端口')
          return
        }
        const created = await addProxy({
          alias: newProxy.alias || `${newProxy.host}:${newProxy.port}`,
          protocol: newProxy.protocol,
          host: newProxy.host,
          port: Number(newProxy.port),
          username: newProxy.username || undefined,
          password: newProxy.password || undefined,
          status: 'unknown',
        })
        resolvedProxyId = created.id
        proxyLabel = `${created.protocol}://${created.host}:***`
      }

      let resolvedGroup = groupId || null
      if (newGroupName.trim()) {
        resolvedGroup = (await addGroup(newGroupName.trim())).id
      }

      setError('')
      if (strategy === 'template' && !templateId) {
        setError('请选择已保存模板')
        return
      }
      const profile = await createProfile({
        name: name.trim(),
        platform: platform.trim(),
        note,
        groupId: resolvedGroup,
        tags: selectedTags,
        proxyId: resolvedProxyId,
        proxyLabel,
        fingerprintStrategy: strategy,
        os,
        alignGeoWithProxy: alignGeo,
        cookiesJson,
        startUrl,
        fingerprint: fingerprintSummary(os),
        templateId: strategy === 'template' ? templateId : null,
      })
      if (andStart) await startProfile(profile.id)
      navigate('/profiles')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <>
      <TopBar title="新建环境向导" />
      <main className="flex-1 overflow-y-auto p-8">
        <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1fr_320px]">
          <div className="space-y-6">
            <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-sm font-bold text-slate-800">基础信息</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="环境名称 *">
                  <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如 亚马逊店铺_US02" />
                </Field>
                <Field label="平台 / 用途">
                  <Input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="Amazon / Facebook…" />
                </Field>
                <Field label="归属分组">
                  <Select value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                    <option value="">未分类</option>
                    {groups.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="快捷新建分组">
                  <Input
                    value={newGroupName}
                    onChange={(e) => setNewGroupName(e.target.value)}
                    placeholder="输入后保存时创建"
                  />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="标签">
                    <div className="flex flex-wrap gap-2">
                      {tags.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => toggleTag(t.name)}
                          className={cn(
                            'rounded-full border px-3 py-1 text-xs',
                            selectedTags.includes(t.name)
                              ? 'border-teal-500 bg-teal-50 text-teal-700'
                              : 'border-slate-200 text-slate-500',
                          )}
                        >
                          {t.name}
                        </button>
                      ))}
                    </div>
                  </Field>
                </div>
                <div className="sm:col-span-2">
                  <Field label="备注">
                    <Input value={note} onChange={(e) => setNote(e.target.value)} />
                  </Field>
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-sm font-bold text-slate-800">代理</h3>
              <div className="mb-4 flex flex-wrap gap-2">
                {(
                  [
                    ['none', '直连'],
                    ['library', '从代理库选择'],
                    ['new', '即时新建'],
                  ] as const
                ).map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setProxyMode(mode)}
                    className={cn(
                      'rounded-lg border px-3 py-2 text-xs font-medium',
                      proxyMode === mode
                        ? 'border-teal-500 bg-teal-50 text-teal-700'
                        : 'border-slate-200 text-slate-500',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {proxyMode === 'library' ? (
                <Select value={proxyId} onChange={(e) => setProxyId(e.target.value)}>
                  <option value="">选择代理…</option>
                  {proxies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.alias} ({p.protocol}://{p.host}:{p.port})
                    </option>
                  ))}
                </Select>
              ) : null}
              {proxyMode === 'new' ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="别名">
                    <Input
                      value={newProxy.alias}
                      onChange={(e) => setNewProxy({ ...newProxy, alias: e.target.value })}
                    />
                  </Field>
                  <Field label="协议">
                    <Select
                      value={newProxy.protocol}
                      onChange={(e) =>
                        setNewProxy({
                          ...newProxy,
                          protocol: e.target.value as ProxyProtocol,
                        })
                      }
                    >
                      <option value="socks5">SOCKS5</option>
                      <option value="http">HTTP</option>
                      <option value="https">HTTPS</option>
                    </Select>
                  </Field>
                  <Field label="主机">
                    <Input
                      value={newProxy.host}
                      onChange={(e) => setNewProxy({ ...newProxy, host: e.target.value })}
                    />
                  </Field>
                  <Field label="端口">
                    <Input
                      value={newProxy.port}
                      onChange={(e) => setNewProxy({ ...newProxy, port: e.target.value })}
                    />
                  </Field>
                  <Field label="用户名">
                    <Input
                      value={newProxy.username}
                      onChange={(e) => setNewProxy({ ...newProxy, username: e.target.value })}
                    />
                  </Field>
                  <Field label="密码">
                    <Input
                      type="password"
                      value={newProxy.password}
                      onChange={(e) => setNewProxy({ ...newProxy, password: e.target.value })}
                    />
                  </Field>
                </div>
              ) : null}
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-sm font-bold text-slate-800">指纹策略</h3>
              <div className="mb-4 grid gap-3 sm:grid-cols-3">
                {(
                  [
                    ['auto', '自动随机', 'BrowserForge 默认'],
                    ['preset', '真实预设', 'fingerprint_preset'],
                    ['template', '已保存模板', '固定 config'],
                  ] as const
                ).map(([key, title, desc]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setStrategy(key)}
                    className={cn(
                      'rounded-xl border p-4 text-left',
                      strategy === key
                        ? 'border-teal-500 bg-teal-50'
                        : 'border-slate-200 hover:border-slate-300',
                    )}
                  >
                    <div className="text-sm font-semibold text-slate-800">{title}</div>
                    <div className="mt-1 text-[10px] text-slate-500">{desc}</div>
                  </button>
                ))}
              </div>
              {strategy === 'template' ? (
                <Field label="选择模板" hint="需先在指纹策略页创建并采样固化">
                  <Select
                    value={templateId}
                    onChange={(e) => setTemplateId(e.target.value)}
                  >
                    <option value="">请选择…</option>
                    {customTemplates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                        {t.hasConfig ? '' : '（未固化）'}
                      </option>
                    ))}
                    {templates
                      .filter((t) => t.kind === 'system' && t.id === 'tpl_preset')
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                  </Select>
                </Field>
              ) : null}
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <Field label="操作系统">
                  <Select value={os} onChange={(e) => setOs(e.target.value as OsChoice)}>
                    <option value="windows">Windows</option>
                    <option value="macos">macOS</option>
                    <option value="linux">Linux</option>
                  </Select>
                </Field>
                <Field label="Geo 对齐">
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      checked={alignGeo}
                      onChange={(e) => setAlignGeo(e.target.checked)}
                    />
                    启动时根据代理对齐时区 / 语言 / WebRTC
                  </label>
                </Field>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-sm font-bold text-slate-800">Cookie 与启动</h3>
              <div className="space-y-4">
                <Field label="Cookie JSON 数组" hint="粘贴 Playwright/浏览器导出的 cookies 数组">
                  <Textarea value={cookiesJson} onChange={(e) => setCookiesJson(e.target.value)} />
                </Field>
                <Field label="启动 URL（可选）">
                  <Input
                    value={startUrl}
                    onChange={(e) => setStartUrl(e.target.value)}
                    placeholder="https://…"
                  />
                </Field>
              </div>
            </section>

            {error ? <p className="text-sm text-rose-600">{error}</p> : null}

            <div className="flex flex-wrap justify-end gap-2 pb-8">
              <Link to="/profiles">
                <Button variant="ghost">放弃配置</Button>
              </Link>
              <Button variant="secondary" onClick={() => save(false)}>
                仅保存
              </Button>
              <Button onClick={() => save(true)}>保存并启动</Button>
            </div>
          </div>

          <aside className="h-fit rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:sticky lg:top-8">
            <h3 className="text-sm font-bold text-slate-800">指纹策略摘要</h3>
            <dl className="mt-4 space-y-3 text-xs text-slate-600">
              <div>
                <dt className="text-slate-400">策略</dt>
                <dd className="mt-0.5 font-medium text-slate-800">{strategyLabel}</dd>
              </div>
              <div>
                <dt className="text-slate-400">操作系统</dt>
                <dd className="mt-0.5 font-medium">{os}</dd>
              </div>
              <div>
                <dt className="text-slate-400">摘要预览</dt>
                <dd className="mt-0.5 font-mono text-[11px]">{fingerprintSummary(os)}</dd>
              </div>
              <div>
                <dt className="text-slate-400">代理 Geo</dt>
                <dd className="mt-0.5">{alignGeo ? '启动时自动对齐' : '不对齐'}</dd>
              </div>
            </dl>
            <p className="mt-4 text-[10px] leading-relaxed text-slate-400">
              启动时由 Camoufox / BrowserForge 自动生成完整指纹，无需手填 UA / Canvas。
            </p>
          </aside>
        </div>
      </main>
    </>
  )
}
