"""A SOCKS5 proxy with a username and password reaches Juggler, not Playwright.

Playwright refuses `proxy={"server": "socks5://...", "username": ...}` ("Browser
does not support socks5 proxy authentication"), so the launchers send the
proxy without its credentials and hand those to Juggler: a launch-level proxy's
through CAMOU_PROXY_AUTH, a context's through an init script that Juggler
takes out of the context's scripts (TargetRegistry.js). The browser side is
browser/tests/playwright/patches/socks5-proxy-auth.py.
"""

import asyncio
import copy
import json
import re

import pytest

from camoufox import ip, utils

SOCKS = {"server": "socks5://127.0.0.1:1080", "username": "user+denver+os-linux", "password": "pw"}
AUTH = {"host": "127.0.0.1", "port": 1080, "username": "user+denver+os-linux", "password": "pw"}


@pytest.mark.parametrize(
    "proxy, bare, auth",
    [
        (SOCKS, {"server": "socks5://127.0.0.1:1080"}, AUTH),
        ({"server": "SOCKS5://[::1]:9", "username": "u"}, {"server": "SOCKS5://[::1]:9"},
         {"host": "::1", "port": 9, "username": "u", "password": ""}),
        ({"server": "socks5://proxy.example", "username": "u", "password": "p", "bypass": "a.test"},
         {"server": "socks5://proxy.example", "bypass": "a.test"},
         {"host": "proxy.example", "port": None, "username": "u", "password": "p"}),
    ],
)
def test_socks5_credentials_are_split_off(proxy, bare, auth):
    before = copy.deepcopy(proxy)
    assert ip.socks5_auth(proxy) == (bare, auth)
    assert proxy == before


@pytest.mark.parametrize(
    "proxy",
    [
        None,
        {"server": "socks5://127.0.0.1:1080"},
        # Playwright sends HTTP proxy credentials itself.
        {"server": "http://127.0.0.1:8080", "username": "u", "password": "p"},
        # Without a scheme Playwright reads the server as an HTTP proxy.
        {"server": "127.0.0.1:1080", "username": "u", "password": "p"},
        # Playwright's own error for socks4 credentials stands.
        {"server": "socks4://127.0.0.1:1080", "username": "u"},
    ],
)
def test_other_proxies_are_left_to_playwright(proxy):
    assert ip.socks5_auth(proxy) == (proxy, None)


def _juggler_reads(script: str) -> dict:
    """What TargetRegistry.js takeProxyAuth() reads from a context's script,
    after Playwright wraps the body in `(() => { ... })();`."""
    wrapped = f"(() => {{\n        {script}\n      }})();"
    body = re.match(r"^\s*\(\(\)\s*=>\s*\{([\s\S]*)\}\)\(\);?\s*$", wrapped)[1].strip()
    assert body.startswith("camoufoxProxyAuth:")
    inner = body[len("camoufoxProxyAuth:"):].strip()
    return json.loads(re.sub(r"\);?$", "", re.sub(r"^\(", "", inner)))


def test_init_script_carries_the_credentials_to_juggler():
    tricky = {**AUTH, "password": 'p"});\n})();alert(1)// '}
    assert _juggler_reads(ip.proxy_auth_init_script(tricky)) == tricky


@pytest.fixture
def isolated_launch_dependencies(monkeypatch):
    monkeypatch.setattr(utils, "add_default_addons", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "generate_fingerprint", lambda *args, **kwargs: object())
    monkeypatch.setattr(utils, "from_fpgen", lambda *args, **kwargs: {})
    monkeypatch.setattr(utils, "get_screen_cons", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "_generate_random_font_subset", lambda *args, **kwargs: [])
    monkeypatch.setattr(utils, "draw_voice_config", lambda *args, **kwargs: {"voices": []})
    monkeypatch.setattr(utils, "fix_navigator_arch", lambda *args: None)
    monkeypatch.setattr(utils, "follow_baseline_protection", lambda *args: None)
    monkeypatch.setattr(utils, "clamp_window_dimensions", lambda *args: None)
    monkeypatch.setattr(utils, "set_media_devices_defaults", lambda *args: None)
    monkeypatch.setattr(utils, "installed_verstr", lambda: "152.0.4-beta.28")
    monkeypatch.setattr(utils, "validate_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "get_env_vars", lambda *args, **kwargs: {})
    monkeypatch.setattr(utils, "launch_path", lambda: "/test/camoufox")


def _launch(proxy):
    return utils.launch_options(proxy=proxy, geoip=False, headless=True, block_webgl=True,
                                i_know_what_im_doing=True)


@pytest.mark.filterwarnings("ignore")
def test_launch_level_credentials_go_to_juggler(isolated_launch_dependencies):
    options = _launch(dict(SOCKS))
    assert options["proxy"] == {"server": "socks5://127.0.0.1:1080"}
    assert json.loads(options["env"][ip.PROXY_AUTH_ENV]) == AUTH
    assert not any("pw" in str(arg) for arg in options["args"])
    assert not any("pw" in json.dumps(pref) for pref in options["firefox_user_prefs"].values())


@pytest.mark.filterwarnings("ignore")
def test_http_proxy_credentials_stay_with_playwright(isolated_launch_dependencies):
    proxy = {"server": "http://127.0.0.1:8080", "username": "u", "password": "p"}
    options = _launch(dict(proxy))
    assert options["proxy"] == proxy
    assert ip.PROXY_AUTH_ENV not in options["env"]


class _Context:
    def __init__(self):
        self.scripts = []

    async def add_init_script(self, script=None, path=None):
        self.scripts.append(script)


class _BrowserImpl:
    """Playwright's async Browser implementation, which both APIs call into."""

    def __init__(self):
        self.calls = []

    async def new_context(self, **kwargs):
        self.calls.append(kwargs)
        return _Context()


class _Browser:
    def __init__(self):
        self._impl_obj = _BrowserImpl()


def test_context_credentials_go_to_juggler_in_an_init_script():
    browser = _Browser()
    utils.attach_socks5_auth(browser)
    utils.attach_socks5_auth(browser)  # a second attach wraps nothing again
    context = asyncio.run(browser._impl_obj.new_context(proxy=dict(SOCKS), locale="en-US"))
    assert browser._impl_obj.calls == [{"proxy": {"server": "socks5://127.0.0.1:1080"}, "locale": "en-US"}]
    assert [_juggler_reads(s) for s in context.scripts] == [AUTH]


@pytest.mark.parametrize("proxy", [None, {"server": "http://h:1", "username": "u", "password": "p"}])
def test_contexts_without_socks5_credentials_get_no_script(proxy):
    browser = _Browser()
    utils.attach_socks5_auth(browser)
    context = asyncio.run(browser._impl_obj.new_context(proxy=proxy))
    assert browser._impl_obj.calls == [{"proxy": proxy}]
    assert context.scripts == []
