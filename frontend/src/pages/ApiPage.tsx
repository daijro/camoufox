import { useState } from 'react'
import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input } from '@/components/ui/Form'
import { SummaryCard } from '@/components/ui/SummaryCard'
import { useDataStore } from '@/stores/data'

const SAMPLE_LOGS = [
  { at: '14:32:01', method: 'POST', path: '/api/v1/profiles/prof_82943558/start', status: 200 },
  { at: '14:31:12', method: 'GET', path: '/api/v1/profiles', status: 200 },
  { at: '14:28:44', method: 'POST', path: '/api/v1/proxies/check', status: 200 },
  { at: '14:20:03', method: 'GET', path: '/api/v1/runtime', status: 200 },
]

export function ApiPage() {
  const settings = useDataStore((s) => s.settings)
  const updateSettings = useDataStore((s) => s.updateSettings)
  const [port, setPort] = useState(String(settings.apiPort))
  const [copied, setCopied] = useState(false)

  const base = `http://127.0.0.1:${settings.apiPort}`

  return (
    <>
      <TopBar title="本地 API 管理中心" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard
            label="服务状态"
            value={settings.apiRunning ? '运行中' : '已停止'}
            accent={settings.apiRunning}
          />
          <SummaryCard label="监听" value={`:${settings.apiPort}`} />
          <SummaryCard label="协议" value="REST" hint="Playwright via WS" />
          <SummaryCard label="Token" value="已启用" />
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold">服务配置</h3>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="端口">
              <Input value={port} onChange={(e) => setPort(e.target.value)} />
            </Field>
            <Field label="API Token">
              <div className="flex gap-2">
                <Input readOnly value={settings.apiToken} className="font-mono text-xs" />
                <Button
                  variant="secondary"
                  onClick={() => {
                    void navigator.clipboard.writeText(settings.apiToken)
                    setCopied(true)
                    setTimeout(() => setCopied(false), 1200)
                  }}
                >
                  {copied ? '已复制' : '复制'}
                </Button>
              </div>
            </Field>
            <div className="flex items-end gap-2">
              <Button
                variant="secondary"
                onClick={() =>
                  updateSettings({
                    apiToken: `cf_dev_${Math.random().toString(36).slice(2, 10)}`,
                  })
                }
              >
                重置 Token
              </Button>
              <Button
                onClick={() =>
                  updateSettings({
                    apiPort: Number(port) || 50325,
                    apiRunning: true,
                  })
                }
              >
                保存并重启
              </Button>
              <Button
                variant="danger"
                onClick={() => updateSettings({ apiRunning: !settings.apiRunning })}
              >
                {settings.apiRunning ? '停止' : '启动'}
              </Button>
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-3 text-sm font-bold">Playwright 接入示例</h3>
          <pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 font-mono text-[11px] leading-relaxed text-teal-100">{`# REST 启停
curl -H "Authorization: Bearer ${settings.apiToken}" \\
  -X POST ${base}/api/v1/profiles/{id}/start

# Playwright 连接返回的 WebSocket 端点
from playwright.async_api import async_playwright
async with async_playwright() as p:
    browser = await p.firefox.connect_over_cdp(ws_endpoint)
    # 注意：Camoufox 走 Juggler/Playwright，不支持 Selenium / 裸 CDP 作为一等公民
`}</pre>
          <p className="mt-3 text-xs text-slate-500">
            Selenium / 原生 CDP 标注为不支持。自动化请使用 Playwright。
          </p>
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-4 py-3 text-sm font-bold">
            最近请求（示意）
          </div>
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-3">时间</th>
                <th className="p-3">方法</th>
                <th className="p-3">路径</th>
                <th className="p-3">状态</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_LOGS.map((l) => (
                <tr key={`${l.at}-${l.path}`} className="border-t border-slate-100">
                  <td className="p-3 font-mono">{l.at}</td>
                  <td className="p-3 font-semibold">{l.method}</td>
                  <td className="p-3 font-mono text-slate-600">{l.path}</td>
                  <td className="p-3 text-teal-600">{l.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </>
  )
}
