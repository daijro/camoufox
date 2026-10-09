<div align="center">

# camoufox (Python)

#### The Python launcher for the Camoufox anti-detect browser.

</div>

`camoufox` drives the Camoufox browser through Playwright. On every launch it
draws a complete device identity from [fpgen](https://github.com/scrapfly/fingerprint-generator),
a model of real-world traffic, checks that the parts agree with each other, and
hands it to the browser, which spoofs it in C++. With a proxy and `geoip=True`
it also matches timezone, locale, geolocation and the WebRTC IP to the proxy's
exit IP.

The TypeScript package ([`../typescript`](../typescript)) is a port of this one
with the same options. Notes for AI coding agents are in
[`../AGENTS.md`](../AGENTS.md#using-camoufox).

## Install

```bash
pip install -U "camoufox[geoip]"
camoufox fetch
```

| Requirement | Value |
|---|---|
| Python | 3.10 or newer |
| Playwright | below 1.63 (installed as a dependency) |
| `geoip` extra | needed for `geoip=`; downloads the [GeoIP All-in-One](https://github.com/daijro/geoip-all-in-one) database, refreshed once it is a week old |

`camoufox fetch` installs the browser build this release is paired with, and
fpgen's model, pinned by sha256. Without it, the first launch downloads both.
Run `fetch` as the user that owns the Python environment if the browser will
run as someone else, for example while building a Docker image.
`camoufox remove` deletes everything that was downloaded.

## Usage

Camoufox returns ordinary Playwright objects, so existing Playwright code works
once the launch is changed.

### Sync and async

```python
from camoufox.sync_api import Camoufox

with Camoufox(headless=True) as browser:
    page = browser.new_page()
    page.goto("https://example.com")
```

```python
import asyncio
from camoufox.async_api import AsyncCamoufox

async def main():
    async with AsyncCamoufox(headless=True) as browser:
        page = await browser.new_page()
        await page.goto("https://example.com")

asyncio.run(main())
```

### Proxy with a matching location

```python
from camoufox.sync_api import Camoufox

with Camoufox(
    proxy={"server": "http://proxy.example.com:8080", "username": "user", "password": "pass"},
    geoip=True,
) as browser:
    page = browser.new_page()
    page.goto("https://example.com")
```

`geoip=True` looks up the exit IP through the proxy, then sets timezone,
locale, geolocation and the WebRTC IP from it. Pass an IP string instead to
skip the lookup.

### Persistent profile

```python
from camoufox.sync_api import Camoufox

with Camoufox(persistent_context=True, user_data_dir="profiles/alice") as context:
    page = context.new_page()
    page.goto("https://example.com")
```

With `persistent_context=True` the context manager yields a `BrowserContext`,
not a `Browser`.

### One browser, many identities

`NewContext()` gives each context its own identity (navigator, screen, WebGL,
fonts, voices, audio seed, timezone, WebRTC IP), applied through
`add_init_script` before any page script runs.

```python
from camoufox.sync_api import Camoufox, NewContext

with Camoufox(headless=True, canvas_noise=True) as browser:
    alice = NewContext(browser, os="windows")
    bob = NewContext(
        browser,
        os="macos",
        proxy={"server": "http://proxy.example.com:8080", "username": "user", "password": "pass"},
    )
    alice.new_page().goto("https://example.com")
    bob.new_page().goto("https://example.com")
```

| `NewContext` argument | Effect |
|---|---|
| `preset` | Use this fingerprint preset dict instead of an fpgen draw. |
| `os` | `"windows"`, `"macos"` or `"linux"` for the drawn identity. On a browser without canvas noise, the host's OS, and anything else raises `ValueError`. |
| `ff_version` | Firefox major version claimed in the User-Agent. Defaults to the browser's own. |
| `webrtc_ip` | IPv4 or IPv6 address WebRTC reports. |
| `proxy` | Per-context proxy, in Playwright's format. Unless `webrtc_ip` and `timezone_id` are both given, they are looked up from the proxy's exit IP, and `InvalidIP` is raised if the lookup fails. |
| `geolocation` | `{"latitude": ..., "longitude": ...}`; also grants the `geolocation` permission. |
| anything else | Passed to Playwright's `new_context()`, overriding the generated value. |

`AsyncNewContext()` is the async twin.

Canvas noise belongs to the browser, not the context (see
[The canvas on another OS](#the-canvas-on-another-os)). On a browser without it,
every context claims the host's OS and GPU too, since its canvas renders there.
Contexts with other OSes, like the ones above, need `canvas_noise=True`.

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
  and Mullvad Browser. Stock Firefox does not do this, so the launch prints a
  `LeakWarning`; the browser reads as a privacy-hardened Firefox rather than a
  stock one.

`canvas_noise=True` turns the protection on for any OS, `canvas_noise=False`
never.

WebGPU follows the same rule. `navigator.gpu` exists only where Firefox on the
claimed device has it (Windows and Apple Silicon Macs), and the adapter is the
host's only when the identity claims the host's GPU. Otherwise
`requestAdapter()` returns `null`, as Firefox does for a blocked or software GPU.

### Headless modes

| `headless=` | What runs | Notes |
|---|---|---|
| `False` (default) | A normal window | Needs a display. |
| `True` | Firefox headless | Camoufox patches the headless tells it knows about. |
| `"virtual"` | A headed browser on a private Xvfb display | Linux only, needs `Xvfb`. Handled by `Camoufox`, `AsyncCamoufox`, `NewBrowser` and `launch_server`. The display is 1x1 unless `CAMOUFOX_VIRTUAL_DISPLAY_SIZE` (e.g. `1920x1080x24`) says otherwise. |

### Remote server

Run Camoufox in one process and connect from any language Playwright supports:

```python
from camoufox.server import launch_server

launch_server(headless=True, geoip=True, port=1234, ws_path="camoufox")
```

It prints the websocket endpoint. Connect with
`playwright.firefox.connect("ws://localhost:1234/camoufox")`. A persistent
context cannot be served.

### Your own Playwright instance

`NewBrowser()` launches on a Playwright instance you already have, and
`launch_options()` returns the keyword arguments for
`playwright.firefox.launch()`:

```python
from playwright.sync_api import sync_playwright
from camoufox import NewBrowser, launch_options

with sync_playwright() as playwright:
    browser = NewBrowser(playwright, os="linux", headless=True)
    browser.close()

    browser = playwright.firefox.launch(**launch_options(os="linux", headless=True))
    browser.close()
```

Prefer `NewBrowser()`: it also defaults new pages to `no_viewport` when the
window size is spoofed, and to the host's own color scheme and motion settings.

## Launch options

`Camoufox`, `AsyncCamoufox`, `NewBrowser`, `AsyncNewBrowser`, `launch_server`
and `launch_options` all take these keyword arguments. Any other keyword is
passed to Playwright's `firefox.launch()` (or `launch_persistent_context()`).

| Option | Type | Default | Effect |
|---|---|---|---|
| `os` | `str` or `list[str]` | fpgen's real-world mix | `"windows"`, `"macos"`, `"linux"`, or a list to pick from. |
| `headless` | `bool` or `"virtual"` | `False` | See [Headless modes](#headless-modes). |
| `proxy` | `dict` | none | Playwright proxy: `server`, `username`, `password`, `bypass`. |
| `geoip` | `bool` or `str` | none | `True` finds the public IP (through `proxy` if set); a string uses that IP. Sets timezone, locale, geolocation and the WebRTC IP. Needs the `geoip` extra. |
| `geoip_db` | `str` | the `camoufox set --geoip` choice | GeoIP database name, e.g. `"GeoIP AIO by daijro"`. |
| `locale` | `str` or `list[str]` | from `geoip`, else the drawn identity's | Locale(s), e.g. `"en-US"` or `["fr-FR", "en-US"]`. The first is used for `Intl`. |
| `humanize` | `bool` or `float` | off | Human cursor movement. A number caps one movement at that many seconds (default cap 1.5). |
| `screen` | `camoufox.fingerprints.Screen` | the real display when headed | Bounds the generated screen: `Screen(max_width=1920, max_height=1080)`. |
| `window` | `(int, int)` | generated | Fixed outer window size. |
| `fonts` | `list[str]` | none | Extra font families on top of the OS's own. |
| `custom_fonts_only` | `bool` | `False` | Use only `fonts`, not the OS fonts. Warns: the font set no longer matches the OS. |
| `addons` | `list[str]` | none | Paths to extracted Firefox addons (folders with a `manifest.json`). |
| `exclude_addons` | `list[DefaultAddons]` | none | Default addons to leave out, e.g. `[DefaultAddons.UBO]`. |
| `block_images` | `bool` | `False` | Block image loading. Warns: some WAFs detect it. |
| `block_webrtc` | `bool` | `False` | Disable WebRTC entirely. |
| `block_webgl` | `bool` | `False` | Disable WebGL. Warns: many WAFs check for it. |
| `webgl_config` | `(vendor, renderer)` | drawn | Use one GPU fpgen has recorded for Firefox on `os` (see `camoufox.webgl.firefox_gpus`); any other pair raises `ValueError`. Needs `os`. |
| `canvas_noise` | `bool` | on for another OS | Random canvas and WebGL readback, as in LibreWolf. Warns. See [The canvas on another OS](#the-canvas-on-another-os). |
| `disable_coop` | `bool` | `False` | Turn off Cross-Origin-Opener-Policy so elements in cross-origin iframes (such as the Turnstile checkbox) can be clicked. Warns. |
| `main_world_eval` | `bool` | `False` | Allow `page.evaluate("mw:...")` and `mw:` init scripts to run in the page's own world. |
| `allow_addon_new_tab` | `bool` | `False` | Let addons open tabs. |
| `enable_cache` | `bool` | `False` | Keep Firefox's page and request caches. Uses more memory. |
| `pin_cpu_cores` | `bool` | `False` | Linux and Windows: pin the browser to as many cores as `navigator.hardwareConcurrency` claims, so a page timing parallel workers measures the same number. Costs CPU and serializes concurrent launches. |
| `fingerprint` | fpgen fingerprint `dict` | drawn | Use this fpgen fingerprint instead of drawing one. Warns. |
| `fingerprint_preset` | `bool` or `dict` | `None` | Opt into a recorded real-device preset instead of fpgen: `True` picks a random bundled one, a dict uses that one. |
| `ff_version` | `int` | the browser's own | Firefox version to claim. Warns: a mismatch with the engine is detectable. |
| `config` | `dict` | none | Raw Camoufox properties ([`properties.json`](../browser/settings/properties.json)). Overrides the generated identity; manual identity keys warn. |
| `firefox_user_prefs` | `dict` | none | Extra Firefox prefs. |
| `args` | `list[str]` | none | Extra browser command-line arguments. |
| `env` | `dict` | a copy of the environment | Environment variables for the browser. |
| `executable_path` | `str` or `Path` | the installed build | Use this binary. `CAMOUFOX_EXECUTABLE_PATH` sets it too. |
| `browser` | `str` | the paired build | Launch another installed build: `"official/beta.20"`, `"beta.20"` or `"134.0.2-beta.20"`. Never downloads; warns like `camoufox set`. |
| `virtual_display` | `str` | none | Use an existing X display, e.g. `":99"`. |
| `i_know_what_im_doing` | `bool` | `False` | Silence the leak warnings above. |
| `debug` | `bool` | `False` | Print the config sent to the browser. |

`NewBrowser` and `AsyncNewBrowser` also take `persistent_context` and
`from_options` (a dict from `launch_options()` to use as is).

## CLI

`camoufox <command>`, or `python -m camoufox <command>`.

| Command | Options | What it does |
|---|---|---|
| `fetch [VERSION]` | | Install the paired build (or, after `set`, the latest in the chosen channel), or `VERSION` without making it active. Syncs first. |
| `sync` | `--spoof-os auto\|mac\|win\|lin`, `--spoof-arch auto\|x86_64\|i686\|arm64` | Refresh the list of available builds from every repository. |
| `set [SPECIFIER]` | `--geoip`, `--release` | Pin a build (`official/stable/134.0.2-beta.20`) or follow a channel (`official/stable`). No specifier opens a picker. `--geoip` picks the GeoIP database instead; `--release` goes back to the paired build. |
| `active` | | Print the active build. A build that is chosen but not downloaded is marked `(not fetched)`. |
| `list [installed\|all]` | `--path` | List installed builds, or every available one, as a tree. |
| `remove [VERSION]` | `--select`, `-y/--yes` | Remove one build, pick one interactively, or (with no argument) the whole data directory. |
| `version` | | Package versions (Camoufox, fpgen, Playwright), the active build and whether it is the latest in its channel, the GeoIP database, and storage paths and sizes. |
| `path` | | Print the data directory (`~/.cache/camoufox` on Linux). |
| `test [URL]` | `--executable-path PATH` | Open a headed browser with the Playwright inspector. |
| `server` | | Start a Playwright server with default options and print its websocket endpoint. |

`set` and `fetch` read builds from these repositories (`repos.yml`):

| Name | Repository |
|---|---|
| Official | `daijro/camoufox` |
| CoryKing | `coryking/camoufox` |
| JWriter20 | `JWriter20/camoufox` |

https://github.com/user-attachments/assets/992b1830-6b21-4024-9165-728854df1473

### Which browser build is used

Each release of this package is paired with the one browser build it was built
and tested with. `camoufox fetch` installs that build and every launch uses it,
even when other builds are installed and even when the paired build is a
prerelease. A launch with the paired build missing downloads it first, so
upgrading the package never runs a browser it was not tested with.

`camoufox set` overrides the pairing. The choice is kept, and each launch warns
that the build differs from the paired one. `camoufox set --release` goes back.
The `browser` launch option overrides it for one launch, the same way: the named
build must already be installed, and nothing is downloaded.

Every browser release declares the interface it speaks, and the package refuses
one it cannot drive: `sync` leaves it out, `fetch` refuses it, and a launch
fails, each saying which package upgrade is needed. Once a sync has seen such a
build, every launch warns that the package needs upgrading.

A development checkout (installed from the repository, not from PyPI) is
paired with nothing and follows its channel, `official/stable` by default.

## Licence

MIT ([`LICENSE`](LICENSE)). The browser itself is MPL-2.0.
