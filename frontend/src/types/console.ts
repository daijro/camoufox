export type ProfileStatus = 'idle' | 'starting' | 'running' | 'error' | 'api'

export type FingerprintStrategy = 'auto' | 'preset' | 'template'
export type OsChoice = 'windows' | 'macos' | 'linux'
export type ProxyProtocol = 'socks5' | 'http' | 'https'

export type Group = {
  id: string
  name: string
  parentId: string | null
}

export type Tag = {
  id: string
  name: string
  color: string
}

export type Proxy = {
  id: string
  alias: string
  protocol: ProxyProtocol
  host: string
  port: number
  username?: string
  password?: string
  exitIp?: string
  country?: string
  latencyMs?: number | null
  lastCheckedAt?: string | null
  status: 'ok' | 'fail' | 'unknown'
}

export type FingerprintTemplate = {
  id: string
  name: string
  kind: 'system' | 'custom'
  os: string
  alignGeo: boolean
  webrtc: 'follow' | 'disable' | string
  usePreset: boolean
  configJson: string | null
  hasConfig: boolean
  isDefault: boolean
  createdAt: string
}

export type PlatformAccount = {
  id: string
  profileId: string
  platformUrl: string
  platformLabel: string
  username: string
  hasPassword: boolean
  hasTotp: boolean
  isActive: boolean
  autoLogin?: boolean
  autoLoginEligible?: boolean
  createdAt: string
  updatedAt: string
  password?: string | null
  totpSecret?: string | null
  totpCode?: string | null
  totpRemaining?: number
}

export type PlatformPreset = {
  label: string
  url: string
}

export type Profile = {
  id: string
  name: string
  platform: string
  note: string
  groupId: string | null
  tags: string[]
  proxyId: string | null
  /** Display string when proxy bound or custom */
  proxyLabel: string | null
  fingerprint: string
  fingerprintStrategy: FingerprintStrategy
  os: OsChoice
  alignGeoWithProxy: boolean
  cookiesJson: string
  startUrl: string
  headless: boolean
  status: ProfileStatus
  lastStartedAt: string | null
  deletedAt: string | null
  pid: number | null
  wsEndpoint: string | null
  profilePath: string
  diskMb: number
  logs: { at: string; level: string; message: string }[]
  templateId?: string | null
  lastExitIp?: string | null
  hasFingerprintConfig?: boolean
  fingerprintConfigJson?: string | null
  restoreSession?: boolean
  cpuPercent?: number | null
  memoryMb?: number | null
}

export type CreateProfileInput = {
  name: string
  platform: string
  note: string
  groupId: string | null
  tags: string[]
  proxyId: string | null
  proxyLabel: string | null
  fingerprintStrategy: FingerprintStrategy
  os: OsChoice
  alignGeoWithProxy: boolean
  cookiesJson: string
  startUrl: string
  fingerprint?: string
  templateId?: string | null
  restoreSession?: boolean
}

export function countRunning(profiles: Profile[]): number {
  return profiles.filter(
    (p) => !p.deletedAt && (p.status === 'running' || p.status === 'api'),
  ).length
}

export function nowStamp(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fingerprintSummary(os: OsChoice): string {
  const label = os === 'windows' ? 'Win' : os === 'macos' ? 'Mac' : 'Linux'
  return `${label} · FF 152 · 1920×1080`
}
