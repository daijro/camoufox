import { create } from 'zustand'
import { isRemoteMode } from '@/lib/api'
import * as remote from '@/services/remote'
import {
  countRunning,
  fingerprintSummary,
  nowStamp,
  type CreateProfileInput,
  type FingerprintTemplate,
  type Group,
  type Profile,
  type ProfileStatus,
  type Proxy,
  type Tag,
} from '@/types/console'

function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`
}

const INITIAL_GROUPS: Group[] = [
  { id: 'grp_main', name: '主力账号', parentId: null },
  { id: 'grp_test', name: '测试', parentId: null },
  { id: 'grp_auto', name: '自动化', parentId: null },
]

const INITIAL_TAGS: Tag[] = [
  { id: 'tag_main', name: '主力账号', color: '#0d9488' },
  { id: 'tag_test', name: '测试实例', color: '#64748b' },
  { id: 'tag_auto', name: '自动化', color: '#4f46e5' },
]

const INITIAL_PROXIES: Proxy[] = [
  {
    id: 'px_1',
    alias: 'US-SOCKS-01',
    protocol: 'socks5',
    host: '192.168.1.20',
    port: 1080,
    exitIp: '104.28.***.**',
    country: 'US',
    latencyMs: 86,
    lastCheckedAt: nowStamp(),
    status: 'ok',
  },
  {
    id: 'px_2',
    alias: 'EU-HTTP-03',
    protocol: 'http',
    host: '103.45.22.11',
    port: 8080,
    exitIp: '185.12.***.**',
    country: 'DE',
    latencyMs: 142,
    lastCheckedAt: nowStamp(),
    status: 'ok',
  },
  {
    id: 'px_3',
    alias: 'ASIA-FAIL',
    protocol: 'socks5',
    host: '45.56.99.8',
    port: 1080,
    latencyMs: null,
    lastCheckedAt: nowStamp(),
    status: 'fail',
  },
]

const INITIAL_PROFILES: Profile[] = [
  {
    id: 'prof_82943558',
    name: '亚马逊店铺_US01',
    platform: 'Amazon',
    note: '',
    groupId: 'grp_main',
    tags: ['主力账号'],
    proxyId: 'px_1',
    proxyLabel: 'socks5://192.168.1.***:1080',
    fingerprint: 'Win · FF 152 · 1920×1080',
    fingerprintStrategy: 'auto',
    os: 'windows',
    alignGeoWithProxy: true,
    cookiesJson: '[]',
    startUrl: 'https://www.amazon.com',
    headless: false,
    status: 'running',
    lastStartedAt: '2026-07-29 14:32',
    deletedAt: null,
    pid: 18432,
    wsEndpoint: 'ws://127.0.0.1:9222/devtools/browser/abc',
    profilePath: 'D:/camoufox-profiles/prof_82943558',
    diskMb: 420,
    logs: [
      { at: '2026-07-29 14:32', level: 'info', message: '浏览器启动成功' },
      { at: '2026-07-29 14:32', level: 'info', message: '指纹注入完成 (BrowserForge)' },
    ],
  },
  {
    id: 'prof_82943559',
    name: '脸书投放_03',
    platform: 'Facebook',
    note: '',
    groupId: 'grp_test',
    tags: ['测试实例'],
    proxyId: 'px_2',
    proxyLabel: 'http://103.45.22.***:8080',
    fingerprint: 'Mac · FF 152 · 1440×900',
    fingerprintStrategy: 'preset',
    os: 'macos',
    alignGeoWithProxy: true,
    cookiesJson: '[]',
    startUrl: '',
    headless: false,
    status: 'starting',
    lastStartedAt: '2026-07-29 14:35',
    deletedAt: null,
    pid: null,
    wsEndpoint: null,
    profilePath: 'D:/camoufox-profiles/prof_82943559',
    diskMb: 88,
    logs: [{ at: '2026-07-29 14:35', level: 'info', message: '正在启动…' }],
  },
  {
    id: 'prof_82943560',
    name: '测试环境_直连',
    platform: '常规浏览',
    note: '直连调试',
    groupId: 'grp_test',
    tags: ['测试'],
    proxyId: null,
    proxyLabel: null,
    fingerprint: 'Linux · FF 152 · 1920×1080',
    fingerprintStrategy: 'auto',
    os: 'linux',
    alignGeoWithProxy: false,
    cookiesJson: '[]',
    startUrl: '',
    headless: false,
    status: 'error',
    lastStartedAt: '2026-07-28 16:20',
    deletedAt: null,
    pid: null,
    wsEndpoint: null,
    profilePath: 'D:/camoufox-profiles/prof_82943560',
    diskMb: 210,
    logs: [
      { at: '2026-07-28 16:20', level: 'error', message: '启动失败: 端口占用' },
    ],
  },
  {
    id: 'prof_82943561',
    name: '美国特卖_店铺02',
    platform: 'eBay',
    note: '',
    groupId: 'grp_main',
    tags: ['主力账号'],
    proxyId: 'px_1',
    proxyLabel: 'socks5://185.120.33.***:9090',
    fingerprint: 'Win · FF 152 · 1920×1080',
    fingerprintStrategy: 'auto',
    os: 'windows',
    alignGeoWithProxy: true,
    cookiesJson: '[]',
    startUrl: '',
    headless: false,
    status: 'error',
    lastStartedAt: '2026-07-28 09:12',
    deletedAt: null,
    pid: null,
    wsEndpoint: null,
    profilePath: 'D:/camoufox-profiles/prof_82943561',
    diskMb: 156,
    logs: [],
  },
  {
    id: 'prof_82943562',
    name: '爬虫自动化_01',
    platform: '数据采集',
    note: '',
    groupId: 'grp_auto',
    tags: ['自动化'],
    proxyId: 'px_3',
    proxyLabel: 'socks5://45.56.99.***:1080',
    fingerprint: 'Linux · FF 152 · 1920×1080',
    fingerprintStrategy: 'template',
    os: 'linux',
    alignGeoWithProxy: true,
    cookiesJson: '[]',
    startUrl: '',
    headless: true,
    status: 'api',
    lastStartedAt: '2026-07-29 10:05',
    deletedAt: null,
    pid: 20111,
    wsEndpoint: 'ws://127.0.0.1:9223/devtools/browser/def',
    profilePath: 'D:/camoufox-profiles/prof_82943562',
    diskMb: 640,
    logs: [{ at: '2026-07-29 10:05', level: 'info', message: 'Playwright 已连接' }],
  },
  {
    id: 'prof_82943563',
    name: '闲置账号_EU',
    platform: 'Amazon',
    note: '',
    groupId: 'grp_main',
    tags: [],
    proxyId: 'px_2',
    proxyLabel: 'http://88.12.44.***:3128',
    fingerprint: 'Win · FF 152 · 1920×1080',
    fingerprintStrategy: 'auto',
    os: 'windows',
    alignGeoWithProxy: true,
    cookiesJson: '[]',
    startUrl: '',
    headless: false,
    status: 'idle',
    lastStartedAt: null,
    deletedAt: null,
    pid: null,
    wsEndpoint: null,
    profilePath: 'D:/camoufox-profiles/prof_82943563',
    diskMb: 32,
    logs: [],
  },
]

const INITIAL_TEMPLATES: FingerprintTemplate[] = [
  {
    id: 'tpl_auto',
    name: '自动随机（默认）',
    kind: 'system',
    os: 'any',
    alignGeo: true,
    webrtc: 'follow',
    usePreset: false,
    configJson: null,
    hasConfig: false,
    isDefault: true,
    createdAt: nowStamp(),
  },
  {
    id: 'tpl_preset',
    name: '真实设备预设采样',
    kind: 'system',
    os: 'any',
    alignGeo: true,
    webrtc: 'follow',
    usePreset: true,
    configJson: null,
    hasConfig: false,
    isDefault: false,
    createdAt: nowStamp(),
  },
]

type Settings = {
  apiPort: number
  apiToken: string
  apiRunning: boolean
  camoufoxVersion: string
  profileRoot: string
  theme: 'light' | 'dark' | 'system'
  defaultHeadless: boolean
}

type DataState = {
  profiles: Profile[]
  proxies: Proxy[]
  groups: Group[]
  tags: Tag[]
  templates: FingerprintTemplate[]
  settings: Settings
  hydrated: boolean
  hydrateError: string | null
  hydrating: boolean
  applyHydrate: (snap: remote.HydrateSnapshot) => void
  hydrateFromApi: () => Promise<boolean>
  refreshRuntime: () => Promise<void>
  setHydrateError: (msg: string | null) => void
  activeProfiles: () => Profile[]
  trashedProfiles: () => Profile[]
  runningCount: () => number
  getProfile: (id: string) => Profile | undefined
  createProfile: (input: CreateProfileInput) => Promise<Profile>
  updateProfile: (id: string, patch: Partial<Profile>) => Promise<void>
  setStatus: (id: string, status: ProfileStatus, extra?: Partial<Profile>) => void
  upsertProfile: (p: Profile) => void
  startProfile: (id: string) => Promise<void>
  stopProfile: (id: string) => Promise<void>
  stopMany: (ids: string[]) => Promise<void>
  softDelete: (id: string) => Promise<void>
  softDeleteMany: (ids: string[]) => Promise<void>
  restore: (id: string) => Promise<void>
  purge: (id: string) => Promise<void>
  purgeAll: () => Promise<void>
  importProfiles: (
    rows: CreateProfileInput[],
  ) => Promise<{ ok: number; fail: number; errors: string[] }>
  addGroup: (name: string, parentId?: string | null) => Promise<Group>
  renameGroup: (id: string, name: string) => Promise<void>
  removeGroup: (id: string) => Promise<void>
  addTag: (name: string, color: string) => Promise<Tag>
  removeTag: (id: string) => Promise<void>
  addProxy: (
    p: Omit<Proxy, 'id' | 'status'> & { status?: Proxy['status'] },
  ) => Promise<Proxy>
  updateProxy: (id: string, patch: Partial<Proxy>) => void
  removeProxy: (id: string) => Promise<void>
  checkProxy: (id: string) => Promise<void>
  importProxiesText: (text: string) => Promise<{ ok: number; errors: string[] }>
  createTemplate: (input: {
    name: string
    os?: string
    alignGeo?: boolean
    webrtc?: string
    usePreset?: boolean
  }) => Promise<FingerprintTemplate>
  sampleTemplate: (id: string) => Promise<void>
  setDefaultTemplate: (id: string) => Promise<void>
  copyTemplate: (id: string) => Promise<void>
  removeTemplate: (id: string) => Promise<void>
  refreshTemplates: () => Promise<void>
  updateSettings: (patch: Partial<Settings>) => void
}

function applyProfile(s: DataState, p: Profile): Profile[] {
  const exists = s.profiles.some((x) => x.id === p.id)
  if (exists) return s.profiles.map((x) => (x.id === p.id ? p : x))
  return [p, ...s.profiles]
}

export const useDataStore = create<DataState>((set, get) => ({
  profiles: isRemoteMode() ? [] : INITIAL_PROFILES,
  proxies: isRemoteMode() ? [] : INITIAL_PROXIES,
  groups: isRemoteMode() ? [] : INITIAL_GROUPS,
  tags: isRemoteMode() ? [] : INITIAL_TAGS,
  templates: isRemoteMode() ? [] : INITIAL_TEMPLATES,
  settings: {
    apiPort: 50325,
    apiToken: 'cf_dev_token_mock_8f3a',
    apiRunning: true,
    camoufoxVersion: '152.0.4-beta.28',
    profileRoot: 'D:/camoufox-profiles',
    theme: 'light',
    defaultHeadless: false,
  },
  hydrated: !isRemoteMode(),
  hydrateError: null,
  hydrating: false,

  applyHydrate: (snap) =>
    set({
      profiles: snap.profiles,
      proxies: snap.proxies,
      groups: snap.groups,
      tags: snap.tags,
      templates: snap.templates ?? [],
      settings: {
        apiPort: snap.settings.apiPort,
        apiToken: snap.settings.apiToken,
        apiRunning: snap.settings.apiRunning,
        camoufoxVersion: snap.settings.camoufoxVersion,
        profileRoot: snap.settings.profileRoot,
        theme: snap.settings.theme,
        defaultHeadless: snap.settings.defaultHeadless,
      },
      hydrated: true,
      hydrateError: null,
      hydrating: false,
    }),

  setHydrateError: (msg) => set({ hydrateError: msg, hydrating: false }),

  hydrateFromApi: async () => {
    if (!isRemoteMode()) {
      set({ hydrated: true, hydrateError: null })
      return true
    }
    set({ hydrating: true, hydrateError: null })
    try {
      const snap = await remote.fetchHydrateSnapshot()
      get().applyHydrate(snap)
      return true
    } catch (e) {
      set({
        hydrating: false,
        hydrateError: `后端不可达：${e instanceof Error ? e.message : String(e)}`,
        hydrated: false,
      })
      return false
    }
  },

  refreshRuntime: async () => {
    if (!isRemoteMode()) return
    try {
      const [all, runtime] = await Promise.all([
        remote.remoteListProfiles(true),
        remote.remoteListRuntime(),
      ])
      void runtime
      set({ profiles: all })
    } catch {
      /* keep current */
    }
  },

  activeProfiles: () => get().profiles.filter((p) => !p.deletedAt),
  trashedProfiles: () => get().profiles.filter((p) => !!p.deletedAt),
  runningCount: () => countRunning(get().profiles),
  getProfile: (id) => get().profiles.find((p) => p.id === id),

  upsertProfile: (p) => set((s) => ({ profiles: applyProfile(s, p) })),

  createProfile: async (input) => {
    if (isRemoteMode()) {
      const profile = await remote.remoteCreateProfile({
        ...input,
        platform: input.platform || '常规浏览',
        fingerprint: input.fingerprint ?? fingerprintSummary(input.os),
      })
      set((s) => ({ profiles: [profile, ...s.profiles] }))
      return profile
    }
    const id = uid('prof')
    const profile: Profile = {
      id,
      name: input.name,
      platform: input.platform || '常规浏览',
      note: input.note || '',
      groupId: input.groupId,
      tags: input.tags,
      proxyId: input.proxyId,
      proxyLabel: input.proxyLabel,
      fingerprint: input.fingerprint ?? fingerprintSummary(input.os),
      fingerprintStrategy: input.fingerprintStrategy,
      os: input.os,
      alignGeoWithProxy: input.alignGeoWithProxy,
      cookiesJson: input.cookiesJson || '[]',
      startUrl: input.startUrl || '',
      headless: get().settings.defaultHeadless,
      status: 'idle',
      lastStartedAt: null,
      deletedAt: null,
      pid: null,
      wsEndpoint: null,
      profilePath: `${get().settings.profileRoot}/${id}`,
      diskMb: 12,
      logs: [{ at: nowStamp(), level: 'info', message: '环境已创建' }],
      templateId: input.templateId ?? null,
      hasFingerprintConfig: false,
      restoreSession: input.restoreSession !== false,
    }
    set((s) => ({ profiles: [profile, ...s.profiles] }))
    return profile
  },

  updateProfile: async (id, patch) => {
    if (isRemoteMode()) {
      const body: Record<string, unknown> = { ...patch }
      try {
        const p = await remote.remotePatchProfile(id, body)
        get().upsertProfile(p)
        return
      } catch (e) {
        get().setHydrateError(`更新失败：${e instanceof Error ? e.message : String(e)}`)
        throw e
      }
    }
    set((s) => ({
      profiles: s.profiles.map((p) => (p.id === id ? { ...p, ...patch } : p)),
    }))
  },

  setStatus: (id, status, extra) =>
    set((s) => ({
      profiles: s.profiles.map((p) =>
        p.id === id ? { ...p, status, ...extra } : p,
      ),
    })),

  startProfile: async (id) => {
    const { setStatus, getProfile, upsertProfile } = get()
    if (isRemoteMode()) {
      setStatus(id, 'starting', { pid: null, wsEndpoint: null })
      try {
        const p = await remote.remoteStartProfile(id)
        upsertProfile(p)
      } catch (err) {
        setStatus(id, 'error', {
          logs: [
            ...(getProfile(id)?.logs ?? []),
            {
              at: nowStamp(),
              level: 'error',
              message: `远程启动失败: ${String(err)}`,
            },
          ],
        })
      }
      return
    }
    setStatus(id, 'starting', { pid: null, wsEndpoint: null })
    await new Promise((r) => setTimeout(r, 800))
    setStatus(id, 'running', {
      pid: 10000 + Math.floor(Math.random() * 50000),
      wsEndpoint: `ws://127.0.0.1:${9222 + Math.floor(Math.random() * 20)}/devtools/browser/${id.slice(-6)}`,
      lastStartedAt: nowStamp(),
      logs: [
        ...(get().getProfile(id)?.logs ?? []),
        { at: nowStamp(), level: 'info', message: '浏览器启动成功 (mock)' },
      ],
    })
  },

  stopProfile: async (id) => {
    if (isRemoteMode()) {
      try {
        const p = await remote.remoteStopProfile(id)
        get().upsertProfile(p)
      } catch {
        get().setStatus(id, 'idle', { pid: null, wsEndpoint: null })
      }
      return
    }
    get().setStatus(id, 'idle', {
      pid: null,
      wsEndpoint: null,
      logs: [
        ...(get().getProfile(id)?.logs ?? []),
        { at: nowStamp(), level: 'info', message: '已停止' },
      ],
    })
  },

  stopMany: async (ids) => {
    await Promise.all(ids.map((id) => get().stopProfile(id)))
  },

  softDelete: async (id) => {
    if (isRemoteMode()) {
      try {
        const p = await remote.remoteTrashProfile(id)
        get().upsertProfile(p)
      } catch (e) {
        get().setHydrateError(`删除失败：${e instanceof Error ? e.message : String(e)}`)
      }
      return
    }
    await get().stopProfile(id)
    set((s) => ({
      profiles: s.profiles.map((p) =>
        p.id === id
          ? { ...p, deletedAt: nowStamp(), status: 'idle' as const, pid: null, wsEndpoint: null }
          : p,
      ),
    }))
  },

  softDeleteMany: async (ids) => {
    await Promise.all(ids.map((id) => get().softDelete(id)))
  },

  restore: async (id) => {
    if (isRemoteMode()) {
      const p = await remote.remoteRestoreProfile(id)
      get().upsertProfile(p)
      return
    }
    await get().updateProfile(id, { deletedAt: null })
  },

  purge: async (id) => {
    if (isRemoteMode()) {
      await remote.remoteDeleteProfile(id)
    }
    set((s) => ({ profiles: s.profiles.filter((p) => p.id !== id) }))
  },

  purgeAll: async () => {
    const trash = get().trashedProfiles()
    if (isRemoteMode()) {
      await Promise.all(trash.map((p) => remote.remoteDeleteProfile(p.id)))
    }
    set((s) => ({ profiles: s.profiles.filter((p) => !p.deletedAt) }))
  },

  importProfiles: async (rows) => {
    let ok = 0
    const errors: string[] = []
    for (const r of rows) {
      try {
        await get().createProfile(r)
        ok += 1
      } catch (e) {
        errors.push(`${r.name}: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
    return { ok, fail: errors.length, errors }
  },

  addGroup: async (name, parentId = null) => {
    if (isRemoteMode()) {
      const g = await remote.remoteCreateGroup(name, parentId)
      set((s) => ({ groups: [...s.groups, g] }))
      return g
    }
    const g: Group = { id: uid('grp'), name, parentId }
    set((s) => ({ groups: [...s.groups, g] }))
    return g
  },

  renameGroup: async (id, name) => {
    set((s) => ({
      groups: s.groups.map((g) => (g.id === id ? { ...g, name } : g)),
    }))
    if (isRemoteMode()) {
      try {
        await remote.remotePatchGroup(id, name)
      } catch {
        /* keep optimistic */
      }
    }
  },

  removeGroup: async (id) => {
    if (isRemoteMode()) {
      await remote.remoteDeleteGroup(id)
    }
    set((s) => ({
      groups: s.groups.filter((g) => g.id !== id),
      profiles: s.profiles.map((p) =>
        p.groupId === id ? { ...p, groupId: null } : p,
      ),
    }))
  },

  addTag: async (name, color) => {
    if (isRemoteMode()) {
      const t = await remote.remoteCreateTag(name, color)
      set((s) => ({ tags: [...s.tags, t] }))
      return t
    }
    const t: Tag = { id: uid('tag'), name, color }
    set((s) => ({ tags: [...s.tags, t] }))
    return t
  },

  removeTag: async (id) => {
    const tag = get().tags.find((t) => t.id === id)
    if (isRemoteMode()) {
      await remote.remoteDeleteTag(id)
    }
    set((s) => ({
      tags: s.tags.filter((t) => t.id !== id),
      profiles: tag
        ? s.profiles.map((p) => ({
            ...p,
            tags: p.tags.filter((n) => n !== tag.name),
          }))
        : s.profiles,
    }))
  },

  addProxy: async (p) => {
    if (isRemoteMode()) {
      const proxy = await remote.remoteCreateProxy({
        alias: p.alias,
        protocol: p.protocol,
        host: p.host,
        port: p.port,
        username: p.username,
        password: p.password,
      })
      set((s) => ({ proxies: [proxy, ...s.proxies] }))
      return proxy
    }
    const proxy: Proxy = {
      id: uid('px'),
      status: p.status ?? 'unknown',
      ...p,
    }
    set((s) => ({ proxies: [proxy, ...s.proxies] }))
    return proxy
  },

  updateProxy: (id, patch) =>
    set((s) => ({
      proxies: s.proxies.map((p) => (p.id === id ? { ...p, ...patch } : p)),
    })),

  removeProxy: async (id) => {
    if (isRemoteMode()) {
      await remote.remoteDeleteProxy(id)
    }
    set((s) => ({
      proxies: s.proxies.filter((p) => p.id !== id),
      profiles: s.profiles.map((p) =>
        p.proxyId === id ? { ...p, proxyId: null, proxyLabel: null } : p,
      ),
    }))
  },

  checkProxy: async (id) => {
    if (isRemoteMode()) {
      const px = await remote.remoteCheckProxy(id)
      get().updateProxy(id, px)
      return
    }
    const ok = Math.random() > 0.25
    get().updateProxy(id, {
      status: ok ? 'ok' : 'fail',
      latencyMs: ok ? 40 + Math.floor(Math.random() * 200) : null,
      exitIp: ok ? `${Math.floor(Math.random() * 200)}.*.*.*` : undefined,
      country: ok ? 'US' : undefined,
      lastCheckedAt: nowStamp(),
    })
  },

  importProxiesText: async (text) => {
    if (isRemoteMode()) {
      const res = await remote.remoteImportProxies(text)
      set((s) => ({ proxies: [...res.created, ...s.proxies] }))
      return {
        ok: res.ok,
        errors: res.errors.map((e) => `L${e.line}: ${e.error} (${e.raw})`),
      }
    }
    const lines = text.split(/\r?\n/)
    let ok = 0
    const errors: string[] = []
    for (const line of lines) {
      const t = line.trim()
      if (!t || t.startsWith('#')) continue
      const parts = t.split(':')
      if (parts.length < 2) {
        errors.push(`无法解析: ${t}`)
        continue
      }
      await get().addProxy({
        alias: `${parts[0]}:${parts[1]}`,
        protocol: 'socks5',
        host: parts[0],
        port: Number(parts[1]),
        username: parts[2],
        password: parts[3],
        status: 'unknown',
      })
      ok += 1
    }
    return { ok, errors }
  },

  createTemplate: async (input) => {
    if (isRemoteMode()) {
      const t = await remote.remoteCreateTemplate(input)
      set((s) => ({ templates: [...s.templates, t] }))
      return t
    }
    const t: FingerprintTemplate = {
      id: uid('tpl'),
      name: input.name,
      kind: 'custom',
      os: input.os ?? 'windows',
      alignGeo: input.alignGeo ?? true,
      webrtc: input.webrtc ?? 'follow',
      usePreset: input.usePreset ?? false,
      configJson: null,
      hasConfig: false,
      isDefault: false,
      createdAt: nowStamp(),
    }
    set((s) => ({ templates: [...s.templates, t] }))
    return t
  },

  sampleTemplate: async (id) => {
    if (isRemoteMode()) {
      const t = await remote.remoteSampleTemplate(id)
      set((s) => ({
        templates: s.templates.map((x) => (x.id === id ? t : x)),
      }))
      return
    }
    set((s) => ({
      templates: s.templates.map((x) =>
        x.id === id
          ? { ...x, hasConfig: true, configJson: '{"mock":true}' }
          : x,
      ),
    }))
  },

  setDefaultTemplate: async (id) => {
    if (isRemoteMode()) {
      const t = await remote.remoteSetDefaultTemplate(id)
      set((s) => ({
        templates: s.templates.map((x) => ({
          ...x,
          isDefault: x.id === t.id,
        })),
      }))
      return
    }
    set((s) => ({
      templates: s.templates.map((x) => ({ ...x, isDefault: x.id === id })),
    }))
  },

  copyTemplate: async (id) => {
    if (isRemoteMode()) {
      const t = await remote.remoteCopyTemplate(id)
      set((s) => ({ templates: [...s.templates, t] }))
      return
    }
    const src = get().templates.find((x) => x.id === id)
    if (!src) return
    const t: FingerprintTemplate = {
      ...src,
      id: uid('tpl'),
      name: `${src.name} 副本`,
      kind: 'custom',
      isDefault: false,
      createdAt: nowStamp(),
    }
    set((s) => ({ templates: [...s.templates, t] }))
  },

  removeTemplate: async (id) => {
    if (isRemoteMode()) {
      await remote.remoteDeleteTemplate(id)
    }
    set((s) => ({ templates: s.templates.filter((t) => t.id !== id) }))
  },

  refreshTemplates: async () => {
    if (!isRemoteMode()) return
    const templates = await remote.remoteListTemplates()
    set({ templates })
  },

  updateSettings: (patch) =>
    set((s) => ({ settings: { ...s.settings, ...patch } })),
}))
