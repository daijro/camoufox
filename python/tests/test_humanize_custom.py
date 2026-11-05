"""custom() humanize engines: the factory, the launch config, the seeded streams
(parity with the browser's), the page wrappers and play()'s pacing.

The page here is a fake that records what reaches Playwright. The browser run is
browser/tests/playwright/patches/humanize-custom.py. typescript/tests/humanize-custom.test.ts runs
the same scenario and must produce the same sequence
(browser/tests/humanize/custom-sequence.json).

Regenerate the sequence after an intended change with
    CAMOUFOX_REGEN_GOLDEN=1 python3 -m pytest python/tests/test_humanize_custom.py
"""

import asyncio
import json
import math
import os
import re
import time
import warnings
from pathlib import Path

import pytest

from camoufox import _humanize_custom as hc
from camoufox.exceptions import HumanizeEngineUnavailable
from camoufox.humanize import (
    CHANNELS,
    SeededRng,
    auto,
    channel_stream,
    custom,
    custom_engines,
    engine,
    humanize_config,
    raw,
    splitmix64,
)

REPO = Path(__file__).resolve().parents[2]
BASE_MANIFEST = json.loads((REPO / "browser" / "settings" / "humanize-engines.json").read_text())
VECTORS = json.loads((REPO / "browser" / "tests" / "humanize" / "rng-vectors.json").read_text())
SEQUENCE = REPO / "browser" / "tests" / "humanize" / "custom-sequence.json"


def noop(page, *args, **kwargs):
    return None


# ---- streams ---------------------------------------------------------------

def test_stream_reference_outputs():
    # The same reference values as browser/tests/juggler/rng.test.mjs.
    assert splitmix64(0) == 0xE220A8397B1DCDAF
    assert splitmix64(0x9E3779B97F4A7C15) == 0x6E789E6AA1B965F4
    rng = SeededRng(0)
    assert [round(rng() * 2**32) for _ in range(3)] == [1144304738, 1416247, 958946056]


def test_stream_derivation_matches_the_browser_pin():
    # rng.test.mjs pins the browser's first draw per channel for seed 1234.
    source = (REPO / "browser" / "tests" / "juggler" / "rng.test.mjs").read_text()
    pinned = dict(
        (k, int(v)) for k, v in re.findall(r"(\w+): (\d+)", re.search(r"const PINNED = \{([^}]*)\}", source)[1])
    )
    assert pinned == {c: round(channel_stream(1234, c)() * 2**32) for c in CHANNELS}


def test_streams_are_the_browsers_draw_for_draw():
    # rng-vectors.json is written from the browser's HumanizeRng.js.
    for seed, value in VECTORS["splitmix64"]:
        assert splitmix64(int(seed)) == int(value)
    for entry in VECTORS["streams"]:
        for channel in CHANNELS:
            stream = channel_stream(int(entry["seed"]), channel)
            draws = [stream() * 2**32 for _ in entry[channel]]
            assert all(d == int(d) for d in draws)
            assert [int(d) for d in draws] == entry[channel], (entry["seed"], channel)
            assert stream.position == len(entry[channel])


def test_stream_helpers():
    rng = channel_stream(7, "mouse")
    first = channel_stream(7, "mouse")()
    assert rng.uniform(10, 20) == 10 + 10 * first
    with pytest.raises(ValueError, match="unknown humanize channel"):
        channel_stream(1, "touch")


# ---- factory and config ----------------------------------------------------

def test_custom_takes_a_function():
    with pytest.raises(ValueError, match=r"custom\(\) takes the function"):
        custom(42)
    with pytest.raises(ValueError, match=r"needs its function, as custom\(fn\)"):
        humanize_config({"mouse": "custom"}, BASE_MANIFEST)
    with pytest.raises(ValueError, match=r"needs its function"):
        humanize_config({"mouse": engine("custom")}, BASE_MANIFEST)
    with pytest.raises(ValueError, match=r"custom\(\) takes no options"):
        humanize_config({"mouse": {**custom(noop), "options": {"speed": 1}}}, BASE_MANIFEST)
    assert custom_engines({"mouse": custom(noop), "keyboard": raw()}) == {"mouse": noop}
    assert custom_engines(True) == {}


def test_custom_channels_run_raw_in_the_browser():
    config = humanize_config(
        {"mouse": custom(noop), "keyboard": custom(noop), "scroll": auto(), "seed": 5}, BASE_MANIFEST
    )
    assert config == {
        "humanize": True,
        "humanize:mouse": "raw",
        "humanize:mouse:internal": "auto",
        "humanize:keyboard": "raw",
        "humanize:scroll": "auto",
        "humanize:seed": "5",
    }
    # Only a custom mouse writes mouse:internal.
    config = humanize_config({"keyboard": custom(noop), "scroll": custom(noop)}, BASE_MANIFEST)
    assert config == {
        "humanize": True,
        "humanize:mouse": "auto",
        "humanize:keyboard": "raw",
        "humanize:scroll": "raw",
    }
    # Every channel custom: the browser humanizes nothing itself.
    config = humanize_config({c: custom(noop) for c in CHANNELS}, BASE_MANIFEST)
    assert config["humanize"] is False and config["humanize:mouse:internal"] == "auto"


def test_custom_mouse_does_not_teleport_a_cursor_moving_scroll():
    manifest = {
        **BASE_MANIFEST,
        "scroll": [*BASE_MANIFEST["scroll"], "fancy"],
        "engines": {**BASE_MANIFEST["engines"], "fancy": {"movesCursor": True}},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        humanize_config({"mouse": custom(noop), "scroll": engine("fancy")}, manifest)
    with pytest.warns(RuntimeWarning, match="single jump"):
        humanize_config({"mouse": raw(), "scroll": engine("fancy")}, manifest)


def test_custom_on_a_build_without_the_manifest():
    # Such a build runs every base engine or none, so custom() goes with raw().
    assert humanize_config({c: custom(noop) for c in CHANNELS}, None) == {}
    assert humanize_config({"mouse": custom(noop), "keyboard": raw(), "scroll": raw()}, None) == {}
    with pytest.raises(HumanizeEngineUnavailable):
        humanize_config({"mouse": custom(noop)}, None)


def test_the_sync_api_refuses_an_async_function():
    async def mover(page, x, y, **_):
        pass

    with pytest.raises(ValueError, match=r"custom\(mover\) is async, but this is the sync API"):
        hc.check({"mouse": custom(mover)}, is_async=False)
    assert hc.check({"mouse": custom(mover)}, is_async=True) == {"mouse": mover}


def test_launch_server_refuses_custom(monkeypatch):
    from camoufox import server

    monkeypatch.setattr(server, "launch_options", lambda **_: pytest.fail("launched"))
    with pytest.raises(ValueError, match="launch_server\\(\\) cannot run custom\\(\\) humanize engines"):
        server.launch_server(humanize={"mouse": custom(noop)})


# ---- play() ----------------------------------------------------------------

@pytest.mark.parametrize(
    "steps, message",
    [
        ("move", "takes a list of steps"),
        ([("hop", 1, 2, 0)], "the kind must be"),
        ([("move", 1, 2)], "move takes 3 values"),
        ([("move", 1, 2, -1)], "t must be a finite number"),
        ([("move", 1, 2, 5), ("move", 1, 2, 4)], "goes back in time"),
        ([("move", float("nan"), 2, 0)], "finite numbers"),
        ([("down", "side", 0)], "the button must be"),
        ([("key", "a", "tap", 0)], 'key takes a key name and "down" or "up"'),
        ([("text", 5, 0)], "text takes a string"),
        ([["move", 1, 2, True]], "t must be"),
    ],
)
def test_play_rejects_bad_steps(steps, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        hc.validate_steps(steps)


def test_play_names_the_bad_step():
    with pytest.raises(ValueError, match=r"play\(\) step 1 \('up', 'side', 3\)"):
        hc.validate_steps([("down", "left", 0), ("up", "side", 3)])


# ---- the fake page ---------------------------------------------------------

class Recorder:
    def __init__(self, is_async):
        self.is_async = is_async
        self.events = []

    def ret(self, value=None, latency=0.0):
        if not self.is_async:
            if latency:
                time.sleep(latency)
            return value

        async def result():
            if latency:
                await asyncio.sleep(latency)
            return value

        return result()


class FakeMouse:
    def __init__(self, rec, latency=0.0):
        self.rec, self.latency = rec, latency

    def move(self, x, y, *, steps=None):
        self.rec.events.append(["mouse.move", x, y])
        return self.rec.ret(latency=self.latency)

    def down(self, *, button=None, click_count=None):
        self.rec.events.append(["mouse.down", button or "left"])
        return self.rec.ret()

    def up(self, *, button=None, click_count=None):
        self.rec.events.append(["mouse.up", button or "left"])
        return self.rec.ret()

    def wheel(self, delta_x, delta_y):
        self.rec.events.append(["mouse.wheel", delta_x, delta_y])
        return self.rec.ret()

    def click(self, x, y, *, delay=None, button=None, click_count=None):
        self.rec.events.append(["mouse.click", x, y])
        return self.rec.ret()

    def dblclick(self, x, y, *, delay=None, button=None):
        self.rec.events.append(["mouse.dblclick", x, y])
        return self.rec.ret()


class FakeKeyboard:
    def __init__(self, rec):
        self.rec = rec

    def down(self, key):
        self.rec.events.append(["keyboard.down", key])
        return self.rec.ret()

    def up(self, key):
        self.rec.events.append(["keyboard.up", key])
        return self.rec.ret()

    def insert_text(self, text):
        self.rec.events.append(["keyboard.insertText", text])
        return self.rec.ret()

    def type(self, text, *, delay=None):
        self.rec.events.append(["keyboard.type", text])
        return self.rec.ret()

    def press(self, key, *, delay=None):
        self.rec.events.append(["keyboard.press", key])
        return self.rec.ret()


# Where the fake page lays out each selector, and whether it is in view.
BOXES = {
    "html": ({"x": 0, "y": 0, "width": 1000, "height": 700}, True),
    "#far": ({"x": 100, "y": 900, "width": 80, "height": 30}, False),
    "#name": ({"x": 40, "y": 120, "width": 200, "height": 24}, True),
    "#near": ({"x": 500, "y": 300, "width": 50, "height": 20}, True),
}


def make_locator_class():
    # A class per test, like Playwright's per-API classes, so patching one
    # never leaks into another test.
    class FakeLocator:
        def __init__(self, page, selector, first=False):
            self._page, self.selector, self._first = page, selector, first

        @property
        def page(self):
            return self._page

        @property
        def first(self):
            return FakeLocator(self._page, self.selector, True)

        def _log(self, name, *args):
            self._page.rec.events.append([f"locator.{name}", self.selector, *args])
            return self._page.rec.ret()

        def click(self, *, modifiers=None, position=None, delay=None, button=None, click_count=None,
                  timeout=None, force=None, no_wait_after=None, trial=None, steps=None):
            return self._log("click", position)

        def dblclick(self, *, modifiers=None, position=None, delay=None, button=None, timeout=None,
                     force=None, no_wait_after=None, trial=None, steps=None):
            return self._log("dblclick", position)

        def hover(self, *, modifiers=None, position=None, timeout=None, no_wait_after=None, force=None, trial=None):
            return self._log("hover", position)

        def fill(self, value, *, timeout=None, no_wait_after=None, force=None):
            return self._log("fill", value)

        def type(self, text, *, delay=None, timeout=None, no_wait_after=None):
            return self._log("type", text)

        def press_sequentially(self, text, *, delay=None, timeout=None, no_wait_after=None):
            return self._log("pressSequentially", text)

        def press(self, key, *, delay=None, timeout=None, no_wait_after=None):
            return self._log("press", key)

        def scroll_into_view_if_needed(self, *, timeout=None):
            BOXES[self.selector] = (BOXES[self.selector][0], True)
            return self._log("scrollIntoViewIfNeeded")

        def select_text(self, *, force=None, timeout=None):
            return self._log("selectText")

        def focus(self, *, timeout=None):
            return self._log("focus")

        def bounding_box(self, *, timeout=None):
            return self._page.rec.ret(dict(BOXES[self.selector][0]))

        def evaluate(self, expression, arg=None, *, timeout=None):
            if "clientLeft" in expression:
                return self._page.rec.ret([2, 3])
            return self._page.rec.ret(BOXES[self.selector][1])

    return FakeLocator


class FakePage:
    def __init__(self, rec, locator_class, latency=0.0):
        self.rec = rec
        self.mouse = FakeMouse(rec, latency)
        self.keyboard = FakeKeyboard(rec)
        self._locator_class = locator_class

    def locator(self, selector):
        return self._locator_class(self, selector)

    def _page_call(self, name, selector, *args):
        self.rec.events.append([f"page.{name}", selector, *args])
        return self.rec.ret()

    def click(self, selector, *, strict=None, **kwargs):
        return self._page_call("click", selector)

    def dblclick(self, selector, *, strict=None, **kwargs):
        return self._page_call("dblclick", selector)

    def hover(self, selector, *, strict=None, **kwargs):
        return self._page_call("hover", selector)

    def fill(self, selector, value, *, strict=None, **kwargs):
        return self._page_call("fill", selector, value)

    def type(self, selector, text, *, strict=None, **kwargs):
        return self._page_call("type", selector, text)

    def press(self, selector, key, *, strict=None, **kwargs):
        return self._page_call("press", selector, key)


class FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.pages = []
        self._handlers = []

    def on(self, event, handler):
        assert event == "page"
        self._handlers.append(handler)

    def open_page(self, latency=0.0):
        """A page the browser opened by itself, such as a popup."""
        page = FakePage(self.browser.rec, self.browser.locator_class, latency)
        page.context = self
        self.pages.append(page)
        for handler in self._handlers:
            handler(page)
        return page


class FakeBrowser:
    def __init__(self, is_async):
        self.rec = Recorder(is_async)
        self.locator_class = make_locator_class()
        self.contexts = []

    def new_context(self, **_):
        context = FakeContext(self)
        self.contexts.append(context)
        return self.rec.ret(context)

    def new_page(self, **_):
        context = FakeContext(self)
        self.contexts.append(context)
        page = context.open_page()
        return self.rec.ret(page)


def run(rec, value):
    return asyncio.run(value) if rec.is_async else value


# ---- the reference engines (mirrored in humanize-custom.test.ts) ----------

def reference_engines(log, is_async):
    """Three engines that draw from their streams, play steps, and use original."""
    at = {"x": 0.0, "y": 0.0}

    def move(page, x, y, *, original, rng, play):
        log.append(["fn.mouse", x, y])
        n = 3 + math.floor(rng() * 4)
        sx, sy = at["x"], at["y"]
        steps = []
        for i in range(1, n + 1):
            f = i / n
            jitter = (rng() - 0.5) * 4 * (1 - f)
            steps.append(["move", sx + (x - sx) * f + jitter, sy + (y - sy) * f - jitter, i * 2])
        at.update(x=x, y=y)
        return play(steps)

    def keys(page, text, *, original, rng, play, kind):
        log.append(["fn.keyboard", kind, text])
        if kind == "press":
            return original()
        steps, t = [], 0
        for ch in text:
            steps.append(["key", ch, "down", t])
            t += 1 + math.floor(rng() * 3)
            steps.append(["key", ch, "up", t])
        return play(steps)

    def scroll(page, target, *, original, rng, play):
        if isinstance(target, tuple):
            log.append(["fn.scroll", list(target)])
            n = 2 + math.floor(rng() * 3)
            return play([["wheel", target[0] / n, target[1] / n, i] for i in range(n)])
        log.append(["fn.scroll", target.selector])
        return original()

    if not is_async:
        return move, keys, scroll

    def asyncify(fn):
        async def engine(*args, **kwargs):
            return await fn(*args, **kwargs)

        return engine

    return asyncify(move), asyncify(keys), asyncify(scroll)


def scenario(is_async):
    """Every wrapped method once, on a browser with all three channels custom."""
    browser = FakeBrowser(is_async)
    rec = browser.rec
    move, keys, scroll = reference_engines(rec.events, is_async)
    humanize = {"mouse": custom(move), "keyboard": custom(keys), "scroll": custom(scroll), "seed": 1234}
    hc.attach(browser, humanize, is_async=is_async)
    BOXES["#far"] = (BOXES["#far"][0], False)

    async def actions_async(page):
        await page.mouse.move(300, 200)
        await page.mouse.wheel(0, 480)
        await page.locator("#far").click()
        await page.locator("#near").hover(position={"x": 5, "y": 6})
        await page.locator("#name").fill("Hi there")
        await page.keyboard.press("Enter")
        await page.keyboard.type("ok")
        await page.mouse.click(10, 20)
        await page.click("#near")
        await page.fill("#name", "")
        await page.locator("#near").click(trial=True)

    def actions_sync(page):
        page.mouse.move(300, 200)
        page.mouse.wheel(0, 480)
        page.locator("#far").click()
        page.locator("#near").hover(position={"x": 5, "y": 6})
        page.locator("#name").fill("Hi there")
        page.keyboard.press("Enter")
        page.keyboard.type("ok")
        page.mouse.click(10, 20)
        page.click("#near")
        page.fill("#name", "")
        page.locator("#near").click(trial=True)

    page = run(rec, browser.new_page())
    run(rec, actions_async(page) if is_async else actions_sync(page))
    return rec.events


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_the_scenario_matches_the_shared_sequence(is_async):
    events = scenario(is_async)
    if os.environ.get("CAMOUFOX_REGEN_GOLDEN") and not is_async:
        SEQUENCE.write_text(json.dumps({"seed": 1234, "events": events}, indent=1) + "\n")
    # The TypeScript launcher is held to the same file.
    assert events == json.loads(SEQUENCE.read_text())["events"]


def test_the_scenario_reads_as_intended():
    events = scenario(False)
    names = [e[0] for e in events]
    # Each mouse move is the engine's path, and the click after it is Playwright's.
    assert names[0] == "fn.mouse" and events[names.index("locator.click")][1] == "#far"
    # The element out of view is scrolled by the scroll engine, through original().
    far = names.index("fn.scroll", names.index("fn.scroll") + 1)
    assert events[far] == ["fn.scroll", "#far"] and names[far + 1] == "locator.scrollIntoViewIfNeeded"
    # hover(position=) moves to the padding-box point: box + border + position.
    assert ["fn.mouse", 500 + 2 + 5, 300 + 3 + 6] in events
    # fill selects, then types key by key; press() declines through original().
    fill = names.index("fn.keyboard")
    assert names[fill - 1] == "locator.selectText" and names[fill + 1] == "keyboard.down"
    assert ["keyboard.press", "Enter"] in events and "keyboard.type" not in names
    # page.click routes to the first match; fill("") and trial clicks are Playwright's alone.
    assert ["locator.fill", "#name", ""] in events and events[-1] == ["locator.click", "#near", None]


# ---- wrappers ----------------------------------------------------------------

def attached_page(humanize, is_async=False, latency=0.0):
    browser = FakeBrowser(is_async)
    hc.attach(browser, humanize, is_async=is_async)
    page = run(browser.rec, browser.new_page())
    if latency:
        page.mouse.latency = latency
    return browser, page


def test_a_click_calls_the_mouse_engine_once_at_the_point():
    seen = []

    def mover(page, x, y, *, original, rng, play):
        seen.append((x, y))
        return original()

    browser, page = attached_page({"mouse": custom(mover)})
    page.locator("#near").click()
    assert seen == [(525.0, 310.0)]
    assert browser.rec.events == [
        ["locator.scrollIntoViewIfNeeded", "#near"],
        ["mouse.move", 525.0, 310.0],
        ["locator.click", "#near", None],
    ]


def test_an_engine_calling_its_own_channel_reaches_playwright():
    def mover(page, x, y, *, original, rng, play):
        page.mouse.move(x - 1, y - 1)  # not back into this function
        return page.mouse.move(x, y)

    browser, page = attached_page({"mouse": custom(mover)})
    page.mouse.move(50, 60)
    assert browser.rec.events == [["mouse.move", 49, 59], ["mouse.move", 50, 60]]


def test_exceptions_propagate():
    def broken(page, text, **_):
        raise RuntimeError("engine failed")

    _, page = attached_page({"keyboard": custom(broken)})
    with pytest.raises(RuntimeError, match="engine failed"):
        page.keyboard.type("x")


def test_popups_and_new_contexts_are_wrapped_and_other_browsers_are_not():
    calls = []

    def mover(page, x, y, *, original, **_):
        calls.append(("a", x, y))
        return original()

    browser, page = attached_page({"mouse": custom(mover)})
    popup = page.context.open_page()
    popup.mouse.move(1, 2)
    context = browser.new_context()
    context.open_page().mouse.move(3, 4)

    other, other_page = attached_page({"keyboard": custom(noop)})
    other_page.mouse.move(5, 6)
    assert calls == [("a", 1, 2), ("a", 3, 4)]
    assert other.rec.events == [["mouse.move", 5, 6]]
    with pytest.raises(ValueError, match="already attached"):
        hc.attach(browser, {"mouse": custom(mover)}, is_async=False)


def test_the_streams_follow_the_seed():
    draws = []

    def drawer(page, x, y, *, rng, **_):
        draws.append(rng())

    for seed in (1, 1, 2):
        _, page = attached_page({"mouse": custom(drawer), "seed": seed})
        page.mouse.move(0, 0)
    assert draws[0] == draws[1] == channel_stream(1, "mouse")() and draws[2] != draws[0]


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_play_holds_its_schedule_under_latency(is_async):
    # 200 steps 10 ms apart against 5 ms of latency per event: a late event
    # delays only itself, so the whole plan ends within one interval of 1990 ms.
    records = []

    def mover(page, x, y, *, play, **_):
        return play([("move", i, i, i * 10) for i in range(200)])

    def asyncmover(*args, **kwargs):
        async def run_it():
            records.extend(await mover(*args, **kwargs))

        return run_it()

    fn = asyncmover if is_async else (lambda *a, **k: records.extend(mover(*a, **k)))
    browser, page = attached_page({"mouse": custom(fn)}, is_async, latency=0.005)
    start = time.monotonic()
    run(browser.rec, page.mouse.move(1, 1))
    elapsed = (time.monotonic() - start) * 1000
    lag = [r["t_actual"] - r["t_planned"] for r in records]
    assert len(records) == 200 and max(lag) < 10, max(lag)
    assert 1990 <= elapsed < 1990 + 10 + 5 + 50, elapsed
