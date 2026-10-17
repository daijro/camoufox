# Host parity: a Windows identity on a Linux host

The Linux build is meant to pass for Firefox on the OS it claims. Measured
against stock Firefox on Windows 10 and on Linux, some answers still came from
the host. This lists each one, what a page reads, and how it is closed.

| Tell (before) | What the page read | Fix | Where |
|---|---|---|---|
| Math from the host's libm | `Math.sin/cos/tan/pow` differ from Windows in the last bit (sin 22, cos 26, tan 30 of 1,670 inputs; pow 45 of 1,410) | the Windows CRT's own algorithms (`javascript.options.use_ucrt_math`), checked bit for bit against `ucrtbase.dll` (`browser/tests/ucrt-math/`) and Windows Firefox | `windows-crt-math.patch`, launcher |

These apply only when the identity claims Windows and the host is not Windows;
on a Windows host the build already behaves this way. Every default yields to a
value the caller sets.
