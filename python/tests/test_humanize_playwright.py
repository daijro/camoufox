"""myuri on Playwright pages: the parts passed to myuri(), raw() channels, and
the page wrappers.

The page here is a fake that records what reaches Playwright and answers
myuri's page functions from a layout with a vertical scroll. The sequence a
scenario records is pinned in browser/tests/humanize/sequence.json, which the
TypeScript launcher is held to as well. The browser run is
browser/tests/playwright/patches/humanize.py.

Regenerate the sequence after an intended change with
    CAMOUFOX_REGEN_GOLDEN=1 python3 -m pytest python/tests/test_humanize_playwright.py
"""

import asyncio
import json
import math
import os
from pathlib import Path

import pytest
from myuri.page_functions import HIT_TEST_JS, SCROLL_PLAN_JS
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from camoufox import _humanize_playwright as hp
from camoufox.driver_defaults import FILL_NEEDS_CLICK
from camoufox.humanize import CHANNELS, myuri, raw

SEQUENCE = Path(__file__).resolve().parents[2] / "browser" / "tests" / "humanize" / "sequence.json"
VIEWPORT = (1000, 700)


# ---- the fake page -------------------------------------------------------------

class Recorder:
    def __init__(self, is_async):
        self.is_async = is_async
        self.events = []

    def ret(self, value=None):
        if not self.is_async:
            return value

        async def result():
            return value

        return result()


class FakeMouse:
    def __init__(self, page):
        self.page = page

    def _log(self, *event):
        self.page.rec.events.append(list(event))
        return self.page.rec.ret()

    def move(self, x, y, *, steps=None):
        return self._log("mouse.move", x, y)

    def down(self, *, button=None, click_count=None):
        return self._log("mouse.down", button or "left", click_count or 1)

    def up(self, *, button=None, click_count=None):
        page = self.page
        if page.aimed:
            page.checked ^= {page.aimed}
            page.focused = page.aimed
        return self._log("mouse.up", button or "left", click_count or 1)

    def wheel(self, delta_x, delta_y):
        self.page.scroll_y += delta_y
        return self._log("mouse.wheel", delta_x, delta_y)

    def click(self, x, y, *, delay=None, button=None, click_count=None):
        return self._log("mouse.click", x, y)

    def dblclick(self, x, y, *, delay=None, button=None):
        return self._log("mouse.dblclick", x, y)


class FakeKeyboard:
    def __init__(self, rec):
        self.rec = rec

    def _log(self, *event):
        self.rec.events.append(list(event))
        return self.rec.ret()

    def down(self, key):
        return self._log("keyboard.down", key)

    def up(self, key):
        return self._log("keyboard.up", key)

    def insert_text(self, text):
        return self._log("keyboard.insertText", text)

    def type(self, text, *, delay=None):
        return self._log("keyboard.type", text)

    def press(self, key, *, delay=None):
        return self._log("keyboard.press", key)


# Where the fake page lays out each selector, in document px. "#framed" is in
# an iframe whose viewport starts at (30, 40) in the page's.
LAYOUT = {
    "#far": {"x": 100, "y": 1600, "width": 80, "height": 30},
    "#name": {"x": 40, "y": 120, "width": 200, "height": 24},
    "#near": {"x": 500, "y": 300, "width": 50, "height": 20},
    "#framed": {"x": 10, "y": 10, "width": 60, "height": 20},
}
FRAME = (30, 40)


def make_locator_class():
    # A class per test, like Playwright's per-API classes, so patching one
    # never leaks into another test.
    class FakeLocator:
        def __init__(self, page, selector):
            self._page, self.selector = page, selector

        @property
        def page(self):
            return self._page

        @property
        def first(self):
            return FakeLocator(self._page, self.selector)

        def _log(self, name, *args):
            self._page.rec.events.append([f"locator.{name}", self.selector, *args])
            return self._page.rec.ret()

        def _box(self):
            """The border box in its frame's viewport."""
            box = dict(LAYOUT[self.selector])
            if self.selector != "#framed":
                box["y"] -= self._page.scroll_y
            return box

        def click(self, *, modifiers=None, position=None, delay=None, button=None, click_count=None,
                  timeout=None, force=None, no_wait_after=None, trial=None, steps=None):
            if not trial:
                self._page.checked ^= {self.selector}
                self._page.focused = self.selector
            return self._log("click", position)

        def dblclick(self, *, modifiers=None, position=None, delay=None, button=None, timeout=None,
                     force=None, no_wait_after=None, trial=None, steps=None):
            return self._log("dblclick", position)

        def hover(self, *, modifiers=None, position=None, timeout=None, no_wait_after=None, force=None, trial=None):
            return self._log("hover", position)

        def check(self, *, position=None, timeout=None, force=None, no_wait_after=None, trial=None):
            return self._log("check", position)

        def uncheck(self, *, position=None, timeout=None, force=None, no_wait_after=None, trial=None):
            return self._log("uncheck", position)

        def fill(self, value, *, timeout=None, no_wait_after=None, force=None):
            return self._log("fill", value)

        def type(self, text, *, delay=None, timeout=None, no_wait_after=None):
            return self._log("type", text)

        def press_sequentially(self, text, *, delay=None, timeout=None, no_wait_after=None):
            return self._log("pressSequentially", text)

        def press(self, key, *, delay=None, timeout=None, no_wait_after=None):
            return self._log("press", key)

        def scroll_into_view_if_needed(self, *, timeout=None):
            box = self._box()
            if box["y"] < 0 or box["y"] + box["height"] > VIEWPORT[1]:
                self._page.scroll_y += box["y"] + box["height"] / 2 - VIEWPORT[1] / 2
            return self._log("scrollIntoViewIfNeeded")

        def select_text(self, *, force=None, timeout=None):
            self._page.focused = self.selector
            return self._log("selectText")

        def focus(self, *, timeout=None):
            self._page.focused = self.selector
            return self._log("focus")

        def is_checked(self, *, timeout=None):
            return self._page.rec.ret(self.selector in self._page.checked)

        def bounding_box(self, *, timeout=None):
            box = self._box()
            if self.selector == "#framed":
                box["x"] += FRAME[0]
                box["y"] += FRAME[1]
            return self._page.rec.ret(box)

        def evaluate(self, expression, arg=None, *, timeout=None):
            page = self._page
            if expression == hp._FRAME_ORIGIN:
                return page.rec.ret(None if self.selector != "#framed" else [self._box()["x"], self._box()["y"]])
            if expression == SCROLL_PLAN_JS:
                return page.rec.ret(self._plan(arg))
            if expression == HIT_TEST_JS:
                # What covers the point at each press, until the list runs out.
                page.aimed = self.selector
                return page.rec.ret(page.covered.pop(0) if page.covered else None)
            if expression == FILL_NEEDS_CLICK:
                return page.rec.ret(page.focused != self.selector)
            raise AssertionError(f"unexpected page function {expression[:40]!r}")

        def _plan(self, arg):
            box = self._box()
            top, bottom = max(box["y"], 0), min(box["y"] + box["height"], VIEWPORT[1])
            region = None if bottom <= top else {**box, "y": top, "height": bottom - top}
            return {
                "inView": box["y"] >= 0 and box["y"] + box["height"] <= VIEWPORT[1],
                "deltaY": box["y"] + box["height"] / 2 - VIEWPORT[1] * arg["finishPosition"],
                "hoverX": VIEWPORT[0] / 2, "hoverY": VIEWPORT[1] / 2, "isPage": True,
                "region": region, "box": box, "borders": [2, 3],
            }

    return FakeLocator


class SelectorMethods:
    """Page and Frame methods that take a selector, with Playwright's parameters."""

    def _selector_call(self, name, selector, *args):
        raise NotImplementedError

    def click(self, selector, *, strict=None, position=None, force=None, timeout=None, trial=None):
        return self._selector_call("click", selector)

    def dblclick(self, selector, *, strict=None, position=None, force=None, timeout=None, trial=None):
        return self._selector_call("dblclick", selector)

    def hover(self, selector, *, strict=None, position=None, force=None, timeout=None, trial=None):
        return self._selector_call("hover", selector)

    def check(self, selector, *, strict=None, position=None, force=None, timeout=None, trial=None):
        return self._selector_call("check", selector)

    def uncheck(self, selector, *, strict=None, position=None, force=None, timeout=None, trial=None):
        return self._selector_call("uncheck", selector)

    def fill(self, selector, value, *, strict=None, force=None, timeout=None):
        return self._selector_call("fill", selector, value)

    def type(self, selector, text, *, strict=None, delay=None, timeout=None):
        return self._selector_call("type", selector, text)

    def press(self, selector, key, *, strict=None, delay=None, timeout=None):
        return self._selector_call("press", selector, key)


class FakeFrame(SelectorMethods):
    def __init__(self, page):
        self.page = page

    def locator(self, selector):
        return self.page.locator(selector)

    def _selector_call(self, name, selector, *args):
        return self.page._selector_call(f"frame.{name}", selector, *args)


class FakePage(SelectorMethods):
    def __init__(self, rec, locator_class):
        self.rec = rec
        self.main_frame = FakeFrame(self)
        self.mouse = FakeMouse(self)
        self.keyboard = FakeKeyboard(rec)
        self._locator_class = locator_class
        self.covered, self.checked = [], set()
        self.aimed = self.focused = None
        self.scroll_y = 0.0
        self.timeout = 30000
        # Playwright's client keeps the default timeout here.
        page = self
        self._impl_obj = type("Impl", (), {"_timeout_settings": type("T", (), {"timeout": lambda _: page.timeout})()})()

    def locator(self, selector):
        return self._locator_class(self, selector)

    def evaluate(self, expression, arg=None):
        assert expression == hp._VIEWPORT, expression
        return self.rec.ret(list(VIEWPORT))

    def _selector_call(self, name, selector, *args):
        self.rec.events.append([f"page.{name}", selector, *args])
        return self.rec.ret()


class FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.pages = []
        self._handlers = []

    def on(self, event, handler):
        assert event == "page"
        self._handlers.append(handler)

    def open_page(self):
        """A page the browser opened by itself, such as a popup."""
        page = FakePage(self.browser.rec, self.browser.locator_class)
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
        return self.rec.ret(context.open_page())


@pytest.fixture(autouse=True)
def virtual_clock(monkeypatch):
    """myuri waits on the host's clock; here a wait only moves the clock on."""
    clock = [0.0]

    def sleep(host, ms):
        clock[0] += ms
        return host.page.rec.ret()

    monkeypatch.setattr(hp._Host, "now", lambda host: clock[0])
    monkeypatch.setattr(hp._Host, "sleep", sleep)


def run(rec, value):
    return asyncio.run(value) if rec.is_async else value


def attached_page(humanize, is_async=False, seed=7):
    """A page whose channels are raw() except those `humanize` names."""
    browser = FakeBrowser(is_async)
    setting = {**{channel: raw() for channel in CHANNELS}, "seed": seed, **humanize}
    hp.attach(browser, setting, "linux", is_async=is_async)
    return browser, run(browser.rec, browser.new_page())


def names(browser):
    return [e[0] for e in browser.rec.events]


# ---- the shared scenario -----------------------------------------------------------

def scenario_parts(is_async):
    """Parts that draw from the stream and play, in place of myuri's timing
    (which follows the clock). myuri still scrolls, aims and checks the hits."""
    at = {"x": 0.0, "y": 0.0}

    def move(page, x, y, *, default, rng, play):
        n = 2 + math.floor(rng() * 3)
        sx, sy = at["x"], at["y"]
        at.update(x=x, y=y)
        return play([("move", sx + (x - sx) * i / n, sy + (y - sy) * i / n, i) for i in range(1, n + 1)])

    def press(page, button, click_count, *, default, rng, play):
        return play([("down", button, 0), ("up", button, 1 + math.floor(rng() * 3))])

    def wheel(page, dx, dy, *, default, rng, play):
        n = 2 + math.floor(rng() * 2)
        return play([("wheel", dx / n, dy / n, i) for i in range(n)])

    def type_(page, text, *, default, rng, play):
        steps, t = [], 0
        for ch in text:
            steps.append(("key", ch, "down", t))
            t += 1 + math.floor(rng() * 3)
            steps.append(("key", ch, "up", t))
        return play(steps)

    def key(page, key, *, default, rng, play):
        # A Playwright call inside a part is Playwright's own.
        return page.keyboard.press(key)

    parts = {"move": move, "press": press, "wheel": wheel, "type": type_, "key": key}
    if is_async:
        def asyncify(fn):
            async def part(*args, **kwargs):
                return await fn(*args, **kwargs)

            return part

        parts = {name: asyncify(fn) for name, fn in parts.items()}
    return {
        "mouse": myuri(move=parts["move"], press=parts["press"]),
        "keyboard": myuri(type=parts["type"], key=parts["key"]),
        "scroll": myuri(wheel=parts["wheel"]),
    }


def scenario(is_async):
    """Every wrapped method once, with every channel myuri's."""
    browser, page = attached_page(scenario_parts(is_async), is_async, seed=1234)

    async def actions_async():
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

    def actions_sync():
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

    run(browser.rec, actions_async() if is_async else actions_sync())
    return browser.rec.events


@pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
def test_the_scenario_matches_the_shared_sequence(is_async):
    events = scenario(is_async)
    if os.environ.get("CAMOUFOX_REGEN_GOLDEN") and not is_async:
        SEQUENCE.write_text(json.dumps({"seed": 1234, "events": events}, indent=1) + "\n")
    assert events == json.loads(SEQUENCE.read_text())["events"]


def test_the_scenario_reads_as_intended():
    events = scenario(False)
    kinds = [e[0] for e in events]
    # Every press is the press part's down and up; only the trial click is Playwright's.
    assert kinds.count("locator.click") == 1 and events[-1] == ["locator.click", "#near", None]
    assert "mouse.click" not in kinds and "locator.scrollIntoViewIfNeeded" not in kinds
    # #far is below the fold, so myuri wheels it into view before moving onto it.
    first_down = kinds.index("mouse.down")
    assert kinds.index("mouse.wheel", kinds.index("mouse.wheel") + 3) < first_down
    # hover(position=) stops on the padding-box point: box + border + position, after the scroll.
    near = LAYOUT["#near"]
    assert any(e[0] == "mouse.move" and e[1] == near["x"] + 2 + 5 for e in events)
    # fill clicks the unfocused field, selects its text and types key by key.
    select = kinds.index("locator.selectText")
    assert kinds[select - 1] == "mouse.up" and kinds[select + 1] == "keyboard.down"
    # The key part's own Playwright call is not routed back into the part.
    assert ["keyboard.press", "Enter"] in events and "keyboard.type" not in kinds
    # fill("") is Playwright's alone.
    assert ["locator.fill", "#name", ""] in events


# ---- myuri's own parts ---------------------------------------------------------------

def in_box(x, y, box):
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]


def test_myuri_moves_to_a_point_in_the_box_and_clicks_there():
    browser, page = attached_page({"mouse": myuri()})
    page.locator("#near").click()
    events = browser.rec.events
    moves = [e for e in events if e[0] == "mouse.move"]
    assert len(moves) > 1 and "locator.click" not in names(browser)
    assert in_box(*moves[-1][1:], LAYOUT["#near"])
    assert events[-2:] == [["mouse.down", "left", 1], ["mouse.up", "left", 1]]


def test_myuri_reaches_into_an_iframe_at_its_offset():
    browser, page = attached_page({"mouse": myuri()})
    page.locator("#framed").click()
    moves = [e for e in browser.rec.events if e[0] == "mouse.move"]
    framed = LAYOUT["#framed"]
    assert in_box(*moves[-1][1:], {**framed, "x": framed["x"] + FRAME[0], "y": framed["y"] + FRAME[1]})


def test_myuri_wheels_an_element_into_view_in_mouse_notches():
    browser, page = attached_page({"mouse": myuri(), "scroll": myuri()})
    page.locator("#far").click()
    wheels = [e for e in browser.rec.events if e[0] == "mouse.wheel"]
    # A Linux or Windows mouse wheel scrolls in 100 px notches (docs/input-dispatch.md).
    assert wheels and all(dx == 0 and dy and dy % 100 == 0 for _, dx, dy in wheels)
    far = {**LAYOUT["#far"], "y": LAYOUT["#far"]["y"] - page.scroll_y}
    assert in_box(*[e for e in browser.rec.events if e[0] == "mouse.move"][-1][1:], far)


def test_a_covered_point_is_reached_for_again():
    browser, page = attached_page({"mouse": myuri()})
    page.covered = ["<div> intercepts pointer events"]
    page.locator("#near").click()
    assert names(browser).count("mouse.down") == 1 and not page.covered


def test_a_forced_press_skips_the_check():
    browser, page = attached_page({"mouse": myuri()})
    page.covered = ["<div> intercepts pointer events"]
    page.locator("#near").click(force=True)
    assert names(browser).count("mouse.down") == 1 and page.covered


def test_a_point_covered_past_the_timeout_raises_as_playwright_does():
    browser, page = attached_page({"mouse": myuri()})
    page.covered = ["<div> intercepts pointer events"] * 100
    with pytest.raises(PlaywrightTimeoutError, match=r"^Timeout 300ms exceeded: click <div> intercepts pointer events$"):
        page.locator("#near").click(timeout=300)
    assert "mouse.down" not in names(browser)


def test_a_hover_is_the_move_alone():
    browser, page = attached_page({"mouse": myuri()})
    page.locator("#near").hover()
    assert "mouse.move" in names(browser)
    assert not {"mouse.down", "mouse.up", "locator.hover"} & set(names(browser))


def test_check_presses_only_when_the_state_differs_and_frames_take_the_locator_flow():
    browser, page = attached_page({"mouse": myuri()})
    page.check("#near")
    page.check("#near")
    page.main_frame.click("#near")
    assert names(browser).count("mouse.down") == 2 and "#near" not in page.checked


def test_the_click_before_a_fill_is_myuris():
    browser, page = attached_page({"mouse": myuri()})
    page.fill("#name", "text")
    kinds = names(browser)
    assert "mouse.move" in kinds and kinds[-2:] == ["mouse.up", "locator.fill"]


def test_myuri_types_into_the_field_it_selected():
    browser, page = attached_page({"keyboard": myuri(), "settings": {"typing": {"wpm": 200}}})
    page.fill("#name", "hi")
    kinds = names(browser)
    # With a raw mouse the click before the fill is Playwright's.
    assert kinds.index("locator.click") < kinds.index("locator.selectText") < kinds.index("keyboard.down")
    # What the field holds, with myuri's typos corrected as it corrects them.
    field = ""
    for kind, key in [e[:2] for e in browser.rec.events if e[0] in ("keyboard.down", "keyboard.insertText")]:
        field = field[:-1] if key == "Backspace" else field + key
    assert field == "hi"


def test_the_stream_follows_the_seed():
    def moves(seed):
        browser, page = attached_page({"mouse": myuri()}, seed=seed)
        page.locator("#near").click()
        return [e for e in browser.rec.events if e[0] == "mouse.move"]

    assert moves(1) == moves(1) != moves(2)


def test_the_settings_set_myuris_speed():
    def moves(settings):
        total = 0
        for seed in range(10):
            browser, page = attached_page({"mouse": myuri(), "settings": settings}, seed=seed)
            page.mouse.move(900, 600)
            total += names(browser).count("mouse.move")
        return total

    # The pointer reports about every 10 ms, so a faster move reports less often.
    assert moves({"mouse": {"speed_factor": 3}}) < moves({}) / 2


# ---- parts and raw() channels ------------------------------------------------------

def test_a_part_gets_the_page_and_can_call_myuris_through_default():
    seen = []

    def move(page, x, y, *, default, rng, play):
        seen.append((page, x, y))
        return default()

    browser, page = attached_page({"mouse": myuri(move=move)})
    page.mouse.move(50, 60)
    assert seen == [(page, 50, 60)]
    assert [e for e in browser.rec.events if e[0] == "mouse.move"][-1] == ["mouse.move", 50, 60]


def test_a_part_calling_its_own_channel_reaches_playwright():
    def move(page, x, y, **_):
        page.mouse.move(x - 1, y - 1)
        return page.mouse.move(x, y)

    browser, page = attached_page({"mouse": myuri(move=move)})
    page.mouse.move(50, 60)
    assert browser.rec.events == [["mouse.move", 49, 59], ["mouse.move", 50, 60]]


def test_an_into_view_part_is_the_scroll_a_click_uses():
    scrolled = []

    def into_view(page, locator, **_):
        scrolled.append(locator.selector)
        return locator.scroll_into_view_if_needed()

    browser, page = attached_page({"mouse": myuri(), "scroll": myuri(into_view=into_view)})
    page.locator("#far").click()
    assert scrolled and set(scrolled) == {"#far"} and "mouse.wheel" not in names(browser)
    assert names(browser).count("mouse.down") == 1


def test_a_raw_scroll_is_playwrights_and_a_raw_mouse_is_one_move():
    browser, page = attached_page({"mouse": myuri()})
    page.locator("#far").click()
    assert "locator.scrollIntoViewIfNeeded" in names(browser) and "mouse.wheel" not in names(browser)

    browser, page = attached_page({"scroll": myuri()})
    page.locator("#far").click()
    kinds = names(browser)
    # myuri wheels over the scroller, reached in one move, then Playwright clicks.
    # A first long scroll takes two passes (myuri reads the page's px per wheel
    # px from the first), and the raw mouse sends each pass's move as asked.
    moves = {tuple(e[1:]) for e in browser.rec.events if e[0] == "mouse.move"}
    assert kinds[0] == "mouse.move" and len(moves) == 1 and kinds[-1] == "locator.click"
    assert "mouse.wheel" in kinds


def test_async_parts_run_on_the_async_api():
    async def press(page, button, click_count, *, default, **_):
        await asyncio.sleep(0)
        return await default()

    browser, page = attached_page({"mouse": myuri(press=press)}, is_async=True)
    run(browser.rec, page.locator("#near").click())
    assert names(browser)[-2:] == ["mouse.down", "mouse.up"]


def test_exceptions_propagate():
    def broken(page, text, **_):
        raise RuntimeError("part failed")

    _, page = attached_page({"keyboard": myuri(type=broken)})
    with pytest.raises(RuntimeError, match="part failed"):
        page.keyboard.type("x")


def test_popups_and_new_contexts_are_wrapped_and_other_browsers_are_not():
    seen = []

    def move(page, x, y, **_):
        seen.append((x, y))

    browser, page = attached_page({"mouse": myuri(move=move)})
    page.context.open_page().mouse.move(1, 2)
    browser.new_context().open_page().mouse.move(3, 4)
    other, other_page = attached_page({"keyboard": myuri()})
    other_page.mouse.move(5, 6)
    assert seen == [(1, 2), (3, 4)]
    assert other.rec.events == [["mouse.move", 5, 6]]
    with pytest.raises(ValueError, match="already attached"):
        hp.attach(browser, {"mouse": myuri()}, "linux", is_async=False)


# ---- the setting -----------------------------------------------------------------

def test_the_sync_api_refuses_an_async_part():
    async def mover(page, x, y, **_):
        pass

    with pytest.raises(ValueError, match=r"myuri\(move=mover\) is async, but this is the sync API"):
        hp.check({"mouse": myuri(move=mover)}, is_async=False)
    hp.check({"mouse": myuri(move=mover)}, is_async=True)


def test_launch_server_refuses_humanize(monkeypatch):
    from camoufox import server

    monkeypatch.setattr(server, "launch_options", lambda **_: pytest.fail("launched"))
    with pytest.raises(ValueError, match="launch_server\\(\\) cannot run humanize engines"):
        server.launch_server(humanize={"mouse": myuri()})
