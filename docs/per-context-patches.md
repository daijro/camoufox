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
| `window.setNavigatorPlatform(platform)` | `navigator-spoofing.patch` | `navigator.platform` |
| `window.setNavigatorOscpu(oscpu)` | `navigator-spoofing.patch` | `navigator.oscpu` |
| `window.setNavigatorHardwareConcurrency(cores)` | `navigator-spoofing.patch` | `navigator.hardwareConcurrency` |
| `window.setWebRTCIPv4(ip)` | `webrtc-ip-spoofing.patch` | WebRTC ICE candidates, SDP, getStats() |
| `window.setWebRTCIPv6(ip)` | `webrtc-ip-spoofing.patch` | WebRTC IPv6 addresses |
| `window.setWebGLVendor(vendor)` | `webgl-spoofing.patch` | `UNMASKED_VENDOR_WEBGL` parameter |
| `window.setWebGLRenderer(renderer)` | `webgl-spoofing.patch` | `UNMASKED_RENDERER_WEBGL` parameter |
| `window.setCanvasSeed(seed)` | `canvas-spoofing.patch` | Canvas 2D `toDataURL()`/`getImageData()` hash |
| `window.setFontList(fonts)` | `font-list-spoofing.patch` | Which fonts appear "installed" to fingerprinters |
| `window.setSpeechVoices(voices)` | `speech-voices-spoofing.patch` | `speechSynthesis.getVoices()` filtering |

All 14 functions **self-destruct after the first call** — page JavaScript cannot detect them via `typeof window.setTimezone`.

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

---

### 3. timezone-spoofing.patch

**Controls:** All time-related APIs — `Date`, `Intl.DateTimeFormat`, `toLocaleString()`, etc. Each context can report a different IANA timezone.

**How it works:** This is the only patch that hooks into SpiderMonkey (Firefox's JS engine). It restores per-realm `DateTimeInfo` support that Playwright had disabled, and adds a `JS::SetRealmTimeZoneOverride()` API. Each JS Realm (one per context) gets its own timezone.

**Navigation persistence:** Hooks `nsGlobalWindowOuter::SetNewDocument()` to automatically re-apply the stored timezone when the user navigates to a new page within the same context. Without this, navigations would create a new Realm that loses the override.

**Worker propagation:** Hooks `WorkerPrivate::GetOrCreateGlobalScope()` to apply the stored timezone to the worker's JS Realm. Dedicated Workers, Shared Workers, and Service Workers all create their own Realm that doesn't inherit the parent page's timezone — this hook ensures they stay consistent.

**API:**
```javascript
window.setTimezone('America/New_York'); // IANA timezone ID
// Invalid timezone IDs throw a TypeError
```

**New C++ files:** `TimezoneManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `nsGlobalWindowOuter.cpp`, `WorkerPrivate.cpp`, `Window.webidl`, `moz.build`
**Modified SpiderMonkey files:** `js/public/Date.h`, `js/src/vm/DateTime.h/cpp`, `js/src/vm/Realm.cpp`

---

### 4. screen-spoofing.patch

**Controls:** `screen.width`, `screen.height`, `screen.colorDepth`, and related CSS media queries.

**How it works:** Stores dimensions per context, then hooks `nsScreen::GetRect()` with a three-tier fallback: per-context values → global `CAMOU_CONFIG` → vanilla Firefox.

Also hooks `nsMediaFeatures.cpp` so CSS media queries like `matchMedia('(device-width: 1920px)')` return results consistent with `screen.width`. Without this, fingerprinters can detect a mismatch between the JavaScript API and CSS media queries.

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

---

### 6. navigator-spoofing.patch

**Controls:** `navigator.platform`, `navigator.oscpu`, `navigator.hardwareConcurrency` — per-context with global `CAMOU_CONFIG` fallback.

**How it works:** Stores values per context via `NavigatorManager`, then hooks `Navigator::GetPlatform()`, `Navigator::GetOscpu()`, and `Navigator::HardwareConcurrency()` with a three-tier fallback: per-context values → global `CAMOU_CONFIG` → vanilla Firefox.

**Worker propagation:** Also hooks `WorkerNavigator::GetPlatform()` and `WorkerNavigator::HardwareConcurrency()` so Web Workers inherit the per-context values. Workers resolve `userContextId` via `WorkerPrivate::GetOriginAttributes()`.

Also adds `EnsureGlobalTimezoneInitialized()` — a lazy initializer that reads `timezone` from `CAMOU_CONFIG` on first access. This replaced a static initializer that caused SIGSEGV crashes because SpiderMonkey wasn't ready at init time.

**API:**
```javascript
window.setNavigatorPlatform('Win32');              // navigator.platform
window.setNavigatorOscpu('Windows NT 10.0; Win64; x64');  // navigator.oscpu
window.setNavigatorHardwareConcurrency(8);         // navigator.hardwareConcurrency
```

**Global config fallback (no JavaScript needed):**
```json
{ "navigator.platform": "MacIntel", "navigator.hardwareConcurrency": 8, "timezone": "America/Los_Angeles" }
```

**New C++ files:** `NavigatorManager.h/cpp`
**Modified Firefox files:** `Navigator.cpp`, `WorkerNavigator.cpp`, `nsGlobalWindowInner.cpp/h`, `Window.webidl`, `moz.build`

---

### 7. webgl-spoofing.patch

**Controls:** `UNMASKED_VENDOR_WEBGL` and `UNMASKED_RENDERER_WEBGL` — the WebGL debug extension parameters that reveal GPU hardware. These are one of the strongest fingerprint vectors since GPU model + driver version is highly unique.

**How it works:** Stores vendor and renderer strings per context via `WebGLParamsManager`, then hooks `ClientWebGLContext::GetParameter()` to intercept `WEBGL_debug_renderer_info` queries. Three-tier fallback: per-context values → global `CAMOU_CONFIG` → real hardware values.

Note: `GL_VENDOR` and `GL_RENDERER` (without the debug extension) already return `"Mozilla"` universally in Firefox — those don't need spoofing.

**Coupled self-destruct:** Calling either `setWebGLVendor()` or `setWebGLRenderer()` removes **both** functions and sets a shared disabled flag. This prevents partial configuration.

**API:**
```javascript
window.setWebGLVendor('Intel Inc.');              // UNMASKED_VENDOR_WEBGL
window.setWebGLRenderer('Intel Iris OpenGL Engine');  // UNMASKED_RENDERER_WEBGL
```

**New C++ files:** `WebGLParamsManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `ClientWebGLContext.cpp`, `Window.webidl`, `moz.build`

---

### 8. canvas-spoofing.patch

**Controls:** Canvas 2D fingerprint hash — websites draw text, shapes, and gradients on a canvas, then call `toDataURL()` or `getImageData()` to hash the pixel output. GPU, driver, and font rendering differences make this hash highly unique.

**How it works:** Stores a seed per context via `CanvasFingerprintManager`, then hooks both canvas data extraction paths in `CanvasRenderingContext2D.cpp`:
- `GetImageBuffer()` — used by `toDataURL()` and `toBlob()`, returns pixels in **BGRA** format
- `GetImageData()` — used by `ctx.getImageData()`, returns pixels in **RGBA** format

The noise algorithm is **format-agnostic**: for each selected pixel, it iterates RGB channels (skipping alpha) and modifies the first non-zero channel by ±1. This works correctly regardless of whether byte 0 is Red (RGBA) or Blue (BGRA).

**Zero-pixel preservation:** Channels with value 0 are skipped. This means `clearRect()` followed by `getImageData()` returns all zeros — no false noise on transparent pixels. This is important because CreepJS specifically tests for noise in cleared canvas regions as a detection vector.

**Noise is deterministic, not random:** Same seed always produces the same pixel modifications, so fingerprinters calling `toDataURL()` multiple times get identical results. This is critical — random noise is trivially detected by calling the API twice and comparing outputs.

**API:**
```javascript
window.setCanvasSeed(55555555); // uint32 seed
```

**New C++ files:** `CanvasFingerprintManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `CanvasRenderingContext2D.cpp`, `Window.webidl`, `moz.build`

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
   → If font not in allowed list → return false
3. Entry point resets thread_local = 0
```

An RAII guard (`AutoFontListContext`) handles the set/reset automatically.

**Why thread-local?** `FindAndAddFamiliesLocked()` is called from 20+ locations including font fallback, CSS matching, and generic font resolution. Threading a parameter through all callers would require modifying ~50 functions.

**API:**
```javascript
window.setFontList('Arial,Helvetica,Georgia,Courier New,Verdana');
// Comma-separated list of font names. Fonts NOT in this list will appear "not installed".
// Case-insensitive matching. Essential web fonts (serif/sans-serif/monospace fallbacks) always work.
```

**New C++ files:** `FontListManager.h/cpp`
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `gfxPlatformFontList.cpp`, `gfxTextRun.cpp`, `FontFaceSet.cpp`, `Window.webidl`, `moz.build`

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
**Modified Firefox files:** `nsGlobalWindowInner.cpp`, `SpeechSynthesis.cpp`, `Window.webidl`, `moz.build`

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

**SOURCES vs UNIFIED_SOURCES:** All new `.cpp` manager files use `SOURCES` (separate compilation) in `moz.build`. This avoids namespace pollution (`mozilla::dom::mozilla::dom::`) that occurs when files including `RoverfoxStorageManager.h` are concatenated in unified builds. Currently applies to: `AudioFingerprintManager.cpp`, `WebRTCIPManager.cpp`, `NavigatorManager.cpp`, `WebGLParamsManager.cpp`, `CanvasFingerprintManager.cpp`, `FontListManager.cpp`, `SpeechVoicesManager.cpp`.

**EXPORTS sort conflicts:** Each patch uses a separate `EXPORTS.mozilla.dom += ["Header.h"]` statement near its `SOURCES` block, rather than inserting into the main sorted EXPORTS list. This avoids sort conflicts when multiple patches add headers at similar alphabetical positions.

**WebIDL:** Each `window.setXxx()` function needs its own `partial interface Window` block. Combining multiple in one block triggers namespace pollution in the binding generator.

**Patch independence:** All patches apply independently to vanilla Firefox. Context lines in hunks reference unpatched source files. Patches apply alphabetically and use fuzzy matching for line shifts caused by other patches.

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
