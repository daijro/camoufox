"""
A Windows identity gets Windows' keyboard; a Linux identity keeps Linux's.

windows-keyboard.patch switches on config "input:windowsKeyboard", which the
launcher sets for Windows identities on a non-Windows host:

- the shortcut tables are Windows' own (ShortcutKeyDefinitions.cpp compiled
  with the Windows platform macros): Alt+Backspace undoes, Shift+Delete with
  nothing selected deletes the next character, Ctrl+Up in a <textarea> goes to
  the start of the line. GTK's tables and bindings have none of these.
- GTK's native text-widget bindings are not consulted: Ctrl+/ in a <textarea>
  does nothing, where GtkTextView selects all.
- AltGr reports keyCode 18 (VK_MENU), as on Windows, not GTK's 225.
- HTML editors use Windows' caret style: Ctrl+Backspace on a selection first
  collapses it to its start, then deletes the previous word.

Shortcut tables and the caret style are checked with Playwright's keys. Native
bindings and AltGr only exist for real key events, so those are sent through
X11 with xdotool on a private Xvfb display, with a German layout so Right Alt
is AltGr. Each check runs for a Windows and a Linux identity, and the Linux one
must keep stock Linux behaviour.

    python browser/tests/playwright/patches/windows-keyboard.py
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import hidden_display, resolve_binary  # noqa: E402

PAGE = """<!doctype html><title>KBGUARD</title>
<input id="undo">
<input id="del" value="hello">
<textarea id="area">abc def</textarea>
<textarea id="lines">abc def
ghi jkl</textarea>
<div id="rich" contenteditable>one two three</div>
<script>
  // In the DOM: page.evaluate runs in an isolated world and cannot read globals.
  addEventListener("keydown", e => {
    document.body.dataset.keys = (document.body.dataset.keys || "") + `${e.key}:${e.keyCode} `;
  }, true);
</script>"""

# What stock Firefox 152 does on each OS.
EXPECTED = {
    "windows": {
        "alt_backspace": "",
        "shift_delete": "ello",
        "rich_ctrl_backspace": "one three",
        "ctrl_slash_selected": 0,
        "ctrl_up_caret": 8,
        "altgr_keycode": 18,
    },
    "linux": {
        "alt_backspace": "abc",
        "shift_delete": "hello",
        "rich_ctrl_backspace": "one two ",
        "ctrl_slash_selected": 7,
        "ctrl_up_caret": 7,
        "altgr_keycode": 225,
    },
}


def xdotool(*args: str) -> None:
    subprocess.run(["xdotool", *args], check=True)


def measure(os_name: str, binary: Path) -> dict:
    from camoufox.sync_api import Camoufox

    got = {}
    with Camoufox(os=os_name, headless=False, executable_path=str(binary),
                  i_know_what_im_doing=True) as browser:
        page = browser.new_page()
        page.set_content(PAGE)

        page.focus("#undo")
        page.keyboard.type("abc")
        page.keyboard.press("Alt+Backspace")
        got["alt_backspace"] = page.eval_on_selector("#undo", "e => e.value")

        page.focus("#del")
        page.keyboard.press("Home")
        page.keyboard.press("Shift+Delete")
        got["shift_delete"] = page.eval_on_selector("#del", "e => e.value")

        page.focus("#rich")
        page.evaluate("""() => {
            const text = document.getElementById("rich").firstChild;
            getSelection().setBaseAndExtent(text, 8, text, 13);
        }""")
        page.keyboard.press("Control+Backspace")
        got["rich_ctrl_backspace"] = page.eval_on_selector(
            "#rich", "e => e.textContent.replace(/\\u00a0/g, ' ')")

        # Real key events: the X window must have the input focus.
        wid = subprocess.run(["xdotool", "search", "--sync", "--onlyvisible", "--name", "KBGUARD"],
                             capture_output=True, text=True, check=True).stdout.split()[0]
        xdotool("windowfocus", "--sync", wid)

        page.focus("#area")
        page.evaluate("() => { const a = document.getElementById('area'); a.setSelectionRange(7, 7); }")
        xdotool("key", "--clearmodifiers", "ctrl+slash")
        time.sleep(0.5)
        got["ctrl_slash_selected"] = page.eval_on_selector(
            "#area", "e => e.selectionEnd - e.selectionStart")

        page.focus("#lines")
        page.evaluate("() => { const a = document.getElementById('lines'); a.setSelectionRange(15, 15); }")
        xdotool("key", "--clearmodifiers", "ctrl+Up")
        time.sleep(0.5)
        got["ctrl_up_caret"] = page.eval_on_selector("#lines", "e => e.selectionStart")

        page.evaluate("() => { delete document.body.dataset.keys; }")
        xdotool("key", "--clearmodifiers", "ISO_Level3_Shift")
        time.sleep(0.5)
        keys = page.evaluate("() => document.body.dataset.keys || ''").split()
        altgr = [int(k.split(":")[1]) for k in keys if k.startswith("AltGraph:")]
        got["altgr_keycode"] = altgr[0] if altgr else f"no AltGraph keydown (saw {keys})"
    return got


def main() -> int:
    for tool in ("xdotool", "setxkbmap"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} is required for this guard")
    binary = resolve_binary()
    failures = []
    with hidden_display() as display:
        os.environ["DISPLAY"] = display
        os.environ["MOZ_ENABLE_WAYLAND"] = "0"
        subprocess.run(["setxkbmap", "-display", display, "de"], check=True)
        for os_name, expected in EXPECTED.items():
            got = measure(os_name, binary)
            for name, want in expected.items():
                ok = got[name] == want
                print(f"  {os_name:8} {name:22}: {got[name]!r} (stock {want!r}){'' if ok else '  <- differs'}")
                if not ok:
                    failures.append(f"{os_name} identity: {name} is {got[name]!r}, stock {os_name} gives {want!r}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: Windows identities get Windows' keyboard, Linux identities keep Linux's.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
