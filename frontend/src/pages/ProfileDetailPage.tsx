import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select, Textarea } from '@/components/ui/Form'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { isRemoteMode } from '@/lib/api'
import { cn } from '@/lib/utils'
import * as remote from '@/services/remote'
import type { PlatformAccount, PlatformPreset } from '@/types/console'
import { useDataStore } from '@/stores/data'

const SECTIONS = [
  { id: 'basic', label: '基本信息' },
  { id: 'accounts', label: '平台账号' },
  { id: 'proxy', label: '代理' },
  { id: 'cookie', label: 'Cookie' },
  { id: 'logs', label: '运行日志' },
  { id: 'danger', label: '危险操作' },
] as const

export function ProfileDetailPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const profile = useDataStore((s) => s.profiles.find((p) => p.id === id))
  const proxies = useDataStore((s) => s.proxies)
  const updateProfile = useDataStore((s) => s.updateProfile)
  const startProfile = useDataStore((s) => s.startProfile)
  const stopProfile = useDataStore((s) => s.stopProfile)
  const softDelete = useDataStore((s) => s.softDelete)

  const initialSection = (searchParams.get('tab') as (typeof SECTIONS)[number]['id']) || 'basic'
  const [section, setSection] = useState<(typeof SECTIONS)[number]['id']>(
    SECTIONS.some((s) => s.id === initialSection) ? initialSection : 'basic',
  )
  const [cookies, setCookies] = useState(profile?.cookiesJson ?? '[]')
  const [cookieMsg, setCookieMsg] = useState('')
  const [proxyPick, setProxyPick] = useState(profile?.proxyId ?? '')

  const [accounts, setAccounts] = useState<PlatformAccount[]>([])
  const [presets, setPresets] = useState<PlatformPreset[]>([])
  const [accMsg, setAccMsg] = useState('')
  const [form, setForm] = useState({
    platformUrl: '',
    platformLabel: '',
    username: '',
    password: '',
    totpSecret: '',
    isActive: true,
  })

  const boundProxy = useMemo(
    () => proxies.find((p) => p.id === profile?.proxyId),
    [proxies, profile?.proxyId],
  )

  const reloadAccounts = async () => {
    if (!profile || !isRemoteMode()) {
      setAccounts([])
      return
    }
    try {
      setAccounts(await remote.remoteListPlatformAccounts(profile.id))
    } catch (e) {
      setAccMsg(e instanceof Error ? e.message : String(e))
    }
  }

  useEffect(() => {
    if (section === 'accounts' && profile && isRemoteMode()) {
      void reloadAccounts()
      void remote.remoteListPlatformPresets().then(setPresets).catch(() => setPresets([]))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, profile?.id])

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

  const createAccount = async () => {
    const label = form.platformLabel.trim()
    if (!isRemoteMode()) {
      setAccMsg('本地 mock 模式不支持平台账号，请配置 VITE_API_BASE')
      return
    }
    if (!form.platformUrl.trim()) {
      setAccMsg('请填写或选择平台 URL')
      return
    }
    try {
      await remote.remoteCreatePlatformAccount(profile.id, {
        platformUrl: form.platformUrl.trim(),
        platformLabel: label,
        username: form.username.trim(),
        password: form.password,
        totpSecret: form.totpSecret.trim(),
        isActive: form.isActive,
      })
      setForm({
        platformUrl: '',
        platformLabel: '',
        username: '',
        password: '',
        totpSecret: '',
        isActive: true,
      })
      setAccMsg('已添加')
      await reloadAccounts()
      if (label) {
        void updateProfile(profile.id, { platform: label })
      }
    } catch (e) {
      setAccMsg(e instanceof Error ? e.message : String(e))
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
            </div>
            <div className="flex gap-2">
              {(profile.status === 'running' || profile.status === 'api') && !profile.headless ? (
                <Button
                  variant="secondary"
                  disabled={!isRemoteMode() || !profile.pid}
                  onClick={() => {
                    void remote
                      .remoteFocusProfile(profile.id)
                      .catch((e) =>
                        window.alert(e instanceof Error ? e.message : String(e)),
                      )
                  }}
                >
                  聚焦窗口
                </Button>
              ) : null}
              {profile.status === 'running' || profile.status === 'api' ? (
                <Button variant="danger" onClick={() => void stopProfile(profile.id)}>
                  强制停止
                </Button>
              ) : (
                <Button onClick={() => void startProfile(profile.id)}>启动</Button>
              )}
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
                <Field label="平台（展示用）">
                  <Input
                    value={profile.platform}
                    onChange={(e) => void updateProfile(profile.id, { platform: e.target.value })}
                  />
                </Field>
                <Field label="指纹摘要">
                  <Input
                    value={`${profile.fingerprintStrategy} · ${profile.fingerprint}`}
                    readOnly
                  />
                </Field>
                <Field label="指纹锁定">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span
                      className={
                        profile.hasFingerprintConfig
                          ? 'rounded bg-teal-50 px-2 py-1 text-teal-700'
                          : 'rounded bg-amber-50 px-2 py-1 text-amber-700'
                      }
                    >
                      {profile.hasFingerprintConfig ? '已锁定（启停不变）' : '未锁定（首次启动将采样锁定）'}
                    </span>
                    <Button
                      variant="secondary"
                      disabled={
                        !isRemoteMode() ||
                        profile.status === 'running' ||
                        profile.status === 'starting' ||
                        profile.status === 'api'
                      }
                      onClick={() => {
                        if (
                          !window.confirm(
                            '重新采样会更换本环境设备指纹（WebGL/UA 等），登录风控可能受影响。确定？',
                          )
                        ) {
                          return
                        }
                        void remote
                          .remoteResampleFingerprint(profile.id)
                          .then((p) => useDataStore.getState().upsertProfile(p))
                          .catch((e) =>
                            window.alert(e instanceof Error ? e.message : String(e)),
                          )
                      }}
                    >
                      重新采样指纹
                    </Button>
                  </div>
                </Field>
                <Field label="启动 URL（关闭会话恢复时可用）">
                  <Input
                    value={profile.startUrl}
                    onChange={(e) => void updateProfile(profile.id, { startUrl: e.target.value })}
                  />
                </Field>
                <Field label="会话与运行模式">
                  <div className="space-y-2 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={profile.restoreSession !== false}
                        onChange={(e) =>
                          void updateProfile(profile.id, {
                            restoreSession: e.target.checked,
                          })
                        }
                      />
                      恢复上次会话（标签页）
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={profile.headless}
                        onChange={(e) =>
                          void updateProfile(profile.id, { headless: e.target.checked })
                        }
                      />
                      无头模式
                    </label>
                  </div>
                </Field>
              </div>
              <Field label="备注">
                <Textarea
                  value={profile.note}
                  onChange={(e) => void updateProfile(profile.id, { note: e.target.value })}
                  rows={3}
                />
              </Field>
              <p className="text-[11px] text-slate-400">
                Cookie JSON 仅在 Profile 尚无 cookies.sqlite 时注入；已有站点登录态不会被覆盖。
              </p>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => setSection('accounts')}>
                  管理平台账号
                </Button>
                <Button
                  variant="secondary"
                  disabled={
                    !isRemoteMode() ||
                    profile.status === 'running' ||
                    profile.status === 'starting' ||
                    profile.status === 'api'
                  }
                  onClick={() => {
                    void remote
                      .remoteClearCache(profile.id)
                      .then((p) => useDataStore.getState().upsertProfile(p))
                      .catch((e) =>
                        window.alert(e instanceof Error ? e.message : String(e)),
                      )
                  }}
                >
                  清除缓存（保留 Cookie）
                </Button>
              </div>
            </section>
          ) : null}

          {section === 'accounts' ? (
            <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-sm font-bold">平台账号 / 当前服务</h3>
              <p className="text-xs text-slate-500">
                启动时使用「当前」账号打开 Console Home（IP / 指纹 / TOTP）。自动登录下期再做。
              </p>
              {!isRemoteMode() ? (
                <p className="text-xs text-amber-700">需要连接 Local API（VITE_API_BASE）</p>
              ) : null}

              <div className="overflow-hidden rounded-lg border border-slate-100">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="p-2">平台</th>
                      <th className="p-2">账号</th>
                      <th className="p-2">2FA</th>
                      <th className="p-2">状态</th>
                      <th className="p-2 text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accounts.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="p-4 text-slate-400">
                          暂无平台账号
                        </td>
                      </tr>
                    ) : (
                      accounts.map((a) => (
                        <tr key={a.id} className="border-t border-slate-100">
                          <td className="p-2">
                            <div className="font-medium text-slate-700">
                              {a.platformLabel || '—'}
                            </div>
                            <div className="max-w-xs truncate font-mono text-[10px] text-slate-400">
                              {a.platformUrl}
                            </div>
                          </td>
                          <td className="p-2 font-mono">{a.username || '—'}</td>
                          <td className="p-2">{a.hasTotp ? '已配置' : '—'}</td>
                          <td className="p-2">
                            {a.isActive ? (
                              <span className="rounded bg-teal-50 px-1.5 py-0.5 text-teal-700">
                                当前
                              </span>
                            ) : (
                              '—'
                            )}
                            {a.autoLoginEligible ? (
                              <div className="mt-1">
                                <label className="flex items-center gap-1 text-[10px] text-slate-500">
                                  <input
                                    type="checkbox"
                                    checked={a.autoLogin !== false}
                                    onChange={(e) =>
                                      void remote
                                        .remotePatchPlatformAccount(profile.id, a.id, {
                                          autoLogin: e.target.checked,
                                        })
                                        .then(() => reloadAccounts())
                                    }
                                  />
                                  允许自动登录
                                </label>
                              </div>
                            ) : null}
                          </td>
                          <td className="space-x-1 whitespace-nowrap p-2 text-right">
                            {!a.isActive ? (
                              <Button
                                variant="secondary"
                                onClick={() =>
                                  void remote
                                    .remoteActivatePlatformAccount(profile.id, a.id)
                                    .then(setAccounts)
                                }
                              >
                                设为当前
                              </Button>
                            ) : null}
                            <Button
                              variant="danger"
                              onClick={() =>
                                void remote
                                  .remoteDeletePlatformAccount(profile.id, a.id)
                                  .then(() => reloadAccounts())
                              }
                            >
                              删除
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <div className="grid gap-3 rounded-lg border border-dashed border-slate-200 p-4 sm:grid-cols-2">
                <Field label="选择预置平台">
                  <Select
                    value=""
                    onChange={(e) => {
                      const p = presets.find((x) => x.url === e.target.value)
                      if (p) {
                        setForm((f) => ({
                          ...f,
                          platformUrl: p.url,
                          platformLabel: p.label,
                        }))
                      }
                    }}
                  >
                    <option value="">请输入或选择平台网址</option>
                    {presets.map((p) => (
                      <option key={p.url} value={p.url}>
                        {p.label} · {p.url}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="平台 URL">
                  <Input
                    value={form.platformUrl}
                    onChange={(e) => setForm({ ...form, platformUrl: e.target.value })}
                    placeholder="https://..."
                  />
                </Field>
                <Field label="平台名称">
                  <Input
                    value={form.platformLabel}
                    onChange={(e) => setForm({ ...form, platformLabel: e.target.value })}
                  />
                </Field>
                <Field label="账号">
                  <Input
                    value={form.username}
                    onChange={(e) => setForm({ ...form, username: e.target.value })}
                  />
                </Field>
                <Field label="密码">
                  <Input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                  />
                </Field>
                <Field label="2FA 密钥">
                  <Input
                    value={form.totpSecret}
                    onChange={(e) => setForm({ ...form, totpSecret: e.target.value })}
                    placeholder="Base32 secret"
                  />
                </Field>
                <label className="flex items-center gap-2 text-sm sm:col-span-2">
                  <input
                    type="checkbox"
                    checked={form.isActive}
                    onChange={(e) => setForm({ ...form, isActive: e.target.checked })}
                  />
                  设为当前服务
                </label>
                <div className="sm:col-span-2">
                  <Button onClick={() => void createAccount()}>添加平台账号</Button>
                  {accMsg ? <span className="ml-3 text-xs text-slate-500">{accMsg}</span> : null}
                </div>
              </div>
            </section>
          ) : null}

          {section === 'proxy' ? (
            <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-sm font-bold">代理</h3>
              {boundProxy ? (
                <p className="text-xs text-slate-500">
                  当前：{boundProxy.alias} · {boundProxy.host}:{boundProxy.port} ·{' '}
                  {boundProxy.status}
                </p>
              ) : (
                <p className="text-xs text-slate-400">未绑定代理（直连）</p>
              )}
              <Field label="选择代理">
                <Select value={proxyPick} onChange={(e) => setProxyPick(e.target.value)}>
                  <option value="">直连</option>
                  {proxies.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.alias} ({p.host}:{p.port})
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                onClick={() => {
                  const px = proxies.find((p) => p.id === proxyPick)
                  void updateProfile(profile.id, {
                    proxyId: proxyPick || null,
                    proxyLabel: px ? `${px.protocol}://${px.host}:***` : null,
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
                <Button onClick={() => void saveCookies()}>导入并解析保存</Button>
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
                      <span className={l.level === 'error' ? 'text-rose-600' : 'text-teal-700'}>
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
            <section className="space-y-6 rounded-xl border border-rose-200 bg-rose-50 p-6">
              <div>
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
              </div>
              <div className="border-t border-rose-200 pt-4">
                <h4 className="text-sm font-bold text-rose-800">重置 Profile 目录</h4>
                <p className="mt-2 text-xs text-rose-700">
                  清空磁盘上的 Profile 目录并重建空目录。保留数据库中的指纹锁定、代理绑定与平台账号；Cookie
                  JSON 清空。须先停止环境。
                </p>
                <Button
                  variant="danger"
                  className="mt-4"
                  disabled={
                    !isRemoteMode() ||
                    profile.status === 'running' ||
                    profile.status === 'starting' ||
                    profile.status === 'api'
                  }
                  onClick={() => {
                    if (
                      !window.confirm(
                        '确定重置 Profile 目录？站点登录态与缓存将被清空，指纹锁定会保留。',
                      )
                    ) {
                      return
                    }
                    void remote
                      .remoteResetProfile(profile.id)
                      .then((p) => {
                        useDataStore.getState().upsertProfile(p)
                        setCookies('[]')
                      })
                      .catch((e) =>
                        window.alert(e instanceof Error ? e.message : String(e)),
                      )
                  }}
                >
                  重置 Profile 目录
                </Button>
              </div>
            </section>
          ) : null}
        </div>
      </main>
    </>
  )
}
