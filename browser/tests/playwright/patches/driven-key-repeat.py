"""
A driven key held down repeats as the claimed OS repeats it.

The OS repeats the last key pressed while it is held. People's recordings on
stock 159.0 (private) and the defaults:
- Windows repeats after 500 ms, then every 31.25 ms (two ticks), and repeats
  Shift too: a person's Shift held a second sends about twenty repeat keydowns.
- macOS repeats after 500 ms, then every 83.3 ms, and never repeats a modifier.
- GNOME repeats after 500 ms, then every 30 ms (its schema defaults), and the
  XKB keymap does not repeat a modifier.
Pressing another key moves the repeat to that key. A driven key held down
sent one keydown however long it was held.

Firefox skips a repeat the OS sent while the page was still handling the last
(BrowserChild::SkipRepeatedKeyEvent), so a busy page gets repeats on the OS's
schedule, fewer of them: stock 159.0 on Linux, its keydown handler busy for
100 ms, got one every 120 ms with the X server repeating every 40. Driven
repeats caught up instead, a burst of the ones the page had missed, with gaps
shorter than the OS's that no person's Firefox shows; with a busy handler they
came every 101 ms, off the OS's schedule.

The guard holds a letter, then Shift, then a letter and another over it, then
a letter whose keydown handler is busy for 100 ms, under each identity, and
checks the repeat keydowns, their delay and interval, and the text the repeats
type.

The browser times a hold from the keydown reaching it to the keyup reaching
it, longer than the driver's sleep by both sides' latency, and a loaded
browser skips repeats as a loaded Firefox does. A repeat the browser was late
with carries the time it was sent, where Firefox's carries the OS's, so the
gap after it is short. So the checks use only what none of that changes: no
repeat after the keyup, the first repeat never early and on time on at least
one hold, most gaps one interval, and the interval measured across repeats
far apart, where one late repeat moves it by a fraction of a millisecond.

    python browser/tests/playwright/patches/driven-key-repeat.py
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

BUSY = 100
PAGE = """<!doctype html><html><body><input id="field"><script>
  const seen = [];
  for (const type of ['keydown', 'keyup'])
    addEventListener(type, (e) => {
      seen.push([type, e.key, e.repeat, e.timeStamp]);
      document.body.dataset.seen = JSON.stringify(seen);
      if (type === 'keydown' && e.key === 'd')
        for (const t = performance.now(); performance.now() - t < BUSY;);
    }, true);
</script></body></html>""".replace("BUSY;", f"{BUSY};")
# Delay and interval in ms, and whether a modifier repeats.
REPEAT = {"windows": (500, 31.25, True), "macos": (500, 1000 / 12, False), "linux": (500, 30, False)}
HOLD = 1100
# Long enough for twenty gaps at macOS's interval.
LONG_HOLD = 2200
# The first repeat's distance from the OS's delay: the keydown and the repeat
# each reach the page late by their own latency. The delays an OS offers are
# 250 ms or more apart.
DELAY_SLACK = 100
# How far a busy page's gaps may sit from a whole number of intervals: each
# stamp is the OS's time plus a millisecond or so of dispatch. A Windows stamp
# is on a 16 ms tick, too coarse to tell.
SLOT_SLACK = 5
# How far an on-time repeat sits from the OS's schedule: a millisecond or so
# of dispatch each side.
ON_TIME = 3


def probe(binary, os_name):
    from camoufox.sync_api import Camoufox

    prefs = {"privacy.reduceTimerPrecision": False}
    with Camoufox(executable_path=str(binary), headless=False, os=os_name, firefox_user_prefs=prefs,
                  i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)
        page.click("#field")
        page.keyboard.down("a")
        page.wait_for_timeout(LONG_HOLD)
        page.keyboard.up("a")
        page.keyboard.down("Shift")
        page.wait_for_timeout(HOLD)
        page.keyboard.up("Shift")
        page.keyboard.down("b")
        page.wait_for_timeout(700)
        page.keyboard.down("c")
        page.wait_for_timeout(700)
        page.keyboard.up("b")
        page.keyboard.up("c")
        page.keyboard.down("d")
        page.wait_for_timeout(LONG_HOLD)
        page.keyboard.up("d")
        page.wait_for_timeout(100)
        return page.evaluate("() => JSON.parse(document.body.dataset.seen || '[]')"), page.input_value("#field")


def held(seen, key):
    downs = [t for type, k, _, t in seen if type == "keydown" and k == key]
    return downs[0], downs[1:]


def after_keyup(seen, key):
    """Keydowns of `key` the page saw after its first keyup."""
    up = next(i for i, (type, k, _, _) in enumerate(seen) if type == "keyup" and k == key)
    return sum(1 for type, k, _, _ in seen[up:] if type == "keydown" and k == key)


def slots(repeats, interval):
    """Each gap between repeats as a whole number of intervals, at least one,
    and the gap's distance from it."""
    gaps = [b - a for a, b in zip(repeats, repeats[1:])]
    whole = [max(1, round(g / interval)) for g in gaps]
    return whole, [g - n * interval for g, n in zip(gaps, whole)]


def measured_interval(repeats):
    """The OS's interval, from the repeats that came on time. Each repeat is
    placed on the schedule by its distance from the first, in median gaps. A
    late repeat is only ever late, so the on-time ones lie on one line: of the
    lines through two repeats at least half the hold apart, the one most
    repeats lie on (within ON_TIME) is the schedule, and the interval is the
    median slope between the repeats on it."""
    rough = statistics.median(b - a for a, b in zip(repeats, repeats[1:]))
    slot = [round((t - repeats[0]) / rough) for t in repeats]
    pairs = [(i, j) for i in range(len(repeats)) for j in range(i + 1, len(repeats)) if slot[j] - slot[i] >= slot[-1] / 2]

    def on(i, j):
        every = (repeats[j] - repeats[i]) / (slot[j] - slot[i])
        return {k for k, t in enumerate(repeats) if abs(t - repeats[i] - (slot[k] - slot[i]) * every) <= ON_TIME}

    best = max((on(i, j) for i, j in pairs), key=len)
    return statistics.median((repeats[j] - repeats[i]) / (slot[j] - slot[i]) for i, j in pairs if {i, j} <= best)


def main() -> int:
    failures = []
    with hidden_display("1920x1080"):
        runs = {os_name: probe(resolve_binary(), os_name) for os_name in REPEAT}
    for os_name, (delay, interval, modifiers) in REPEAT.items():
        seen, value = runs[os_name]
        flagged = [k for type, k, repeat, _ in seen if type == "keydown" and repeat]
        for key in "abcd":
            if after_keyup(seen, key):
                failures.append(f"{os_name}: '{key}' repeated {after_keyup(seen, key)} times after its keyup")
        # No hold's first repeat comes before the OS's delay, and unless the
        # browser was late on every hold, one comes on it.
        starts = {key: round(held(seen, key)[1][0] - held(seen, key)[0]) for key in "abd" if held(seen, key)[1]}
        if len(starts) < 3:
            failures.append(f"{os_name}: held keys that never repeated: {set('abd') - set(starts)}")
        elif not delay - DELAY_SLACK <= min(starts.values()) <= delay + DELAY_SLACK:
            failures.append(f"{os_name}: first repeats {starts} ms after the keydown, the OS's {delay}")
        repeats = held(seen, "a")[1]
        if len(repeats) < 10:
            failures.append(f"{os_name}: 'a' held {LONG_HOLD} ms repeated {len(repeats)} times")
        else:
            # A gap of more than one interval is a repeat the page skipped
            # while late; most gaps are one.
            gap = statistics.median(b - a for a, b in zip(repeats, repeats[1:]))
            every = measured_interval(repeats)
            if not 0.75 <= gap / interval <= 1.5 or abs(every - interval) > 2:
                failures.append(f"{os_name}: 'a' repeated every {every:.1f} ms (median gap {gap:.1f}), "
                                f"the OS every {interval:.1f}")
        if os_name != "windows":
            # A page busy longer than an interval skips repeats: its gaps are
            # more than one interval, and whole numbers of them.
            d_whole, d_off = slots(held(seen, "d")[1], interval)
            if not d_off or statistics.median(d_whole) < 2 or statistics.median(abs(d) for d in d_off) > SLOT_SLACK:
                gaps = [round(n * interval + d, 1) for n, d in zip(d_whole, d_off)]
                failures.append(f"{os_name}: a page busy {BUSY} ms on each keydown got 'd' repeats {gaps} ms "
                                f"apart, not on the OS's {interval:.1f} ms schedule")
        shift = len(held(seen, "Shift")[1])
        if bool(shift) != modifiers:
            failures.append(f"{os_name}: Shift held {HOLD} ms repeated {shift} times; "
                            f"{'it repeats' if modifiers else 'a modifier does not repeat'} there")
        b_repeats = held(seen, "b")[1]
        c_down, c_repeats = held(seen, "c")
        if not b_repeats or any(t > c_down for t in b_repeats) or not c_repeats:
            failures.append(f"{os_name}: the repeat did not move from 'b' to 'c' when 'c' was pressed")
        if any(k not in "abcdShift" for k in flagged):
            failures.append(f"{os_name}: repeats of keys not held: {set(flagged)}")
        typed = "".join(key * (1 + len(held(seen, key)[1])) for key in "abcd")
        if value != typed:
            failures.append(f"{os_name}: the field holds {value!r}, the repeats typed {typed!r}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a held key repeats as each OS repeats it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
