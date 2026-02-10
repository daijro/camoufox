# Per-Context Fingerprint Patches

Camoufox spoofs fingerprints globally via `CAMOU_CONFIG` — every browser context shares the same identity. These patches add **per-context isolation**, so each Playwright context can have a unique, deterministic fingerprint. This lets you run multiple concurrent sessions from a single Camoufox process without cross-context correlation.

## Quick Reference

| Function | Patch | What it controls |
|----------|-------|-----------------|
| `window.setFontSpacingSeed(seed)` | `anti-font-fingerprinting.patch` | Canvas `measureText()` letter spacing |
| `window.setAudioFingerprintSeed(seed)` | `audio-fingerprint-manager.patch` | Audio buffer/analyser fingerprint hash |
| `window.setTimezone(tz)` | `timezone-spoofing.patch` | `Date`, `Intl.DateTimeFormat`, all time APIs |
| `window.setScreenDimensions(w, h)` | `screen-spoofing.patch` | `screen.width`, `screen.height` |
| `window.setScreenColorDepth(depth)` | `screen-spoofing.patch` | `screen.colorDepth` |
| `window.setWebRTCIPv4(ip)` | `webrtc-ip-spoofing.patch` | WebRTC ICE candidates, SDP, getStats() |
| `window.setWebRTCIPv6(ip)` | `webrtc-ip-spoofing.patch` | WebRTC IPv6 addresses |

All functions **self-destruct after the first call** — page JavaScript cannot detect them via `typeof window.setTimezone`.

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
}, {
  fontSpacingSeed: 12345678,
  audioFingerprintSeed: 87654321,
  timezone: 'America/New_York',
  screenWidth: 1920,
  screenHeight: 1080,
  screenColorDepth: 24,
  webrtcIPv4: '203.0.113.1',  // your proxy IP
});

const page = await context.newPage();
await page.goto('https://example.com');
// Fingerprints are already applied. Functions are already self-destructed.
```

**Why `addInitScript`?** Each `window.setXxx()` function self-destructs after the first call. On new tabs or navigations, Camoufox recreates the functions, and the init script calls them again before any page scripts can run. This ensures fingerprints are always applied and functions are never visible to website code.

**Why `typeof` guards?** The init script runs on every page load. If Camoufox is ever used without these patches (e.g. vanilla build), the guards prevent `ReferenceError`. They also handle the case where the function was already called and self-destructed.

### Running Multiple Isolated Contexts

```javascript
// Context A — appears as a New York user
const ctxA = await browser.newContext();
await ctxA.addInitScript((v) => {
  if (typeof window.setTimezone === 'function') window.setTimezone(v.tz);
  if (typeof window.setAudioFingerprintSeed === 'function') window.setAudioFingerprintSeed(v.audio);
  if (typeof window.setScreenDimensions === 'function') window.setScreenDimensions(v.sw, v.sh);
}, { tz: 'America/New_York', audio: 11111, sw: 1920, sh: 1080 });

// Context B — appears as a Tokyo user (fully isolated from A)
const ctxB = await browser.newContext();
await ctxB.addInitScript((v) => {
  if (typeof window.setTimezone === 'function') window.setTimezone(v.tz);
  if (typeof window.setAudioFingerprintSeed === 'function') window.setAudioFingerprintSeed(v.audio);
  if (typeof window.setScreenDimensions === 'function') window.setScreenDimensions(v.sw, v.sh);
}, { tz: 'Asia/Tokyo', audio: 99999, sw: 2560, sh: 1440 });
```

---

## Architecture

### Per-Context Storage

All patches share `RoverfoxStorageManager`, a thread-safe C++ key-value store keyed by `userContextId`. Each Playwright context gets a unique `userContextId` via Firefox's container identity system.

Flow:
1. `window.setXxx()` is called on a page
2. The function resolves `userContextId` from the window's `BrowsingContext`
3. The value is stored in `RoverfoxStorageManager` keyed by that ID
4. When Firefox needs the value (rendering, API calls, etc.), it checks per-context storage first, then falls back to global `CAMOU_CONFIG`

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

---

## Patch Details

### 1. anti-font-fingerprinting.patch

**Controls:** Canvas `measureText()` letter spacing — makes text width measurements unique per context.

**How it works:** Stores a seed per context, then applies a deterministic spacing transformation in HarfBuzz (the text shaping engine). The seed is propagated through the entire text rendering pipeline: `nsTextFrame` → `gfxFont` → `gfxTextRun` → `gfxHarfBuzzShaper`.

The transformation adds ~0.0–0.1 em of extra spacing using a Linear Congruential Generator seeded with the profile's value. Same seed always produces the same spacing.

**Also provides:** `RoverfoxStorageManager` — the shared storage layer used by all other per-context patches.

**API:**
```javascript
window.setFontSpacingSeed(12345678); // uint32 seed
```

**New C++ files:** `FontSpacingSeedManager.h/cpp`, `RoverfoxStorageManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `gfxHarfBuzzShaper.cpp`, `gfxTextRun.cpp/h`, `gfxFont.cpp/h`, `nsFontMetrics.cpp`, `CanvasRenderingContext2D.cpp`, `nsTextFrame.cpp`, `nsLayoutUtils.cpp`, `Window.webidl`, `moz.build`

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

**API:**
```javascript
window.setAudioFingerprintSeed(87654321); // uint32 seed
```

**New C++ files:** `AudioFingerprintManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `AudioBuffer.cpp`, `AnalyserNode.cpp`, `Window.webidl`, `moz.build` (dom/base + dom/media/webaudio)

**Build note:** Uses `SOURCES` (separate compilation) because the filename sorts before `BarProps.cpp`, which triggers namespace pollution in unified builds.

---

### 3. timezone-spoofing.patch

**Controls:** All time-related APIs — `Date`, `Intl.DateTimeFormat`, `toLocaleString()`, etc. Each context can report a different IANA timezone.

**How it works:** This is the only patch that hooks into SpiderMonkey (Firefox's JS engine). It restores per-realm `DateTimeInfo` support that Playwright had disabled, and adds a `JS::SetRealmTimeZoneOverride()` API. Each JS Realm (one per context) gets its own timezone.

**Navigation persistence:** Hooks `nsGlobalWindowOuter::SetNewDocument()` to automatically re-apply the stored timezone when the user navigates to a new page within the same context. Without this, navigations would create a new Realm that loses the override.

**API:**
```javascript
window.setTimezone('America/New_York'); // IANA timezone ID
// Invalid timezone IDs throw a TypeError
```

**New C++ files:** `TimezoneManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `nsGlobalWindowOuter.cpp`, `Window.webidl`, `moz.build`
**Modified SpiderMonkey files:** `js/public/Date.h`, `js/src/vm/DateTime.h/cpp`, `js/src/vm/Realm.cpp`

---

### 4. screen-spoofing.patch

**Controls:** `screen.width`, `screen.height`, `screen.colorDepth`, and related CSS media queries.

**How it works:** Stores dimensions per context, then hooks `nsScreen::GetRect()` with a three-tier fallback: per-context values → global `CAMOU_CONFIG` → vanilla Firefox. Also hooks `nsDeviceContext` and CSS media features for consistency.

This replaces the old `screen-hijacker.patch` (which only supported global config). It includes the same global `CAMOU_CONFIG` fallback, so it works for both single-context and multi-context use cases.

**API:**
```javascript
window.setScreenDimensions(1920, 1080); // width, height
window.setScreenColorDepth(24);         // bits per pixel
```

**New C++ files:** `ScreenDimensionManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `nsScreen.cpp`, `nsDeviceContext.cpp`, `nsMediaFeatures.cpp`, `Window.webidl`, `moz.build`

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
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `PeerConnectionImpl.cpp/h`, `Window.webidl`, `moz.build` (dom/base + dom/media/webrtc)

**Build note:** Uses `SOURCES` (separate compilation) like audio-fingerprint-manager.

---

## Global-Only Patches (No JavaScript API)

These patches read from `CAMOU_CONFIG` at startup and apply to all contexts equally. They don't expose any `window.setXxx()` functions.

### navigator-spoofing.patch

**What it adds:** Hooks `Navigator::GetPlatform()` and `Navigator::HardwareConcurrency()` in the main window's `Navigator.cpp`. The existing `fingerprint-injection.patch` only hooked `WorkerNavigator.cpp` (Web Workers), so the main window was missing these overrides.

Also adds `EnsureGlobalTimezoneInitialized()` — a lazy initializer that reads `timezone` from `CAMOU_CONFIG` on first access. This replaced a static initializer that caused SIGSEGV crashes because SpiderMonkey wasn't ready at init time.

```json
{ "navigator.platform": "MacIntel", "navigator.hardwareConcurrency": 8, "timezone": "America/Los_Angeles" }
```

**Modified:** `Navigator.cpp`

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

**SOURCES vs UNIFIED_SOURCES:** New `.cpp` files that include `RoverfoxStorageManager.h` and sort alphabetically before `BarProps.cpp` must use `SOURCES` (separate compilation) in `moz.build`. This avoids namespace pollution (`mozilla::dom::mozilla::dom::`) caused by unified build concatenation. Currently applies to: `AudioFingerprintManager.cpp`, `WebRTCIPManager.cpp`.

**WebIDL:** Each `window.setXxx()` function needs its own `partial interface Window` block. Combining multiple in one block triggers namespace pollution in the binding generator.

**Patch independence:** All patches apply independently to vanilla Firefox. Context lines in hunks reference unpatched source files. Patches apply alphabetically and use fuzzy matching for line shifts caused by other patches.
