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
| `chromeutil.patch` | `debug` |
| `fingerprint-injection.patch` | `navigator.*`, `screen.*`, `window.*` |
| `font-hijacker.patch` | `fonts`, `navigator.platform` |
| `font-system-fonts-css2.patch` | `navigator.platform`, `window.devicePixelRatio` |
| `force-default-pointer.patch` | `navigator.maxTouchPoints` |
| `geolocation-spoofing.patch` | `geolocation:*` |
| `locale-spoofing.patch` | `locale:*`, `navigator.language` |
| `media-codec-spoofing.patch` | `media:spoof_codecs` (bypasses `PDMFactory::Supports()` in `MP4Decoder`/`MatroskaDecoder` so `canPlayType()`/`isTypeSupported()` don't leak system codec libraries, and answers `decodingInfo()` to match) |
| `media-device-spoofing.patch` | `mediaDevices:*` |
| `navigator-spoofing.patch` | `navigator.*` |
| `network-patches.patch` | `headers.*`, `navigator.userAgent` |
| `no-css-animations.patch` | `instantAnimations` |
| `screen-spoofing.patch` | `screen.*` |
| `system-ui-font-spoofing.patch` | `navigator.platform` |
| `timezone-spoofing.patch` | `timezone` |
| `touchscreen-fingerprint-spoofing.patch` | `navigator.maxTouchPoints` |
| `virtual-display-claimed-screen.patch` | `screen.width`, `screen.height`, `screen.avail*` (the X screen reports the claimed screen when it is smaller) |
| `voice-spoofing.patch` | `voices`, `voices:speechd`, `voices:blockIfNotDefined` |
| `webgl-spoofing.patch` | `webGl:*`, `webGl2:*` |
| `webrtc-ip-spoofing.patch` | `webrtc:ipv4`, `webrtc:ipv6`, `navigator.platform` |
| `windows-keyboard.patch` | `input:windowsKeyboard` (launch-wide: the shortcut tables and GTK's key handling are process-level) |
| `zz-stock-cost-parity.patch` | `navigator.hardwareConcurrency`, `navigator.maxTouchPoints`, `screen.*` (re-orders the getters above so stock's work runs first) |

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
| `font-system-fonts-css2.patch`, `system-ui-font-spoofing.patch`, `webrtc-ip-spoofing.patch`, `zz-stock-cost-parity.patch` | `navigator-spoofing.patch` for `NavigatorManager::GetSpoofedOS()` |
| `per-context-http-user-agent.patch` | `navigator-spoofing.patch` for `NavigatorManager::GetUserAgent()` (exported as `mozilla/dom/NavigatorManager.h`); `cross-process-storage.patch` for reading the context's value in the parent and worker processes |
| `virtual-display-claimed-screen.patch` | `windows-keyboard.patch` for `/camoucfg` in `widget/gtk/moz.build` |
| `windows-keyboard.patch` | `touchscreen-fingerprint-spoofing.patch` for `/camoucfg` in `dom/events/moz.build` |
| `zz-stock-cost-parity.patch` | `cross-process-storage.patch` for `RoverfoxStorageManager::Generation()`; `screen-spoofing.patch` for `ScreenDimensionManager` in `dom/base/nsScreen.cpp` |

## RoverfoxStorageManager

Per-context values set from Playwright (WebRTC IP, timezone,
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

## Driver input and the page's globals

- `input-coalescing-parity.patch` uses `mJugglerEventId` and the
  `juggler-mouse-event-hit-renderer` ack from `playwright/0-playwright.patch`.
  Its JS half is in `additions/juggler` (`MouseDispatch.sendQueuedMove`,
  `PageHandler.beforeDispatch`), and either half without the other wedges
  every move until the ack deadline.
- `drag-source-events.patch` extends the drag branch that
  `playwright/0-playwright.patch` adds to `nsContentUtils::SynthesizeMouseEvent`.
- `isolated-world-global-order.patch` stands alone. It recognises Juggler as
  the scripted caller (its `resource://gre/modules/juggler/` modules, and the
  sandboxes those modules create, whose location names them) and leaves the
  interfaces it creates undefined on the page's window until the page uses
  them. It edits `Codegen.py` (the window Xray's resolve on the window), so
  every generated binding rebuilds, and `BindingUtils.h`
  (`DoGetOrCreateDOMReflector`), which most of `dom/` includes.

## WebRTC behind a proxy

`webrtc-socks5-udp.patch` builds on two earlier patches and uses their lines as
context:

- `webrtc-proxy-local-network.patch` keeps UDP host sockets behind a proxy and
  limits them to the local network (`NrSocketBase::RefusesDestination`). The
  new patch adds `NrUdpRelaySocket`, which sends the rest through a SOCKS5 UDP
  ASSOCIATE relay on the tab's proxy, and makes a refused destination fail at
  once instead of being dropped silently.
- `webrtc-ip-spoofing.patch` rewrites candidate, SDP and `getStats()` addresses
  to `webrtc:ipv4`/`ipv6`; it makes up host candidates when none reached the
  page, never a srflx. It also decides whether a page is behind a proxy
  (`ShouldForceProxy`): Juggler records each proxy it sets, which decides for a
  document with no HTTP channel, so a direct launch stays direct and a proxied
  one never gathers around its proxy. The new patch keeps a srflx or
  relay address gathered through the proxy as it is, because a page's own STUN
  server already saw that address. Behind an HTTP proxy, or a SOCKS5 proxy that
  refuses UDP, no srflx surfaces: the page reads a machine whose UDP is
  blocked, not one that made a STUN answer up.

ICE sockets live in the socket process, and proxies are resolved in the
parent. The patch adds an optional `LoadInfoArgs` to the existing
`PProxyConfigLookup` constructor (`netwerk/ipc`), so the parent resolves the
proxy with the tab's load info, as it does for the tab's own loads. Juggler's
per-context proxy filter then picks that context's proxy. The SOCKS5 control
connection (`WebrtcUdpAssociation`) runs in the socket process, so the relay
sees the control connection and the datagrams come from the same address.

## Backports

These patches carry upstream Firefox changes that `browser/upstream.sh`'s
version does not have yet. Drop each one when the Firefox it moves to ships
the change.

None at present. Firefox 159 ships the startup import of the bundled OneCRL
list ([Bug 2084311](https://bugzilla.mozilla.org/show_bug.cgi?id=2084311)),
which `remote-security-settings.patch` carried for 158.0.1.

## Playwright

Everything else is written against a tree that already has
`playwright/0-playwright.patch` and `playwright/1-leak-fixes.patch` applied.
