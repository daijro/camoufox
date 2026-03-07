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

## CLI Mananger

#### Demonstration

https://github.com/user-attachments/assets/992b1830-6b21-4024-9165-728854df1473


<details>
<summary>See help message</summary>

```
$ python -m camoufox --help

 Usage: python -m camoufox [OPTIONS] COMMAND [ARGS]...

╭─ Options ─────────────────────────────────────────────────────────────────────────╮
│ --help  Show this message and exit.                                               │
╰───────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ──────────────────────────────────────────────────────────────────────────────────╮
│ active      Print the current active version                                                 │
│ fetch       Install the active version, or a specific version.                               │
│ gui         Launch the Camoufox Manager GUI (requires PySide6)                               │
│ list        List Camoufox versions                                                           │
│ path        Print the install directory path                                                 │
│ remove      Remove Camoufox data directory, or an installed browser version                  │
│             Or, remove a specific version:                                                   │
│                 Select a version:     camoufox remove --select                               │
│                 Remove a version:     camoufox remove official/stable/134.0.2-beta.20        │
│ server      Launch a Playwright server                                                       │
│ set         Interactive selector for versions and settings                                   │
│             Or, pass a specifier to activate directly:                                       │
│                 Pin version:          camoufox set official/stable/134.0.2-beta.20            │
│                 Auto-update channel:  camoufox set official/stable                           │
│ sync        Sync available versions from remote repositories.                                │
│ test        Open the Playwright inspector                                                    │
│ version     Display version, package, browser, and storage info                              │
╰─────────────────────────────────────────────────────────────────────────────────────────────╯
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
> camoufox set official/stable  # Default setting
```

Follow latest prerelease version from the official repo, if applicable:

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
> camoufox active  # Default channel is active
official/stable
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

Install the latest version from the active channel. By default, this is official/stable. This will also automatically sync repository assets.

```bash
> camoufox fetch  # Install the latest in the channel
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
  Camoufox                    v0.5.0
  Browserforge                v1.2.4
  Apify Fingerprints          v0.10.0
  Playwright                  v1.57.1.dev0+g732639b35.d20251217
Browser
  Active                      official/stable/135.0.1-beta.24
  Browser                     v135.0.1-beta.24
  Installed                   Yes
  Latest in official/stable?  Yes
  Last Sync                   2026-03-07 00:23
GeoIP
  Database                    MaxMind GeoLite2
  Updated                     2026-03-07 00:24
Storage
  Install path                /home/name/.cache/camoufox
  Browser(s) directory size   1.2 GB
  GeoIP database size         40.7 MB
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

---

## Usage

All of the latest stable documentation is avaliable at [camoufox.com/python](https://camoufox.com/python).
