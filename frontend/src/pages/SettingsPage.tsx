import { TopBar } from '@/components/layout/TopBar'
import { Button, Field, Input, Select } from '@/components/ui/Form'
import { useDataStore } from '@/stores/data'

export function SettingsPage() {
  const settings = useDataStore((s) => s.settings)
  const updateSettings = useDataStore((s) => s.updateSettings)

  return (
    <>
      <TopBar title="系统设置中心" />
      <main className="flex-1 space-y-6 overflow-y-auto p-8">
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold">常规</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="主题">
              <Select
                value={settings.theme}
                onChange={(e) =>
                  updateSettings({
                    theme: e.target.value as 'light' | 'dark' | 'system',
                  })
                }
              >
                <option value="light">浅色</option>
                <option value="dark">深色（预留）</option>
                <option value="system">跟随系统</option>
              </Select>
            </Field>
            <Field label="默认启动模式">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={settings.defaultHeadless}
                  onChange={(e) =>
                    updateSettings({ defaultHeadless: e.target.checked })
                  }
                />
                默认无头
              </label>
            </Field>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold">存储</h3>
          <Field label="Profile 根目录">
            <Input
              value={settings.profileRoot}
              onChange={(e) => updateSettings({ profileRoot: e.target.value })}
            />
          </Field>
          <p className="mt-2 text-xs text-slate-400">
            清理缓存、重置目录等操作将作用于此根路径下的各环境子目录。
          </p>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold">Camoufox / GeoIP</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="当前 Active 版本（只读，请到版本页切换）">
              <Input readOnly value={settings.camoufoxVersion} />
            </Field>
            <Field label="GeoIP 数据库">
              <div className="flex gap-2">
                <Input readOnly value="远程同步 mmdb（不可手动上传）" />
                <Button variant="secondary">同步</Button>
              </div>
            </Field>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-bold">Local API</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="端口">
              <Input
                type="number"
                value={settings.apiPort}
                onChange={(e) =>
                  updateSettings({ apiPort: Number(e.target.value) || 50325 })
                }
              />
            </Field>
            <Field label="服务">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={settings.apiRunning}
                  onChange={(e) => updateSettings({ apiRunning: e.target.checked })}
                />
                启用 Local API
              </label>
            </Field>
          </div>
        </section>
      </main>
    </>
  )
}
