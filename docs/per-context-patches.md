# Per-Context Fingerprint Patches

Camoufox spoofs fingerprints globally via `CAMOU_CONFIG` — every browser context shares the same identity. These patches add **per-context isolation**, so each Playwright context can have a unique, deterministic fingerprint. This lets you run multiple concurrent sessions from a single Camoufox process without cross-context correlation.

### What's New

**New patches (8):**
- `audio-fingerprint-manager.patch` — per-context audio fingerprint seeding (all 6 AudioBuffer + AnalyserNode methods)
- `timezone-spoofing.patch` — true per-realm timezone isolation via SpiderMonkey DateTimeInfo
- `navigator-spoofing.patch` — per-context platform, oscpu, hardwareConcurrency, userAgent
- `webgl-spoofing.patch` — per-context UNMASKED_VENDOR/RENDERER_WEBGL
- `canvas-spoofing.patch` — per-context canvas 2D fingerprint noise
- `font-list-spoofing.patch` — per-context installed font list filtering via thread-local propagation
- `speech-voices-spoofing.patch` — per-context `speechSynthesis.getVoices()` filtering
- `cross-process-storage.patch` — IPDL message for content-to-parent pref writes, enabling cross-process fingerprint storage

**Enhanced existing patches (5):**
- `anti-font-fingerprinting.patch` — added `RoverfoxStorageManager` (cross-process Preferences-based storage), `WordCacheKey` fix (userContextId in glyph cache to prevent cross-context cache hits), random font subset generation
- `screen-spoofing.patch` — replaces old `screen-hijacker.patch` with full per-context support via `ScreenDimensionManager`
- `webrtc-ip-spoofing.patch` — added `getStats()` API sanitization, per-context IP storage, comprehensive IPv6 regex
- `geolocation-spoofing.patch` — updated for Firefox 146, fixed malformed hunks and moz.build line offsets
- `locale-spoofing.patch` — updated for Firefox 146 compatibility

## Quick Reference

| Function | Patch | What it controls |
|----------|-------|-----------------|
| `window.setFontSpacingSeed(seed)` | `anti-font-fingerprinting.patch` | Canvas `measureText()` letter spacing |
| `window.setAudioFingerprintSeed(seed)` | `audio-fingerprint-manager.patch` | Audio buffer/analyser fingerprint hash |
| `window.setTimezone(tz)` | `timezone-spoofing.patch` | `Date`, `Intl.DateTimeFormat`, all time APIs |
| `window.setScreenDimensions(w, h)` | `screen-spoofing.patch` | `screen.width`, `screen.height` |
| `window.setScreenColorDepth(depth)` | `screen-spoofing.patch` | `screen.colorDepth` |
| `window.setNavigatorPlatform(platform)` | `navigator-spoofing.patch` | `navigator.platform` |
| `window.setNavigatorOscpu(oscpu)` | `navigator-spoofing.patch` | `navigator.oscpu` |
| `window.setNavigatorHardwareConcurrency(cores)` | `navigator-spoofing.patch` | `navigator.hardwareConcurrency` |
| `window.setNavigatorUserAgent(ua)` | `navigator-spoofing.patch` | `navigator.userAgent` (+ worker UA) |
| `window.setWebRTCIPv4(ip)` | `webrtc-ip-spoofing.patch` | WebRTC ICE candidates, SDP, getStats() |
| `window.setWebRTCIPv6(ip)` | `webrtc-ip-spoofing.patch` | WebRTC IPv6 addresses |
| `window.setWebGLVendor(vendor)` | `webgl-spoofing.patch` | `UNMASKED_VENDOR_WEBGL` parameter |
| `window.setWebGLRenderer(renderer)` | `webgl-spoofing.patch` | `UNMASKED_RENDERER_WEBGL` parameter |
| `window.setCanvasSeed(seed)` | `canvas-spoofing.patch` | Canvas 2D `toDataURL()`/`getImageData()` hash |
| `window.setFontList(fonts)` | `font-list-spoofing.patch` | Which fonts appear "installed" to fingerprinters |
| `window.setSpeechVoices(voices)` | `speech-voices-spoofing.patch` | `speechSynthesis.getVoices()` filtering |

All 16 functions **self-destruct after the first call** — page JavaScript cannot detect them via `typeof window.setTimezone`.

---

## How to Use with Playwright

The recommended pattern is `context.addInitScript()`, which runs before any page scripts on every new page, tab, or navigation:

```javascript
const { firefox } = require('playwright');

const browser = await firefox.launch({
  executablePath: '/path/to/camoufox',
});

const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
});

// Apply fingerprints via addInitScript — fires on every new page automatically
await context.addInitScript((values) => {
  const w = window;

  if (typeof w.setFontSpacingSeed === 'function') {
    w.setFontSpacingSeed(values.fontSpacingSeed);
  }
  if (typeof w.setAudioFingerprintSeed === 'function') {
    w.setAudioFingerprintSeed(values.audioFingerprintSeed);
  }
  if (typeof w.setTimezone === 'function') {
    w.setTimezone(values.timezone);
  }
  if (typeof w.setScreenDimensions === 'function') {
    w.setScreenDimensions(values.screenWidth, values.screenHeight);
  }
  if (typeof w.setScreenColorDepth === 'function') {
    w.setScreenColorDepth(values.screenColorDepth);
  }
  if (typeof w.setWebRTCIPv4 === 'function') {
    w.setWebRTCIPv4(values.webrtcIPv4);
  }
  if (typeof w.setNavigatorPlatform === 'function') {
    w.setNavigatorPlatform(values.navigatorPlatform);
  }
  if (typeof w.setNavigatorOscpu === 'function') {
    w.setNavigatorOscpu(values.navigatorOscpu);
  }
  if (typeof w.setNavigatorHardwareConcurrency === 'function') {
    w.setNavigatorHardwareConcurrency(values.hardwareConcurrency);
  }
  if (typeof w.setNavigatorUserAgent === 'function') {
    w.setNavigatorUserAgent(values.userAgent);
  }
  if (typeof w.setWebGLVendor === 'function') {
    w.setWebGLVendor(values.webglVendor);
  }
  if (typeof w.setWebGLRenderer === 'function') {
    w.setWebGLRenderer(values.webglRenderer);
  }
  if (typeof w.setCanvasSeed === 'function') {
    w.setCanvasSeed(values.canvasSeed);
  }
  if (values.fontList && values.fontList.length > 0 && typeof w.setFontList === 'function') {
    w.setFontList(values.fontList.join(','));
  }
  if (values.speechVoices && typeof w.setSpeechVoices === 'function') {
    w.setSpeechVoices(values.speechVoices);
  }
}, {
  fontSpacingSeed: 12345678,
  audioFingerprintSeed: 87654321,
  timezone: 'America/New_York',
  screenWidth: 1920,
  screenHeight: 1080,
  screenColorDepth: 24,
  webrtcIPv4: '203.0.113.1',  // your proxy IP
  navigatorPlatform: 'MacIntel',
  navigatorOscpu: 'Intel Mac OS X 10.15',
  hardwareConcurrency: 8,
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0',
  webglVendor: 'Intel Inc.',
  webglRenderer: 'Intel Iris OpenGL Engine',
  canvasSeed: 55555555,
  fontList: ['Arial', 'Helvetica', 'Georgia', 'Courier New', 'Verdana', 'Times New Roman'],
  speechVoices: 'Microsoft David,Microsoft Zira,Google US English',
});

const page = await context.newPage();
await page.goto('https://example.com');
// Fingerprints are already applied. Functions are already self-destructed.
```

**Why `addInitScript`?** Each `window.setXxx()` function self-destructs after the first call. On new tabs or navigations, Camoufox recreates the functions, and the init script calls them again before any page scripts can run. This ensures fingerprints are always applied and functions are never visible to website code.

**Why `typeof` guards?** The init script runs on every page load. If Camoufox is ever used without these patches (e.g. vanilla build), the guards prevent `ReferenceError`. They also handle the case where the function was already called and self-destructed.

### Running Multiple Isolated Contexts

```javascript
// Context A — appears as a New York user with Intel GPU
const ctxA = await browser.newContext();
await ctxA.addInitScript((v) => {
  if (typeof window.setTimezone === 'function') window.setTimezone(v.tz);
  if (typeof window.setAudioFingerprintSeed === 'function') window.setAudioFingerprintSeed(v.audio);
  if (typeof window.setScreenDimensions === 'function') window.setScreenDimensions(v.sw, v.sh);
  if (typeof window.setCanvasSeed === 'function') window.setCanvasSeed(v.canvas);
  if (typeof window.setWebGLRenderer === 'function') window.setWebGLRenderer(v.gpu);
}, { tz: 'America/New_York', audio: 11111, sw: 1920, sh: 1080, canvas: 44444, gpu: 'Intel Iris OpenGL Engine' });

// Context B — appears as a Tokyo user with Apple GPU (fully isolated from A)
const ctxB = await browser.newContext();
await ctxB.addInitScript((v) => {
  if (typeof window.setTimezone === 'function') window.setTimezone(v.tz);
  if (typeof window.setAudioFingerprintSeed === 'function') window.setAudioFingerprintSeed(v.audio);
  if (typeof window.setScreenDimensions === 'function') window.setScreenDimensions(v.sw, v.sh);
  if (typeof window.setCanvasSeed === 'function') window.setCanvasSeed(v.canvas);
  if (typeof window.setWebGLRenderer === 'function') window.setWebGLRenderer(v.gpu);
}, { tz: 'Asia/Tokyo', audio: 99999, sw: 2560, sh: 1440, canvas: 88888, gpu: 'Apple M1' });
```

---

## Architecture

### Per-Context Storage

All patches share `RoverfoxStorageManager`, a thread-safe C++ key-value store keyed by `userContextId`. Each Playwright context gets a unique `userContextId` via Firefox's container identity system.

**Write path:**
1. `window.setXxx()` is called on a page
2. The function resolves `userContextId` from the window's `BrowsingContext`
3. The value is stored in RoverfoxStorageManager's local HashMap cache (thread-safe `nsTHashMap` protected by `Mutex`)
4. The value is also written to Firefox Preferences (`Preferences::SetCString`) with a `roverfox.s.` prefix — all value types (uint32, bool, string) are serialized as CString internally
5. In content processes, values are sent to the parent (browser) process via sync IPC (`SendRoverfoxStoragePut`)
6. Some patches also store the value under ucid=0 as a global fallback — this ensures workers that cannot resolve a specific `userContextId` can still read the value. Patches with ucid=0 fallback: **audio**, **canvas**, **navigator** (all 4 functions), **timezone**, **webgl**. Patches without: font-spacing, screen, font-list, speech-voices, webrtc-ip

**Read path (3-tier fallback):**
1. **Local cache** — in-process `nsTHashMap` protected by `Mutex` (fastest, same-process reads)
2. **Firefox Preferences** — `Preferences::GetCString()` reads from the shared pref store, which Firefox automatically syncs across all content processes
3. **Sync IPC to parent** — if Preferences returns empty (e.g. pref not yet synced), `SendRoverfoxStorageGet` makes a synchronous IPC call to the parent process to read the value directly. Only runs on the main thread (`NS_IsMainThread()` guard)

This 3-tier architecture ensures per-context values are available in all processes — the main page's content process, worker content processes, and the parent process itself.

### Cross-Process Storage (`cross-process-storage.patch`)

Firefox runs content in separate processes (Fission). Without special handling, `RoverfoxStorageManager`'s in-process HashMap would be empty in worker processes. The `cross-process-storage.patch` solves this with three components:

**1. IPDL Sync Messages** — Two new messages in `PContent.ipdl`:
- `sync RoverfoxStoragePut(nsCString prefName, nsCString value)` — writes a value to the parent process. Synchronous to guarantee the value is available before any worker process starts.
- `sync RoverfoxStorageGet(nsCString prefName) returns (nsCString value)` — reads a value from the parent process. Used as a fallback when the local cache and Preferences are empty.

**2. Parent Process Handlers** — `ContentParent.cpp` implements both handlers with a security check: only pref names starting with `"roverfox.s."` are allowed. All other names are silently ignored. The parent calls `Preferences::SetCString()` / `Preferences::GetCString()` to persist values.

**3. Preference Whitelist** — Firefox strips dynamically-created String prefs from content processes via `ShouldSanitizePreference()`. The patch adds `PREF_LIST_ENTRY("roverfox.s.")` to `sDynamicPrefOverrideList` in `Preferences.cpp`, whitelisting all roverfox storage prefs for cross-process sync.

**Thread safety:** Sync IPC can only be called from the main thread. A `NS_IsMainThread()` guard in all three getter methods (GetUint, GetBool, GetString) prevents crashes when non-main threads (HarfBuzz font rendering, compositor) try to read values. Non-main threads fall back to the local cache and Preferences only.

**Modified files:** `ContentParent.cpp/h`, `PContent.ipdl`, `ipc/ipdl/sync-messages.ini`, `modules/libpref/Preferences.cpp`

### Self-Destruct

Every `window.setXxx()` function uses a dual self-destruct:

1. **`JS_DeleteProperty`** — removes the function from the current window object immediately after the call
2. **`DisableFunction`** — marks the function as disabled in storage, so it won't appear on future pages in the same context

This makes the functions invisible to any fingerprinting script that checks for their existence.

### userContextId Resolution

All patches resolve `userContextId` from `BrowsingContext` directly:

```cpp
if (BrowsingContext* bc = win->GetBrowsingContext()) {
  userContextId = bc->OriginAttributesRef().mUserContextId;
}
```

`BrowsingContext` is the canonical source — it's set at context creation time, before DocShell or Document attributes are populated. This ensures correct resolution even during early page lifecycle events.

Workers resolve `userContextId` via `WorkerPrivate::GetOriginAttributes()`, which inherits from the creating context's BrowsingContext.

### Configuration (`settings/camoufox.cfg`)

The `camoufox.cfg` file sets Firefox preferences at startup (before `prefs.js` is loaded). Key settings:

- `fission.autostart = true` — keeps Fission (site isolation) enabled. Some WAFs can detect disabled Fission. With the cross-process storage patch, Fission works correctly because values are synced across all content processes.
- `fission.webContentIsolationStrategy = 1` — standard isolation strategy.
- `dom.ipc.processPrelaunch.enabled = false` — prevents Firefox from reusing pre-launched content processes that may have stale overridden values (locale, timezone). Ensures each new content process starts clean.
- No `dom.ipc.processCount` override — Firefox uses its default multi-process behavior. The cross-process storage patch eliminates the need for `processCount=1`.

---

## Patch Details

### 1. anti-font-fingerprinting.patch

**Controls:** Canvas `measureText()` letter spacing — makes text width measurements unique per context.

**How it works:** Stores a seed per context, then applies a deterministic spacing transformation in HarfBuzz (the text shaping engine). The seed is propagated through the entire text rendering pipeline: `nsTextFrame` → `gfxFont` → `gfxTextRun` → `gfxHarfBuzzShaper`.

The transformation adds ~0.0-0.1 em of extra spacing using a Linear Congruential Generator seeded with the profile's value. Same seed always produces the same spacing.

**Also provides:** `RoverfoxStorageManager` — the shared storage layer used by all other per-context patches. See the [Cross-Process Storage](#cross-process-storage-cross-process-storagepatch) section for how it works across processes.

**WordCacheKey fix:** Added `mUserContextId` to the `WordCacheKey` struct in `gfxFont.h`. Without this, Firefox's shaped word cache shared results across contexts — context 1's font spacing result would be returned for context 2 (a cache hit based on text content alone). The fix adds `mUserContextId` to both constructors, the hash computation (via `* 0x1000000`), and the `match()` comparison, ensuring each context has its own cache entries. Also adds `GetUserContextId()` virtual method to `gfxShapedText` and `gfxShapedWord` so the context ID propagates through the text run pipeline.

**API:**
```javascript
window.setFontSpacingSeed(12345678); // uint32 seed
```

**New C++ files:** `FontSpacingSeedManager.h/cpp`, `RoverfoxStorageManager.h/cpp`
**Modified Firefox files (22):** `nsGlobalWindowInner.cpp/h`, `CanvasRenderingContext2D.cpp`, `OffscreenCanvas.cpp`, `WorkerPrivate.h`, `Window.webidl`, `moz.build` (dom/base), `gfxHarfBuzzShaper.cpp`, `gfxTextRun.cpp/h`, `gfxFont.cpp/h`, `nsFontMetrics.cpp/h`, `nsLayoutUtils.cpp/h`, `nsPresContext.cpp`, `nsTextFrame.cpp`, `MathMLTextRunFactory.cpp`, `nsTextRunTransformations.cpp`, `nsMathMLChar.cpp`, `FontVisibilityProvider.h`

---

### 2. audio-fingerprint-manager.patch

**Controls:** Audio fingerprint hash — websites generate a tone, process it through Web Audio API, and hash the output buffer. This patch makes every context produce a different hash.

**How it works:** Stores a seed per context, then applies a deterministic transformation (0.8% variance with non-linear polynomial twist) to audio sample data. Hooks **all 6 methods** that fingerprinting scripts use:

| Method | Vector |
|--------|--------|
| `AudioBuffer.getChannelData()` | Raw audio samples (most common) |
| `AudioBuffer.copyFromChannel()` | Alternative buffer read |
| `AnalyserNode.getFloatFrequencyData()` | Frequency spectrum |
| `AnalyserNode.getByteFrequencyData()` | Byte frequency data |
| `AnalyserNode.getFloatTimeDomainData()` | Time-domain waveform |
| `AnalyserNode.getByteTimeDomainData()` | Byte waveform |

Covering all 6 is critical — Brave was bypassed in 2024 because they only protected `getChannelData()` and attackers switched to AnalyserNode methods.

**Worker support:** The 4 AnalyserNode hooks include an explicit `WorkerPrivate` fallback for resolving `userContextId` when running in Web Worker contexts. The 2 AudioBuffer hooks (`getChannelData`, `copyFromChannel`) rely on the ucid=0 global fallback instead — `SetAudioFingerprintSeed()` stores the seed under both the real `userContextId` AND ucid=0, so workers without a window reference still find the correct seed.

**MaskConfig fallback:** If no per-context seed is set, checks `MaskConfig::GetUint32("audio:seed")` from `CAMOU_CONFIG`. This enables the Camoufox Python package to set a global audio seed without per-context JavaScript.

**API:**
```javascript
window.setAudioFingerprintSeed(87654321); // uint32 seed
```

**New C++ files:** `AudioFingerprintManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `AudioBuffer.cpp`, `AnalyserNode.cpp`, `Window.webidl`, `moz.build` (dom/base + dom/media/webaudio)

---

### 3. timezone-spoofing.patch

**Controls:** All time-related APIs — `Date`, `Intl.DateTimeFormat`, `toLocaleString()`, etc. Each context can report a different IANA timezone.

**How it works:** This is the only patch that hooks into SpiderMonkey (Firefox's JS engine). It restores per-realm `DateTimeInfo` support that Playwright had disabled, and adds a `JS::SetRealmTimeZoneOverride()` API. Each JS Realm (one per context) gets its own timezone.

**Navigation persistence:** Hooks `nsGlobalWindowOuter::SetNewDocument()` to automatically re-apply the stored timezone when the user navigates to a new page within the same context. Without this, navigations would create a new Realm that loses the override.

**Worker propagation:** Hooks `WorkerPrivate::GetOrCreateGlobalScope()` to apply the stored timezone to the worker's JS Realm. Dedicated Workers, Shared Workers, and Service Workers all create their own Realm that doesn't inherit the parent page's timezone — this hook ensures they stay consistent.

**Process-wide fallback:** `SetTimezone()` also calls `JS::SetTimeZoneOverride()` as a global process-wide fallback, ensuring workers that create their Realm before the per-realm hook fires still get the correct timezone. Additionally stores under ucid=0 so cross-process reads find a value.

**API:**
```javascript
window.setTimezone('America/New_York'); // IANA timezone ID
// Invalid timezone IDs throw a TypeError
```

**New C++ files:** `TimezoneManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `nsGlobalWindowOuter.cpp`, `WorkerPrivate.cpp`, `Window.webidl`, `moz.build`
**Modified SpiderMonkey files:** `js/public/Date.h`, `js/src/vm/DateTime.h/cpp`, `js/src/vm/Realm.cpp`

---

### 4. screen-spoofing.patch

**Controls:** `screen.width`, `screen.height`, `screen.colorDepth`, and related CSS media queries.

**How it works:** Stores dimensions per context, then hooks `nsScreen::GetRect()` with a three-tier fallback: per-context values -> global `CAMOU_CONFIG` -> vanilla Firefox.

Also hooks `nsMediaFeatures.cpp` so CSS media queries like `matchMedia('(device-width: 1920px)')` return results consistent with `screen.width`. Without this, fingerprinters can detect a mismatch between the JavaScript API and CSS media queries.

This replaces the old `screen-hijacker.patch` (which only supported global config). It includes the same global `CAMOU_CONFIG` fallback, so it works for both single-context and multi-context use cases.

**API:**
```javascript
window.setScreenDimensions(1920, 1080); // width, height
window.setScreenColorDepth(24);         // bits per pixel
```

**New C++ files:** `ScreenDimensionManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `nsScreen.cpp`, `nsDeviceContext.cpp`, `nsMediaFeatures.cpp`, `Window.webidl`, `moz.build`

---

### 5. webrtc-ip-spoofing.patch

**Controls:** All WebRTC IP leak vectors. Replaces real IPs in ICE candidates, SDP, and stats with a configured proxy exit IP.

**How it works:** Stores an IPv4 and optional IPv6 per context, then hooks 5 WebRTC vectors:

| Vector | Hook |
|--------|------|
| SDP (local/remote description) | `SanitizeSDPForIPLeak()` — regex-replaces IPs line-by-line |
| ICE candidate strings | `SpoofCandidateIP()` in `CandidateReady()` |
| ICE candidate properties | `.address`, `.relatedAddress` spoofed before reaching JS |
| `getStats()` API | Sanitizes `mIceCandidateStats[].mAddress` in async callback |
| Default candidate addresses | `UpdateDefaultCandidate()` sanitization |

Also forces `default_address_only` mode when spoofing is active (limits ICE candidate gathering) and skips masking for loopback/link-local/private IPs.

IPv6 regex handles all compressed formats: `::1`, `fe80::`, `2001:db8::1`, full 8-group, etc.

**API:**
```javascript
window.setWebRTCIPv4('203.0.113.1');   // proxy exit IPv4
window.setWebRTCIPv6('2001:db8::1');   // proxy exit IPv6 (optional)
```

**New C++ files:** `WebRTCIPManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `PeerConnectionImpl.cpp/h`, `Window.webidl`, `moz.build` (dom/base + dom/media/webrtc)

---

### 6. navigator-spoofing.patch

**Controls:** `navigator.platform`, `navigator.oscpu`, `navigator.hardwareConcurrency`, `navigator.userAgent`, and `navigator.appVersion` — per-context with global `CAMOU_CONFIG` fallback.

**How it works:** Stores values per context via `NavigatorManager`, then hooks these Navigator methods with a three-tier fallback: per-context values -> global `CAMOU_CONFIG` -> vanilla Firefox:

| Hook | Per-context | Global fallback | Worker hook |
|------|-------------|-----------------|-------------|
| `Navigator::GetPlatform()` | YES | YES | `WorkerNavigator::GetPlatform()` |
| `Navigator::GetOscpu()` | YES | YES | No (oscpu not exposed in workers) |
| `Navigator::HardwareConcurrency()` | YES | YES | `WorkerNavigator::HardwareConcurrency()` |
| `Navigator::GetUserAgent()` | YES | YES (MaskConfig) | `WorkerNavigator::GetUserAgent()` |
| `Navigator::GetAppVersion()` | No | YES (MaskConfig) | No |

**`setNavigatorUserAgent`:** Stores a per-context User-Agent string so workers report the correct UA. Without this, workers on Linux would read the global `CAMOU_CONFIG` UA (which may be a Linux UA) even when the per-context fingerprint specifies macOS. The WorkerNavigator hook checks `NavigatorManager` BEFORE `MaskConfig`, ensuring workers match the main page.

**Worker propagation:** Hooks `WorkerNavigator::GetPlatform()`, `WorkerNavigator::HardwareConcurrency()`, and `WorkerNavigator::GetUserAgent()` so Web Workers inherit per-context values. Workers resolve `userContextId` via `WorkerPrivate::GetOriginAttributes()`.

**Lazy timezone init:** Also adds `EnsureGlobalTimezoneInitialized()` — a lazy initializer that reads `timezone` from `CAMOU_CONFIG` on first access to `GetPlatform()` or `HardwareConcurrency()`. This replaced a static initializer that caused SIGSEGV crashes because SpiderMonkey wasn't ready at init time.

**API:**
```javascript
window.setNavigatorPlatform('Win32');              // navigator.platform
window.setNavigatorOscpu('Windows NT 10.0; Win64; x64');  // navigator.oscpu
window.setNavigatorHardwareConcurrency(8);         // navigator.hardwareConcurrency
window.setNavigatorUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) Gecko/20100101 Firefox/146.0');
```

**Global config fallback (no JavaScript needed):**
```json
{ "navigator.platform": "MacIntel", "navigator.hardwareConcurrency": 8, "navigator.appVersion": "5.0 (Macintosh)", "timezone": "America/Los_Angeles" }
```

**New C++ files:** `NavigatorManager.h/cpp`
**Modified Firefox files:** `Navigator.cpp`, `WorkerNavigator.cpp`, `nsGlobalWindowInner.cpp/h`, `Window.webidl`, `moz.build`

---

### 7. webgl-spoofing.patch

**Controls:** `UNMASKED_VENDOR_WEBGL` and `UNMASKED_RENDERER_WEBGL` — the WebGL debug extension parameters that reveal GPU hardware. These are one of the strongest fingerprint vectors since GPU model + driver version is highly unique.

**How it works:** Stores vendor and renderer strings per context via `WebGLParamsManager`, then hooks `ClientWebGLContext::GetParameter()` to intercept `WEBGL_debug_renderer_info` queries. Three-tier fallback: per-context values -> global `CAMOU_CONFIG` -> real hardware values.

Note: `GL_VENDOR` and `GL_RENDERER` (without the debug extension) already return `"Mozilla"` universally in Firefox — those don't need spoofing.

**Global MaskConfig scope:** Beyond per-context vendor/renderer, this patch also includes comprehensive global `CAMOU_CONFIG` spoofing for many other WebGL parameters — context attributes, shader precision, extensions, enabled states, and array parameters. These global overrides apply to all contexts equally and don't require per-context JavaScript.

**Worker support:** Includes a `WorkerPrivate` fallback (via a `GetUserContextId()` helper on `ClientWebGLContext`) for resolving `userContextId` when `GetParameter()` is called from an OffscreenCanvas context in a Web Worker.

**Self-destruct:** Each function (`setWebGLVendor`, `setWebGLRenderer`) has its own disabled flag and removes only itself after the first call. Both should be called from your init script to ensure consistent vendor/renderer pairing.

**API:**
```javascript
window.setWebGLVendor('Intel Inc.');              // UNMASKED_VENDOR_WEBGL
window.setWebGLRenderer('Intel Iris OpenGL Engine');  // UNMASKED_RENDERER_WEBGL
```

**New C++ files:** `WebGLParamsManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `ClientWebGLContext.cpp`, `Window.webidl`, `moz.build`

---

### 8. canvas-spoofing.patch

**Controls:** Canvas 2D fingerprint hash — websites draw text, shapes, and gradients on a canvas, then call `toDataURL()` or `getImageData()` to hash the pixel output. GPU, driver, and font rendering differences make this hash highly unique.

**How it works:** Stores a seed per context via `CanvasFingerprintManager`, then hooks both canvas data extraction paths in `CanvasRenderingContext2D.cpp`:
- `GetImageBuffer()` — used by `toDataURL()` and `toBlob()`, returns pixels in **BGRA** format
- `GetImageData()` — used by `ctx.getImageData()`, returns pixels in **RGBA** format

The noise algorithm is **format-agnostic**: for each selected pixel, it iterates RGB channels (skipping alpha) and modifies the first non-zero channel by +/-1. This works correctly regardless of whether byte 0 is Red (RGBA) or Blue (BGRA).

**Zero-pixel preservation:** Channels with value 0 are skipped. This means `clearRect()` followed by `getImageData()` returns all zeros — no false noise on transparent pixels. This is important because CreepJS specifically tests for noise in cleared canvas regions as a detection vector.

**Noise is deterministic, not random:** Same seed always produces the same pixel modifications, so fingerprinters calling `toDataURL()` multiple times get identical results. This is critical — random noise is trivially detected by calling the API twice and comparing outputs.

**Worker support:** Includes a `WorkerPrivate` fallback for resolving `userContextId` when canvas operations happen in a Web Worker via OffscreenCanvas.

**MaskConfig fallback:** If no per-context seed is set, checks `MaskConfig::GetUint32("canvas:seed")` from `CAMOU_CONFIG`.

**API:**
```javascript
window.setCanvasSeed(55555555); // uint32 seed
```

**New C++ files:** `CanvasFingerprintManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `CanvasRenderingContext2D.cpp`, `Window.webidl`, `moz.build`

---

### 9. font-list-spoofing.patch

**Controls:** Which fonts appear "installed" to fingerprinting scripts. Websites detect fonts by measuring text widths (canvas `measureText()`) — if the width changes compared to a fallback font, the font is present. Each context can have a different subset of fonts.

**How it works:** Stores a set of allowed font names (lowercase) per context in `FontListManager`. Uses a **thread-local** `uint32_t` to propagate the context ID deep into the font resolution stack without changing any function signatures.

The hook is in `gfxPlatformFontList::FindAndAddFamiliesLocked()` — the single function that all font lookups pass through. When a font name isn't in the allowed set for the current context, the function returns `false` (font "not found"), and CSS falls back to the next font in `font-family`.

**Thread-local context propagation:**
```
1. Entry point sets thread_local = userContextId
   - FontFaceSet::Check() / FontFaceSet::Load() (JS API: document.fonts)
   - gfxFontGroup::EnsureFontList() (CSS rendering + canvas text)
2. Deep in font stack: FindAndAddFamiliesLocked() reads thread_local
   -> If font not in allowed list -> return false
3. Entry point resets thread_local = 0
```

An RAII guard (`AutoFontListContext`) handles the set/reset automatically.

**Why thread-local?** `FindAndAddFamiliesLocked()` is called from 20+ locations including font fallback, CSS matching, and generic font resolution. Threading a parameter through all callers would require modifying ~50 functions.

**Storage architecture:** Font list data is stored in a local `static nsTHashMap` with `Mutex` protection inside `FontListManager` — NOT in `RoverfoxStorageManager`. This means font list data is per-process only and does not sync cross-process via Preferences/IPDL. Only the disabled flag (for self-destruct) uses `RoverfoxStorageManager`.

**Worker limitation:** Font list filtering does **not** work in Web Workers. The `thread_local` context is only set from window-level entry points (`FontFaceSet::Check/Load`, `gfxFontGroup::EnsureFontList`). Worker threads never set the thread-local, so `FindAndAddFamiliesLocked()` always sees ucid=0 (no filtering). In practice this is acceptable because workers rarely enumerate fonts — fingerprinters use `document.fonts` and canvas `measureText()`, both of which run on the main thread.

**API:**
```javascript
window.setFontList('Arial,Helvetica,Georgia,Courier New,Verdana');
// Comma-separated list of font names. Fonts NOT in this list will appear "not installed".
// Case-insensitive matching. Essential web fonts (serif/sans-serif/monospace fallbacks) always work.
```

**New C++ files:** `FontListManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `gfxPlatformFontList.cpp`, `gfxTextRun.cpp`, `FontFaceSet.cpp`, `Window.webidl`, `moz.build`

---

### 10. speech-voices-spoofing.patch

**Controls:** `speechSynthesis.getVoices()` — the list of installed text-to-speech voices. This varies by OS and installed language packs, making it a fingerprinting vector. Each context can expose a different subset of voices.

**How it works:** Stores a set of allowed voice names per context in `SpeechVoicesManager`. Hooks `SpeechSynthesis::GetVoices()` to filter the real voice list, returning only voices whose names match the allowed set.

**API:**
```javascript
window.setSpeechVoices('Microsoft David,Samantha,Alex');
// Comma-separated list of voice names. Only voices matching these names will
// appear in getVoices(). If the browser doesn't have a matching voice installed,
// it's simply omitted from the result (no error).
```

**New C++ files:** `SpeechVoicesManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp/h`, `SpeechSynthesis.cpp`, `Window.webidl`, `moz.build`

---

### 11. cross-process-storage.patch

**Controls:** Cross-process synchronization of all per-context fingerprint values. This is an infrastructure patch — it has no JavaScript API of its own. It enables all other per-context patches to work correctly when Firefox runs content in multiple processes (Fission).

**How it works:** Adds two synchronous IPDL messages to `PContent.ipdl`:

```
child -> parent:
  sync RoverfoxStoragePut(nsCString prefName, nsCString value)
  sync RoverfoxStorageGet(nsCString prefName) returns (nsCString value)
```

When `window.setXxx()` stores a value, `RoverfoxStorageManager` writes it locally AND sends it to the parent process via `SendRoverfoxStoragePut`. The parent stores it in Firefox Preferences, which automatically syncs to all content processes. When a worker process needs a value, it checks the local cache, then Preferences, then falls back to `SendRoverfoxStorageGet` for a direct parent read.

**Security:** Both parent handlers (`RecvRoverfoxStoragePut`, `RecvRoverfoxStorageGet`) validate that the pref name starts with `"roverfox.s."`. Non-conforming names are silently rejected.

**Why sync?** `RoverfoxStoragePut` must be synchronous so the value is guaranteed to be in the parent's Preferences store before any worker content process starts. An async message would create a race condition where a worker reads an empty value.

**Modified files:** `ContentParent.cpp/h`, `PContent.ipdl`, `ipc/ipdl/sync-messages.ini`, `modules/libpref/Preferences.cpp`

---

## Global-Only Patches (No JavaScript API)

These patches read from `CAMOU_CONFIG` at startup and apply to all contexts equally. They don't expose any `window.setXxx()` functions.

### geolocation-spoofing.patch

**What it adds:** Auto-grants geolocation permission when coordinates are configured, and returns the configured lat/lon instead of making real network geolocation requests. Hooks `Geolocation.cpp` (permission), `GeolocationPosition.cpp` (coordinate getters), and `NetworkGeolocationProvider.sys.mjs` (network provider bypass).

For per-context geolocation, use Playwright's built-in `context.setGeolocation()` instead — it's already per-context via Juggler.

```json
{ "geolocation:latitude": 40.7128, "geolocation:longitude": -74.006, "geolocation:accuracy": 100 }
```

**Modified:** `Geolocation.cpp`, `GeolocationPosition.cpp`, `NetworkGeolocationProvider.sys.mjs`, `moz.build`

### locale-spoofing.patch

**What it adds:** Overrides `navigator.language`, `Accept-Language` header, and `Intl` locale APIs. Hooks `browser-init.js` (sets `intl.accept_languages` pref), `Locale.cpp/h` (language/script/region getters), and `OSPreferences.cpp` (system locale).

```json
{ "navigator.language": "en-US", "locale:all": "en-US", "locale:language": "en", "locale:region": "US" }
```

**Modified:** `browser-init.js`, `Locale.cpp`, `Locale.h`, `OSPreferences.cpp`

### force-default-pointer.patch

**What it adds:** Simplifies `GetPointerCapabilities()` in `nsMediaFeatures.cpp` to always return `PointerCapabilities::Fine` on desktop. Prevents CSS `pointer` media queries from revealing the actual hardware environment.

**Modified:** `nsMediaFeatures.cpp`

---

## Build Notes

**SOURCES vs UNIFIED_SOURCES:** Most new `.cpp` manager files use `SOURCES` (separate compilation) in `moz.build` to avoid namespace pollution (`mozilla::dom::mozilla::dom::`) that occurs when files including `RoverfoxStorageManager.h` are concatenated in unified builds. Currently in `SOURCES`: `AudioFingerprintManager.cpp`, `WebRTCIPManager.cpp`, `NavigatorManager.cpp`, `WebGLParamsManager.cpp`, `CanvasFingerprintManager.cpp`, `FontListManager.cpp`, `SpeechVoicesManager.cpp`. Four files use `UNIFIED_SOURCES` instead: `FontSpacingSeedManager.cpp`, `RoverfoxStorageManager.cpp` (both from `anti-font-fingerprinting.patch`), `TimezoneManager.cpp` (from `timezone-spoofing.patch`), and `ScreenDimensionManager.cpp` (from `screen-spoofing.patch`) — these were written before the SOURCES pattern was established and happen to compile without namespace issues in their alphabetical position.

**EXPORTS sort conflicts:** Each patch uses a separate `EXPORTS.mozilla.dom += ["Header.h"]` statement near its `SOURCES` block, rather than inserting into the main sorted EXPORTS list. This avoids sort conflicts when multiple patches add headers at similar alphabetical positions.

**WebIDL:** Each `window.setXxx()` function needs its own `partial interface Window` block. Combining multiple in one block triggers namespace pollution in the binding generator.

**Patch independence:** All patches apply independently to vanilla Firefox. Context lines in hunks reference unpatched source files. Patches apply alphabetically and use fuzzy matching for line shifts caused by other patches.

**camoufox.cfg:** The `settings/camoufox.cfg` file sets `fission.autostart=true`, `fission.webContentIsolationStrategy=1`, and `dom.ipc.processPrelaunch.enabled=false`. No `dom.ipc.processCount` override is needed — the cross-process storage patch enables all per-context values to sync across Firefox's default multi-process architecture.

---

## Bundled Fontconfig & Fonts

Camoufox bundles OS-specific fontconfig configurations and font files so that font rendering and font detection produce OS-consistent results, regardless of the host system's installed fonts.

**Directory structure** (in `bundle/`, packaged via Makefile `--includes`):

```
bundle/
├── fontconfig/
│   ├── macos/fonts.conf    ← sans-serif→Helvetica, monospace→Menlo, cursive→Apple Chancery
│   ├── linux/fonts.conf    ← sans-serif→Arimo, monospace→Cousine
│   └── windows/fonts.conf  ← sans-serif→Arial, monospace→Consolas
└── fonts/
    ├── macos/              ← 355 font files (Helvetica, Menlo, PingFang, SF Pro, etc.)
    ├── linux/              ← 143 font files (Noto Sans, Arimo, Cousine, Tinos, etc.)
    └── windows/            ← 144 font files (Segoe UI, Tahoma, Cambria, etc.)
```

**What each `fonts.conf` defines:**
- **Generic family defaults** — `sans-serif`, `serif`, `monospace`, `cursive`, `fantasy`, `system-ui` mapped to OS-appropriate fonts
- **TTC weight-variant aliases** — macOS TrueType Collections register with weight suffixes ("PingFang HK Light") but Linux fontconfig only sees the base name. Aliases rewrite queries so CreepJS marker font detection works cross-platform.
- **MONO redirect** — "MONO" is a Linux-only font. Redirected to the OS-appropriate monospace (Menlo on macOS, Cousine on Linux) to prevent host OS leakage.
- **Rendering settings** — Standardized antialias, hinting, and lcdfilter across all configs.

**Runtime path rewriting:** At launch time, `createRuntimeFontconfig()` reads the bundled `fonts.conf` and rewrites font directory paths to absolute paths pointing at the correct OS-specific font subdirectory (e.g. `fonts/macos/` for macOS profiles). This prevents cross-OS font leakage (e.g. Linux font Arimo appearing in a macOS profile) and avoids CWD-dependent path issues.

**`FONTCONFIG_PATH` environment variable:** Must be set when launching Camoufox on Linux. Points to the correct OS-specific fontconfig directory (e.g. `camoufox/fontconfig/macos/`). The Go launcher sets this dynamically based on the target OS.

---

## Python Library Changes

The Camoufox Python package (`pythonlib/`) generates fingerprints for both `NewBrowser` (global CAMOU_CONFIG) and `NewContext` (per-context init script). **BrowserForge is the default for both paths.** Real fingerprint presets are available as an opt-in alternative. Both paths can also take `fingerprint_seed` to reuse the same Camoufox-generated identity values across runs.

### Fingerprint Source Priority

| Path | Default | Opt-in Alternative |
|------|---------|-------------------|
| **NewBrowser** (`launch_options()` in `utils.py`) | BrowserForge synthetic | Pass `fingerprint_preset=True` or a preset dict |
| **NewContext** (`generate_context_fingerprint()` in `fingerprints.py`) | BrowserForge synthetic | Pass `preset=dict` explicitly |

### Persistent Fingerprint Seeds

`fingerprint_seed` accepts `str`, `int`, or `bytes`. It derives independent
sub-seeds for each random fingerprint domain so one stable seed can reproduce
the same identity while keeping BrowserForge, WebGL, font, voice, audio, canvas,
and screen-offset sampling separate.

```python
from camoufox.sync_api import Camoufox, NewContext

with Camoufox(fingerprint_seed="account-123") as browser:
    context = NewContext(browser, fingerprint_seed="account-123:context-2")
```

The seed only controls generated fingerprint values. It does not persist
cookies, local storage, cache, or Playwright browser profile state.

Persistent browser state should be handled separately with Playwright's
persistent context support. Reuse the same `fingerprint_seed` and the same
`user_data_dir` when cookies/storage should remain tied to the same generated
identity:

```python
from pathlib import Path

from camoufox.sync_api import Camoufox

with Camoufox(
    persistent_context=True,
    user_data_dir=Path("profiles/account-123"),
    fingerprint_seed="account-123",
) as context:
    ...
```

### What Each Path Sets

| Property | Source | Notes |
|----------|--------|-------|
| UA, platform, HWC, oscpu | BrowserForge or preset | UA version patched to match Camoufox Firefox version |
| Screen dims, colorDepth | BrowserForge or preset | Viewport adjusted by -28px for browser chrome |
| WebGL vendor/renderer | Preset values or `sample_webgl()` from `webgl_data.db` | BrowserForge does NOT generate WebGL (commented out in `browserforge.yml`). Synthetic paths use OS-weighted probability sampling, deterministic when `fingerprint_seed` is supplied. Preset paths use preset WebGL values when present. |
| Font list | `_generate_random_font_subset()` | Random 30-78% of OS fonts, or deterministic when `fingerprint_seed` is supplied. Essential + marker fonts always included. Normally generated fresh per call unless seeded; preset fonts are only used as a fallback if OS font generation fails. |
| Font spacing seed | Random uint32, or derived from `fingerprint_seed` | Excludes 0 (0 = no-op in C++) |
| Audio seed | Random uint32, or derived from `fingerprint_seed` | Excludes 0 |
| Canvas seed | Random uint32, or derived from `fingerprint_seed` | Excludes 0 |
| Timezone | From preset, or Intl.DateTimeFormat fallback in init script | NewBrowser: from preset or geolocation detection. NewContext: preset or browser default. |
| Speech voices | `_generate_random_voice_subset()` | Random 40-80% of OS voices, or deterministic when `fingerprint_seed` is supplied. Essential voices always included. macOS: 6 essentials + random subset of ~184. Windows: all voices (too few to subset). Linux: empty (no native voices). Normally generated fresh per call unless seeded; preset voices are only used as a fallback if OS voice generation fails. |
| WebRTC IP | Not set by default | User sets via `window.setWebRTCIPv4()`. NewContext init script defaults to empty string `""` |
| Geolocation | User parameter or geoip detection | Via Playwright `context.setGeolocation()` |

### Key Files

**`fingerprints.py`** — Per-context fingerprint generation:
- `generate_context_fingerprint()` — main API. Returns `{init_script, context_options, config, preset}`
- `fingerprint_seed.py` — derives independent deterministic sub-seeds for BrowserForge, WebGL, fonts, voices, and noise seeds
- `from_preset()` — converts real preset to CAMOU_CONFIG format
- `from_browserforge()` — converts BrowserForge Fingerprint to CAMOU_CONFIG using `browserforge.yml` mappings
- `_build_init_script()` — generates JavaScript IIFE calling 15 `window.setXxx()` functions with `typeof` guards (`setWebRTCIPv6` is not included — IPv6 is optional and rarely set)
- `_generate_random_font_subset()` — random by default, deterministic when passed a seeded RNG (essential + marker fonts always included)
- `_generate_random_voice_subset()` — random by default, deterministic when passed a seeded RNG (essential voices always included, OS-aware)

**`utils.py`** — Global browser launch configuration:
- `launch_options()` — builds CAMOU_CONFIG env var, Playwright args, and Firefox prefs
- `fingerprint_seed` — optional stable seed for launch-level BrowserForge, preset, font, voice, WebGL, history, and noise generation
- Font subset generated via same `_generate_random_font_subset()` function
- Voice subset generated via same `_generate_random_voice_subset()` function
- WebGL sampled via same `sample_webgl()` function
- Config validated against `properties.json` before serialization

**`fingerprint-presets.json`** — Bundled real fingerprints organized by OS (macOS, Windows, Linux). Each preset includes navigator properties, screen dimensions, WebGL params, speech voices, and timezone. Fonts and voices are normally generated from OS lists, deterministic when seeded, and preset values are fallback-only if OS generation fails.

**`fonts.json`** — Complete OS-specific font lists for random font subset generation.

**`voices.json`** — Complete OS-specific speech voice lists for random voice subset generation. macOS: 190 voices, Windows: 53 voices, Linux: empty. Format: `"Name:locale:type"` — names extracted at load time.

**`properties.json`** — Includes `audio:seed` and `canvas:seed` as `CAMOU_CONFIG` properties (uint type). These enable the MaskConfig fallback in the audio and canvas patches when using global config without per-context JavaScript.

**`camoufox.cfg`** — Sets `fission.autostart=true` and `dom.ipc.processPrelaunch.enabled=false`. No `dom.ipc.processCount` override needed with cross-process storage.

---

## Known Limitations

These patches control what JavaScript APIs report, but they cannot change how the underlying OS renders content. Several detection vectors operate below the browser layer and will leak the real OS identity:

| Vector | Why it can't be spoofed |
|--------|------------------------|
| **Font rendering** | macOS uses Core Text, Windows uses DirectWrite, Linux uses FreeType. Same font, same size, different subpixel hinting and glyph outlines. Canvas `measureText()` widths and `toDataURL()` hashes differ at the rendering engine level. |
| **Canvas device class** | GPU drivers produce OS-specific rasterization. A "MacIntel" profile running on Linux will have Linux GPU output — detectable by comparing canvas hashes against known-good samples per platform. |
| **Scrollbar rendering** | macOS overlay scrollbars vs Windows/Linux classic scrollbars affect layout metrics (`offsetWidth` with/without scrollbar) and are visible in screenshots. |
| **System color schemes** | CSS `prefers-color-scheme`, `AccentColor`, and system colors differ by OS and desktop environment. |
| **WebGL shader precision** | `getShaderPrecisionFormat()` returns driver-specific values that vary by OS + GPU combination. |

Advanced fingerprinting services (reCAPTCHA, hCaptcha, Kasada, etc.) cross-reference these signals against what `navigator.platform` and the User-Agent claim. A mismatch is a strong bot signal.

**Recommendation:** Always run Camoufox on the OS that matches the fingerprint profile. Use macOS fingerprints on macOS workers, Linux fingerprints on Linux workers. The per-context patches are designed to make each context look like a *different person on the same OS*, not to impersonate a different OS entirely.
