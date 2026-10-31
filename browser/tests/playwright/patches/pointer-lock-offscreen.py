r"""
A pointer-locked window partly off the top or left of the screen keeps running.

On X11, pointer lock confines the cursor with four XFixes pointer barriers on
the window's edges, rebuilt on every move and resize
(nsWindowX11::UpdateNativePointerBarriers). The X server refuses a barrier
whose fixed coordinate is negative with BadValue. Firefox's own X error handler
only logs, but GDK installs its handler for as long as it holds an error trap,
and that one aborts on any error outside a trap: MOZ_CRASH in
HandleGLibMessage, "BadValue ... XFIXES minor_code 31". So a locked window
whose left or top edge was even a pixel off screen crashed the browser
whenever GDK happened to read the refusal inside one of its traps, which a
window manager placing the window at startup made likely (2 launches in 24
under openbox). Stock Firefox crashes the same way.

The guard forces that order on every barrier: assets/barrier-trap-shim.c,
preloaded into the browser, opens and closes a GDK trap right after each
request. The fix clamps the barriers to the screen, whose edge already stops
the pointer there, and makes them inside a trap of their own.

    python browser/tests/playwright/patches/pointer-lock-offscreen.py [binary]
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, hidden_display, marionette_args, resolve_binary  # noqa: E402

SHIM = Path(__file__).resolve().parent / "assets" / "barrier-trap-shim.c"

PAGE = ("data:text/html,<body style='margin:0;height:100vh'>"
        "<script>document.body.onclick=()=>document.body.requestPointerLock()</script>")

CLICK = {"actions": [{"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"},
                      "actions": [{"type": "pointerMove", "x": 200, "y": 200, "origin": "viewport"},
                                  {"type": "pointerDown", "button": 0},
                                  {"type": "pointerUp", "button": 0}]}]}


def build_shim(directory):
    if not shutil.which("cc"):
        raise SystemExit("a C compiler is required for this guard")
    out = Path(directory, "barrier-trap-shim.so")
    subprocess.run(["cc", "-shared", "-fPIC", "-o", str(out), str(SHIM), "-ldl"], check=True)
    return out


def connect(proc, port):
    """Marionette on port, or None once the browser has exited."""
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            return None
        try:
            return Marionette(port, timeout=5)
        except OSError:
            time.sleep(0.5)
    raise SystemExit("Marionette never answered")


def barriers(log_path):
    """(x1, y1, x2, y2) of every barrier the shim has seen made so far."""
    marker = "barrier-trap-shim-call "
    return [tuple(int(v) for v in line[len(marker):].split())
            for line in Path(log_path).read_text(errors="replace").splitlines()
            if line.startswith(marker)]


def run(binary, shim, x, y):
    """Lock the pointer, then move the window to (x, y).

    Returns (locked, still answering, barriers made before the move, barriers made after it).
    """
    port = free_port()
    with tempfile.TemporaryDirectory() as profile:
        Path(profile, "user.js").write_text(f'user_pref("marionette.port", {port});\n')
        env = {**os.environ, "LD_PRELOAD": str(shim), "MOZ_CRASHREPORTER_DISABLE": "1"}
        log_path = Path(profile, "stderr.log")
        log = open(log_path, "wb")
        proc = subprocess.Popen([str(binary), "-no-remote", "-profile", profile, *marionette_args()],
                                stdout=subprocess.DEVNULL, stderr=log, env=env)
        before = None
        try:
            m = connect(proc, port)
            if m is None:
                return False, False, [], []
            m.sock.settimeout(20)
            locked = answered = False
            try:
                m.js("window.moveTo(40, 40); window.resizeTo(1000, 700);")
                m.call("Marionette:SetContext", {"value": "content"})
                m.call("WebDriver:Navigate", {"url": PAGE})
                m.call("WebDriver:PerformActions", CLICK)
                time.sleep(1)
                locked = m.call("WebDriver:ExecuteScript",
                                {"script": "return !!document.pointerLockElement", "args": []}).get("value")
                m.call("Marionette:SetContext", {"value": "chrome"})
                before = len(barriers(log_path))
                m.js(f"window.moveTo({x}, {y});")
                time.sleep(3)
                # A process that still exists is not enough: GDK's fatal path can leave it hung.
                answered = m.js("return 1") == 1
            except (OSError, RuntimeError):
                pass
            finally:
                m.close()
            alive = answered and proc.poll() is None
        finally:
            proc.kill()
            proc.wait()
            log.close()
            said = log_path.read_text(errors="replace")
            if "barrier-trap-shim:" in said:
                raise SystemExit(said[said.index("barrier-trap-shim:"):].splitlines()[0])
        made = barriers(log_path)
        split = len(made) if before is None else before
        return locked, alive, made[:split], made[split:]


def main() -> int:
    binary = Path(sys.argv[1]) if len(sys.argv) > 1 else resolve_binary()
    failures = []
    with tempfile.TemporaryDirectory() as tmp, hidden_display("1920x1080"):
        shim = build_shim(tmp)
        locked, alive, made, _ = run(binary, shim, 60, 60)
        print(f"control, moved on screen: locked={locked} alive={alive} barriers={len(made)}")
        if not (locked and alive):
            failures.append("the pointer did not lock, or the browser died, with the window on screen,"
                            " so the check proves nothing")
        elif not made:
            # document.pointerLockElement is set even when Firefox never takes the native
            # lock, and without it there are no barriers for the move to break.
            failures.append("pointer lock made no X barriers, so the check proves nothing")
        else:
            for x, y in [(-30, 60), (60, -30)]:
                locked, alive, _, after = run(binary, shim, x, y)
                # The edge that moved off screen: the left one when x < 0, else the top one.
                edge = [min(b[0], b[2]) if x < 0 else min(b[1], b[3]) for b in after]
                print(f"moved to ({x},{y}): locked={locked} alive={alive} off-screen edge at {sorted(set(edge))}")
                if not alive:
                    failures.append(f"the browser died when the locked window moved to ({x},{y})")
                elif not locked:
                    failures.append(f"the pointer did not lock before the move to ({x},{y})")
                elif not any(e <= 0 for e in edge):
                    failures.append(f"the move to ({x},{y}) did not rebuild the barriers at the screen edge,"
                                    " so the check proves nothing")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: a pointer-locked window partly off screen keeps running")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
