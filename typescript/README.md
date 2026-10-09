<div align="center">

# camoufox (TypeScript)

#### The Node.js launcher for the Camoufox anti-detect browser.

</div>

`camoufox` drives the Camoufox browser through `playwright-core`. On every
launch it draws a complete device identity from
[`fpgen`](https://www.npmjs.com/package/fpgen), the TypeScript port of
[scrapfly's fpgen](https://github.com/scrapfly/fingerprint-generator), checks that the
parts agree with each other, and hands it to the browser, which spoofs it in
C++. With a proxy and `geoip: true` it also matches timezone, locale,
geolocation and the WebRTC IP to the proxy's exit IP.

It is a port of the Python package ([`../python`](../python)) and does not call
Python. Both launchers read the same `properties.json`, write the same
`CAMOU_CONFIG`, share one browser install directory, and draw the same
identities: a pinned identity looks the same from either language. Notes for
AI coding agents are in [`../AGENTS.md`](../AGENTS.md#using-camoufox).

## Install

```bash
npm install camoufox playwright-core
npx camoufox fetch
```

| Requirement | Value |
|---|---|
| Node.js | 22.15 or newer |
| `playwright-core` | peer dependency, below 1.63 |
| GeoIP | built in; the [GeoIP All-in-One](https://github.com/daijro/geoip-all-in-one) database downloads on first use |

`camoufox fetch` installs the browser build this release is paired with.
Without it, the first launch downloads it.

## Usage

`Camoufox()` returns a Playwright `Browser` (or a `BrowserContext` for a
persistent profile), so existing Playwright code works once the launch is
changed.

```javascript
import { Camoufox } from "camoufox";

const browser = await Camoufox({ headless: true });
const page = await browser.newPage();
await page.goto("https://example.com");
await browser.close();
```

Playwright-Python has a sync and an async API, so the Python package has both.
`playwright-core` has one, so here every function returns a promise.
`AsyncCamoufox`, `AsyncNewBrowser` and `AsyncNewContext` are aliases kept for
parity with Python.

### Proxy with a matching location

```javascript
import { Camoufox } from "camoufox";

const browser = await Camoufox({
    proxy: { server: "http://proxy.example.com:8080", username: "user", password: "pass" },
    geoip: true,
});
```

`geoip: true` looks up the exit IP through the proxy, then sets timezone,
locale, geolocation and the WebRTC IP from it. Pass an IP string instead to
skip the lookup.

### Persistent profile

```javascript
import { Camoufox } from "camoufox";

const context = await Camoufox({ persistent_context: true, user_data_dir: "./profiles/alice" });
const page = await context.newPage();
await page.goto("https://example.com");
await context.close();
```

### One browser, many identities

`NewContext()` gives each context its own identity (navigator, screen, WebGL,
fonts, voices, audio seed, timezone, WebRTC IP), applied through
`addInitScript` before any page script runs.

```javascript
import { Camoufox, NewContext } from "camoufox";

const browser = await Camoufox({ headless: true, canvas_noise: true });
const alice = await NewContext(browser, { os: "windows" });
const bob = await NewContext(browser, {
    os: "macos",
    proxy: { server: "http://proxy.example.com:8080", username: "user", password: "pass" },
});
await (await alice.newPage()).goto("https://example.com");
await (await bob.newPage()).goto("https://example.com");
await browser.close();
```

| `NewContext` option | Effect |
|---|---|
| `preset` | Use this fingerprint preset object instead of an fpgen draw. |
| `os` | `"windows"`, `"macos"` or `"linux"` for the drawn identity. On a browser without canvas noise, the host's OS, and anything else throws `ValueError`. |
| `ff_version` | Firefox major version claimed in the User-Agent. Defaults to the browser's own. |
| `webrtc_ip` | IPv4 or IPv6 address WebRTC reports. |
| `proxy` | Per-context proxy, in Playwright's format. Unless `webrtc_ip` and `timezoneId` are both given, they are looked up from the proxy's exit IP, and `InvalidIP` is thrown if the lookup fails. |
| `geolocation` | `{ latitude, longitude }`; also grants the `geolocation` permission. |
| anything else | Passed to Playwright's `browser.newContext()` (camelCase, e.g. `timezoneId`), overriding the generated value. |

Canvas noise belongs to the browser, not the context (see
[The canvas on another OS](#the-canvas-on-another-os)). On a browser without it,
every context claims the host's OS and GPU too, since its canvas renders there.
Contexts with other OSes, like the ones above, need `canvas_noise: true`.

### The canvas on another OS

A page can draw a canvas or a WebGL scene and read the pixels back. Those pixels
come from the real OS, driver and GPU, whatever the identity claims.

- **On the host's OS**, the launcher starts the browser once, unspoofed and with
  the same display, reads the GPU Firefox reports, and the identity claims it.
  The pixels then agree with the identity. A host that renders in software (no
  GPU driver, as on most servers) keeps a drawn GPU: it reads as a machine
  whose driver failed to load.
- **On another OS**, the pixels would show the real one. Camoufox then turns on
  the canvas protection of `privacy.resistFingerprinting`, and only that:
  canvas and WebGL readback return random data, as in LibreWolf, Tor Browser
  and Mullvad Browser. Stock Firefox does not do this, so the launch emits a
  `LeakWarning`; the browser reads as a privacy-hardened Firefox rather than a
  stock one.

`canvas_noise: true` turns the protection on for any OS, `canvas_noise: false`
never.

WebGPU follows the same rule. `navigator.gpu` exists only where Firefox on the
claimed device has it (Windows and Apple Silicon Macs), and the adapter is the
host's only when the identity claims the host's GPU. Otherwise
`requestAdapter()` returns `null`, as Firefox does for a blocked or software GPU.

### Headless modes

| `headless:` | What runs | Notes |
|---|---|---|
| `false` (default) | A normal window | Needs a display. |
| `true` | Firefox headless | Camoufox patches the headless tells it knows about. |
| `"virtual"` | A headed browser on a private Xvfb display | Linux only, needs `Xvfb`. Handled by `Camoufox()`, `NewBrowser()` and `launchServer()`. The display is 1x1 unless `CAMOUFOX_VIRTUAL_DISPLAY_SIZE` (e.g. `1920x1080x24`) says otherwise. |

### Remote server

```javascript
import { launchServer } from "camoufox";

const server = await launchServer({ headless: true, port: 1234, ws_path: "camoufox" });
console.log(server.wsEndpoint());
```

Connect from any Playwright client with `firefox.connect(endpoint)`. A
persistent context cannot be served.

### Your own Playwright instance

`NewBrowser()` launches on a `BrowserType` you pass, and `launchOptions()`
returns the options for `firefox.launch()`:

```javascript
import { firefox } from "playwright-core";
import { NewBrowser, launchOptions } from "camoufox";

const browser = await NewBrowser(firefox, { os: "linux", headless: true });
await browser.close();

const plain = await firefox.launch(await launchOptions({ os: "linux", headless: true }));
await plain.close();
```

Prefer `NewBrowser()`: it also defaults new pages to no viewport when the
window size is spoofed, and to the host's own color scheme and motion settings.
`launchOptions()` returns Playwright's camelCase keys (`executablePath`,
`firefoxUserPrefs`), and does not handle `headless: "virtual"`.

## Launch options

`Camoufox()`, `NewBrowser()`, `launchServer()` and `launchOptions()` take one
options object. Camoufox's own options keep the Python package's snake_case
names. Any other key is passed to Playwright's `firefox.launch()` (or
`launchPersistentContext()`), in Playwright's camelCase.

| Option | Type | Default | Effect |
|---|---|---|---|
| `os` | `string \| string[]` | fpgen's real-world mix | `"windows"`, `"macos"`, `"linux"`, or a list to pick from. |
| `headless` | `boolean \| "virtual"` | `false` | See [Headless modes](#headless-modes). |
| `proxy` | `{ server, username?, password?, bypass? }` | none | Playwright proxy. |
| `geoip` | `boolean \| string` | none | `true` finds the public IP (through `proxy` if set); a string uses that IP. Sets timezone, locale, geolocation and the WebRTC IP. |
| `geoip_db` | `string` | the `camoufox set --geoip` choice | GeoIP database name, e.g. `"GeoIP AIO by daijro"`. |
| `locale` | `string \| string[]` | from `geoip`, else the drawn identity's | Locale(s), e.g. `"en-US"`. The first is used for `Intl`. |
| `humanize` | `boolean \| number` | off | Human cursor movement. A number caps one movement at that many seconds (default cap 1.5). |
| `screen` | `Screen \| { max_width?, max_height?, min_width?, min_height? }` | the real display when headed | Bounds the generated screen. |
| `window` | `[number, number]` | generated | Fixed outer window size. |
| `fonts` | `string[]` | none | Extra font families on top of the OS's own. |
| `custom_fonts_only` | `boolean` | `false` | Use only `fonts`, not the OS fonts. Warns: the font set no longer matches the OS. |
| `addons` | `string[]` | none | Paths to extracted Firefox addons (folders with a `manifest.json`). |
| `exclude_addons` | `("UBO")[]` | none | Default addons to leave out. |
| `block_images` | `boolean` | `false` | Block image loading. Warns: some WAFs detect it. |
| `block_webrtc` | `boolean` | `false` | Disable WebRTC entirely. |
| `block_webgl` | `boolean` | `false` | Disable WebGL. Warns: many WAFs check for it. |
| `webgl_config` | `[vendor, renderer]` | drawn | Use one GPU fpgen has recorded for Firefox on `os`; any other pair throws. Needs `os`. |
| `canvas_noise` | `boolean` | on for another OS | Random canvas and WebGL readback, as in LibreWolf. Warns. See [The canvas on another OS](#the-canvas-on-another-os). |
| `disable_coop` | `boolean` | `false` | Turn off Cross-Origin-Opener-Policy so elements in cross-origin iframes (such as the Turnstile checkbox) can be clicked. Warns. |
| `main_world_eval` | `boolean` | `false` | Allow `page.evaluate("mw:...")` and `mw:` init scripts to run in the page's own world. |
| `allow_addon_new_tab` | `boolean` | `false` | Let addons open tabs. |
| `enable_cache` | `boolean` | `false` | Keep Firefox's page and request caches. Uses more memory. |
| `pin_cpu_cores` | `boolean` | `false` | Linux and Windows: pin the browser to as many cores as `navigator.hardwareConcurrency` claims. Costs CPU and serializes concurrent launches. |
| `fingerprint` | fpgen fingerprint object | drawn | Use this fpgen fingerprint instead of drawing one. Warns. |
| `fingerprint_preset` | `boolean \| object` | `undefined` | Opt into a recorded real-device preset instead of fpgen: `true` picks a random bundled one, an object uses that one. |
| `ff_version` | `number` | the browser's own | Firefox version to claim. Warns: a mismatch with the engine is detectable. |
| `config` | `object` | none | Raw Camoufox properties ([`properties.json`](../browser/settings/properties.json)). Overrides the generated identity; manual identity keys warn. |
| `firefox_user_prefs` | `object` | none | Extra Firefox prefs. |
| `args` | `string[]` | none | Extra browser command-line arguments. |
| `env` | `object` | a copy of `process.env` | Environment variables for the browser. |
| `executable_path` | `string` | the installed build | Use this binary. `CAMOUFOX_EXECUTABLE_PATH` sets it too. |
| `browser` | `string` | the active build | Use another installed build: `"official/beta.20"`, `"beta.20"` or `"134.0.2-beta.20"`. |
| `virtual_display` | `string` | none | Use an existing X display, e.g. `":99"`. |
| `i_know_what_im_doing` | `boolean` | `false` | Silence the leak warnings above. |
| `debug` | `boolean` | `false` | Print the config sent to the browser. |

`Camoufox()` and `NewBrowser()` also take `persistent_context`, `user_data_dir`
and `from_options` (an object from `launchOptions()` to use as is).
`launchServer()` also takes `port` and `ws_path`.

## CLI

`npx camoufox <command>`. The commands match the Python package's.

| Command | Options | What it does |
|---|---|---|
| `fetch [version]` | | Install the paired build (or, after `set`, the latest in the chosen channel), or `version` without making it active. Syncs first. |
| `sync` | `--spoof-os auto\|mac\|win\|lin`, `--spoof-arch auto\|x86_64\|i686\|arm64` | Refresh the list of available builds. |
| `set [specifier]` | `--geoip`, `--release` | Pin a build (`official/stable/134.0.2-beta.20`) or follow a channel (`official/stable`). No specifier opens a picker. `--geoip` picks the GeoIP database instead; `--release` goes back to the paired build. |
| `active` | | Print the active build. A build that is chosen but not downloaded is marked `(not fetched)`. |
| `list [installed\|all]` | `--path` | List installed builds, or every available one. |
| `remove [version]` | `--select`, `-y/--yes` | Remove one build, pick one interactively, or (with no argument) everything. |
| `version` | | Package versions, the active build, the GeoIP database, and storage paths and sizes. |
| `path` | | Print the data directory (`~/.cache/camoufox` on Linux). |
| `test [url]` | `--executable-path <path>` | Open a headed browser with the Playwright inspector. |
| `server` | | Start a Playwright server and print its websocket endpoint. |

Each release is paired with the one browser build it was built and tested with,
the same build as the Python release of the same version, and every launch uses
it until `camoufox set` chooses another. The Python README explains the rules:
[Which browser build is used](../python/README.md#which-browser-build-is-used).

## Development

The tests compare this package's output with the Python package's, so they need
a Python with `python/` installed: the repository's `.venv`, or
`CAMOUFOX_PYTHON`.

```bash
python3.14 -m venv .venv                                           # repo root
.venv/bin/pip install -r ci/requirements.txt -e python
.venv/bin/python browser/scripts/pin-fpgen-model.py
cd typescript
pnpm install
pnpm build       # tsc -> dist/, then copy the Python package's data files into dist/data-files
pnpm test        # records the golden fixtures from python/, then runs vitest
pnpm check       # biome lint and format
pnpm typecheck   # tsc --noEmit
```

The data files (presets, fonts, voices, `territoryInfo.xml`, ...) have one copy,
in `python/src/camoufox/`. `DATA_FILES` in `src/paths.ts` lists them, and the
build copies them into the package.

**Parity.** Before the suite runs, `tests/golden-setup.ts` runs the scripts in
`scripts/golden/`, which record the Python package's output over fixed inputs
into `tests/fixtures/` (git-ignored). The TypeScript tests must reproduce it
exactly, `launch_options()` byte for byte including the `CAMOU_CONFIG` blob. A
Python change that is not mirrored here fails `pnpm test`. Use Python 3.14:
`pySum()` follows its `sum()`, and that test skips on 3.12 and 3.13.

The end-to-end suite launches a real browser through both launchers and
compares what a page sees:

```bash
CAMOUFOX_E2E=1 CAMOUFOX_EXECUTABLE=/path/to/camoufox-bin pnpm test tests/e2e.test.ts
```

**Releases.** The npm and PyPI packages are released together by
[`release.yml`](../.github/workflows/release.yml), at the same version
([`ci/README.md`](../ci/README.md#releases)). `scripts/check-pack.mjs` checks
that the tarball carries every data file and installs into an empty project.
npm uploads use trusted publishing; no token is stored.

## Licence

MIT ([`LICENSE`](LICENSE)). The browser itself is MPL-2.0. The package
contains a port of NumPy's pairwise summation; its notice is in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). It depends on
[`fpgen`](https://www.npmjs.com/package/fpgen) (Apache-2.0) and
[`python-random`](https://www.npmjs.com/package/python-random), a bit-exact port
of CPython's `random`, so seeded draws match the Python launcher.
