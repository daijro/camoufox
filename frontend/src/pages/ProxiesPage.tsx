import { useState } from 'react'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select } from '@/components/ui/Form'
import { Drawer } from '@/components/ui/Drawer'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { useDataStore } from '@/stores/data'
import type { Proxy, ProxyProtocol } from '@/types/console'

export function ProxiesPage() {
  const proxies = useDataStore((s) => s.proxies)
  const profiles = useDataStore((s) => s.profiles)
  const addProxy = useDataStore((s) => s.addProxy)
  const removeProxy = useDataStore((s) => s.removeProxy)
  const checkProxy = useDataStore((s) => s.checkProxy)

  const [drawerId, setDrawerId] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [bulk, setBulk] = useState('')
  const [bulkMsg, setBulkMsg] = useState('')
  const importProxiesText = useDataStore((s) => s.importProxiesText)
  const [form, setForm] = useState({
    alias: '',
    protocol: 'socks5' as ProxyProtocol,
    host: '',
    port: '1080',
    username: '',
    password: '',
  })

  const filtered = proxies.filter(
    (p) =>
      !q.trim() ||
      p.alias.toLowerCase().includes(q.toLowerCase()) ||
      p.host.includes(q) ||
      (p.exitIp?.includes(q) ?? false),
  )
  const ok = proxies.filter((p) => p.status === 'ok').length
  const fail = proxies.filter((p) => p.status === 'fail').length
  const avg =
    proxies.filter((p) => p.latencyMs != null).reduce((s, p) => s + (p.latencyMs ?? 0), 0) /
      Math.max(1, proxies.filter((p) => p.latencyMs != null).length) || 0

  const boundCount = (id: string) =>
    profiles.filter((p) => !p.deletedAt && p.proxyId === id).length

  const drawer: Proxy | undefined = proxies.find((p) => p.id === drawerId)

  return (
    <>
      <TopBar title="代理管理中心" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="可用比" value={`${ok}/${proxies.length}`} accent />
          <SummaryCard label="平均延迟" value={`${Math.round(avg)} ms`} />
          <SummaryCard label="正常" value={`${ok}`} />
          <SummaryCard label="异常" value={`${fail}`} danger />
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold">新建代理</h3>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Field label="别名">
              <Input
                value={form.alias}
                onChange={(e) => setForm({ ...form, alias: e.target.value })}
              />
            </Field>
            <Field label="协议">
              <Select
                value={form.protocol}
                onChange={(e) =>
                  setForm({ ...form, protocol: e.target.value as ProxyProtocol })
                }
              >
                <option value="socks5">SOCKS5</option>
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
              </Select>
            </Field>
            <Field label="主机">
              <Input
                value={form.host}
                onChange={(e) => setForm({ ...form, host: e.target.value })}
              />
            </Field>
            <Field label="端口">
              <Input
                value={form.port}
                onChange={(e) => setForm({ ...form, port: e.target.value })}
              />
            </Field>
            <Field label="用户名">
              <Input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </Field>
            <div className="flex items-end">
              <Button
                className="w-full"
                onClick={() => {
                  if (!form.host || !form.port) return
                  void (async () => {
                    const created = await addProxy({
                      alias: form.alias || `${form.host}:${form.port}`,
                      protocol: form.protocol,
                      host: form.host,
                      port: Number(form.port),
                      username: form.username || undefined,
                      password: form.password || undefined,
                      status: 'unknown',
                    })
                    await checkProxy(created.id)
                    setForm({
                      alias: '',
                      protocol: 'socks5',
                      host: '',
                      port: '1080',
                      username: '',
                      password: '',
                    })
                  })()
                }}
              >
                添加并检测
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-2 text-sm font-bold">批量粘贴导入</h3>
          <p className="mb-3 text-[11px] text-slate-500">
            每行：host:port 或 host:port:user:pass 或 socks5://user:pass@host:port
          </p>
          <textarea
            className="min-h-[88px] w-full rounded-lg border border-slate-200 p-3 font-mono text-xs"
            value={bulk}
            onChange={(e) => setBulk(e.target.value)}
          />
          <div className="mt-3 flex items-center gap-3">
            <Button
              variant="secondary"
              onClick={() =>
                void (async () => {
                  try {
                    const res = await importProxiesText(bulk)
                    setBulkMsg(`导入 ${res.ok} 条` + (res.errors.length ? `，失败 ${res.errors.length}` : ''))
                    if (res.ok) setBulk('')
                  } catch (e) {
                    setBulkMsg(e instanceof Error ? e.message : String(e))
                  }
                })()
              }
            >
              导入
            </Button>
            {bulkMsg ? <span className="text-xs text-slate-500">{bulkMsg}</span> : null}
          </div>
        </section>

        <div className="flex items-center justify-between gap-3">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索别名 / 出口 IP / 地址…"
            className="w-80 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
          />
          <Button
            variant="secondary"
            onClick={() => void Promise.all(proxies.map((p) => checkProxy(p.id)))}
          >
            批量检测
          </Button>
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-3">别名</th>
                <th className="p-3">协议</th>
                <th className="p-3">连接地址</th>
                <th className="p-3">出口 IP</th>
                <th className="p-3">国家</th>
                <th className="p-3">延迟</th>
                <th className="p-3">关联环境</th>
                <th className="p-3">检测时间</th>
                <th className="p-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.id} className="border-t border-slate-100">
                  <td className="p-3 font-semibold">{p.alias}</td>
                  <td className="p-3 uppercase">{p.protocol}</td>
                  <td className="p-3 font-mono">
                    {p.host}:***
                  </td>
                  <td className="p-3 font-mono">{p.exitIp ?? '—'}</td>
                  <td className="p-3">{p.country ?? '—'}</td>
                  <td className="p-3">
                    {p.latencyMs != null ? `${p.latencyMs} ms` : '—'}
                  </td>
                  <td className="p-3">{boundCount(p.id)}</td>
                  <td className="p-3 font-mono text-slate-400">
                    {p.lastCheckedAt ?? '—'}
                  </td>
                  <td className="space-x-1 p-3 text-right">
                    <Button variant="secondary" onClick={() => void checkProxy(p.id)}>
                      检测
                    </Button>
                    <Button variant="ghost" onClick={() => setDrawerId(p.id)}>
                      详情
                    </Button>
                    <Button
                      variant="danger"
                      onClick={() =>
                        void (async () => {
                          try {
                            await removeProxy(p.id)
                          } catch (e) {
                            window.alert(e instanceof Error ? e.message : String(e))
                          }
                        })()
                      }
                    >
                      删除
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>

      <Drawer
        open={!!drawer}
        title={drawer ? `代理 · ${drawer.alias}` : ''}
        onClose={() => setDrawerId(null)}
      >
        {drawer ? (
          <dl className="space-y-3 text-xs text-slate-600">
            <div>
              <dt className="text-slate-400">完整地址</dt>
              <dd className="font-mono">
                {drawer.protocol}://{drawer.host}:{drawer.port}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400">状态</dt>
              <dd>{drawer.status}</dd>
            </div>
            <div>
              <dt className="text-slate-400">绑定环境数</dt>
              <dd>{boundCount(drawer.id)}</dd>
            </div>
          </dl>
        ) : null}
      </Drawer>
    </>
  )
}
