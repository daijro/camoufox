# Host parity: a Windows identity on a Linux host

The Linux build is meant to pass for Firefox on the OS it claims. Measured
against stock Firefox on Windows 10 and on Linux, some answers still came from
the host. This lists each one, what a page reads, and how it is closed.

| Tell (before) | What the page read | Fix | Where |
|---|---|---|---|
| Math from the host's libm | `Math.sin/cos/tan/pow` differ from Windows in the last bit (sin 22, cos 26, tan 30 of 1,670 inputs; pow 45 of 1,410) | the algorithms the Windows CRT uses (`javascript.options.use_ucrt_math`): Tang's table-driven log and exp for pow, Cody-Waite and Payne-Hanek reduction with AMD LibM's kernels for sin/cos/tan, tables generated from their definitions (`browser/scripts/gen-ucrt-math-tables.py`); checked bit for bit against outputs recorded from `ucrtbase.dll` (`browser/tests/ucrt-math/`) and from Windows Firefox | `windows-crt-math.patch`, launcher |
| GTK keyboard | Ctrl+Up in `<textarea>` moved up a line (Windows: line start); Alt+Backspace no undo; Shift+Delete with nothing selected did nothing; Ctrl+/ selected all; AltGr `keyCode` 225 (Windows: 18); Ctrl+Backspace on a rich-text selection deleted only the selection | `input:windowsKeyboard`: Windows' shortcut tables replace GTK's text bindings (native and the ones synthesized events get), AltGr reports Alt, Windows' caret style in HTML editors. Launch-wide; set it `false` to keep Linux behaviour | `windows-keyboard.patch`, launcher |
| Linux behaviour defaults | middle click pastes the primary selection, double-click selects no trailing space, instant fullscreen, unstyled `<select>` popups, GTK scrollbar clicks | Windows' defaults (`windowsBehaviourPrefs` in `launcher-constants.json`) | launcher |
| Scrollbars from the host theme | a Windows 10 identity's classic scrollbars 12 px (GTK's); stock Windows 17 px | Windows' non-native scrollbars (`widget.non-native-theme.scrollbar.style` 4 or 5, following `ui.useOverlayScrollbars`) at Windows' size | launcher |

These apply only when the identity claims Windows and the host is not Windows;
on a Windows host the build already behaves this way. Every default yields to a
value the caller sets.

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
  recorded as `fff8000000000000` still read back so. Re-record on the pinned version when an update touches
  any of these.
