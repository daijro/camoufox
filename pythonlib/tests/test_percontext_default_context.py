"""Guard: the per-context font list must apply in the default browser context.

Regression guard for the font-list gap. `window.setFontList()` stored the spoofed
list, but the filter in gfxPlatformFontList::FindAndAddFamiliesLocked was gated on

    if (ctx != 0 && FontListManager::HasFontList(ctx)) { ... }

and juggler's default browser context IS userContextId 0 --
additions/juggler/TargetRegistry.js:

    // Default context has userContextId === 0, but we pass undefined to many APIs
    this.userContextId = 0;

That is the context Playwright's launch_persistent_context() runs in, so
setFontList() stored a list there, deleted itself from window, reported nothing,
and nothing ever read it. Measured on 152.0.4-beta.30, macOS mask, no global
CAMOU_CONFIG["fonts"] allowlist: a persistent context resolved all 14 probed
Windows-only families -- identical to an unmasked baseline -- while
navigator.platform read MacIntel. A non-default context resolved 4.

Playwright's browser.new_page() is not affected: it creates its own context, so
it never lands in id 0. build-tester never caught it either, because
scripts/runner.py builds every profile with browser.new_context() (lines 109,
339), which allocates a non-zero id.

HasFontList() is the correct guard on its own -- false until setFontList() has run
for that context, so id 0 behaves as before when nothing set a list.

Note this is the *lookup* side. A `userContextId != 0` test on the *setter* side is
a different, legitimate pattern: SetAudioFingerprintSeed, SetScreenDimensions,
SetTimezone and SetWebGLVendor all mirror their write into context 0 as a fallback
for workers whose context id differs from the parent page. Those are writes to an
extra context, not a refusal to read one, and this test does not touch them.

Second assertion: the filter must keep chrome documents out. `ctx != 0` was also,
accidentally, the only thing doing that -- a chrome document resolves fonts with the
thread-local still at 0 -- so removing it makes the exemption load-bearing. Without
it this is daijro/camoufox#695 again: the Windows titlebar draws tofu instead of its
Segoe Fluent Icons glyphs.

Run with:
    cd pythonlib && python -m pytest tests/test_percontext_default_context.py -v
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / "patches" / "font-list-spoofing.patch"
TARGET = "gfx/thebes/gfxPlatformFontList.cpp"

# `ctx != 0`, `userContextId != 0`, `0 != ctx`, ... on a context identifier.
CONTEXT_VAR = r"(?:a?[Uu]ser[Cc]ontext[Ii]d|ctx|contextId)"
NONZERO_GUARD = re.compile(
    r"(?:%s\s*!=\s*0)|(?:0\s*!=\s*%s)" % (CONTEXT_VAR, CONTEXT_VAR)
)


def _added_lines_for(patch: Path, target: str, code_only: bool = False) -> list:
    """Lines the patch adds to `target`, as (line number in patch, text).

    With code_only, `//` comment lines are dropped -- the comment above the fix
    quotes the `ctx != 0` guard it removed, and that quote is not the guard.
    """
    added, in_target = [], False
    for n, line in enumerate(patch.read_text(errors="ignore").splitlines(), 1):
        if line.startswith("diff --git "):
            in_target = line.endswith(target)
            continue
        if in_target and line.startswith("+") and not line.startswith("+++"):
            text = line[1:]
            if code_only and text.lstrip().startswith("//"):
                continue
            added.append((n, text))
    return added


def test_font_list_filter_applies_to_the_default_context():
    added = _added_lines_for(PATCH, TARGET, code_only=True)
    assert added, f"{PATCH.name} no longer patches {TARGET}"

    offenders = [
        f"{PATCH.name}:{n}: {text.strip()}"
        for n, text in added
        if NONZERO_GUARD.search(text)
    ]
    assert not offenders, (
        "the per-context font list lookup is gated on the context id being "
        "non-zero, which skips the default browser context -- juggler's "
        "userContextId 0, where browser.new_page() lands:\n  "
        + "\n  ".join(offenders)
    )


def test_font_list_filter_exempts_chrome_documents():
    added = "\n".join(text for _, text in _added_lines_for(PATCH, TARGET))

    assert "FontListManager::HasFontList" in added, (
        f"the font list filter is no longer in {TARGET}; this guard needs "
        "updating to point at wherever it moved"
    )
    assert "IsChrome()" in added, (
        "the per-context font filter has no chrome exemption. The browser UI is "
        "painted from this same font list, so filtering it leaves the Windows "
        "titlebar drawing tofu instead of its Segoe Fluent Icons glyphs "
        "(daijro/camoufox#695)."
    )
