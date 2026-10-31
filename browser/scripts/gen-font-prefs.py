#!/usr/bin/env python3
"""Write python/src/camoufox/font-prefs.json: the font.* defaults stock Firefox
ships on each OS, read from modules/libpref/init/all.js.

A Linux build only compiles Linux's defaults, so an identity claiming Windows
or macOS resolves generics and per-language fonts the Linux way (Thai 'serif'
went through fontconfig where Windows names Tahoma; emoji to Noto Color Emoji
where Windows names Segoe UI Emoji). The launcher applies the claimed OS's
values from this file.

all.js selects per-OS values with #ifdef blocks; they are evaluated here for
each OS's defines. Regenerate on a Firefox bump:

    python3 browser/scripts/gen-font-prefs.py <all.js of that release>
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "python" / "src" / "camoufox" / "font-prefs.json"

DEFINES = {
    "windows": {"XP_WIN", "MOZ_WIDGET_WINDOWS"},
    "macos": {"XP_UNIX", "XP_MACOSX", "MOZ_WIDGET_COCOA"},
    "linux": {"XP_UNIX", "XP_LINUX", "MOZ_WIDGET_GTK"},
}

_DIRECTIVE = re.compile(r"#(ifdef|ifndef|if|elif|else|endif)\b\s*(.*?)\s*(//.*)?$")
_PREF = re.compile(r'\s*pref\(\s*"(font\.[^"]+)"\s*,\s*(.+?)\s*\)\s*;')


def evaluate(expr, defines):
    # Channel comparisons (MOZ_UPDATE_CHANNEL != release) guard no font prefs.
    if "==" in expr or "!=" in expr:
        return False
    expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: "1" if m.group(1) in defines else "0", expr)
    expr = re.sub(r"\b([A-Z_][A-Z0-9_]*)\b", lambda m: "1" if m.group(1) in defines else "0", expr)
    expr = expr.replace("&&", " and ").replace("||", " or ").replace("!", " not ")
    return bool(eval(expr, {"__builtins__": {}}))


def value(raw):
    if raw.startswith('"'):
        return json.loads(raw)
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    raise ValueError(f"unexpected font pref value {raw!r}")


def font_prefs(all_js, defines):
    prefs = {}
    stack = []  # [active, a branch was taken, parent active]
    active = True
    for line in all_js.splitlines():
        directive = _DIRECTIVE.match(line.strip())
        if directive:
            kind, arg = directive.group(1), directive.group(2)
            if kind in ("ifdef", "ifndef", "if"):
                if kind == "ifdef":
                    cond = arg in defines
                elif kind == "ifndef":
                    cond = arg not in defines
                else:
                    cond = evaluate(arg, defines)
                stack.append([active and cond, cond, active])
            elif kind == "elif":
                top = stack[-1]
                cond = not top[1] and evaluate(arg, defines)
                top[0] = top[2] and cond
                top[1] = top[1] or cond
            elif kind == "else":
                top = stack[-1]
                top[0] = top[2] and not top[1]
                top[1] = True
            else:
                stack.pop()
            active = stack[-1][0] if stack else True
            continue
        if active:
            pref = _PREF.match(line)
            if pref:
                prefs[pref.group(1)] = value(pref.group(2))
    return prefs


def main():
    all_js = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = {os_name: font_prefs(all_js, defines) for os_name, defines in DEFINES.items()}
    if not all(out.values()):
        sys.exit("no font prefs found for some OS -- not an all.js?")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{OUT}: " + ", ".join(f"{k} {len(v)}" for k, v in out.items()))


if __name__ == "__main__":
    main()
