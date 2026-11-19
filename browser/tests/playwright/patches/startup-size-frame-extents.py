r"""
The window keeps the identity's outer size when the window manager's frame
arrives after it is mapped.

CamoufoxWindow.sys.mjs resizes a new window to the identity's
window.outerWidth/outerHeight and holds that size through startup. An X11
window manager announces its frame through _NET_FRAME_EXTENTS, which Firefox
adds to the outer size. When the frame arrives after the window maps, only
those margins change. The content area keeps its size, so the chrome window
gets no resize event, the hold never runs, and the page reads the identity's
size plus the frame. Under WSLg that made outerWidth larger than screen.width.

This guard plays such a window manager on a private Xvfb display. It
advertises _NET_FRAME_EXTENTS through EWMH on the root window, then sets a
frame on the browser window after it maps. The page must still read the
identity's outer size once the hold has run.

    python browser/tests/playwright/patches/startup-size-frame-extents.py
"""

import ctypes
import ctypes.util
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, launch_kwargs  # noqa: E402

OUTER = {"window.outerWidth": 1200, "window.outerHeight": 800}
# left, right, top, bottom: what WSLg's window manager sets.
FRAME = (38, 38, 59, 38)
# CamoufoxWindow.sys.mjs holds the startup size for 5 s from the window opening.
HOLD_S = 5

XA_ATOM, XA_CARDINAL, XA_WINDOW = 4, 6, 33
PROP_MODE_REPLACE = 0


class XClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_char_p), ("res_class", ctypes.c_char_p)]


class X11:
    """The few Xlib calls a window manager would make. Its connection stays open
    for the whole test, which also stops Xvfb resetting the server (and dropping
    these properties) when its other clients disconnect."""

    def __init__(self):
        self.lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.lib.XOpenDisplay.restype = ctypes.c_void_p
        self.lib.XDefaultRootWindow.restype = ctypes.c_ulong
        self.lib.XInternAtom.restype = ctypes.c_ulong
        self.dpy = self.lib.XOpenDisplay(os.environ["DISPLAY"].encode())
        if not self.dpy:
            raise SystemExit(f"FAIL: cannot open display {os.environ['DISPLAY']}")
        self.dpy = ctypes.c_void_p(self.dpy)
        self.root = self.lib.XDefaultRootWindow(self.dpy)

    def atom(self, name: str) -> int:
        return self.lib.XInternAtom(self.dpy, name.encode(), False)

    def set32(self, window: int, name: str, type_: int, values) -> None:
        data = (ctypes.c_long * len(values))(*values)
        self.lib.XChangeProperty(self.dpy, ctypes.c_ulong(window), ctypes.c_ulong(self.atom(name)),
                                 ctypes.c_ulong(type_), 32, PROP_MODE_REPLACE, data, len(values))
        self.lib.XSync(self.dpy, False)

    def advertise_frame_extents(self) -> None:
        """Claim an EWMH window manager that supports _NET_FRAME_EXTENTS; GDK
        ignores the property otherwise. The root window is its own check window."""
        self.set32(self.root, "_NET_SUPPORTING_WM_CHECK", XA_WINDOW, [self.root])
        self.set32(self.root, "_NET_SUPPORTED", XA_ATOM, [self.atom("_NET_FRAME_EXTENTS")])

    def browser_window(self) -> int:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            root_ret, parent_ret = ctypes.c_ulong(), ctypes.c_ulong()
            children, count = ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
            self.lib.XQueryTree(self.dpy, ctypes.c_ulong(self.root), ctypes.byref(root_ret),
                                ctypes.byref(parent_ret), ctypes.byref(children), ctypes.byref(count))
            windows = [children[i] for i in range(count.value)]
            if children:
                self.lib.XFree(children)
            for window in windows:
                hint = XClassHint()
                found = (self.lib.XGetClassHint(self.dpy, ctypes.c_ulong(window), ctypes.byref(hint))
                         and hint.res_name == b"Navigator")
                if found:
                    return window
            time.sleep(0.1)
        raise SystemExit("FAIL: the browser window never appeared")


def probe() -> tuple:
    from camoufox.sync_api import Camoufox

    with hidden_display(screen="1400x900"):
        x11 = X11()
        x11.advertise_frame_extents()
        with Camoufox(**launch_kwargs(headless=False, os="windows", config=OUTER,
                                      i_know_what_im_doing=True)) as browser:
            page = browser.new_page()
            started = time.monotonic()
            before = page.evaluate("[outerWidth, outerHeight, innerWidth, innerHeight]")
            x11.set32(x11.browser_window(), "_NET_FRAME_EXTENTS", XA_CARDINAL, FRAME)
            readings = []
            while time.monotonic() - started < HOLD_S + 2:
                readings.append(page.evaluate("[outerWidth, outerHeight, innerWidth, innerHeight]"))
                time.sleep(0.5)
            return before, readings


def main() -> int:
    before, readings = probe()
    print(json.dumps({"before": before, "after": readings}))
    want = [OUTER["window.outerWidth"], OUTER["window.outerHeight"]]
    left, right = FRAME[:2]
    last = readings[-1]
    # The frame counts towards the outer size whether or not the window was
    # resized to make up for it, so outerWidth - innerWidth grows by its width.
    # (The height also moves with the toolbars' layout, so it is no control.)
    if last[0] - last[2] != before[0] - before[2] + left + right:
        print("FAIL: Firefox never counted the frame, so the check proves nothing")
        return 1
    if readings[-1][:2] != want:
        print(f"FAIL: outer size settled at {readings[-1][:2]}, not the identity's {want}")
        return 1
    print("PASS: a late window-manager frame does not change the identity's outer size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
