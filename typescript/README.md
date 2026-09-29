# camoufox (TypeScript)

This is the JavaScript/TypeScript client for Camoufox. It is a port of the
Python wrapper in [`../pythonlib`](../pythonlib) — it does **not** shell out
to Python.

The two launchers are twins: they read the same `properties.json`, write the
same chunked `CAMOU_CONFIG`, share the same browser install directory, and
ship the same fingerprint presets, font/voice lists and GeoIP configuration.
They draw the same identities too: fingerprints and WebGL devices come from a
TypeScript port of [fpgen](https://github.com/scrapfly/fingerprint-generator)
using the same pinned model, and the per-identity draws (fonts, voices, GPU,
media devices, noise seeds) use a bit-exact port of CPython's `random`, so a
pinned identity presents identically from either language.

## Installation

```bash
npm install @camoufox/camoufox playwright-core
# then download the browser
npx camoufox fetch
```

`playwright-core` is a peer dependency — bring your own version (`<1.63`,
the same ceiling as the Python package). Node 22.15 or newer is required.

## Usage

```javascript
import { Camoufox } from "@camoufox/camoufox";

const browser = await Camoufox({
    // any Camoufox option, plus any Playwright Firefox launch option
    headless: true,
    os: "windows",
    geoip: true,
});

const page = await browser.newPage(); // a Playwright Page
await page.goto("https://example.com");
await browser.close();
```

### Persistent profiles

```javascript
const context = await Camoufox({ user_data_dir: "./profiles/alice" });
const page = await context.newPage();
```

### Per-context identities

`NewContext()` gives each context its own fingerprint — real preset or
fpgen-synthesised — with its own audio noise seed. The
values are applied through `addInitScript`, so the setters self-destruct before
any page script runs.

```javascript
import { Camoufox, NewContext } from "@camoufox/camoufox";

const browser = await Camoufox({ headless: true });
const context = await NewContext(browser, {
    os: "macos",
    proxy: { server: "http://proxy:8080", username: "u", password: "p" },
});
```

When a `proxy` is given and no `webrtc_ip`/`timezoneId` is, both are resolved
from the proxy's exit IP. If that lookup fails, `NewContext()` throws
`InvalidIP` rather than open a context that would show the host's values.

### Server mode

```javascript
import { launchServer } from "@camoufox/camoufox";

const server = await launchServer({ headless: true, port: 9222 });
console.log(server.wsEndpoint());
```

Persistent contexts are not servable — Playwright's `launchServer` can only
expose a pre-launched `Browser`.

### Building launch options yourself

```javascript
import { launchOptions } from "@camoufox/camoufox";
import { firefox } from "playwright-core";

const browser = await firefox.launch(await launchOptions({ os: "linux" }));
```

## Options

Every option from the Python `launch_options()` is supported, with the same
snake_case names: `os`, `config`, `block_images`, `block_webrtc`,
`block_webgl`, `disable_coop`, `webgl_config`, `geoip`, `geoip_db`, `humanize`,
`locale`, `addons`, `fonts`, `custom_fonts_only`, `exclude_addons`, `screen`,
`window`, `fingerprint`, `fingerprint_preset`, `ff_version`, `headless`,
`main_world_eval`, `allow_addon_new_tab`, `executable_path`, `browser`,
`firefox_user_prefs`, `proxy`, `enable_cache`, `args`, `env`,
`i_know_what_im_doing`, `debug`, `virtual_display`, `pin_cpu_cores`. Anything else is passed
straight through to Playwright.

The returned launch options use Playwright's camelCase keys
(`executablePath`, `firefoxUserPrefs`) rather than Python's snake_case. As in
Python, `headless: "virtual"` is handled by `Camoufox()`, `NewBrowser()` and
`launchServer()`, not by `launchOptions()`.

## CLI

```
camoufox sync                     # refresh the version catalogue
camoufox fetch [version]          # install the paired (or chosen) build, or a specific version
camoufox set [specifier]          # pin a version or channel; no specifier opens a picker
camoufox set --release            # go back to the build this release is paired with
camoufox set --geoip              # pick a GeoIP source
camoufox list [installed|all]     # list versions
camoufox remove [version]         # remove one version, or everything (--select to pick)
camoufox active                   # print the active version
camoufox path                     # print the install directory
camoufox version                  # version / storage info
camoufox test [url]               # open the Playwright inspector
camoufox server                   # launch a Playwright server
```

Each release of this package is paired with the one browser build it was built
and tested with, the same build as the `camoufox` Python release of the same
version. The first launch installs that build, and every launch uses it, until
you choose another with `camoufox set`. A launch then warns that the build
differs from the paired one. See the Python package's README, under "Which
browser build is used".

The commands and pickers match the Python CLI. The one exception is `gui`, a
PySide6 desktop app that only the Python package provides.

## Development

The tests need a Python with pythonlib next to them, at the repo root (or
point `CAMOUFOX_PYTHON` at one):

```bash
python3.14 -m venv .venv                                           # repo root
.venv/bin/pip install -r ci/requirements.txt -e pythonlib
.venv/bin/python scripts/pin-fpgen-model.py
cd typescript
pnpm install
pnpm build       # tsc -> dist/, then copy pythonlib's data files into dist/data-files
pnpm test        # records the golden fixtures from pythonlib, then vitest
pnpm check       # biome lint + format
pnpm typecheck   # tsc --noEmit
```

The data files (presets, fonts, voices, territoryInfo.xml, ...) are read from
`pythonlib/camoufox/`, the only copy in the repo; `DATA_FILES` in
`src/paths.ts` lists them, and the build copies them into the package.

### Parity with pythonlib

The golden tests are what keep the two launchers twins. Before the suite runs,
`tests/golden-setup.ts` runs the scripts under `scripts/golden/`, which put the
Python code through hundreds of fixed inputs and record its output in
`tests/fixtures/` (git-ignored); the TS tests must reproduce it exactly --
`launch_options()` byte for byte, including the `CAMOU_CONFIG` blob. A
pythonlib change that is not mirrored here fails `pnpm test`. Use Python 3.14:
`pySum()` follows its `sum()`, and on 3.12/3.13 that one test skips.

The end-to-end suite launches a real browser through both launchers and compares
what a page sees:

```bash
CAMOUFOX_E2E=1 CAMOUFOX_EXECUTABLE=/path/to/camoufox-bin pnpm test tests/e2e.test.ts
```

## Releasing

The npm package and pythonlib are released together by
[`.github/workflows/release.yml`](../.github/workflows/release.yml): a
prerelease under the `next` dist-tag for every tested merge to `main` that
changes the package, and a stable release under `latest` for a `vX.Y.Z` tag (see
[`ci/README.md`](../ci/README.md#releases)). One job builds both packages and
runs `scripts/check-pack.mjs` (the version must equal pythonlib's; every data
file must be in the tarball; the tarball must install and import in an empty
project); PyPI gets its upload first, then npm gets that same tarball, published
with trusted publishing (no token is stored).

## Licence

MIT, like the Python package ([`LICENSE`](LICENSE)); the browser itself is
MPL-2.0. The package contains ports of fpgen (Apache-2.0), CPython's `random`
and NumPy's pairwise summation; their notices are in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md), which ships with it.
