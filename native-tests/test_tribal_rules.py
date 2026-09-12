"""Enforce the decisions this repository has already made.

Every rule in `ci/tribal-rules.yml` was settled once, with evidence, usually
because someone proposed the opposite and it was rejected on the merits. Those
are exactly the decisions that get quietly undone -- by a contributor who has
not read the closed PRs, or by an agent rebasing patches at three in the
morning.

A comment explaining a decision only works on someone who reads it. A test
works on everyone.

Needs no browser: these are assertions about the source, so they run in the fast
static job and fail a pull request in seconds rather than after a 40-minute
build.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "pythonlib"))

RULES_PATH = REPO_ROOT / "ci" / "tribal-rules.yml"


def load_rules() -> List[Dict[str, Any]]:
    import yaml

    return (yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}).get("rules") or []


RULES = load_rules()
AUTOMATED = [r for r in RULES if r.get("check") == "automated"]


def rule(rule_id: str) -> Dict[str, Any]:
    for entry in RULES:
        if entry.get("id") == rule_id:
            return entry
    raise AssertionError(f"no rule {rule_id!r} in {RULES_PATH}")


def explain(rule_id: str) -> str:
    entry = rule(rule_id)
    evidence = "; ".join(entry.get("evidence") or [])
    return f"\n\nRule `{rule_id}` — {entry.get('title')}\n{' '.join(str(entry.get('rationale','')).split())}\nEvidence: {evidence}"


# ---------------------------------------------------------------------------
# the file itself
# ---------------------------------------------------------------------------


def test_every_rule_carries_evidence_and_a_rationale():
    """A rule nobody can trace gets deleted the first time it is inconvenient."""
    assert RULES, f"{RULES_PATH} has no rules"
    for entry in RULES:
        assert entry.get("id"), f"rule without an id: {entry}"
        assert entry.get("evidence"), f"rule {entry['id']} cites no issue, PR or commit"
        assert str(entry.get("rationale", "")).strip(), f"rule {entry['id']} says nothing about why"
        assert entry.get("check") in ("automated", "manual"), entry["id"]


def test_every_automated_rule_is_actually_asserted():
    """Marking a rule `automated` with no test is worse than marking it manual."""
    source = Path(__file__).read_text(encoding="utf-8")
    unasserted = [r["id"] for r in AUTOMATED if f'"{r["id"]}"' not in source and f"'{r['id']}'" not in source]
    assert not unasserted, (
        f"rules marked `check: automated` with no assertion in this file: {unasserted}. "
        "Either write the test or change the rule to `check: manual`."
    )


# ---------------------------------------------------------------------------
# virtual display
# ---------------------------------------------------------------------------


def test_virtual_display_default_is_1x1x24():
    from camoufox import virtdisplay

    assert virtdisplay.DEFAULT_SCREEN == "1x1x24", (
        "The Xvfb default screen size changed." + explain("virtual-display-default-1x1x24")
    )


def test_the_screen_size_override_still_exists():
    from camoufox import virtdisplay

    assert virtdisplay.SCREEN_ENV_VAR == "CAMOUFOX_VIRTUAL_DISPLAY_SIZE", explain(
        "virtual-display-size-override-exists"
    )


def test_a_valid_override_is_honoured(monkeypatch):
    from camoufox import virtdisplay

    monkeypatch.setenv(virtdisplay.SCREEN_ENV_VAR, "1920x1080x24")
    assert virtdisplay._resolve_screen() == "1920x1080x24", explain(
        "virtual-display-size-override-exists"
    )


def test_a_nonsense_override_is_rejected_rather_than_silently_ignored(monkeypatch):
    from camoufox import virtdisplay

    monkeypatch.setenv(virtdisplay.SCREEN_ENV_VAR, "enormous")
    with pytest.raises(Exception):
        virtdisplay._resolve_screen()


def test_composite_extension_is_off_by_default():
    from camoufox import virtdisplay

    assert virtdisplay.COMPOSITE_ENV_VAR == "CAMOUFOX_VIRTUAL_DISPLAY_COMPOSITE", explain(
        "composite-extension-off"
    )
    args = [str(a) for a in virtdisplay.VirtualDisplay().xvfb_args]
    # The flag is a pair: "-extension COMPOSITE" disables, "+extension" enables.
    # Asserting on the pair, not on the word, is the difference between checking
    # the setting and checking that the word is still spelled the same.
    assert "COMPOSITE" in args, "Xvfb no longer configures the Composite extension at all"
    assert args[args.index("COMPOSITE") - 1] == "-extension", (
        "Xvfb now starts with Composite ENABLED." + explain("composite-extension-off")
    )


def test_composite_can_still_be_turned_on(monkeypatch):
    from camoufox import virtdisplay

    monkeypatch.setenv(virtdisplay.COMPOSITE_ENV_VAR, "1")
    args = [str(a) for a in virtdisplay.VirtualDisplay().xvfb_args]
    assert args[args.index("COMPOSITE") - 1] == "+extension", (
        "the Composite escape hatch no longer works." + explain("composite-extension-off")
    )


def test_displays_are_claimed_with_displayfd_not_a_lockfile_scan():
    from camoufox import virtdisplay

    # Asserted against the argv Xvfb is actually launched with, not against the
    # source text -- a first draft of this test passed on the *comment* above
    # the call, which is exactly the kind of vacuous assertion that makes a rule
    # file worse than nothing.
    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = list(cmd)
            captured["kwargs"] = kwargs
            self.pid = 424242

        def poll(self):
            return None

    display = virtdisplay.VirtualDisplay()
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(type(display), "xvfb_path", property(lambda self: "/usr/bin/Xvfb"))
        monkey.setattr(virtdisplay.subprocess, "Popen", FakePopen)
        # get() blocks reading the display number back from a pipe the fake
        # never writes to; the bounded read is what makes that safe to do here.
        monkey.setattr(virtdisplay, "DISPLAYFD_READ_TIMEOUT_S", 0.2)
        try:
            display.get()
        except Exception:
            pass
    finally:
        monkey.undo()

    cmd = captured.get("cmd") or []
    assert "-displayfd" in cmd, (
        "Xvfb is no longer launched with -displayfd, so display allocation has gone back "
        f"to a userspace race. argv was: {cmd}" + explain("displayfd-not-lockfile-scan")
    )
    assert captured.get("kwargs", {}).get("pass_fds"), (
        "the displayfd pipe is no longer passed through to the child, so Xvfb cannot "
        "report the number it chose." + explain("displayfd-not-lockfile-scan")
    )


def test_the_displayfd_read_is_bounded():
    from camoufox import virtdisplay

    timeout = virtdisplay.DISPLAYFD_READ_TIMEOUT_S
    assert isinstance(timeout, (int, float)) and timeout > 0, explain("displayfd-read-timeout")


def test_cleanup_is_not_gated_on_the_process_still_running():
    """The unlink must not sit behind a `poll() is None` check.

    Asserted structurally so it runs without Xvfb installed; the behavioural
    half is native-tests/test_no_leaks.py::test_cleanup_runs_even_when_xvfb_already_died.
    """
    import ast as _ast

    from camoufox import virtdisplay

    tree = _ast.parse(inspect.getsource(virtdisplay.VirtualDisplay.kill).lstrip())
    parents = {}
    for node in _ast.walk(tree):
        for child in _ast.iter_child_nodes(node):
            parents[child] = node

    removes = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Call)
        and isinstance(n.func, _ast.Attribute)
        and n.func.attr == "remove"
    ]
    assert removes, "kill() no longer removes the X11 lock or socket at all"

    for call in removes:
        node = call
        while node in parents:
            node = parents[node]
            if isinstance(node, _ast.If) and "poll" in _ast.dump(node.test):
                raise AssertionError(
                    "the X11 cleanup is gated on the Xvfb process still running, so a "
                    "display whose Xvfb already died is never cleaned up."
                    + explain("xvfb-cleanup-runs-even-if-it-already-died")
                )


def test_kill_sigkills_reaps_and_unlinks():
    """All three halves of PR #652 and #618, read off the source.

    Asserted structurally rather than behaviourally so it runs without Xvfb
    installed; the behavioural half lives in test_no_leaks.py.
    """
    from camoufox import virtdisplay

    source = inspect.getsource(virtdisplay.VirtualDisplay.kill)
    assert "SIGKILL" in source, (
        "kill() no longer sends SIGKILL. The terminate-wait-kill ladder it replaced "
        "left zombie Xvfb processes." + explain("xvfb-sigkill-and-socket-cleanup")
    )
    assert ".wait(" in source, (
        "kill() no longer reaps the child, so Xvfb becomes a zombie."
        + explain("xvfb-sigkill-and-socket-cleanup")
    )
    assert "-lock" in source and "X11-unix" in source, (
        "kill() no longer removes the X11 lock and socket files, so the display number "
        "stays blocked for every later process." + explain("xvfb-sigkill-and-socket-cleanup")
    )


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------


def _dependency_files():
    """Every file that can cause a pip install, except pythonlib's own metadata."""
    out = []
    for pattern in ("**/requirements*.txt", "**/pyproject.toml", "**/setup.cfg"):
        for path in REPO_ROOT.glob(pattern):
            parts = set(path.parts)
            if "node_modules" in parts or ".venv" in parts or "venv" in parts:
                continue
            # Skip the generated Firefox tree and any fetched upstream checkout.
            if any(p.startswith("camoufox-1") or p.startswith("playwright-python-") for p in path.parts):
                continue
            if path.relative_to(REPO_ROOT).as_posix() == "pythonlib/pyproject.toml":
                continue
            out.append(path)
    return out


def test_no_third_party_camoufox_distribution_is_installed():
    """The only `camoufox` this repository installs is its own pythonlib.

    build-tester generates the fingerprints it grades with, so whichever
    distribution provides `camoufox` *is* the thing under test. This caught a
    real one: build-tester/requirements.txt pinned `cloverlabs-camoufox` from
    #521 until it was replaced with `-e ../pythonlib`.
    """
    allowed = {"-e ../pythonlib", "-e ./pythonlib", "-e pythonlib", "-e .", "camoufox"}
    offenders = []
    for path in _dependency_files():
        for lineno, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line or "camoufox" not in line.lower():
                continue
            if line in allowed:
                continue
            # A requirement line naming camoufox that is not a local path is a
            # redistribution by definition.
            if line.startswith("-e ") and "pythonlib" in line:
                continue
            # pyproject metadata (name/urls) is not a dependency.
            if any(line.startswith(k) for k in ("name", "repository", "homepage", "documentation", "#")):
                continue
            if "=" in line and "camoufox" not in line.split("=")[0].lower():
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line}")

    assert not offenders, (
        "a third-party camoufox distribution is being installed:\n  "
        + "\n  ".join(offenders)
        + explain("no-third-party-camoufox-distribution")
    )


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", ["camoufox.async_api", "camoufox.sync_api"])
def test_launch_failure_tears_down_the_playwright_session(module_name):
    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    assert "__aexit__" in source or "__exit__" in source, module_name
    assert "except BaseException" in source, (
        f"{module_name} no longer catches a failing launch to tear the session down."
        + explain("launch-failure-tears-down-playwright")
    )


@pytest.mark.parametrize("module_name", ["camoufox.async_api", "camoufox.sync_api"])
def test_close_failure_still_tears_down(module_name):
    module = importlib.import_module(module_name)
    source = inspect.getsource(module)
    assert "finally:" in source, (
        f"{module_name} no longer guarantees teardown when close() raises -- which is "
        "precisely the path a crashed browser takes." + explain("close-failure-still-tears-down")
    )


# ---------------------------------------------------------------------------
# contexts and windows
# ---------------------------------------------------------------------------


def test_no_viewport_when_window_is_spoofed():
    from camoufox import utils

    for name in ("spoofs_window_dimensions", "attach_no_viewport_default"):
        assert callable(getattr(utils, name, None)), (
            f"camoufox.utils.{name} is gone; Playwright's default viewport deadlocks "
            "Juggler under a spoofed window." + explain("no-viewport-when-window-is-spoofed")
        )


def test_a_virtual_display_never_clamps_the_generated_screen():
    """The guard that makes the 1x1 default safe.

    Remove it and a 1x1 root window clamps every generated screen to 1x1, which
    would make the display size stop being a free choice -- so this rule and
    `virtual-display-default-1x1x24` stand or fall together.
    """
    import ast as _ast

    from camoufox import utils

    # Structural, via the syntax tree: find every `if` whose body calls
    # clamp_screen_to_display, and require virtual_display in its condition.
    # A plain substring search passes on any unrelated `not virtual_display`
    # elsewhere in the file -- which is how the first draft of this test failed
    # to notice the guard being removed.
    tree = _ast.parse(Path(utils.__file__).read_text(encoding="utf-8"))
    parents = {}
    for node in _ast.walk(tree):
        for child in _ast.iter_child_nodes(node):
            parents[child] = node

    def guarded_by_virtual_display(node) -> bool:
        """Does any enclosing `if` test virtual_display?"""
        while node in parents:
            node = parents[node]
            if isinstance(node, _ast.If) and "virtual_display" in _ast.dump(node.test):
                return True
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                return False
        return False

    call_sites = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Call)
        and isinstance(n.func, _ast.Name)
        and n.func.id == "clamp_screen_to_display"
    ]
    assert call_sites, (
        "clamp_screen_to_display is not called anywhere in camoufox.utils."
        + explain("virtual-display-skips-screen-clamp")
    )
    unguarded = [n.lineno for n in call_sites if not guarded_by_virtual_display(n)]
    assert not unguarded, (
        f"clamp_screen_to_display is reachable without checking virtual_display "
        f"(utils.py line(s) {unguarded}). A 1x1 Xvfb root would then clamp every "
        "generated screen down to 1x1." + explain("virtual-display-skips-screen-clamp")
    )


def test_virtual_display_teardown_is_attached_in_a_finally():
    """The virtual display must be killed even when browser.close() raises."""
    import ast as _ast

    from camoufox import utils

    for name in ("async_attach_vd", "sync_attach_vd"):
        source = inspect.getsource(getattr(utils, name))
        tree = _ast.parse(source.lstrip())
        kills_in_finally = any(
            isinstance(node, _ast.Try)
            and any(
                isinstance(n, _ast.Call)
                and isinstance(n.func, _ast.Attribute)
                and n.func.attr == "kill"
                for stmt in node.finalbody
                for n in _ast.walk(stmt)
            )
            for node in _ast.walk(tree)
        )
        assert kills_in_finally, (
            f"{name} no longer kills the virtual display in a finally block, so a browser "
            "that crashes on close leaks an Xvfb process and its X11 socket."
            + explain("close-failure-still-tears-down")
        )


def test_evaluate_is_isolated_by_default():
    """Isolation is the default; "mw:" is the deliberate way out.

    The upstream Playwright suite runs with isolation disabled because it
    asserts upstream semantics -- that must never become the default here.
    """
    juggler = REPO_ROOT / "additions" / "juggler"
    haystack = ""
    for path in juggler.rglob("*.js"):
        haystack += path.read_text(encoding="utf-8", errors="replace")
    assert "mw:" in haystack, (
        "the main-world opt-in prefix is gone from additions/juggler."
        + explain("evaluate-is-isolated-by-default")
    )

    plugin = (REPO_ROOT / "ci" / "pw_camoufox_plugin.py").read_text(encoding="utf-8")
    assert "disableWorldIsolation" in plugin, (
        "the upstream-suite plugin no longer enables main-world execution explicitly, "
        "which suggests isolation is no longer the default."
        + explain("evaluate-is-isolated-by-default")
    )
    settings = (REPO_ROOT / "settings" / "camoufox.cfg").read_text(encoding="utf-8", errors="replace")
    assert "disableWorldIsolation" not in settings or "true" not in settings.lower().split(
        "disableworldisolation"
    )[-1][:40], (
        "world isolation looks disabled in the shipped config. It is the reason this fork "
        "exists; only the conformance suite may turn it off."
        + explain("evaluate-is-isolated-by-default")
    )


# ---------------------------------------------------------------------------
# juggler frame lifecycle
# ---------------------------------------------------------------------------


def test_per_frame_state_reset_on_navigation_is_also_released_on_dispose():
    """The two teardown paths must agree about Camoufox's own per-frame fields.

    Frame.dispose() is inherited from upstream, which has no Camoufox-specific
    per-frame state, so a newly added field tends to get wired into the
    navigation path (_onGlobalObjectCleared) and nowhere else. A frame that is
    destroyed rather than navigated then keeps it -- and an iframe-heavy page
    destroys frames constantly.

    Compares the `this._x = null` assignments in the two methods rather than
    naming fields, so this keeps working for the next one somebody adds.
    """
    import ast as _ast
    import re as _re

    source = (REPO_ROOT / "additions" / "juggler" / "content" / "FrameTree.js").read_text(
        encoding="utf-8"
    )

    def bodies_of(method: str):
        """Every method of this name, since FrameTree.js defines three classes."""
        return [
            m.group(1)
            for m in _re.finditer(
                rf"\n  {_re.escape(method)}\(\) \{{(.*?)\n  \}}", source, _re.S
            )
        ]

    def body_of(method: str, *, containing: str) -> str:
        """The one belonging to the class we mean.

        FrameTree, Frame and Worker each define dispose(). Picking the first
        match compared Frame's _onGlobalObjectCleared against FrameTree's
        dispose() -- two different classes -- and reported a field as missing
        that had just been released. Anchor on a member only the intended class
        has instead.
        """
        found = [b for b in bodies_of(method) if containing in b]
        assert found, f"could not find a {method}() containing {containing!r} in FrameTree.js"
        return found[0]

    def nulled_fields(body: str) -> set:
        return set(_re.findall(r"this\.(_[A-Za-z0-9_]+)\s*=\s*null", body))

    # Both are Frame methods; _worldNameToContext is Frame's alone.
    on_cleared = nulled_fields(body_of("_onGlobalObjectCleared", containing="this._frameTree"))
    disposed = body_of("dispose", containing="_worldNameToContext")

    missing = sorted(
        field for field in on_cleared
        if field not in disposed
    )
    assert not missing, (
        "these per-frame fields are released when the document changes but not when "
        f"the frame is destroyed: {missing}. A destroyed frame keeps them, and an "
        "iframe-heavy page destroys frames continuously."
        + explain("per-frame-state-released-on-dispose")
    )


def test_a_sandbox_held_over_a_page_window_is_nuked_not_just_dropped():
    """Dropping the reference leaves the compartment to the cycle collector.

    A Cu.Sandbox built with sandboxPrototype over a page window holds that
    window's global. Nuking severs the cross-compartment wrappers so the
    compartment can actually be reclaimed.
    """
    source = (REPO_ROOT / "additions" / "juggler" / "content" / "FrameTree.js").read_text(
        encoding="utf-8"
    )
    if "Cu.Sandbox(" not in source or "_masterSandbox" not in source:
        pytest.skip("no cached sandbox in this version of FrameTree.js")
    assert "nukeSandbox" in source, (
        "FrameTree.js caches a Cu.Sandbox over a page window but never nukes it."
        + explain("per-frame-state-released-on-dispose")
    )


def test_the_canvas_check_hashes_pixels_rather_than_a_data_url_prefix():
    """A truncated data URL is mostly PNG header, not image.

    Checks the paths that actually run. The first version of this test guarded a
    helper called canvasHash that nothing called -- the live collector had its
    own copy of the same truncation, so the rule passed while the defect stayed
    exactly where it was.
    """
    source = (
        REPO_ROOT / "build-tester" / "src" / "lib" / "checks" / "collectors.ts"
    ).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("//")
    )

    # Every canvas readback in the collector, wherever it lives.
    offenders = []
    for marker in ("toDataURL().substring(", "url.substring(0, 100)"):
        if marker in code:
            offenders.append(marker)
    assert not offenders, (
        f"a canvas fingerprint is built from a truncated data URL: {offenders}"
        + explain("canvas-fingerprint-is-hashed-not-truncated")
    )
    assert code.count("simpleHash(ctx.getImageData") >= 2, (
        "the canvas and emoji-canvas fingerprints should both hash their pixels"
        + explain("canvas-fingerprint-is-hashed-not-truncated")
    )
