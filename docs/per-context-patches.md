# Per-context fingerprint patches

`CAMOU_CONFIG` sets one identity for the whole browser. The per-context patches
let each Playwright context carry its own, so one Camoufox process can run many
sessions that do not correlate. The launchers use them through `NewContext()`
([Python](../python/README.md#one-browser-many-identities),
[TypeScript](../typescript/README.md#one-browser-many-identities)); this page is
for people working on the patches or driving the browser without a launcher.

## The setters

Each per-context patch adds a function to `window`. A setter stores its value
for the calling window's context, and is gone before any page script runs
(`window-setter-seal.patch`).

| Function | Patch | What a page sees |
|---|---|---|
| `setAudioFingerprintSeed(seed)` | `audio-fingerprint-manager.patch` | `AudioBuffer` and `AnalyserNode` output |
| `setTimezone(tz)` | `timezone-spoofing.patch` | `Date`, `Intl.DateTimeFormat` and every other time API |
| `setScreenDimensions(w, h)` | `screen-spoofing.patch` | `screen.width`, `screen.height`, matching CSS media features |
| `setScreenColorDepth(depth)` | `screen-spoofing.patch` | `screen.colorDepth` |
| `setNavigatorPlatform(platform)` | `navigator-spoofing.patch` | `navigator.platform` |
| `setNavigatorOscpu(oscpu)` | `navigator-spoofing.patch` | `navigator.oscpu` |
| `setNavigatorHardwareConcurrency(cores)` | `navigator-spoofing.patch` | `navigator.hardwareConcurrency` |
| `setNavigatorUserAgent(ua)` | `navigator-spoofing.patch` | `navigator.userAgent`, in workers too |
| `setWebRTCIPv4(ip)` | `webrtc-ip-spoofing.patch` | ICE candidates, SDP, `getStats()` |
| `setWebRTCIPv6(ip)` | `webrtc-ip-spoofing.patch` | The same, for IPv6 |
| `setWebGLVendor(vendor)` | `webgl-spoofing.patch` | `UNMASKED_VENDOR_WEBGL` |
| `setWebGLRenderer(renderer)` | `webgl-spoofing.patch` | `UNMASKED_RENDERER_WEBGL` |
| `setFontList(fonts)` | `font-list-spoofing.patch` | Which fonts exist (comma-separated, case-insensitive) |
| `setSpeechVoices(voices)` | `speech-voices-spoofing.patch` | `speechSynthesis.getVoices()` (comma-separated names) |

Supporting patches, with no setter of their own:

| Patch | Provides |
|---|---|
| `anti-font-fingerprinting.patch` | The context id on each font group |
| `cross-process-storage.patch` | `RoverfoxStorageManager`, the per-context store, with the IPC that makes a value set in one process readable in every other, and the guard and removal every setter uses |

There is no canvas pixel noise and no glyph-spacing noise: both produce output
no real machine does ([`ci/tribal-rules.yml`](../ci/tribal-rules.yml)).

## Using the setters

Call them from `addInitScript`, which runs before page scripts on every new
page, frame and navigation. The `typeof` guards keep the script harmless on a
build without the patches.

```javascript
import { firefox } from "playwright-core";

const browser = await firefox.launch({ executablePath: "/path/to/camoufox-bin" });
const context = await browser.newContext();
await context.addInitScript((v) => {
  const w = window;
  if (typeof w.setTimezone === "function") w.setTimezone(v.timezone);
  if (typeof w.setAudioFingerprintSeed === "function") w.setAudioFingerprintSeed(v.audioSeed);
  if (typeof w.setScreenDimensions === "function") w.setScreenDimensions(v.width, v.height);
  if (typeof w.setNavigatorPlatform === "function") w.setNavigatorPlatform(v.platform);
  if (typeof w.setWebRTCIPv4 === "function") w.setWebRTCIPv4(v.webrtcIp);
}, {
  timezone: "America/New_York",
  audioSeed: 87654321,
  width: 1920,
  height: 1080,
  platform: "Win32",
  webrtcIp: "203.0.113.1",
});
const page = await context.newPage();
await page.goto("https://example.com");
await browser.close();
```

Values set this way must still describe one plausible machine. The launchers'
`generate_context_fingerprint()` (`fingerprints.py`) draws them together and
builds this script; prefer it to hand-picked values.

## Architecture

### Storage

All setters share `RoverfoxStorageManager`, a mutex-protected key-value store
keyed by `userContextId` (each Playwright context is a Firefox container with
its own id).

| Step | Write path |
|---|---|
| 1 | The setter resolves `userContextId` from the window's `BrowsingContext`. |
| 2 | The value goes into the in-process cache. |
| 3 | It is also written as a pref with the `roverfox.s.` prefix (every type serialized as a string). |
| 4 | In a content process, it is sent to the parent with sync IPC (`SendRoverfoxStoragePut`). |
| 5 | Audio, navigator, screen, timezone and WebGL also store it under id 0, for workers that cannot resolve their context. Fonts, voices and WebRTC do not. |

| Tier | Read path |
|---|---|
| 1 | The in-process cache |
| 2 | Firefox prefs, which Firefox syncs to every content process |
| 3 | Sync IPC to the parent (`SendRoverfoxStorageGet`), main thread only |

Off the main thread (HarfBuzz, the compositor) only tiers 1 and 2 are used,
because sync IPC is main-thread only.

### Cross-process storage

`cross-process-storage.patch` adds two sync messages to `PContent.ipdl`,
`RoverfoxStoragePut` and `RoverfoxStorageGet`. The parent accepts only pref
names starting with `roverfox.s.`. Put is synchronous so the value is in the
parent before any worker process starts. The patch also adds `roverfox.s.` to
`sDynamicPrefOverrideList` in `Preferences.cpp`, because Firefox otherwise
strips dynamically created string prefs from content processes.

Files: `dom/base/RoverfoxStorageManager.cpp/h`, `ContentParent.cpp/h`,
`PContent.ipdl`, `ipc/ipdl/sync-messages.ini`, `modules/libpref/Preferences.cpp`.

### Setter guard and removal

Every setter uses the same three `RoverfoxStorageManager` helpers:

| Helper | Used by | Does |
|---|---|---|
| `IsSetterOffered` | The setter's WebIDL `Func=` guard | False once the window is sealed or the context has used the setter |
| `MarkSetterUsed` | The setter, or its manager's `Set*` | Records the use in the shared store, so later documents of the context, in any process, are never offered it |
| `RemoveSetter` | The setter, after it runs | Deletes the name from the calling global |

### Context resolution and lookup order

Windows resolve the id from `BrowsingContext`, which exists before the
DocShell or Document attributes are populated:

```cpp
if (BrowsingContext* bc = win->GetBrowsingContext()) {
  userContextId = bc->OriginAttributesRef().mUserContextId;
}
```

Workers use `WorkerPrivate::GetOriginAttributes()`. A spoofed getter checks the
per-context value first, then `CAMOU_CONFIG` through `MaskConfig`, then the
real value.

### Prefs that make it work

[`browser/settings/camoufox.cfg`](../browser/settings/camoufox.cfg):

| Pref | Why |
|---|---|
| `fission.autostart = true` | Disabled Fission is detectable; cross-process storage makes per-context values work with it |
| `fission.webContentIsolationStrategy = 0` | Cross-site iframes stay in their parent's process |
| `dom.ipc.processPrelaunch.enabled = false` | A prelaunched process could carry stale values |

`dom.ipc.processCount` is not overridden.

## Patch details

| Patch | Hooks | Notes |
|---|---|---|
| `audio-fingerprint-manager.patch` | `AudioBuffer.getChannelData`, `copyFromChannel`; `AnalyserNode.getFloatFrequencyData`, `getByteFrequencyData`, `getFloatTimeDomainData`, `getByteTimeDomainData` | A small deterministic transform of the samples, seeded per context. All six read paths are covered, because covering only `getChannelData` is bypassable. Falls back to `audio:seed` in `CAMOU_CONFIG`. |
| `timezone-spoofing.patch` | SpiderMonkey `DateTimeInfo` per realm (`JS::SetRealmTimeZoneOverride`), `nsGlobalWindowOuter::SetNewDocument`, `WorkerPrivate::GetOrCreateGlobalScope` | The only patch inside SpiderMonkey. Re-applied on navigation and in dedicated, shared and service workers; also sets a process-wide override. Invalid IDs throw `TypeError`. |
| `screen-spoofing.patch` | `nsScreen::GetRect`, `nsDeviceContext`, `nsMediaFeatures.cpp` | CSS `device-width` and `color` agree with `screen.*`. |
| `navigator-spoofing.patch` | `Navigator::GetPlatform`, `GetOscpu`, `HardwareConcurrency`, `GetUserAgent`, `GetAppVersion` (global only); the `WorkerNavigator` versions of platform, cores and UA | Falls back to `navigator.*` in `CAMOU_CONFIG`. |
| `webrtc-ip-spoofing.patch` | `SanitizeSDPForIPLeak`, `CandidateReady`, candidate `.address`/`.relatedAddress`, `getStats()`, `UpdateDefaultCandidate`, `NrSocketBase::CreateSocket` | Forces `default_address_only` while spoofing; loopback, link-local and private addresses are left alone. UDP candidate ports come from the ephemeral range of the identity's OS (`MaskConfig::SpoofedEphemeralPorts()`), so a Windows identity on Linux never shows a Linux port. |
| `webgl-spoofing.patch` | `ClientWebGLContext::GetParameter` | Per context: vendor and renderer. Global only (`CAMOU_CONFIG`): parameters, extensions, shader precision. Works from `OffscreenCanvas` in workers. |
| `font-list-spoofing.patch` | `gfxPlatformFontList::FindAndAddFamiliesLocked` | A thread-local context id, set by an RAII guard in `FontFaceSet::Check/Load` and `gfxFontGroup::EnsureFontList`, avoids changing ~50 signatures. The list is in the shared store, so it holds in every content process. Workers are not filtered. |
| `speech-voices-spoofing.patch` | `SpeechSynthesis::GetVoices` | Filters the real list by name; a listed voice that is not installed is left out. |

Global-only patches (no setter) read `CAMOU_CONFIG` at startup:

| Patch | Config keys | Effect |
|---|---|---|
| `geolocation-spoofing.patch` | `geolocation:latitude`, `geolocation:longitude`, `geolocation:accuracy` | Returns these coordinates and grants the permission. Per context, use Playwright's `geolocation` option. |
| `locale-spoofing.patch` | `locale:*`, `navigator.language` | `navigator.language`, `Accept-Language`, `Intl`, the OS locale. |
| `force-default-pointer.patch` | `navigator.maxTouchPoints` | CSS `pointer` reports a fine pointer on desktop. |

Every patch that reads `CAMOU_CONFIG` is listed in
[`browser/patches/patch-dependencies.md`](../browser/patches/patch-dependencies.md).

## Build notes

| Topic | Rule |
|---|---|
| `SOURCES` vs `UNIFIED_SOURCES` | Manager `.cpp` files go in `SOURCES`, because unified builds that include `RoverfoxStorageManager.h` hit `mozilla::dom::mozilla::dom::`. `RoverfoxStorageManager.cpp` and `TimezoneManager.cpp` compile unified. |
| `EXPORTS` | Each patch adds its own `EXPORTS.mozilla.dom += [...]` next to its `SOURCES`, to avoid conflicts in the sorted list. |
| WebIDL | Each setter has its own `partial interface Window` block. |

## Where the launcher's values come from

`NewBrowser` puts one identity in `CAMOU_CONFIG`; `NewContext` builds a
per-context init script. fpgen draws both by default.
`fingerprint_preset=True` (or `preset=` for `NewContext`) opts into recorded
real-device presets instead:

| Bundle | Firefox | Presets (macOS / Windows / Linux) |
|---|---|---|
| `fingerprint-presets-v150.json` | 149 and newer (`PRESETS_V150_MIN_FF`) | 285 (58 / 168 / 59) |
| `fingerprint-presets.json` | older | 113 (25 / 71 / 17) |

The User-Agent's version is rewritten to the running browser's.

| Value | Source |
|---|---|
| UA, platform, cores, oscpu | fpgen or the preset; UA version set to the browser's |
| Screen, color depth | fpgen or the preset |
| WebGL | One GPU fpgen recorded for Firefox on that OS, weighted by its share and checked against the machine (`coherence.gpu_fits_machine()`); `webgl_for_gpu()` adds its parameters, extensions and shader precisions |
| Fonts | `_generate_random_font_subset()`: one OS-version base plus measured additions ([FONTS.md](FONTS.md)); never from presets |
| Voices | `_generate_random_voice_subset()`, from `voice-manifests.json`, seeded by the identity; never from presets |
| Audio seed | Derived from the identity (`NewBrowser`) or random (`NewContext`), never 0 |
| Timezone | The preset, or `timezone` in `CAMOU_CONFIG` (from geoip); with a proxy, `NewContext` looks it up from the exit IP |
| WebRTC IP | `NewContext`'s `webrtc_ip` or the proxy's exit IP, to the IPv4 or IPv6 setter; an invalid address raises `InvalidIP` |
| Geolocation | The `geolocation` argument, via Playwright |

## Known limitations

These patches control what APIs report. They cannot change how the host OS
renders, so some signals still show the real OS:

| Signal | Why |
|---|---|
| Text rendering | Core Text, DirectWrite and FreeType rasterize the same font differently, which shows in canvas hashes |
| GPU rasterization | Canvas and WebGL output carry the host GPU driver's rasterization |
| System colors | `AccentColor` and system colors differ by OS and desktop |
| Shader precision behaviour | Actual precision follows the real driver even when the reported formats are spoofed |

Run each identity on the OS it claims. The per-context patches make each
context a different person on the same OS, not a different OS.
