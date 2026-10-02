r"""
Verify the spoofed locale replaces only the DEFAULT locale, never one a page names.

patches/locale-spoofing.patch once overrode Language()/Region() on every
mozilla::intl::Locale object, so any locale or region a page passed explicitly
was rewritten to the spoofed one. With locale="tr-TR",
new Intl.DisplayNames(['en'], {type: 'region'}).of('FR') returned "Türkiye" for
every code (daijro/camoufox#824): a one-line detection and a broken country
picker on every site that uses one. The patch now spoofs only
Locale::GetDefaultLocale and OSPreferences.

The guard launches with a spoofed locale whose region differs from every code
it asks about, and checks:
  * the spoofed locale reached the page (otherwise the check is vacuous). That
    is read from navigator.language, not Intl's default: Intl only defaults to
    a locale the build has packaged, and the unpackaged objdir build CI tests
    has only en-US (scripts/package.py injects the language packs);
  * DisplayNames translates each explicit region code to its own name;
  * an explicitly named Intl.Locale keeps its own subtags.

    python tests/patches/locale-explicit-names.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

SPOOFED = "tr-TR"
REGIONS = {"US": "United States", "DE": "Germany", "FR": "France", "JP": "Japan"}

PROBE = """codes => ({
  language: navigator.language,
  defaultLocale: Intl.DateTimeFormat().resolvedOptions().locale,
  names: Object.fromEntries(codes.map(
    c => [c, new Intl.DisplayNames(['en'], {type: 'region'}).of(c)])),
  minimized: new Intl.Locale('ja-Jpan-JP').minimize().toString(),
  region: new Intl.Locale('de-AT').region,
})"""


def main() -> int:
    from camoufox.sync_api import Camoufox

    binary = resolve_binary()
    with Camoufox(headless=True, executable_path=str(binary), locale=SPOOFED, i_know_what_im_doing=True) as b:
        page = b.new_page()
        page.goto("about:blank")
        got = page.evaluate(PROBE, list(REGIONS))

    print(f"  navigator.language        : {got['language']}")
    print(f"  Intl default locale       : {got['defaultLocale']} (en-US on an unpackaged build)")
    for code, name in got["names"].items():
        print(f"  DisplayNames.of({code!r})     : {name}")
    print(f"  Intl.Locale('ja-Jpan-JP') : minimize() = {got['minimized']}")
    print(f"  Intl.Locale('de-AT')      : region = {got['region']}")

    failures = []
    if got["language"] != SPOOFED:
        failures.append(f"navigator.language is {got['language']}, not the spoofed {SPOOFED} -- check is vacuous")
    for code, name in REGIONS.items():
        if got["names"][code] != name:
            failures.append(f"DisplayNames.of({code!r}) = {got['names'][code]!r}, expected {name!r}")
    if got["minimized"] != "ja":
        failures.append(f"Intl.Locale('ja-Jpan-JP').minimize() = {got['minimized']!r}, expected 'ja'")
    if got["region"] != "AT":
        failures.append(f"Intl.Locale('de-AT').region = {got['region']!r}, expected 'AT'")
    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: the spoofed locale is the default only; explicit locales and regions are left alone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
