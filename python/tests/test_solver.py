"""The cfsolve solver package: bridge argument building, detection, injection.

No network and no browser: the bridge is exercised against a stand-in script,
and pages are small fakes that record what was asked of them.
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camoufox.solver import bridge as bridge_mod  # noqa: E402
from camoufox.solver import autosolve, detect  # noqa: E402
from camoufox.solver.bridge import CFSolveBridge, CFSolveError, proxy_to_url  # noqa: E402
from camoufox.solver.profile import default_profile, profile_user_agent  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _write_fake(binary, stdout, code=0, stderr=""):
    """A stand-in for the challenge binary that prints a fixed answer."""
    binary.write_text(
        "#!/bin/sh\n"
        f'printf %b "{stdout}"\n'
        f'printf %b "{stderr}" >&2\n'
        f"exit {code}\n",
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    return binary


@pytest.fixture
def profile(tmp_path):
    """A fingerprint file shaped like cfsolve's own profiles."""
    path = tmp_path / "fp.json"
    path.write_text(
        json.dumps(
            {"transport": {"headers": {"User-Agent": "Mozilla/5.0 (iPhone) Safari/26.6.3"}}}
        ),
        encoding="utf-8",
    )
    return path


class FakePage:
    """Only what the solver touches: url, context, title, DOM queries, evaluate."""

    def __init__(self, url="https://example.com/x", title="Just a moment...", html=None):
        self.url = url
        self._title = title
        self._html = html or {}
        self.evaluated = []
        self.context = FakeContext()
        self.goto_calls = []
        self.reloads = 0

    def title(self):
        return self._title

    def query_selector(self, selector):
        return self._html.get(selector)

    def evaluate(self, script, *args):
        self.evaluated.append((script, args))
        return self._html.get("__sitekey__")

    def wait_for_load_state(self, *args, **kwargs):
        self.reloads += 1

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        return "response"


class FakeContext:
    def __init__(self):
        self.cookies = []
        self.fail_domains = set()

    def add_cookies(self, cookies):
        for cookie in cookies:
            if cookie["domain"] in self.fail_domains:
                raise RuntimeError("bad domain")
        self.cookies.extend(cookies)


# --------------------------------------------------------------------------- #
# bridge
# --------------------------------------------------------------------------- #


def test_build_command_matches_the_documented_cli(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "token-abc")
    cmd = CFSolveBridge(binary, profile).build_command("https://a.test/p", "/tmp/out")
    assert cmd == [
        str(binary),
        "--page",
        "https://a.test/p",
        "/tmp/out",
        "--solve",
        "--fingerprint",
        str(profile),
    ]


def test_build_command_orders_sitekey_options(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "token-abc")
    cmd = CFSolveBridge(binary, profile).build_command(
        "https://a.test/p",
        "/tmp/out",
        sitekey="SK",
        action="login",
        cdata="CD",
        blank_page=True,
    )
    assert cmd[-7:] == ["--sitekey", "SK", "--action", "login", "--cdata", "CD", "--blank-page"]


def test_action_without_sitekey_is_dropped(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "token-abc")
    cmd = CFSolveBridge(binary, profile).build_command("https://a.test", "/tmp/o", action="login")
    assert "--action" not in cmd


def test_blank_page_needs_a_sitekey(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "token-abc")
    bridge = CFSolveBridge(binary, profile)
    # cli.rs: --blank-page requires both --solve and --sitekey.
    with pytest.raises(CFSolveError, match="requires a sitekey"):
        bridge.build_command("https://a.test", "/tmp/o", blank_page=True)


def test_missing_binary_is_reported(tmp_path, profile):
    with pytest.raises(CFSolveError, match="binary not found"):
        CFSolveBridge(tmp_path / "nope", profile)


def test_missing_profile_is_reported(tmp_path):
    binary = _write_fake(tmp_path / "challenge", "token-abc")
    with pytest.raises(CFSolveError, match="profile not found"):
        CFSolveBridge(binary, tmp_path / "nope.json")


def test_solve_reads_a_token(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "0.token-value")
    result = CFSolveBridge(binary, profile).solve("https://a.test")
    assert result.kind == "token"
    assert result.value == "0.token-value"


def test_solve_reads_clearance(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "starting\\ncf_clearance=abc.def")
    result = CFSolveBridge(binary, profile).solve("https://a.test")
    assert result.kind == "clearance"
    assert result.value == "abc.def"


def test_solve_reports_stderr_on_failure(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "", code=1, stderr="no fingerprint")
    with pytest.raises(CFSolveError, match="no fingerprint"):
        CFSolveBridge(binary, profile).solve("https://a.test")


def test_solve_reports_empty_stdout(tmp_path, profile):
    binary = _write_fake(tmp_path / "challenge", "")
    with pytest.raises(CFSolveError, match="no stdout"):
        CFSolveBridge(binary, profile).solve("https://a.test")


def test_solve_cleans_up_its_directory(tmp_path, profile, monkeypatch):
    binary = _write_fake(tmp_path / "challenge", "tok")
    made = []
    real = bridge_mod.tempfile.mkdtemp

    def recording(*args, **kwargs):
        path = real(*args, **kwargs)
        made.append(path)
        return path

    monkeypatch.setattr(bridge_mod.tempfile, "mkdtemp", recording)
    CFSolveBridge(binary, profile).solve("https://a.test")
    assert made and not os.path.exists(made[0])


def test_proxy_dict_becomes_a_url():
    assert proxy_to_url({"server": "socks5://h:1080", "username": "u", "password": "p@ss"}) == (
        "socks5://u:p%40ss@h:1080"
    )


def test_proxy_without_credentials_is_passed_through():
    assert proxy_to_url({"server": "http://h:8080"}) == "http://h:8080"


# --------------------------------------------------------------------------- #
# detection and profile
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("title", ["Just a moment...", "Attention Required!", "Checking your browser"])
def test_challenge_titles_are_recognised(title):
    assert detect.is_cloudflare_challenge(FakePage(title=title))


def test_prose_about_cloudflare_is_not_a_challenge():
    assert not detect.is_cloudflare_challenge(FakePage(title="How Cloudflare works"))


def test_turnstile_container_counts_as_a_challenge():
    page = FakePage(title="Sign in", html={detect.TURNSTILE_SELECTOR: object()})
    assert detect.is_cloudflare_challenge(page)


def test_sitekey_is_read_from_the_container():
    page = FakePage(html={"__sitekey__": "0x4AAA"})
    assert detect.extract_sitekey(page) == "0x4AAA"


def test_sitekey_is_none_when_evaluate_fails():
    page = FakePage()
    page.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    assert detect.extract_sitekey(page) is None


def test_profile_user_agent_reads_transport_headers(profile):
    assert profile_user_agent(profile) == "Mozilla/5.0 (iPhone) Safari/26.6.3"


def test_profile_without_a_user_agent_names_the_file(tmp_path):
    path = tmp_path / "fp.json"
    path.write_text('{"browser": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="fp.json"):
        profile_user_agent(path)


def test_default_profile_points_at_the_shipped_safari(tmp_path):
    cfsolve = tmp_path / "cfsolve"
    (cfsolve / "profiles").mkdir(parents=True)
    (cfsolve / "profiles" / "safari-26-ios.json").write_text(
        '{"transport":{"headers":{"User-Agent":"UA"}}}', encoding="utf-8"
    )
    assert default_profile(cfsolve) == str(cfsolve / "profiles" / "safari-26-ios.json")


def test_default_profile_is_an_error_when_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        default_profile(tmp_path)


# --------------------------------------------------------------------------- #
# solving a page
# --------------------------------------------------------------------------- #


class StubBridge:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def solve(self, url, sitekey=None, action=None, cdata=None, blank_page=False):
        self.calls.append({"url": url, "sitekey": sitekey, "action": action})
        if self.error:
            raise CFSolveError(self.error)
        return self.result


def test_solve_page_ignores_a_page_without_a_challenge():
    bridge = StubBridge()
    assert autosolve.solve_page(FakePage(title="Welcome"), bridge) is None
    assert bridge.calls == []


def test_solve_page_injects_a_token():
    page = FakePage()
    result = bridge_mod.SolveResult("token", "0.abc", "0.abc")
    out = autosolve.solve_page(page, StubBridge(result))
    assert out is result
    script, args = page.evaluated[-1]
    assert args == (autosolve.RESPONSE_FIELD, "0.abc")


def test_solve_page_writes_a_clearance_cookie():
    page = FakePage(url="https://sub.example.co.uk/x")
    result = bridge_mod.SolveResult("clearance", "abc", "cf_clearance=abc")
    autosolve.solve_page(page, StubBridge(result))
    cookie = page.context.cookies[0]
    assert cookie["name"] == "cf_clearance"
    assert cookie["value"] == "abc"
    assert cookie["domain"] in {"sub.example.co.uk", ".example.co.uk"}
    assert page.reloads == 1


def test_clearance_falls_back_when_the_first_domain_is_refused():
    page = FakePage(url="https://sub.example.co.uk/x")
    # Both exact-host forms refused, so the registrable domain is the only place left.
    page.context.fail_domains = {"sub.example.co.uk", ".sub.example.co.uk"}
    result = bridge_mod.SolveResult("clearance", "abc", "cf_clearance=abc")
    autosolve.solve_page(page, StubBridge(result))
    assert page.context.cookies[0]["domain"] == ".example.co.uk"


def test_cookie_domains_never_include_a_public_suffix():
    assert ".co.uk" not in autosolve._cookie_domains("sub.example.co.uk")
    assert ".example.co.uk" in autosolve._cookie_domains("sub.example.co.uk")
    assert autosolve._cookie_domains("example.com") == ["example.com", ".example.com"]


def test_a_failed_solve_is_swallowed_by_default():
    page = FakePage()
    assert autosolve.solve_page(page, StubBridge(error="blocked")) is None


def test_a_failed_solve_raises_in_strict_mode():
    page = FakePage()
    with pytest.raises(autosolve.AutoSolveError, match="blocked"):
        autosolve.solve_page(page, StubBridge(error="blocked"), strict=True)


# --------------------------------------------------------------------------- #
# install()
# --------------------------------------------------------------------------- #


class FakeBrowser:
    def __init__(self):
        self.pages = []
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def new_page(self):
        page = FakePage(title="Welcome")
        self.pages.append(page)
        for handler in self.handlers.get("page", []):
            handler(page)
        return page


def test_install_solves_after_navigation():
    browser = FakeBrowser()
    bridge = StubBridge(bridge_mod.SolveResult("token", "tok", "tok"))
    autosolve.install(browser, bridge, solve_existing=False)

    page = browser.new_page()
    page._title = "Just a moment..."  # what the navigation returns
    page.goto("https://a.test")
    assert len(bridge.calls) == 1
    assert page.goto_calls == ["https://a.test"]


def test_install_solves_a_challenge_once_per_page():
    browser = FakeBrowser()
    bridge = StubBridge(bridge_mod.SolveResult("token", "tok", "tok"))
    autosolve.install(browser, bridge, solve_existing=False)
    page = browser.new_page()
    page._title = "Just a moment..."
    page.goto("https://a.test")
    page.goto("https://a.test/again")
    assert len(bridge.calls) == 1


def test_install_leaves_clean_pages_alone():
    browser = FakeBrowser()
    bridge = StubBridge()
    autosolve.install(browser, bridge, solve_existing=False)
    browser.new_page().goto("https://a.test")
    assert bridge.calls == []


def test_install_solves_pages_already_open():
    browser = FakeBrowser()
    stuck = FakePage(title="Just a moment...")
    browser.pages = [stuck]
    bridge = StubBridge(bridge_mod.SolveResult("token", "tok", "tok"))
    autosolve.install(browser, bridge)
    assert len(bridge.calls) == 1


def test_install_returns_its_target():
    browser = FakeBrowser()
    assert autosolve.install(browser, StubBridge(), solve_existing=False) is browser
