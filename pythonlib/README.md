<div align="center">

# Camoufox Python Interface

#### Lightweight wrapper around the Playwright API to help launch Camoufox.

</div>

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
  remove   Remove all downloaded files
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

<details>
<summary>Parameters</summary>

```
Launches a new browser instance for Camoufox.
Accepts all Playwright Firefox launch options, along with the following:

Parameters:
    config (Optional[Dict[str, Any]]):
        Camoufox properties to use.
    os (Optional[ListOrString]):
        Operating system to use for the fingerprint generation.
        Can be "windows", "macos", or "linux", or a list of these to choose from randomly.
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
    locale (Optional[str]):
        Locale to use in Camoufox.
    addons (Optional[List[str]]):
        List of Firefox addons to use.
    fonts (Optional[List[str]]):
        Fonts to load into Camoufox (in addition to the default fonts for the target `os`).
        Takes a list of font family names that are installed on the system.
    exclude_addons (Optional[List[DefaultAddons]]):
        Default addons to exclude. Passed as a list of camoufox.DefaultAddons enums.
    fingerprint (Optional[Fingerprint]):
        Use a custom BrowserForge fingerprint. Note: Not all values will be implemented.
        If not provided, a random fingerprint will be generated based on the provided os & user_agent.
    screen (Optional[Screen]):
        Constrains the screen dimensions of the generated fingerprint.
        Takes a browserforge.fingerprints.Screen instance.
    headless (Optional[bool]):
        Whether to run the browser in headless mode. Defaults to True.
    executable_path (Optional[str]):
        Custom Camoufox browser executable path.
    firefox_user_prefs (Optional[Dict[str, Any]]):
        Firefox user preferences to set.
    proxy (Optional[Dict[str, str]]):
        Proxy to use for the browser.
        Note: If geoip is True, a request will be sent through this proxy to find the target IP.
    ff_version (Optional[int]):
        Firefox version to use. Defaults to the current Camoufox version.
        To prevent leaks, only use this for special cases.
    args (Optional[List[str]]):
        Arguments to pass to the browser.
    env (Optional[Dict[str, Union[str, float, bool]]]):
        Environment variables to set.
    **launch_options (Dict[str, Any]):
        Additional Firefox launch options.
```

</details>

---

### Config

Camoufox [config data](https://github.com/daijro/camoufox?tab=readme-ov-file#fingerprint-injection) can be passed as a dictionary to the `config` parameter:

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

<hr width=50>

### GeoIP & Proxy Support

By passing `geoip=True`, or passing in a target IP address, Camoufox will automatically use the target IP's longitude, latitude, timezone, country, locale, & spoof the WebRTC IP address.

It will also calculate and spoof the browser's language based on the distribution of language speakers in the target region.

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

### BrowserForge Integration

Camoufox is compatible with [BrowserForge](https://github.com/daijro/browserforge) fingerprints.

By default, Camoufox will use a random fingerprint. You can also inject your own Firefox Browserforge fingerprint into Camoufox with the following example:

```python
from camoufox.sync_api import Camoufox
from browserforge.fingerprints import FingerprintGenerator

fg = FingerprintGenerator(browser='firefox')

# Launch Camoufox with a random Firefox fingerprint
with Camoufox(fingerprint=fg.generate()) as browser:
    page = browser.new_page()
    page.goto("https://example.com/")
```

<hr width=50>

**Note:** As of now, some properties from BrowserForge fingerprints will not be passed to Camoufox. This is due to the outdated fingerprint dataset from Apify's fingerprint-suite (see [here](https://github.com/apify/fingerprint-suite/discussions/308)). Properties will be re-enabled as soon as an updated dataset is available.

---
