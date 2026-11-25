"""
A Windows identity's native line break is CRLF, not the Linux build's LF.

For `new Blob(parts, {endings: "native"})`, a real Windows Firefox converts
`\n` to `\r\n`; that conversion lives in dom/file/BlobSet.cpp under `#ifdef
XP_WIN`, so a Linux build keeps `\n` and a Windows identity reports the host's
line endings (DataDome reads exactly this to fail the device check). The plain
-text serializer leaks the same thing through `Selection.toString()`.

native-line-break.patch answers both from the presented OS via
MaskConfig::NativeLineBreakIsCRLF() instead of the build.

What PASS means: with os="windows", Blob(["a\nb"], {endings:"native"}).size is
4 (CRLF) and Selection.toString() across two <p> blocks is "x\r\n\r\ny"; with
os="linux" the sizes stay 3 and "x\n\ny", matching stock on that OS.

    python browser/tests/playwright/patches/native-line-break.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PROBE = """() => {
  const blobSize = new Blob(["a\\nb"], { endings: "native" }).size;
  const p1 = document.createElement("p");
  const p2 = document.createElement("p");
  p1.textContent = "x";
  p2.textContent = "y";
  document.body.append(p1, p2);
  const range = document.createRange();
  range.selectNodeContents(document.body);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  const text = sel.toString();
  sel.removeAllRanges();
  p1.remove();
  p2.remove();
  return [blobSize, text];
}"""

# Stock Firefox 159 on Windows measured 4 ("a\\r\\nb"); Camoufox on Linux kept 3.
EXPECTED = {"windows": [4, "x\r\n\r\ny"], "linux": [3, "x\n\ny"]}


async def probe(binary, os):
    from camoufox.async_api import AsyncCamoufox

    async with AsyncCamoufox(headless=True, os=os, executable_path=str(binary),
                             i_know_what_im_doing=True) as browser:
        page = await browser.new_page()
        await page.set_content("<body></body>")
        return await page.evaluate(PROBE)


def main():
    binary = resolve_binary()
    failures = []
    for os_name, expected in EXPECTED.items():
        got = asyncio.run(probe(binary, os_name))
        ok = got == expected
        print(f"{os_name}: got {got}, expected {expected}")
        if not ok:
            failures.append(f"{os_name}: got {got}, expected {expected}")
    for f in failures:
        print("FAIL", f)
    print("FAIL" if failures else "PASS")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
