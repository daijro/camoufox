# Host parity: a Windows identity on a Linux host

The Linux build is meant to pass for Firefox on the OS it claims. Measured
against stock Firefox on Windows 10, Windows 11 and Linux, some answers still came from
the host. This lists each one, what a page reads, and how it is closed.

| Tell (before) | What the page read | Fix | Where |
|---|---|---|---|
| Math from the host's libm | `Math.sin/cos/tan/pow` differ from Windows 11 in the last bit (beta.40 against stock Firefox 158 on Windows 11 25H2: sin 345, cos 458, tan 753 of 33,386 inputs, about 1% of a million random ones; pow 10 of 27,249 and 398 of a million random) | the algorithms the Windows CRT uses (`javascript.options.use_ucrt_math`): for pow, Arm's optimized-routines pow (128-entry log table, 256-entry exp table, FMA in the log step), which Windows 11 24H2 and later ship; for sin/cos/tan, Cody-Waite and Payne-Hanek reduction with AMD LibM's kernels, and the CRT's NaN for an infinite argument. Tables generated from their definitions (`browser/scripts/gen-ucrt-math-tables.py`); checked bit for bit against outputs recorded from `ucrtbase.dll` (`browser/tests/ucrt-math/`) and from Windows Firefox | `windows-crt-math.patch`, launcher |
| GTK keyboard | Ctrl+Up in `<textarea>` moved up a line (Windows: line start); Alt+Backspace no undo; Shift+Delete with nothing selected did nothing; Ctrl+/ selected all; AltGr `keyCode` 225 (Windows: 18); Ctrl+Backspace on a rich-text selection deleted only the selection | `input:windowsKeyboard`: Windows' shortcut tables replace GTK's text bindings (native and the ones synthesized events get), AltGr reports Alt, Windows' caret style in HTML editors. Launch-wide; set it `false` to keep Linux behaviour. The tables, text bindings and AltGr are GTK code, so on a macOS host only the caret style changes | `windows-keyboard.patch`, launcher |
| Linux behaviour defaults | middle click pastes the primary selection, double-click selects no trailing space, instant fullscreen, GTK scrollbar clicks, scrollbars without arrow buttons, contextmenu on button press | Windows' defaults (`windowsBehaviourPrefs` in `launcher-constants.json`). Measured on stock Windows: `middlemouse.paste`, `general.autoScroll`, `eat_space_to_next_word`, the fullscreen transition. From Firefox 158's `all.js`, `firefox.js` and `StaticPrefList.yaml` only: `middlemouse.scrollbarPosition`, `ui.scrollToClick`, `slider.snapMultiplier`, `click_and_hold_track`, `ui.scrollArrowStyle` (4097, eScrollArrowStyle_Single: Windows' LookAndFeel, nsLookAndFeel.cpp `ScrollArrowStyle`), `ui.context_menus.after_mouseup` (Windows sends WM_CONTEXTMENU after the button is released) | launcher |
| Scrollbars from the host theme | a Windows 10 identity's classic scrollbars 12 px (GTK's); stock Windows 17 px | Windows' non-native scrollbars (`widget.non-native-theme.scrollbar.style` 4 or 5, following `ui.useOverlayScrollbars`) at Windows' size | launcher |

These apply only when the identity claims Windows and the host is not Windows;
on a Windows host the build already behaves this way. Every default yields to a
value the caller sets.

They are the browser's, not a context's: prefs and launch config set from the
OS the browser was launched with. On a browser launched as Windows, a context
created with `NewContext(os="macos")` still has Windows' math, keyboard and
behaviour; on a browser launched as Linux, a Windows context has Linux's.
`NewContext` does not refuse that, because a launch without `os` draws its OS
from fpgen's mix, and a refusal would then come and go with the draw. Launch
with the `os` whose behaviour the contexts need, or one browser per OS.

## AltGr: what is left

On Windows, AltGr is Ctrl+Alt to the OS. Pressing it sends a ControlLeft
`WM_KEYDOWN` before the AltRight one (Firefox's `widget/windows/KeyboardLayout.cpp`
says so), so stock Firefox on Windows fires a `keydown` with `code`
`ControlLeft`, `key` `Control` and `ctrlKey` true, then one with `code`
`AltRight`, `key` `AltGraph` and `keyCode` 18. While AltGr is down on a layout
that has it, Firefox's `ModifierKeyState` sets only the AltGraph modifier, so
the AltGraph events and the characters typed with it carry `ctrlKey` and
`altKey` false, as they do here. (Chromium on Windows reports them true; Firefox
does not.)

This build fires the AltRight event with Windows' `keyCode` (18) but not the
ControlLeft events before and after it. Adding them means dispatching extra key
events from GTK's `KeymapWrapper`, which `GetDOMKeyCodeFromKeyPairs` cannot do,
and their order on release (ControlLeft before or after AltRight) has to be
recorded on Windows first. So a page that listens for the ControlLeft keydown
around AltGr can still tell. Pages see this only from a keyboard layout with
AltGr; a US layout has none.

## Reference data for the math

Both references were recorded on Windows; neither can be produced on Linux.
They come from one machine: Windows 11 25H2 (build 26200.9711) on an Intel
i9-11900H, which has FMA3, so the CRT takes its FMA3 paths.

- `browser/tests/ucrt-math/expected.u64.xz` is what `ucrtbase.dll`
  10.0.26100.9711 returns for every input in `inputs.py`, written by
  `record.py` with its provenance in `provenance.json`. It depends only on the
  CRT, not on Firefox.
- `browser/tests/playwright/patches/assets/windows-crt-math.json` is what stock
  Firefox 158.0 (the release build from archive.mozilla.org) returned on that
  machine for a sample of those inputs, cold, JIT-hot and constant-folded,
  written by `record_firefox.py`. The three paths agreed on every input;
  `check.py` checks that the sample is the one `record_firefox.py` draws and
  that each result there that comes from the CRT equals `expected.u64.xz`'s.

Every other `Math` function (exp, log and their variants, the inverse and
hyperbolic trig functions, cbrt, sqrt, atan2, hypot) uses fdlibm on Windows as
it does here; on 200,000 random inputs each, and on all three paths, they
matched stock Windows Firefox 158 bit for bit without any change.

Windows 10 and Windows 11 before 24H2 ship an older `ucrtbase.dll` (10.0.22621
and earlier) whose pow is AMD LibM's, not Arm's. Its results differ from the
24H2 pow in about 0.2% of the inputs in `inputs.py` (52 of 27,249). This build
returns the 24H2 results, so against a Windows 10 identity those pow results
are the newer Windows'. sin, cos and tan are the same in both.

Re-record on the pinned Firefox version when an update touches SpiderMonkey's
sin, cos, tan or `ecmaPow`, the JIT's paths to them, or constant folding, and
on a new Windows build when its `ucrtbase.dll` changes.
