import type {
  CreateProfileInput,
  FingerprintTemplate,
  Group,
  Profile,
  Proxy,
  Tag,
} from '@/types/console'
import { apiFetch, getApiBase, isRemoteMode, useMockApi } from '@/lib/api'

export { useMockApi, getApiBase, isRemoteMode }

function authHeaders(): HeadersInit {
  const token = import.meta.env.VITE_API_TOKEN as string | undefined
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function opts(init?: RequestInit): RequestInit {
  return {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...authHeaders(),
    },
  }
}

export async function remoteHealth(): Promise<{
  ok: boolean
  realLaunch: boolean
  version: string
}> {
  return apiFetch('/api/v1/health')
}

export async function remoteSettings(): Promise<{
  apiPort: number
  apiToken: string
  apiRunning: boolean
  camoufoxVersion: string
  profileRoot: string
  theme: 'light' | 'dark' | 'system'
  defaultHeadless: boolean
  realLaunch?: boolean
  maxConcurrency?: number
}> {
  return apiFetch('/api/v1/settings', opts())
}

export async function remotePatchSettings(patch: {
  maxConcurrency?: number
  defaultHeadless?: boolean
  theme?: string
}): Promise<Awaited<ReturnType<typeof remoteSettings>>> {
  return apiFetch('/api/v1/settings', opts({
    method: 'PATCH',
    body: JSON.stringify(patch),
  }))
}

export async function remoteListProfiles(includeDeleted = false): Promise<Profile[]> {
  const q = includeDeleted ? '?include_deleted=true' : ''
  return apiFetch(`/api/v1/profiles${q}`, opts())
}

export async function remoteCreateProfile(input: CreateProfileInput): Promise<Profile> {
  return apiFetch('/api/v1/profiles', opts({
    method: 'POST',
    body: JSON.stringify(input),
  }))
}

export async function remotePatchProfile(
  id: string,
  patch: Record<string, unknown>,
): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}`, opts({
    method: 'PATCH',
    body: JSON.stringify(patch),
  }))
}

export async function remoteStartProfile(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/start`, opts({ method: 'POST' }))
}

export async function remoteStopProfile(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/stop`, opts({ method: 'POST' }))
}

export async function remoteResampleFingerprint(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/resample-fingerprint`, opts({ method: 'POST' }))
}

export async function remoteFocusProfile(id: string): Promise<{ ok: boolean; pid: number }> {
  return apiFetch(`/api/v1/profiles/${id}/focus`, opts({ method: 'POST' }))
}

export async function remoteClearCache(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/clear-cache`, opts({ method: 'POST' }))
}

export async function remoteResetProfile(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/reset-profile`, opts({ method: 'POST' }))
}

export async function remoteTrashProfile(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/trash`, opts({ method: 'POST' }))
}

export async function remoteRestoreProfile(id: string): Promise<Profile> {
  return apiFetch(`/api/v1/profiles/${id}/restore`, opts({ method: 'POST' }))
}

export async function remoteDeleteProfile(id: string): Promise<void> {
  await apiFetch(`/api/v1/profiles/${id}`, opts({ method: 'DELETE' }))
}

export async function remoteListRuntime(): Promise<
  (Profile & { cpuPercent?: number | null; memoryMb?: number | null })[]
> {
  return apiFetch('/api/v1/runtime', opts())
}

export async function remoteRuntimeStats(): Promise<{
  cpuPercent: number | null
  memoryUsedMb: number | null
  memoryTotalMb: number | null
  running: number
  maxConcurrency: number
}> {
  return apiFetch('/api/v1/runtime/stats', opts())
}

export async function remoteListProxies(): Promise<Proxy[]> {
  return apiFetch('/api/v1/proxies', opts())
}

export async function remoteCreateProxy(body: {
  alias: string
  protocol: string
  host: string
  port: number
  username?: string
  password?: string
}): Promise<Proxy> {
  return apiFetch('/api/v1/proxies', opts({
    method: 'POST',
    body: JSON.stringify(body),
  }))
}

export async function remoteCheckProxy(id: string): Promise<Proxy> {
  return apiFetch(`/api/v1/proxies/${id}/check`, opts({ method: 'POST' }))
}

export async function remoteDeleteProxy(id: string): Promise<void> {
  await apiFetch(`/api/v1/proxies/${id}`, opts({ method: 'DELETE' }))
}

export async function remoteListGroups(): Promise<Group[]> {
  return apiFetch('/api/v1/groups', opts())
}

export async function remoteCreateGroup(name: string, parentId?: string | null): Promise<Group> {
  return apiFetch('/api/v1/groups', opts({
    method: 'POST',
    body: JSON.stringify({ name, parentId: parentId ?? null }),
  }))
}

export async function remotePatchGroup(id: string, name: string): Promise<Group> {
  return apiFetch(`/api/v1/groups/${id}`, opts({
    method: 'PATCH',
    body: JSON.stringify({ name }),
  }))
}

export async function remoteDeleteGroup(id: string): Promise<void> {
  await apiFetch(`/api/v1/groups/${id}`, opts({ method: 'DELETE' }))
}

export async function remoteListTags(): Promise<Tag[]> {
  return apiFetch('/api/v1/tags', opts())
}

export async function remoteCreateTag(name: string, color: string): Promise<Tag> {
  return apiFetch('/api/v1/tags', opts({
    method: 'POST',
    body: JSON.stringify({ name, color }),
  }))
}

export async function remoteDeleteTag(id: string): Promise<void> {
  await apiFetch(`/api/v1/tags/${id}`, opts({ method: 'DELETE' }))
}

export async function remoteListTemplates(): Promise<FingerprintTemplate[]> {
  return apiFetch('/api/v1/fingerprint-templates', opts())
}

export async function remoteCreateTemplate(body: {
  name: string
  os?: string
  alignGeo?: boolean
  webrtc?: string
  usePreset?: boolean
}): Promise<FingerprintTemplate> {
  return apiFetch('/api/v1/fingerprint-templates', opts({
    method: 'POST',
    body: JSON.stringify(body),
  }))
}

export async function remoteSampleTemplate(id: string): Promise<FingerprintTemplate> {
  return apiFetch(`/api/v1/fingerprint-templates/${id}/sample`, opts({ method: 'POST' }))
}

export async function remotePatchTemplate(
  id: string,
  patch: {
    name?: string
    os?: string
    alignGeo?: boolean
    webrtc?: string
    usePreset?: boolean
    configJson?: string
  },
): Promise<FingerprintTemplate> {
  return apiFetch(`/api/v1/fingerprint-templates/${id}`, opts({
    method: 'PATCH',
    body: JSON.stringify(patch),
  }))
}

export async function remoteSetDefaultTemplate(id: string): Promise<FingerprintTemplate> {
  return apiFetch(`/api/v1/fingerprint-templates/${id}/default`, opts({ method: 'POST' }))
}

export async function remoteCopyTemplate(id: string): Promise<FingerprintTemplate> {
  return apiFetch(`/api/v1/fingerprint-templates/${id}/copy`, opts({ method: 'POST' }))
}

export async function remoteDeleteTemplate(id: string): Promise<void> {
  await apiFetch(`/api/v1/fingerprint-templates/${id}`, opts({ method: 'DELETE' }))
}

export async function remoteBrowserVersions(): Promise<{
  active: string
  installed: { version: string; path?: string | null; repo?: string | null }[]
  remote: { version: string; channel: string }[]
  note?: string
}> {
  return apiFetch('/api/v1/browser/versions', opts())
}

export async function remoteBrowserSetActive(version: string) {
  return apiFetch('/api/v1/browser/active', opts({
    method: 'POST',
    body: JSON.stringify({ version }),
  }))
}

export async function remoteBrowserRefresh() {
  return apiFetch('/api/v1/browser/refresh', opts({ method: 'POST' }))
}

export async function remoteImportProxies(text: string): Promise<{
  created: Proxy[]
  errors: { line: number; error: string; raw: string }[]
  ok: number
}> {
  return apiFetch('/api/v1/proxies/import', opts({
    method: 'POST',
    body: JSON.stringify({ text }),
  }))
}

export async function remoteListPlatformPresets(): Promise<
  import('@/types/console').PlatformPreset[]
> {
  return apiFetch('/api/v1/platform-presets', opts())
}

export async function remoteListPlatformAccounts(
  profileId: string,
): Promise<import('@/types/console').PlatformAccount[]> {
  return apiFetch(`/api/v1/profiles/${profileId}/platform-accounts`, opts())
}

export async function remoteCreatePlatformAccount(
  profileId: string,
  body: {
    platformUrl: string
    platformLabel?: string
    username?: string
    password?: string
    totpSecret?: string
    isActive?: boolean
  },
): Promise<import('@/types/console').PlatformAccount> {
  return apiFetch(`/api/v1/profiles/${profileId}/platform-accounts`, opts({
    method: 'POST',
    body: JSON.stringify(body),
  }))
}

export async function remotePatchPlatformAccount(
  profileId: string,
  accountId: string,
  body: Record<string, unknown>,
): Promise<import('@/types/console').PlatformAccount> {
  return apiFetch(
    `/api/v1/profiles/${profileId}/platform-accounts/${accountId}`,
    opts({ method: 'PATCH', body: JSON.stringify(body) }),
  )
}

export async function remoteActivatePlatformAccount(
  profileId: string,
  accountId: string,
): Promise<import('@/types/console').PlatformAccount[]> {
  return apiFetch(
    `/api/v1/profiles/${profileId}/platform-accounts/${accountId}/activate`,
    opts({ method: 'POST' }),
  )
}

export async function remoteDeletePlatformAccount(
  profileId: string,
  accountId: string,
): Promise<void> {
  await apiFetch(
    `/api/v1/profiles/${profileId}/platform-accounts/${accountId}`,
    opts({ method: 'DELETE' }),
  )
}

export type HydrateSnapshot = {
  profiles: Profile[]
  proxies: Proxy[]
  groups: Group[]
  tags: Tag[]
  templates: FingerprintTemplate[]
  settings: Awaited<ReturnType<typeof remoteSettings>>
}

export async function fetchHydrateSnapshot(): Promise<HydrateSnapshot> {
  const [profiles, proxies, groups, tags, templates, settings] = await Promise.all([
    remoteListProfiles(true),
    remoteListProxies(),
    remoteListGroups(),
    remoteListTags(),
    remoteListTemplates(),
    remoteSettings(),
  ])
  return { profiles, proxies, groups, tags, templates, settings }
}
