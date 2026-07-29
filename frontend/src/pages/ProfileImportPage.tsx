import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Select } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { useDataStore } from '@/stores/data'
import type { CreateProfileInput, OsChoice } from '@/types/console'
import { fingerprintSummary } from '@/types/console'

type PreviewRow = {
  name: string
  platform: string
  proxy: string
  tags: string
  cookies: string
  note: string
  ok: boolean
  error?: string
}

const CSV_TEMPLATE =
  'name,platform,proxy,tags,cookies,note\n导入测试_A,Amazon,,测试,[],示例备注\n导入测试_B,Facebook,US-SOCKS-01,主力账号,[],\n'

function parseCsv(text: string): PreviewRow[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length === 0) return []
  const start = lines[0].toLowerCase().includes('name') ? 1 : 0
  return lines.slice(start).map((line, i) => {
    // naive CSV: split on comma not inside []
    const cols: string[] = []
    let cur = ''
    let depth = 0
    for (const ch of line) {
      if (ch === '[') depth += 1
      if (ch === ']') depth = Math.max(0, depth - 1)
      if (ch === ',' && depth === 0) {
        cols.push(cur.trim())
        cur = ''
      } else {
        cur += ch
      }
    }
    cols.push(cur.trim())
    const [name, platform = '', proxy = '', tags = '', cookies = '[]', note = ''] = cols
    if (!name) {
      return {
        name: `(空行 ${i + 1})`,
        platform,
        proxy,
        tags,
        cookies,
        note,
        ok: false,
        error: '缺少名称',
      }
    }
    if (cookies) {
      try {
        const parsed = JSON.parse(cookies)
        if (!Array.isArray(parsed)) {
          return {
            name,
            platform,
            proxy,
            tags,
            cookies,
            note,
            ok: false,
            error: 'cookies 须为 JSON 数组',
          }
        }
      } catch {
        return {
          name,
          platform,
          proxy,
          tags,
          cookies,
          note,
          ok: false,
          error: 'cookies JSON 无效',
        }
      }
    }
    return { name, platform, proxy, tags, cookies: cookies || '[]', note, ok: true }
  })
}

export function ProfileImportPage() {
  const navigate = useNavigate()
  const importProfiles = useDataStore((s) => s.importProfiles)
  const proxies = useDataStore((s) => s.proxies)
  const templates = useDataStore((s) => s.templates)
  const [raw, setRaw] = useState(CSV_TEMPLATE)
  const [fpMode, setFpMode] = useState<'auto' | 'template'>('auto')
  const [filter, setFilter] = useState<'all' | 'ok' | 'bad'>('all')
  const [result, setResult] = useState<{
    ok: number
    fail: number
    errors: string[]
  } | null>(null)
  const [busy, setBusy] = useState(false)

  const rows = useMemo(() => parseCsv(raw), [raw])
  const shown = rows.filter((r) => {
    if (filter === 'ok') return r.ok
    if (filter === 'bad') return !r.ok
    return true
  })
  const okCount = rows.filter((r) => r.ok).length
  const defaultTpl = templates.find((t) => t.isDefault && t.kind === 'custom')

  const confirm = async () => {
    setBusy(true)
    setResult(null)
    const inputs: CreateProfileInput[] = rows
      .filter((r) => r.ok)
      .map((r) => {
        const px = proxies.find(
          (p) => p.alias === r.proxy || `${p.host}:${p.port}` === r.proxy,
        )
        const os: OsChoice = 'windows'
        const useTpl = fpMode === 'template'
        return {
          name: r.name,
          platform: r.platform,
          note: r.note || '批量导入',
          groupId: null,
          tags: r.tags
            ? r.tags
                .split('|')
                .map((t) => t.trim())
                .filter(Boolean)
            : [],
          proxyId: px?.id ?? null,
          proxyLabel: px
            ? `${px.protocol}://${px.host}:***`
            : r.proxy || null,
          fingerprintStrategy: useTpl ? 'template' : 'auto',
          templateId: useTpl ? defaultTpl?.id ?? 'tpl_preset' : null,
          os,
          alignGeoWithProxy: true,
          cookiesJson: r.cookies || '[]',
          startUrl: '',
          fingerprint: fingerprintSummary(os),
        }
      })
    try {
      const res = await importProfiles(inputs)
      setResult(res)
      if (res.fail === 0) {
        navigate('/profiles')
      }
    } finally {
      setBusy(false)
    }
  }

  const copyTemplate = async () => {
    await navigator.clipboard.writeText(CSV_TEMPLATE)
  }

  return (
    <>
      <TopBar title="批量导入中心" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="解析行数" value={`${rows.length}`} />
          <SummaryCard label="可导入" value={`${okCount}`} accent />
          <SummaryCard label="异常" value={`${rows.length - okCount}`} danger />
          <SummaryCard label="格式" value="CSV" hint="含 cookies 列" />
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold">CSV 内容</h3>
              <p className="mt-1 text-xs text-slate-500">
                列：name, platform, proxy, tags（| 分隔）, cookies（JSON 数组）, note
              </p>
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => void copyTemplate()}>
                复制模板
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  const blob = new Blob([CSV_TEMPLATE], { type: 'text/csv' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = 'profiles-template.csv'
                  a.click()
                  URL.revokeObjectURL(url)
                }}
              >
                下载模板
              </Button>
            </div>
          </div>
          <textarea
            className="min-h-[160px] w-full rounded-lg border border-slate-200 p-3 font-mono text-xs"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
          />
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="指纹规则">
              <Select
                value={fpMode}
                onChange={(e) => setFpMode(e.target.value as 'auto' | 'template')}
              >
                <option value="auto">全部自动随机</option>
                <option value="template">使用默认模板策略</option>
              </Select>
            </Field>
            <Field label="预览过滤">
              <Select
                value={filter}
                onChange={(e) => setFilter(e.target.value as typeof filter)}
              >
                <option value="all">全部</option>
                <option value="ok">仅正常</option>
                <option value="bad">仅异常</option>
              </Select>
            </Field>
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-3">#</th>
                <th className="p-3">校验</th>
                <th className="p-3">名称</th>
                <th className="p-3">平台</th>
                <th className="p-3">代理</th>
                <th className="p-3">标签</th>
                <th className="p-3">Cookie</th>
                <th className="p-3">异常说明</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr
                  key={`${r.name}-${i}`}
                  className={`border-t border-slate-100 ${r.ok ? '' : 'bg-rose-50/50'}`}
                >
                  <td className="p-3 font-mono text-slate-400">{i + 1}</td>
                  <td className="p-3">{r.ok ? '✓' : '✗'}</td>
                  <td className="p-3 font-medium">{r.name}</td>
                  <td className="p-3">{r.platform || '—'}</td>
                  <td className="p-3 font-mono">{r.proxy || '直连'}</td>
                  <td className="p-3">{r.tags || '—'}</td>
                  <td className="max-w-[120px] truncate p-3 font-mono">
                    {r.cookies === '[]' ? '—' : r.cookies}
                  </td>
                  <td className="p-3 text-rose-600">{r.error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {result ? (
          <section className="rounded-xl border border-slate-200 bg-white p-5 text-sm shadow-sm">
            <h3 className="font-bold">导入结果</h3>
            <p className="mt-2 text-xs text-slate-600">
              成功 {result.ok} · 失败 {result.fail}
            </p>
            {result.errors.length ? (
              <ul className="mt-2 list-inside list-disc text-xs text-rose-600">
                {result.errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        <div className="flex justify-end gap-2">
          <Link to="/profiles">
            <Button variant="ghost">取消</Button>
          </Link>
          <Button disabled={okCount === 0 || busy} onClick={() => void confirm()}>
            确认导入 {okCount} 条
          </Button>
        </div>
      </main>
    </>
  )
}
