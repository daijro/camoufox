<div align="center">

# Camoufox Python Interface

#### Lightweight wrapper around the Playwright API to help launch Camoufox.

</div>

> [!NOTE]
> All the the latest documentation is avaliable [here](https://camoufox.com/python).

---

## What is this?

This Python library wraps around Playwright's API to help automatically generate & inject unique device characteristics (OS, CPU info, navigator, fonts, headers, screen dimensions, viewport size, WebGL, addons, etc.) into Camoufox.

It uses [BrowserForge](https://github.com/daijro/browserforge) under the hood to generate fingerprints that mimic the statistical distribution of device characteristics in real-world traffic.

In addition, it will also calculate your target geolocation, timezone, and locale to avoid proxy protection ([see demo](https://i.imgur.com/UhSHfaV.png)).

---

## Installation

First, install the `camoufox` package:

```bash
pip install -U camoufox[geoip]
```

The `geoip` parameter is optional, but heavily recommended if you are using proxies. It will download an extra dataset to determine the user's longitude, latitude, timezone, country, & locale.

Next, download the Camoufox browser:

**Windows**

```bash
camoufox fetch
```

**MacOS & Linux**

```bash
python3 -m camoufox fetch
```

To uninstall, run `camoufox remove`.

---

## Installing browser versions

### UI Manager

To use the gui, install the needed library:

```bash
pip install 'camoufox[gui]'
```

---

### CLI Commands

<details>
<summary>See help message</summary>

```
$ python -m camoufox --help

 Usage: python -m camoufox [OPTIONS] COMMAND [ARGS]...

╭─ Options ─────────────────────────────────────────────────────────────────────────╮
│ --help  Show this message and exit.                                               │
╰───────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ────────────────────────────────────────────────────────────────────────╮
│ active    Print the current active version                                        │
│ fetch     Install the active version, or a specific version.                      │
│ gui       Launch the Camouman GUI (requires PySide6)                              │
│ list      List Camoufox versions.                                                 │
│ path      Print the install directory path                                        │
│ remove    Remove installed version(s)                                             │
│           Or, pass a specifier to remove directly:                                │
│             camoufox remove official/stable/134.0.2-beta.20                       │
│ server    Launch a Playwright server                                              │
│ set       Interactive selector for versions and settings                          │
│           Or, pass a specifier to activate directly:                              │
│               Pin version:          camoufox set official/stable/134.0.2-beta.20  │
│               Auto-update channel:  camoufox set official/stable                  │
│ sync      Sync available versions from remote repositories.                       │
│ test      Open the Playwright inspector                                           │
│ version   Display version info                                                    │
╰───────────────────────────────────────────────────────────────────────────────────╯
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

### `set`

Choose a version channel or pin a specific version. Can also be called with a specifier to activate directly.

Interactive selector:

```bash
> camoufox set
```

You can also pass a specifier to pin a specific version or choose a channel to follow directly. This will pull the latest stable version from the official repo on `camoufox fetch`.

```bash
> camoufox set official/stable  # This is the default setting
```

Follow latest prerelease version from the official repo:

```bash
> camoufox set official/prerelease
```

Pin a specific version:

```bash
> camoufox set official/stable/134.0.2-beta.20
```

<hr width=50>

### `active`

Prints the current active version string:

```bash
> camoufox active
official/stable
```

```bash
> camoufox set coryking/stable/142.0.1-fork.26
Pinned: coryking/stable/142.0.1-fork.26
Run 'camoufox fetch' to install.

> camoufox active
coryking/stable/142.0.1-fork.26 (not installed)
```

<hr width=50>

### `fetch`

Install the active version, or a specific version. This will also automatically sync repository assets.

```bash
> camoufox fetch                              # install active channel's latest
> camoufox fetch official/135.0-beta.25       # install a specific version
```

<hr width=50>

### `list`

List installed or all available Camoufox versions as a tree.

```bash
> camoufox list                       # show installed versions
> camoufox list all                   # show all available versions from synced repos
> camoufox list --path                # show full install paths
```

<hr width=50>

### `remove`

Remove installed browser versions and/or GeoIP data. Opens an interactive selector, or pass a specifier to remove directly.

Interactively select a specific version to remove:

```bash
camoufox remove                                     # interactive selection
```

Remove a specific version:

```bash
camoufox remove official/stable/134.0.2-beta.20     # remove a specific version
```

Remove all:

```bash
camoufox remove --all                               # remove everything
camoufox remove --all -y                            # skip confirmation prompts
```

<hr width=50>

### `version`

Display the Python package version, active browser version, channel, and update status.

```bash
camoufox version
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

Open the Playwright inspector for debugging.

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

---

## Usage

All of the latest documentation is avaliable at [camoufox.com/python](https://camoufox.com/python).
