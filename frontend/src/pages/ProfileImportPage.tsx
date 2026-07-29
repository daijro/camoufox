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
  ok: boolean
  error?: string
}

function parseCsv(text: string): PreviewRow[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length === 0) return []
  const start = lines[0].toLowerCase().includes('name') ? 1 : 0
  return lines.slice(start).map((line, i) => {
    const cols = line.split(',').map((c) => c.trim())
    const [name, platform = '', proxy = '', tags = ''] = cols
    if (!name) {
      return {
        name: `(空行 ${i + 1})`,
        platform,
        proxy,
        tags,
        ok: false,
        error: '缺少名称',
      }
    }
    return { name, platform, proxy, tags, ok: true }
  })
}

export function ProfileImportPage() {
  const navigate = useNavigate()
  const importProfiles = useDataStore((s) => s.importProfiles)
  const proxies = useDataStore((s) => s.proxies)
  const [raw, setRaw] = useState(
    'name,platform,proxy,tags\n导入测试_A,Amazon,,测试\n导入测试_B,Facebook,US-SOCKS-01,主力账号',
  )
  const [fpMode, setFpMode] = useState<'auto' | 'template'>('auto')
  const [filter, setFilter] = useState<'all' | 'ok' | 'bad'>('all')

  const rows = useMemo(() => parseCsv(raw), [raw])
  const shown = rows.filter((r) => {
    if (filter === 'ok') return r.ok
    if (filter === 'bad') return !r.ok
    return true
  })
  const okCount = rows.filter((r) => r.ok).length

  const confirm = async () => {
    const inputs: CreateProfileInput[] = rows
      .filter((r) => r.ok)
      .map((r) => {
        const px = proxies.find(
          (p) => p.alias === r.proxy || `${p.host}:${p.port}` === r.proxy,
        )
        const os: OsChoice = 'windows'
        return {
          name: r.name,
          platform: r.platform,
          note: '批量导入',
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
          fingerprintStrategy: fpMode === 'auto' ? 'auto' : 'template',
          os,
          alignGeoWithProxy: true,
          cookiesJson: '[]',
          startUrl: '',
          fingerprint: fingerprintSummary(os),
        }
      })
    await importProfiles(inputs)
    navigate('/profiles')
  }

  return (
    <>
      <TopBar title="批量导入中心" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="解析行数" value={`${rows.length}`} />
          <SummaryCard label="可导入" value={`${okCount}`} accent />
          <SummaryCard label="异常" value={`${rows.length - okCount}`} danger />
          <SummaryCard label="限制" value="Mock" hint="≤50MB / CSV" />
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold">CSV 内容</h3>
              <p className="mt-1 text-xs text-slate-500">
                列：name, platform, proxy（别名或留空）, tags（| 分隔）
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                const blob = new Blob(
                  ['name,platform,proxy,tags\n示例环境,Amazon,,测试\n'],
                  { type: 'text/csv' },
                )
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
                <th className="p-3">异常说明</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={`${r.name}-${i}`} className="border-t border-slate-100">
                  <td className="p-3 font-mono text-slate-400">{i + 1}</td>
                  <td className="p-3">{r.ok ? '✓' : '✗'}</td>
                  <td className="p-3 font-medium">{r.name}</td>
                  <td className="p-3">{r.platform || '—'}</td>
                  <td className="p-3 font-mono">{r.proxy || '直连'}</td>
                  <td className="p-3">{r.tags || '—'}</td>
                  <td className="p-3 text-rose-600">{r.error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <div className="flex justify-end gap-2">
          <Link to="/profiles">
            <Button variant="ghost">取消</Button>
          </Link>
          <Button disabled={okCount === 0} onClick={confirm}>
            确认导入 {okCount} 条
          </Button>
        </div>
      </main>
    </>
  )
}
