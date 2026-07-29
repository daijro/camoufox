import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select, Textarea } from '@/components/ui/Form'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { cn } from '@/lib/utils'
import { useDataStore } from '@/stores/data'

const SECTIONS = [
  { id: 'basic', label: '基本信息' },
  { id: 'proxy', label: '代理' },
  { id: 'cookie', label: 'Cookie' },
  { id: 'logs', label: '运行日志' },
  { id: 'danger', label: '危险操作' },
] as const

export function ProfileDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const profile = useDataStore((s) => s.profiles.find((p) => p.id === id))
  const proxies = useDataStore((s) => s.proxies)
  const updateProfile = useDataStore((s) => s.updateProfile)
  const startProfile = useDataStore((s) => s.startProfile)
  const stopProfile = useDataStore((s) => s.stopProfile)
  const softDelete = useDataStore((s) => s.softDelete)

  const [section, setSection] = useState<(typeof SECTIONS)[number]['id']>('basic')
  const [cookies, setCookies] = useState(profile?.cookiesJson ?? '[]')
  const [cookieMsg, setCookieMsg] = useState('')
  const [proxyPick, setProxyPick] = useState(profile?.proxyId ?? '')

  const boundProxy = useMemo(
    () => proxies.find((p) => p.id === profile?.proxyId),
    [proxies, profile?.proxyId],
  )

  if (!profile || profile.deletedAt) {
    return (
      <>
        <TopBar title="环境详情" />
        <main className="flex-1 p-8">
          <p className="text-sm text-slate-500">环境不存在或已在回收站。</p>
          <Link to="/profiles" className="mt-4 inline-block text-sm text-teal-600">
            返回列表
          </Link>
        </main>
      </>
    )
  }

  const saveCookies = async () => {
    try {
      const parsed = JSON.parse(cookies)
      if (!Array.isArray(parsed)) throw new Error('not array')
      await updateProfile(profile.id, { cookiesJson: cookies })
      setCookieMsg(`已保存，共 ${parsed.length} 条`)
    } catch {
      setCookieMsg('JSON 格式无效，未保存')
    }
  }

  return (
    <>
      <TopBar title={`环境详情 · ${profile.name}`} />
      <main className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="w-56 flex-shrink-0 space-y-4 overflow-y-auto border-r border-slate-200 bg-white p-4">
          <div className="rounded-lg bg-slate-50 p-3 text-[10px] text-slate-500">
            <div className="font-medium text-slate-700">Profile 路径</div>
            <div className="mt-1 break-all font-mono">{profile.profilePath}</div>
            <div className="mt-2">占用 {profile.diskMb} MB</div>
          </div>
          <nav className="space-y-1">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSection(s.id)}
                className={cn(
                  'block w-full rounded-lg px-3 py-2 text-left text-xs font-medium',
                  section === s.id
                    ? 'bg-teal-50 text-teal-700'
                    : 'text-slate-500 hover:bg-slate-50',
                )}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </aside>

        <div className="flex-1 space-y-6 overflow-y-auto p-8">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-3">
              <StatusBadge status={profile.status} />
              <span className="font-mono text-xs text-slate-500">
                PID: {profile.pid ?? '—'}
              </span>
              {profile.wsEndpoint ? (
                <span className="max-w-xs truncate font-mono text-[10px] text-slate-400">
                  {profile.wsEndpoint}
                </span>
              ) : null}
            </div>
            <div className="flex gap-2">
              {profile.status === 'running' || profile.status === 'api' ? (
                <Button variant="danger" onClick={() => void stopProfile(profile.id)}>
                  强制停止
                </Button>
              ) : (
                <Button onClick={() => void startProfile(profile.id)}>启动</Button>
              )}
              <Button variant="secondary" disabled={!profile.pid}>
                聚焦窗口
              </Button>
            </div>
          </div>

          {section === 'basic' ? (
            <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-sm font-bold">基本信息与启动配置</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="名称">
                  <Input
                    value={profile.name}
                    onChange={(e) => void updateProfile(profile.id, { name: e.target.value })}
                  />
                </Field>
                <Field label="平台">
                  <Input
                    value={profile.platform}
                    onChange={(e) => void updateProfile(profile.id, { platform: e.target.value })}
                  />
                </Field>
                <Field label="指纹策略（只读）">
                  <Input value={`${profile.fingerprintStrategy} · ${profile.fingerprint}`} readOnly />
                </Field>
                <Field label="启动 URL">
                  <Input
                    value={profile.startUrl}
                    onChange={(e) => void updateProfile(profile.id, { startUrl: e.target.value })}
                  />
                </Field>
                <Field label="运行模式">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={profile.headless}
                      onChange={(e) =>
                        void updateProfile(profile.id, { headless: e.target.checked })
                      }
                    />
                    无头模式
                  </label>
                </Field>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  onClick={() =>
                    void updateProfile(profile.id, {
                      diskMb: Math.max(8, Math.floor(profile.diskMb * 0.5)),
                    })
                  }
                >
                  清除缓存（保留 Cookie）
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => void updateProfile(profile.id, { diskMb: 8, cookiesJson: '[]' })}
                >
                  重置 Profile 目录
                </Button>
              </div>
            </section>
          ) : null}

          {section === 'proxy' ? (
            <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-sm font-bold">代理与地理网络</h3>
              {boundProxy ? (
                <dl className="grid gap-2 text-xs sm:grid-cols-2">
                  <div>别名：{boundProxy.alias}</div>
                  <div>
                    地址：{boundProxy.protocol}://{boundProxy.host}:{boundProxy.port}
                  </div>
                  <div>出口 IP：{boundProxy.exitIp ?? '—'}</div>
                  <div>国家：{boundProxy.country ?? '—'}</div>
                  <div>延迟：{boundProxy.latencyMs ?? '—'} ms</div>
                  <div>状态：{boundProxy.status}</div>
                </dl>
              ) : (
                <p className="text-xs text-slate-500">当前直连</p>
              )}
              <Field label="更换代理">
                <Select value={proxyPick} onChange={(e) => setProxyPick(e.target.value)}>
                  <option value="">直连</option>
                  {proxies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.alias}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                onClick={() => {
                  const px = proxies.find((p) => p.id === proxyPick)
                  void updateProfile(profile.id, {
                    proxyId: proxyPick || null,
                    proxyLabel: px
                      ? `${px.protocol}://${px.host}:***`
                      : null,
                  })
                }}
              >
                保存代理绑定
              </Button>
            </section>
          ) : null}

          {section === 'cookie' ? (
            <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-sm font-bold">Cookie 凭证</h3>
              <Textarea value={cookies} onChange={(e) => setCookies(e.target.value)} rows={12} />
              {cookieMsg ? <p className="text-xs text-slate-500">{cookieMsg}</p> : null}
              <div className="flex gap-2">
                <Button onClick={saveCookies}>导入并解析保存</Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setCookies('[]')
                    void updateProfile(profile.id, { cookiesJson: '[]' })
                    setCookieMsg('已清空')
                  }}
                >
                  清空
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    const blob = new Blob([cookies], { type: 'application/json' })
                    const url = URL.createObjectURL(blob)
                    const a = document.createElement('a')
                    a.href = url
                    a.download = `${profile.id}-cookies.json`
                    a.click()
                    URL.revokeObjectURL(url)
                  }}
                >
                  导出 JSON
                </Button>
              </div>
            </section>
          ) : null}

          {section === 'logs' ? (
            <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="mb-4 text-sm font-bold">运行日志（最近）</h3>
              <ul className="space-y-2">
                {profile.logs.length === 0 ? (
                  <li className="text-xs text-slate-400">暂无日志</li>
                ) : (
                  [...profile.logs].reverse().map((l, i) => (
                    <li
                      key={`${l.at}-${i}`}
                      className="flex gap-3 rounded-lg bg-slate-50 px-3 py-2 font-mono text-[11px]"
                    >
                      <span className="text-slate-400">{l.at}</span>
                      <span
                        className={
                          l.level === 'error' ? 'text-rose-600' : 'text-teal-700'
                        }
                      >
                        [{l.level}]
                      </span>
                      <span className="text-slate-700">{l.message}</span>
                    </li>
                  ))
                )}
              </ul>
            </section>
          ) : null}

          {section === 'danger' ? (
            <section className="rounded-xl border border-rose-200 bg-rose-50 p-6">
              <h3 className="text-sm font-bold text-rose-800">危险操作</h3>
              <p className="mt-2 text-xs text-rose-700">
                将环境移入回收站（软删除）。可在回收站恢复或彻底删除。
              </p>
              <Button
                variant="danger"
                className="mt-4"
                onClick={() => {
                  void softDelete(profile.id).then(() => navigate('/profiles/trash'))
                }}
              >
                扔进回收站
              </Button>
            </section>
          ) : null}
        </div>
      </main>
    </>
  )
}
