"""
Verify that, on macOS, the bundled fonts never stand in for the host's hidden
system fonts (font-hijacker.patch, daijro/camoufox#918).

The bundle carries copies of macOS fonts whose PostScript names start with "."
(.SFNS-Regular is the UI font). Registered in the parent, the copy shaped the
browser's own text, but WebRender in the GPU process loads hidden fonts by name
and got the host's, so the toolbar and URL bar drew the wrong glyphs. That
happened whenever the bundle is on: a launch without an identity, or one of
another OS.

For both launches this resolves hidden names in the parent with
CGFontCreateWithFontName, as WebRender does, and fails if one comes from the
bundle. SegoeUI must come from the bundle, which shows the bundle is on.

    python browser/tests/playwright/patches/macos-hidden-system-fonts.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import Marionette, free_port, marionette_args, resolve_binary  # noqa: E402

HIDDEN = [".SFNS-Regular", ".SFNSMono-Light", ".LucidaGrandeUI", ".AppleColorEmojiUI", ".HiraKakuInterface-W3"]
BUNDLED = "SegoeUI"
LAUNCHES = {"no identity": None, "Windows identity": {"navigator.platform": "Win32"}}

JS = """
const { ctypes } = ChromeUtils.importESModule("resource://gre/modules/ctypes.sys.mjs");
const lib = name => ctypes.open(`/System/Library/Frameworks/${name}.framework/${name}`);
const [cf, cg, ct] = [lib("CoreFoundation"), lib("CoreGraphics"), lib("CoreText")];
const p = ctypes.voidptr_t;
const cfString = cf.declare("CFStringCreateWithCString", ctypes.default_abi, p, p, ctypes.char.ptr, ctypes.uint32_t);
const cgFont = cg.declare("CGFontCreateWithFontName", ctypes.default_abi, p, p);
const ctFont = ct.declare("CTFontCreateWithGraphicsFont", ctypes.default_abi, p, p, ctypes.double, p, p);
const copyAttribute = ct.declare("CTFontCopyAttribute", ctypes.default_abi, p, p, p);
const urlAttribute = ct.declare("kCTFontURLAttribute", p);
const urlPath = cf.declare("CFURLGetFileSystemRepresentation", ctypes.default_abi, ctypes.bool, p, ctypes.bool, ctypes.char.ptr, ctypes.long);
const files = {};
for (const name of arguments[0]) {
  const font = cgFont(cfString(null, name, 0x08000100));
  const url = font.isNull() ? font : copyAttribute(ctFont(font, 12, null, null), urlAttribute);
  const buf = ctypes.char.array(4096)();
  files[name] = !url.isNull() && urlPath(url, true, buf, 4096) ? buf.readString() : null;
}
return { bundle: PathUtils.join(Services.dirsvc.get("GreD", Ci.nsIFile).path, "fonts"), files };
"""


def resolve(binary: Path, config) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "CAMOU_CONFIG"}
    if config:
        env["CAMOU_CONFIG"] = json.dumps(config)
    port = free_port()
    with tempfile.TemporaryDirectory() as profile:
        Path(profile, "user.js").write_text(f'user_pref("marionette.port", {port});\n')
        proc = subprocess.Popen(
            [str(binary), "-headless", "-no-remote", "-profile", profile, *marionette_args(), "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
        )
        try:
            m = Marionette(port)
            state = m.call("WebDriver:ExecuteScript", {"script": JS, "args": [HIDDEN + [BUNDLED]]})["value"]
            m.close()
        finally:
            proc.kill()
            proc.wait()
    return state


def main() -> int:
    if sys.platform != "darwin":
        print("  (not macOS -- the hidden system fonts are a macOS host's; skipped)")
        return 0

    binary = resolve_binary()
    failures = []
    for label, config in LAUNCHES.items():
        state = resolve(binary, config)
        bundle = state["bundle"] + os.sep
        print(f"  {label}:")
        for name, path in state["files"].items():
            print(f"    {name:24s} {path}")
            from_bundle = bool(path) and path.startswith(bundle)
            if name == BUNDLED and not from_bundle:
                failures.append(f"{label}: {BUNDLED} is not loaded from the bundle, so it is off")
            elif name != BUNDLED and from_bundle:
                failures.append(f"{label}: {name} resolves to the bundled {Path(path).name}")

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: the host's hidden system fonts are never replaced by bundled copies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
