# Host parity: a Windows identity on a Linux host

The Linux build is meant to pass for Firefox on the OS it claims. Measured
against stock Firefox on Windows 10 and on Linux, some answers still came from
the host. This lists each one, what a page reads, and how it is closed.

| Tell (before) | What the page read | Fix | Where |
|---|---|---|---|
| Math from the host's libm | `Math.sin/cos/tan/pow` differ from Windows in the last bit (sin 22, cos 26, tan 30 of 1,670 inputs; pow 45 of 1,410) | the algorithms the Windows CRT uses (`javascript.options.use_ucrt_math`): Tang's table-driven log and exp for pow, Cody-Waite and Payne-Hanek reduction with AMD LibM's kernels for sin/cos/tan, tables generated from their definitions (`browser/scripts/gen-ucrt-math-tables.py`); checked bit for bit against outputs recorded from `ucrtbase.dll` (`browser/tests/ucrt-math/`) and from Windows Firefox | `windows-crt-math.patch`, launcher |
| GTK keyboard | Ctrl+Up in `<textarea>` moved up a line (Windows: line start); Alt+Backspace no undo; Shift+Delete with nothing selected did nothing; Ctrl+/ selected all; AltGr `keyCode` 225 (Windows: 18); Ctrl+Backspace on a rich-text selection deleted only the selection | `input:windowsKeyboard`: Windows' shortcut tables replace GTK's text bindings (native and the ones synthesized events get), AltGr reports Alt, Windows' caret style in HTML editors. Launch-wide; set it `false` to keep Linux behaviour | `windows-keyboard.patch`, launcher |
| Linux behaviour defaults | middle click pastes the primary selection, double-click selects no trailing space, instant fullscreen, GTK scrollbar clicks | Windows' defaults (`windowsBehaviourPrefs` in `launcher-constants.json`) | launcher |
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

- `browser/tests/ucrt-math/expected.u64.xz` is what `ucrtbase.dll`
  10.0.22621.3593 (Windows 10.0.22621, FMA3 path) returns for every input in
  `inputs.py`, written by `record.py` with its provenance in `provenance.json`.
  It depends only on the CRT, not on Firefox.
- `browser/tests/playwright/patches/assets/windows-crt-math.json` is what stock
  Firefox 152.0.4 on Windows returned for a sample of those inputs, cold,
  JIT-hot and constant-folded, written by `record_firefox.py`. Upstream is now
  158.0, and the file was not re-recorded, because nothing that decides these
  results changed between 152.0.4 and 158.0: SpiderMonkey's sin, cos, tan and
  `ecmaPow` (158 sends the libm call through `pow_libm_or_fdlibm`, which is
  `std::pow` everywhere but ARM Android at API 28 and below), the JIT's paths
  to them (the CacheIR emitters, Ion's code generation and folding for
  `MathFunction`, `Pow` and `PowHalf`), constant folding, and the Windows
  default of `javascript.options.use_fdlibm_for_sin_cos_tan` (false). NaN
  results keep their sign as before: 152's `Value::setDouble` stored a NaN as
  the CRT returned it, and 158's Math natives and `**` store their results with
  the `AssumeCanonicalNaN` setters, which do the same, so the 399 pow results
  recorded as `fff8000000000000` still read back so. Re-record on the pinned
  version when an update touches any of these.
