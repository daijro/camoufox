# Host parity: a Windows identity on a Linux host

The Linux build is meant to pass for Firefox on the OS it claims. Measured
against stock Firefox on Windows 10 and on Linux, some answers still came from
the host. This lists each one, what a page reads, and how it is closed.

| Tell (before) | What the page read | Fix | Where |
|---|---|---|---|
| Math from the host's libm | `Math.sin/cos/tan/pow` differ from Windows in the last bit (sin 22, cos 26, tan 30 of 1,670 inputs; pow 45 of 1,410) | the Windows CRT's own algorithms (`javascript.options.use_ucrt_math`), checked bit for bit against `ucrtbase.dll` (`browser/tests/ucrt-math/`) and Windows Firefox | `windows-crt-math.patch`, launcher |
| GTK keyboard | Ctrl+Up in `<textarea>` moved up a line (Windows: line start); Alt+Backspace no undo; Shift+Delete with nothing selected did nothing; Ctrl+/ selected all; AltGr `keyCode` 225 (Windows: 18); Ctrl+Backspace on a rich-text selection deleted only the selection | `input:windowsKeyboard`: Windows' shortcut tables replace GTK's text bindings (native and the ones synthesized events get), AltGr reports Alt, Windows' caret style in HTML editors. Launch-wide; set it `false` to keep Linux behaviour | `windows-keyboard.patch`, launcher |
| Linux behaviour defaults | EME off ("EME has been preffed off"), middle click pastes the primary selection, double-click selects no trailing space, instant fullscreen, unstyled `<select>` popups, GTK scrollbar clicks | Windows' defaults (`windowsBehaviourPrefs` in `launcher-constants.json`) | launcher |
| Scrollbars from the host theme | a Windows 10 identity's classic scrollbars 12 px (GTK's); stock Windows 17 px | Windows' non-native scrollbars (`widget.non-native-theme.scrollbar.style` 4 or 5, following `ui.useOverlayScrollbars`) at Windows' size | launcher |

These apply only when the identity claims Windows and the host is not Windows;
on a Windows host the build already behaves this way. Every default yields to a
value the caller sets.
