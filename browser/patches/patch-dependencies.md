# Patch Dependencies

Quick reference for the shared infrastructure patches build on. `scripts/patch.py`
applies every `patches/**/*.patch` in order of file name, so the
`playwright/0-*` and `playwright/1-*` patches go first and the rest follow
alphabetically. Each patch is generated against a tree with every earlier one
applied, and many hunks use an earlier patch's lines as context, so they apply
only in that order. The dependencies below are the ones a patch needs to
compile.

## camoucfg (MaskConfig)

`additions/camoucfg/MaskConfig.hpp` reads the spoofing config (`CAMOU_CONFIG` /
`camoufox.cfg`) through `MaskConfig::GetBool()`, `GetString()`, `GetUint32()`
and friends. `GetBool()` is false for an unset key; `GetOptionalBool()` is for
the rare caller that must tell unset from false. `SpoofedOSFor()` is the one
reading of a `navigator.platform` as an OS. `GetSpoofedOS()` is the launch's,
for process-wide decisions only (`font-hijacker.patch`'s bundled fonts, the
WebRTC host socket's port range in `webrtc-ip-spoofing.patch`); anything a page
can observe asks `NavigatorManager::GetSpoofedOS()` (`navigator-spoofing.patch`)
for its own context's OS, which is that context's `navigator.platform` when it
set one and the launch's otherwise.
`scripts/copy-additions.sh` copies it into the source tree before any patch
applies. A patch that calls MaskConfig from a directory whose `moz.build` does
not already see `/camoucfg` must add `LOCAL_INCLUDES += ["/camoucfg"]` itself.

Config keys are declared in `settings/properties.json`; a key a patch reads must
be listed there.

### Patches that read config

| Patch | Config keys |
|-------|-------------|
| `audio-context-spoofing.patch` | `AudioContext:sampleRate`, `AudioContext:outputLatency`, `AudioContext:maxChannelCount` |
| `audio-fingerprint-manager.patch` | `audio:seed` |
| `chromeutil.patch` | `debug` |
| `fingerprint-injection.patch` | `navigator.*`, `screen.*`, `window.*` |
| `font-hijacker.patch` | `fonts`, `navigator.platform` |
| `font-system-fonts-css2.patch` | `navigator.platform`, `window.devicePixelRatio` |
| `force-default-pointer.patch` | `navigator.maxTouchPoints` |
| `geolocation-spoofing.patch` | `geolocation:*` |
| `locale-spoofing.patch` | `locale:*`, `navigator.language` |
| `media-codec-spoofing.patch` | `media:spoof_codecs` (bypasses `PDMFactory::Supports()` in `MP4Decoder`/`MatroskaDecoder` so `canPlayType()`/`isTypeSupported()` don't leak system codec libraries) |
| `media-device-spoofing.patch` | `mediaDevices:*` |
| `navigator-spoofing.patch` | `navigator.*` |
| `network-patches.patch` | `headers.*`, `navigator.userAgent` |
| `no-css-animations.patch` | `instantAnimations` |
| `screen-spoofing.patch` | `screen.*` |
| `system-ui-font-spoofing.patch` | `navigator.platform` |
| `timezone-spoofing.patch` | `timezone` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator.maxTouchPoints` |
| `voice-spoofing.patch` | `voices`, `voices:blockIfNotDefined` |
| `webgl-spoofing.patch` | `webGl:*`, `webGl2:*` |
| `webrtc-ip-spoofing.patch` | `webrtc:ipv4`, `webrtc:ipv6`, `navigator.platform` |

To regenerate the list: `grep -l 'MaskConfig::' patches/*.patch`.

### Includes another patch provides

Some patches call MaskConfig from a file or directory that an earlier patch
already set up, and do not add the include or `LOCAL_INCLUDES` themselves:

| Patch | Relies on |
|-------|-----------|
| `force-default-pointer.patch` | `screen-spoofing.patch` for `MaskConfig.hpp` in `layout/style/nsMediaFeatures.cpp`; `font-hijacker.patch` for `/camoucfg` in `layout/style/moz.build` |
| `media-device-spoofing.patch` | `audio-context-spoofing.patch` for `/camoucfg` in `dom/media/moz.build` |
| `system-ui-font-spoofing.patch` | `font-hijacker.patch` for `MaskConfig.hpp` in `gfx/thebes/gfxPlatformFontList.cpp` and `/camoucfg` in `gfx/thebes/moz.build` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator-spoofing.patch` for `MaskConfig.hpp` in `dom/base/Navigator.cpp` |
| `font-list-spoofing.patch` | `anti-font-fingerprinting.patch` for `gfxFontGroup::mUserContextId` |
| `timezone-spoofing.patch`, `webrtc-ip-spoofing.patch` | `audio-fingerprint-manager.patch` for `RoverfoxStorageManager.h` in `dom/base/nsGlobalWindowInner.cpp` |
| `font-system-fonts-css2.patch`, `system-ui-font-spoofing.patch`, `webrtc-ip-spoofing.patch` | `navigator-spoofing.patch` for `NavigatorManager::GetSpoofedOS()` |

## RoverfoxStorageManager

Per-context values set from Playwright (audio seed, WebRTC IP, timezone,
screen, navigator, WebGL, font list, voices, ...) are kept in
`RoverfoxStorageManager`, which `cross-process-storage.patch` adds under
`dom/base/` with its cross-process put/get IPC. Every content process reads it:
a context's documents can land in any of them, and only the first document
calls the setter. The same patch provides the guard and removal every setter
uses (`IsSetterOffered`, `MarkSetterUsed`, `RemoveSetter`), and
`window-setter-seal.patch` adds its seal check to `IsSetterOffered`.

`RoverfoxStorageManager::UserContextId()` is the one way a patch finds the
context a value is stored under: the principal of the node, document or window
at hand. A browsing context is not used, because a document created by
`document.implementation.createHTMLDocument()` or `DOMParser` has none, while it
shares its creator's principal. A value is stored only under its own context;
nothing writes a fallback copy under context 0.

## Playwright

Everything else is written against a tree that already has
`playwright/0-playwright.patch` and `playwright/1-leak-fixes.patch` applied.
