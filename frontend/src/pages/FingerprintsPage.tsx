import { TopBar } from '@/components/layout/TopBar'
import { Button } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { cn } from '@/lib/utils'

const TEMPLATES = [
  {
    id: 'tpl_auto',
    name: '自动随机（默认）',
    desc: '每次启动调用 BrowserForge generate_fingerprint()',
    kind: 'system' as const,
    os: '任意',
  },
  {
    id: 'tpl_preset',
    name: '真实设备预设采样',
    desc: 'fingerprint_preset=True，从真实指纹库采样',
    kind: 'system' as const,
    os: 'Win / Mac / Linux',
  },
  {
    id: 'tpl_win_shop',
    name: 'Win 电商稳态',
    desc: '固定 seed · 1920×1080 · 跟随代理 Geo',
    kind: 'custom' as const,
    os: 'Windows',
  },
  {
    id: 'tpl_linux_headless',
    name: 'Linux 无头采集',
    desc: '固定 seed · 无头优先 · WebRTC 禁用可选',
    kind: 'custom' as const,
    os: 'Linux',
  },
]

export function FingerprintsPage() {
  return (
    <>
      <TopBar title="指纹策略模板" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard label="模板数" value={`${TEMPLATES.length}`} />
          <SummaryCard label="系统预设" value="2" accent />
          <SummaryCard label="自定义" value="2" />
          <SummaryCard label="默认策略" value="自动随机" />
        </div>

        <div className="rounded-xl border border-teal-100 bg-teal-50/60 p-4 text-xs text-teal-800">
          Camoufox 指纹在 C++ 层注入。控制台默认推荐「自动随机」，无需手填 UA / Canvas /
          WebGL。
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          {TEMPLATES.map((t) => (
            <article
              key={t.id}
              className={cn(
                'rounded-xl border bg-white p-5 shadow-sm',
                t.kind === 'system' ? 'border-teal-200' : 'border-slate-200',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-bold text-slate-800">{t.name}</h3>
                  <p className="mt-1 text-xs text-slate-500">{t.desc}</p>
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                  {t.kind === 'system' ? '系统' : '自定义'}
                </span>
              </div>
              <p className="mt-3 text-[11px] text-slate-400">OS：{t.os}</p>
              <div className="mt-4 flex gap-2">
                <Button variant="secondary" disabled={t.kind === 'system'}>
                  编辑
                </Button>
                <Button variant="ghost">设为默认</Button>
                <Button variant="ghost">复制</Button>
              </div>
            </article>
          ))}
        </div>
      </main>
    </>
  )
}
