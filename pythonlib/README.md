<div align="center">

# Camoufox Python Interface

#### Lightweight wrapper around the Playwright API to help launch Camoufox.

</div>

> [!NOTE]
> All the latest documentation is available [here](https://camoufox.com/python).

---

## What is this?

This Python library wraps around Playwright's API to help automatically generate & inject unique device characteristics (OS, CPU info, navigator, fonts, headers, screen dimensions, viewport size, WebGL, addons, etc.) into Camoufox.

It uses [fpgen](https://github.com/scrapfly/fingerprint-generator) under the hood to generate fingerprints that mimic the statistical distribution of device characteristics in real-world traffic.

In addition, it will also calculate your target geolocation, timezone, and locale to avoid proxy protection ([see demo](https://i.imgur.com/UhSHfaV.png)).

---

## Installation

First, install the `camoufox` package:

```bash
pip install -U camoufox[geoip]
```

The `geoip` parameter is optional, but heavily recommended if you are using proxies. It will download an extra dataset to determine the user's longitude, latitude, timezone, country, & locale.

The dataset is [GeoIP All-in-One](https://github.com/daijro/geoip-all-in-one), which merges several IP databases and is rebuilt weekly. Camoufox fetches the newest build and refreshes it once it is a week old.

Next, download the Camoufox browser:

```bash
camoufox fetch
```

`fetch` also installs fpgen's model, pinned by sha256, into fpgen's package directory. Otherwise the first generated fingerprint installs it. Run `fetch` as that directory's owner if the browser will run as another user, e.g. while building a Docker image.

To uninstall, run `camoufox remove`.

---

# Installing multiple Camoufox versions & from other repos

## UI Manager

Manage installed browsers, active version, IP geolocation databases, and package info. Basically a Qt front end for the Python CLI tool.

More updates on it will be coming soon.

<img width="802" height="552" alt="ui-screenshot" src="https://github.com/user-attachments/assets/6668f8f0-5b08-4c36-bbea-fea4baeccc9c" />

<hr width=50>

To use the gui, install Camoufox with the `[gui]` extra:

```bash
pip install 'camoufox[gui]'
```

To launch:

```bash
camoufox gui
```

---

## CLI Manager

#### Demonstration

https://github.com/user-attachments/assets/992b1830-6b21-4024-9165-728854df1473

<details>
<summary>See help message</summary>

```
$ python -m camoufox --help

 Usage: python -m camoufox [OPTIONS] COMMAND [ARGS]...

╭─ Options ─────────────────────────────────────────────────────────────────────────────╮
│ --help  Show this message and exit.                                                   │
╰───────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ────────────────────────────────────────────────────────────────────────────╮
│ active    Print the current active version                                            │
│ fetch     Install the active version, or a specific version                           │
│ gui       Launch the Camoufox Manager GUI (requires PySide6)                          │
│ list      List Camoufox versions                                                      │
│ path      Print the install directory path                                            │
│ remove    Remove downloaded data. By default, this removes everything.                │
│           Pass --select to pick a browser version to remove.                          │
│ rest      Launch a REST API that runs page jobs                                       │
│ server    Launch a Playwright server                                                  │
│ set       Set the active Camoufox version to use & fetch.                             │
│           By default, this opens an interactive selector for versions and settings.   │
│           You can also pass a specifier to activate directly:                         │
│           Pin version:                                                                │
│               camoufox set official/stable/134.0.2-beta.20                            │
│           Automatically find latest in a channel source:                              │
│               camoufox set official/stable                                            │
│ sync      Sync available versions from remote repositories                            │
│ test      Open the Playwright inspector                                               │
│ version   Display version, package, browser, and storage info                         │
╰───────────────────────────────────────────────────────────────────────────────────────╯
```

</details>

### `sync`

Pull a list of release assets from GitHub.

```bash
> camoufox sync
Syncing repositories...
  Official... 24 versions
  CoryKing... 2 versions

Synced 26 versions from 2 repos.
```

<hr width=50>

### Which browser build is used

Each camoufox release is paired with the one browser build it was built and tested with. By default, `camoufox fetch` installs exactly that build and every launch uses it. A launch with the paired build missing downloads it first. That holds even when other builds are installed, and even when the paired build is a prerelease (a prerelease of this package pairs with a prerelease browser). Upgrading the package therefore never runs a browser it was not tested with. Run `camoufox fetch` after upgrading to install the new pairing.

Choosing a channel or a build with `camoufox set` overrides the pairing. The choice is kept, and a launch warns that the build differs from the paired one. `camoufox set --release` goes back to the paired build.

Every browser release also declares the interface it speaks, and this package refuses one it cannot drive. `camoufox sync` leaves such a build out of the installable versions and says to upgrade the package, `camoufox fetch` refuses it with the same advice, and a launch with one installed fails rather than misbehaving. Once a sync has seen such a build, every launch warns that the package needs upgrading, without a network request.

A development checkout (installed from the repository, not from PyPI) is paired with nothing and follows its channel, `official/stable` by default.

<hr width=50>

### `set`

Choose a version channel or pin a specific version, overriding the paired build. Can also be called with a specifier to activate directly.

Interactive selector:

```bash
> camoufox set
```

You can also pass a specifier to pin a specific version or choose a channel to follow directly. Following `official/stable` pulls the latest stable version from the official repo on `camoufox fetch`:

```bash
> camoufox set official/stable
```

Follow latest prerelease version from the official repo, if applicable:

```bash
> camoufox set official/prerelease
```

Pin a specific version:

```bash
> camoufox set official/stable/134.0.2-beta.20
```

Go back to the build this release is paired with:

```bash
> camoufox set --release
```

<hr width=50>

### `active`

Prints the current active version string:

```bash
> camoufox active  # A released package uses its paired build by default
official/prerelease/156.0.1-beta.33 (1a2b3c4d) (paired with this release)
```

```bash
> camoufox set coryking/stable/142.0.1-fork.26
Pinned: coryking/stable/142.0.1-fork.26
Run 'camoufox fetch' to install.

> camoufox active  # A specific version is pinned
coryking/stable/142.0.1-fork.26 (not installed)
```

<hr width=50>

### `fetch`

Install the browser build this release is paired with, or, after `camoufox set`, the latest version from the chosen channel. This will also automatically sync repository assets.

```bash
> camoufox fetch  # Install the paired build (or the latest in the chosen channel)
```

To download the latest from a different channel, or pin a version:

```bash
> camoufox set coryking/stable
> camoufox fetch  # Will download the latest release from CoryKing's repo for now on
```

Or pass in the identifier to download directly without activating it:

```bash
> camoufox fetch official/stable/135.0-beta.25   # Install a specific version
```

<hr width=50>

### `list`

List installed or all available Camoufox versions as a tree.

```bash
> camoufox list          # show installed versions
> camoufox list all      # show all available versions from synced repos
> camoufox list --path   # show full install paths
```

<hr width=50>

### `remove`

By default, removes the entire camoufox data directory.

```bash
> camoufox remove
> camoufox remove -y  # skip confirmation prompt
```

Remove a specific version:

```bash
> camoufox remove official/stable/134.0.2-beta.20
```

Interactively select a version to remove:

```bash
> camoufox remove --select
```

<hr width=50>

### `version`

Display the Python package version, active browser version, channel, and update status.

```bash
> camoufox version
Python Packages
  Camoufox                    v0.5.7
  fpgen                       v1.3.0
  Playwright                  v1.62.0
Browser
  Active                      official/stable/152.0.4-beta.31
  Current browser             v152.0.4-beta.31
  Installed                   Yes
  Latest in official/stable?  Yes
  Last Sync                   2026-03-07 00:23
GeoIP
  Database                    GeoIP AIO by daijro
  Updated                     2026-03-07 00:24
Storage
  Install path                /home/name/.cache/camoufox
  Browser(s) directory size   1.2 GB
  GeoIP database size         116.4 MB
  Config file                 /home/name/.cache/camoufox/config.json
  Repo cache                  /home/name/.cache/camoufox/repo_cache.json
```

<hr width=50>

### `path`

Print the install directory path.

```bash
> camoufox path
/home/name/.cache/camoufox
```

<hr width=50>

### `test`

Open Camoufox with the Playwright inspector for debugging.

```bash
> camoufox test
> camoufox test https://example.com
```

<hr width=50>

### `server`

Launch a remote Playwright server.

```bash
> camoufox server
```

<hr width=50>

### `rest`

Launch a REST API, for clients that want plain HTTP instead of the SDK. It runs
one headless Camoufox and gives every job a fresh browser context, closed when
the job ends.

```bash
> camoufox rest --port 8000 --concurrency 2 --timeout 30
Camoufox REST API listening on http://127.0.0.1:8000
```

Open that address in a browser for a web page that submits jobs, follows their
status and shows the HTML or screenshot. Paste the token under **Token** when
the service has one. `/docs` is an interactive (Swagger UI) reference for every
endpoint and field, generated from `/openapi.json`; its **Authorize** button
takes the token.

Submit a job, poll it, then fetch the result. `operation` is `content` (final
URL, title and HTML) or `screenshot` (final URL, title and a base64 PNG).

```bash
id=$(curl -s -X POST localhost:8000/jobs -d '{"url": "https://example.com", "operation": "content"}' | jq -r .id)
curl -s localhost:8000/jobs/$id          # {"id": ..., "status": "succeeded", "error": null, ...}
curl -s localhost:8000/jobs/$id/result   # {"url": "https://example.com/", "title": "Example Domain", "html": ...}
```

A job takes these fields:

| Field | Default | Meaning |
|---|---|---|
| `url` | required | The `http` or `https` page to open |
| `operation` | required | `content` or `screenshot` |
| `wait_until` | `load` | When navigation counts as done: `commit`, `domcontentloaded`, `load` or `networkidle` |
| `selector` | none | A [Playwright selector](https://playwright.dev/python/docs/selectors) to wait for; the result is then only that element (its outer HTML, or a screenshot of it) |
| `full_page` | `false` | Screenshot the whole page, not only the viewport (screenshots without `selector`) |
| `timeout` | `--timeout` | Seconds the job may run, at most `--timeout` |

A page that keeps loading third-party resources may never fire `load` and
times out. For such pages, wait for `domcontentloaded` plus a `selector` for
the content you need:

```bash
curl -s -X POST localhost:8000/jobs -d '{"url": "https://example.com", "operation": "screenshot",
  "wait_until": "domcontentloaded", "selector": "h1", "timeout": 60}'
```

Send the URL as the browser would, percent-encoded and with `&` (not `&amp;`)
between query parameters.

| Endpoint | Response |
|---|---|
| `POST /jobs` | `202` and the job; `400` for an invalid field or a blocked URL; `503` when `--max-jobs` unfinished jobs are held |
| `GET /jobs/{id}` | The job's fields, its `status` (`queued`, `running`, `succeeded`, `failed`) and `error` |
| `GET /jobs/{id}/result` | `200` and the result once succeeded, otherwise `409` with the job and its error |
| `GET /openapi.json`, `GET /docs` | The OpenAPI 3.1 description, and Swagger UI for it (loaded from jsDelivr, pinned and integrity-checked); neither needs the token |

At most `--concurrency` jobs run at once; the rest queue. `--timeout` bounds a
running job, and a job's own `timeout` can only shorten it. Results stay in memory, and the oldest finished job is dropped
when a new one needs its slot. Stopping the service (Ctrl-C or SIGTERM) cancels
unfinished jobs and closes the browser.

The defaults are restrictive:

- Only `http` and `https` URLs are accepted, and launch options and page
  scripts cannot be set over HTTP.
- A URL that resolves to a loopback, private, link-local or otherwise
  non-public address is refused, a page's requests to one are aborted, and a
  job whose redirect lands on one fails without returning anything. Pass
  `--allow-private-networks` to lift this. The check cannot stop the browser
  from sending a redirected request, or a WebSocket, to such an address, so
  restrict egress at the network level when the service is exposed to
  untrusted clients.
- It binds to `127.0.0.1`. To bind elsewhere, set `CAMOUFOX_REST_TOKEN`;
  clients then send an `Authorization` header of `Bearer <token>`.

To run it in Docker, build the image from `pythonlib/` (BuildKit, the default
since Docker 23). The browser is downloaded at build time, in a layer that
editing the REST service or the README does not rebuild. Inside the container the service binds `0.0.0.0`, so
it needs a token; publish the port on loopback unless clients are remote.

```bash
docker build -t camoufox-rest pythonlib
export CAMOUFOX_REST_TOKEN=$(openssl rand -hex 16) && echo "$CAMOUFOX_REST_TOKEN"
docker run --rm --shm-size=1g -p 127.0.0.1:8000:8000 -e CAMOUFOX_REST_TOKEN camoufox-rest
```

Docker gives a container 64 MB of `/dev/shm`, which Firefox can outgrow on heavy
pages; `--shm-size` raises it.

Options go after the image name, for example `camoufox-rest --concurrency 4`.

---

## Usage

All of the latest stable documentation is available at [camoufox.com/python](https://camoufox.com/python).
