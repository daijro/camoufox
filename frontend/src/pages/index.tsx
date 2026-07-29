import { PlaceholderPage } from './PlaceholderPage'

export { ProfilesPage } from './ProfilesPage'
export { ProfileNewPage } from './ProfileNewPage'
export { ProfileDetailPage } from './ProfileDetailPage'
export { ProfileImportPage } from './ProfileImportPage'
export { ProfileGroupsPage } from './ProfileGroupsPage'
export { ProfileTrashPage } from './ProfileTrashPage'
export { ProxiesPage } from './ProxiesPage'
export { FingerprintsPage } from './FingerprintsPage'
export { FingerprintEditPage } from './FingerprintEditPage'
export { RuntimePage } from './RuntimePage'
export { BrowserPage } from './BrowserPage'
export { ApiPage } from './ApiPage'
export { SettingsPage } from './SettingsPage'

export function AddonsPage() {
  return (
    <PlaceholderPage
      title="插件中心"
      description="Phase 2：Firefox .xpi 插件库与全局策略。"
    />
  )
}

export function TasksPage() {
  return (
    <PlaceholderPage
      title="任务中心"
      description="Phase 2：Playwright 脚本任务与定时调度。"
    />
  )
}
