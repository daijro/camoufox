# Patch Dependencies

Quick reference for the shared infrastructure patches build on. `scripts/patch.py`
applies every `patches/**/*.patch` in order of file name, so the
`playwright/0-*` and `playwright/1-*` patches go first and the rest follow
alphabetically. The dependencies below are compile-time: a patch applies without
them, but the tree will not build.

## camoucfg (MaskConfig)

`additions/camoucfg/MaskConfig.hpp` reads the spoofing config (`CAMOU_CONFIG` /
`camoufox.cfg`) through `MaskConfig::GetBool()`, `GetString()`, `GetUint32()`
and friends. `scripts/copy-additions.sh` copies it into the source tree before
any patch applies. A patch that calls MaskConfig from a directory whose
`moz.build` does not already see `/camoucfg` must add
`LOCAL_INCLUDES += ["/camoucfg"]` itself.

Config keys are declared in `settings/properties.json`; a key a patch reads must
be listed there.

### Patches that read config

| Patch | Config keys |
|-------|-------------|
| `audio-context-spoofing.patch` | `AudioContext:outputLatency` |
| `audio-fingerprint-manager.patch` | `audio:seed` |
| `chromeutil.patch` | `debug` |
| `fingerprint-injection.patch` | `navigator.*`, `screen.*`, `window.*` |
| `font-hijacker.patch` | `navigator.platform` |
| `font-system-fonts-css2.patch` | `navigator.platform`, `window.devicePixelRatio` |
| `force-default-pointer.patch` | `navigator.maxTouchPoints` |
| `geolocation-spoofing.patch` | `geolocation:*` |
| `global-style-sheets.patch` | `disableTheming` |
| `locale-spoofing.patch` | `locale:*`, `navigator.language` |
| `media-codec-spoofing.patch` | `media:spoof_codecs` (bypasses `PDMFactory::Supports()` in `MP4Decoder`/`MatroskaDecoder` so `canPlayType()`/`isTypeSupported()` don't leak system codec libraries) |
| `media-device-spoofing.patch` | `mediaDevices:*` |
| `navigator-spoofing.patch` | `navigator.*`, `timezone` |
| `network-patches.patch` | `headers.*`, `navigator.userAgent` |
| `no-css-animations.patch` | `instantAnimations` |
| `screen-spoofing.patch` | `screen.width`, `screen.height` |
| `system-ui-font-spoofing.patch` | `navigator.platform` |
| `timezone-spoofing.patch` | `timezone` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator.maxTouchPoints` |
| `voice-spoofing.patch` | `voices:*` |
| `webgl-spoofing.patch` | `webGl:*` |
| `webrtc-ip-spoofing.patch` | `webrtc:ipv4`, `webrtc:ipv6`, `navigator.platform` |

To regenerate the list: `grep -l 'MaskConfig::' patches/*.patch`.

## RoverfoxStorageManager

Per-context values set from Playwright (audio seed, WebRTC IP, timezone,
screen, navigator, voices, ...) are kept in `RoverfoxStorageManager`, which
`anti-font-fingerprinting.patch` adds under `dom/base/`. Its cross-process
put/get IPC lives in `cross-process-storage.patch`. Any patch that uses the
storage manager needs both.

## Playwright

Everything else is written against a tree that already has
`playwright/0-playwright.patch` and `playwright/1-leak-fixes.patch` applied.
