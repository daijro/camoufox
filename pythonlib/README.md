<div align="center">

# Camoufox Python Interface

#### Lightweight wrapper around the Playwright API to help launch Camoufox.

</div>

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

<details>
<summary>CLI options</summary>

```
Usage: python -m camoufox [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  fetch    Fetch the latest version of Camoufox
  path     Display the path to the Camoufox executable
  remove   Remove all downloaded files
  server   Launch a Playwright server
  test     Open the Playwright inspector
  version  Display the current version
```

</details>

<hr width=50>

## Usage

Camoufox is fully compatible with your existing Playwright code. You only have to change your browser initialization:

#### Sync API

```python
from camoufox.sync_api import Camoufox

with Camoufox(headless=False) as browser:
    page = browser.new_page()
    page.goto("https://example.com/")
```

#### Async API

```python
from camoufox.async_api import AsyncCamoufox

async with AsyncCamoufox(headless=False) as browser:
    page = await browser.new_page()
    await page.goto("https://example.com")
```

### Parameters List

<details>

<summary><strong>See parameters list...</strong></summary>

```
Launches a new browser instance for Camoufox.
Accepts all Playwright Firefox launch options, along with the following:

Parameters:
    os (Optional[ListOrString]):
        Operating system to use for the fingerprint generation.
        Can be "windows", "macos", "linux", or a list to randomly choose from.
        Default: ["windows", "macos", "linux"]
    block_images (Optional[bool]):
        Whether to block all images.
    block_webrtc (Optional[bool]):
        Whether to block WebRTC entirely.
    allow_webgl (Optional[bool]):
        Whether to allow WebGL. To prevent leaks, only use this for special cases.
    geoip (Optional[Union[str, bool]]):
        Calculate longitude, latitude, timezone, country, & locale based on the IP address.
        Pass the target IP address to use, or `True` to find the IP address automatically.
    humanize (Optional[Union[bool, float]]):
        Humanize the cursor movement.
        Takes either `True`, or the MAX duration in seconds of the cursor movement.
        The cursor typically takes up to 1.5 seconds to move across the window.
    locale (Optional[str]):
        Locale to use in Camoufox.
    addons (Optional[List[str]]):
        List of Firefox addons to use.
    fonts (Optional[List[str]]):
        Fonts to load into Camoufox (in addition to the default fonts for the target `os`).
        Takes a list of font family names that are installed on the system.
    exclude_addons (Optional[List[DefaultAddons]]):
        Default addons to exclude. Passed as a list of camoufox.DefaultAddons enums.
    screen (Optional[Screen]):
        Constrains the screen dimensions of the generated fingerprint.
        Takes a browserforge.fingerprints.Screen instance.
    fingerprint (Optional[Fingerprint]):
        *WILL BE DEPRECATED SOON*
        Pass a custom BrowserForge fingerprint. Note: Not all values will be implemented.
        If not provided, a random fingerprint will be generated based on the provided
        `os` & `screen` constraints.
    ff_version (Optional[int]):
        Firefox version to use. Defaults to the current Camoufox version.
        To prevent leaks, only use this for special cases.
    config (Optional[Dict[str, Any]]):
        Camoufox properties to use. Camoufox will warn you if you are manually setting
        properties that it handles internally.
    headless (Union[bool, Literal['virtual']]):
        Whether to run the browser in headless mode. Defaults to False.
        If you are running linux, passing 'virtual' will use Xvfb.
    executable_path (Optional[str]):
        Custom Camoufox browser executable path.
    firefox_user_prefs (Optional[Dict[str, Any]]):
        Firefox user preferences to set.
    proxy (Optional[Dict[str, str]]):
        Proxy to use for the browser.
        Note: If geoip is True, a request will be sent through this proxy to find the target IP.
    args (Optional[List[str]]):
        Arguments to pass to the browser.
    env (Optional[Dict[str, Union[str, float, bool]]]):
        Environment variables to set.
    persistent_context (Optional[bool]):
        Whether to use a persistent context.
    debug (Optional[bool]):
        Prints the config being sent to Camoufox.
    **launch_options (Dict[str, Any]):
        Additional Firefox launch options.
```

</details>

Camoufox will warn you if your passed configuration might cause leaks.

---

### GeoIP & Proxy Support

By passing `geoip=True`, or passing in a target IP address, Camoufox will automatically use the target IP's longitude, latitude, timezone, country, locale, & spoof the WebRTC IP address.

It will also calculate and spoof the browser's language based on the distribution of language speakers in the target region.

[See demo](https://i.imgur.com/UhSHfaV.png).

#### Installation

Install Camoufox with the `geoip` extra:

```bash
pip install -U camoufox[geoip]
```

#### Usage

Pass in the proxy dictionary as you would with Playwright's `proxy` parameter:

```python
with Camoufox(
    geoip=True,
    proxy={
        'server': 'http://example.com:8080',
        'username': 'username',
        'password': 'password'
    }
) as browser:
    page = browser.new_page()
    page.goto("https://www.browserscan.net")
```

<hr width=50>

### Remote Server (experimental)

**Warning! This feature is experimental. It uses a hacky workaround to gain access to undocumented Playwright methods.**

Camoufox can be ran as a remote websocket server. It can be accessed from other devices, and languages other than Python supporting the Playwright API.

#### Launching

To launch a remote server, run the following CLI command:

```bash
python -m camoufox server
```

Or, configure the server with a launch script:

```python
from camoufox.server import launch_server

launch_server(
    headless=True,
    geoip=True,
    proxy={
        'server': 'http://example.com:8080',
        'username': 'username',
        'password': 'password'
    }
)
```

#### Connecting

To connect to the remote server, use Playwright's `connect` method:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    # Example endpoint
    browser = p.firefox.connect('ws://localhost:34091/8c7c6cdea3368d937ef7db2277d6647b')
    page = browser.new_page()
    ...
```

**Note:** Because servers only use **one browser instance**, fingerprints will not rotate between sessions. If you plan on using Camoufox at scale, consider rotating the server between sessions.

<hr width=50>

### Virtual Display

While Camoufox includes patches to prevent headless detection, running in headless mode may still be detectable in the future. It's recommended to use a virtual display buffer to run Camoufox headlessly.

If you are running Linux, and would like to run Camoufox headlessly in a virtual display, install `xvfb`:

#### Debian-based distros

```bash
sudo apt-get install xvfb
```

#### Arch-based distros

```bash
sudo pacman -S xorg-server-xvfb
```

#### Confirm `Xvfb` is installed:

```bash
$ which Xvfb
/usr/bin/Xvfb
```

Now, passing `headless='virtual'` will spawn a new lightweight virtual display in the background for Camoufox to run in.

<hr width=50>

### BrowserForge Integration

Camoufox is compatible with [BrowserForge](https://github.com/daijro/browserforge) fingerprints.

By default, Camoufox will generate an use a random BrowserForge fingerprint based on the target `os` & `screen` constraints.

```python
from camoufox.sync_api import Camoufox
from browserforge.fingerprints import Screen

with Camoufox(
    os=('windows', 'macos', 'linux'),
    screen=Screen(max_width=1920, max_height=1080),
) as browser:
    page = browser.new_page()
    page.goto("https://example.com/")
```

If Camoufox is being ran in headful mode, the max screen size will be generated based on your monitor's dimensions unless otherwise specified.

**Note:** To prevent UA mismatch detection, Camoufox only generates fingerprints with the same browser version as the current Camoufox version by default. If rotating the Firefox version is absolutely necessary, it would be more advisable to rotate between older versions of Camoufox instead.

<details>
<summary>Injecting custom Fingerprint objects...</summary>

> [!WARNING]
> It is recommended to pass `os` & `screen` constraints into Camoufox instead. Camoufox will handle fingerprint generation for you. This will be deprecated in the future.

You can also inject your own Firefox BrowserForge fingerprint into Camoufox.

```python
from camoufox.sync_api import Camoufox
from browserforge.fingerprints import FingerprintGenerator

fg = FingerprintGenerator(browser='firefox')

# Launch Camoufox with a random Firefox fingerprint
with Camoufox(fingerprint=fg.generate()) as browser:
    page = browser.new_page()
    page.goto("https://example.com/")
```

**Note:** As of now, some properties from BrowserForge fingerprints will not be passed to Camoufox. This is due to the outdated fingerprint dataset from Apify's fingerprint-suite (see [here](https://github.com/apify/fingerprint-suite/discussions/308)). Properties will be re-enabled as soon as an updated dataset is available.

</details>

<hr width=50>

### Config

If needed, Camoufox [config data](https://github.com/daijro/camoufox?tab=readme-ov-file#fingerprint-injection) can be overridden/passed as a dictionary to the `config` parameter. This can be used to enable features that have not yet been implemented into the Python library.

Although, this isn't recommended, as Camoufox will populate this data for you automatically. See the parameters list above for more proper usage.

```python
from camoufox.sync_api import Camoufox

with Camoufox(
    config={
        'webrtc:ipv4': '123.45.67.89',
        'webrtc:ipv6': 'e791:d37a:88f6:48d1:2cad:2667:4582:1d6d',
    }
) as browser:
    page = browser.new_page()
    page.goto("https://www.browserscan.net/webrtc")
```

Camoufox will warn you if you are manually setting properties that the Python library handles internally.

---
