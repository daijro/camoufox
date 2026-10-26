#!/usr/bin/env python3
"""
On a Mac, fail if a bundled font stands in for the host's hidden UI font (#918).

WebRender loads .SFNS-Regular by name and gets the host's copy, so a bundled copy
in the parent draws the browser's UI with the wrong glyphs. CI has no Mac; run it
by hand on one, with and without an identity:

    python3 scripts/check-macos-hidden-fonts.py --binary Camoufox.app/Contents/MacOS/camoufox
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests" / "playwright" / "patches"))
from helpers import Marionette, free_port, marionette_args, resolve_binary  # noqa: E402

# The host must win the hidden name; SegoeUI from the bundle shows the bundle is on.
EXPECT = {".SFNS-Regular": False, "SegoeUI": True}

JS = """
const { ctypes } = ChromeUtils.importESModule("resource://gre/modules/ctypes.sys.mjs");
const lib = n => ctypes.open(`/System/Library/Frameworks/${n}.framework/${n}`);
const [cf, cg, ct] = [lib("CoreFoundation"), lib("CoreGraphics"), lib("CoreText")];
const p = ctypes.voidptr_t;
const str = cf.declare("CFStringCreateWithCString", ctypes.default_abi, p, p, ctypes.char.ptr, ctypes.uint32_t);
const cgFont = cg.declare("CGFontCreateWithFontName", ctypes.default_abi, p, p);
const ctFont = ct.declare("CTFontCreateWithGraphicsFont", ctypes.default_abi, p, p, ctypes.double, p, p);
const attr = ct.declare("CTFontCopyAttribute", ctypes.default_abi, p, p, p);
const urlKey = ct.declare("kCTFontURLAttribute", p);
const path = cf.declare("CFURLGetFileSystemRepresentation", ctypes.default_abi, ctypes.bool, p, ctypes.bool, ctypes.char.ptr, ctypes.long);
const bundle = PathUtils.join(Services.dirsvc.get("GreD", Ci.nsIFile).path, "fonts");
const out = {};
for (const name of arguments[0]) {
  const font = cgFont(str(null, name, 0x08000100));
  const url = font.isNull() ? font : attr(ctFont(font, 12, null, null), urlKey);
  const buf = ctypes.char.array(4096)();
  out[name] = !url.isNull() && path(url, true, buf, 4096) && buf.readString().startsWith(bundle + "/");
}
return out;
"""


def from_bundle(binary: Path, config) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "CAMOU_CONFIG"}
    if config:
        env["CAMOU_CONFIG"] = json.dumps(config)
    port = free_port()
    with tempfile.TemporaryDirectory() as profile:
        Path(profile, "user.js").write_text(f'user_pref("marionette.port", {port});\n')
        proc = subprocess.Popen([str(binary), "-headless", "-no-remote", "-profile", profile, *marionette_args()],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        try:
            return Marionette(port).call("WebDriver:ExecuteScript", {"script": JS, "args": [list(EXPECT)]})["value"]
        finally:
            proc.kill()
            proc.wait()


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("macOS only: the hidden system fonts are a Mac host's")
    failed = False
    for label, config in (("no identity", None), ("Windows identity", {"navigator.platform": "Win32"})):
        for name, bundled in from_bundle(resolve_binary(), config).items():
            ok = bundled == EXPECT[name]
            failed |= not ok
            print(f"{'ok  ' if ok else 'FAIL'} {label}: {name} {'from the bundle' if bundled else 'from the host'}")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
