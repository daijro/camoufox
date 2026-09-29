# Bundled fonts: what ships, what is reported, how to verify

Camoufox ships its own fonts so that font enumeration and text rendering are a
property of the *claimed* OS rather than of the host. There are two halves: a
font bundle (`bundle/fonts/`) and one fontconfig per OS
(`bundle/fontconfig/<os>/fonts.conf`). The data the launcher draws from
(`pythonlib/camoufox/fonts.json`, `font-bases.json`, `font-groups.json` and the
`_ESSENTIAL_FONTS_*` / `_BASE_VARIANT_FONTS_*` / `_*_MARKER_FONTS` constants in
`fingerprints.py`) is generated against that bundle and must be regenerated with
it.

## Getting the bundle

The bundle is **a release asset, not repo content** — 1513 faces, 2.16 GB
extracted, 843 MB as `.tar.xz`. It cannot live in git: GitHub caps a tracked
file at 100 MiB (`Apple Color Emoji.ttc` alone is 183 MiB) and an `.xz` archive
cannot be delta-compressed, so every font update would append another ~843 MB
blob to history forever. Release assets allow 2 GB per file, which fits the
whole bundle with no splitting and no LFS. It is the same trust model the build
already uses for the Firefox source itself.

```
make fetch-fonts     # download + verify the archive (bundle/fonts-bundle-*.tar.xz)
make fonts-extract   # ...and unpack it to bundle/fonts/   (gitignored)
make fonts-check     # verify the archive against the pin; non-zero if absent
make fonts-clean     # drop the extracted tree
```

`scripts/data/font-bundle.json` pins the tag, asset name, size and **sha256**,
so a given commit expects one exact bundle and a truncated or substituted
download fails loudly instead of silently producing a browser that reports fonts
it cannot draw. `make fonts-extract` stamps the unpacked tree with that sha256
(`bundle/fonts/.bundle-sha256`), so re-running it is free — which is what lets
`package-*` and `stage-fonts` depend on it unconditionally.

The asset is hosted by this repository, never by a fork: a build input that
lives in someone's personal account breaks the moment that account renames the
repo or deletes the release.

Publishing a new bundle: rebuild the archive, `python3 scripts/fetch-fonts.py
--write-spec <archive> --tag font-bundle-vN`, then upload it under that tag.
Font-bundle tags do not match `release.yml`'s `vX.Y.Z` trigger, so they do not
start a release, and they carry no `manifest.json`, so no library pairs with them.

## Layout: each face stored once

A face used by several OSes is stored **once**, in a directory named for the set
of OSes that use it. `bundle/fonts/groups.json` records which groups each OS
reads.

| group | faces | read by |
|-------|------:|---------|
| `LMW` | 328 | all three |
| `LM`  |  92 | Linux + macOS |
| `LW`  |  71 | Linux + Windows |
| `MW`  |  48 | macOS + Windows |
| `L`   | 301 | Linux only |
| `M`   | 311 | macOS only |
| `W`   | 362 | Windows only |

An OS reads the four groups its letter appears in: Linux `L+LM+LMW+LW` (792
faces), macOS `LM+LMW+M+MW` (779), Windows `LMW+LW+MW+W` (809). Storing a full
copy per OS instead made 41% of the bundle byte-identical duplicates (2955 files
/ 3.96 GB became 1513 / 2.16 GB) while leaving every OS's set unchanged.

Every package ships **all seven groups**, so the fingerprint is built from the
fonts actually available. What differs is how they are gated:

- **Linux packages** keep the group subdirectories and `groups.json`.
  `utils._generate_fontconfig` reads it at launch and hands fontconfig one
  `<dir>` per group the claimed OS reads. The parent is never named, because
  fontconfig scans `<dir>` **recursively** — naming it would put every other
  OS's faces on the search path.
- **macOS and Windows packages** flatten the groups into one directory: CoreText
  and DirectWrite activate a single directory and cannot read subfolders. There
  is no directory gate on those hosts; the allowlist in
  `patches/font-hijacker.patch` is what restricts a lookup. Basenames therefore
  must not collide within a package's group set, which `verify-fonts.py` checks.

This replaced the 455 `<glob>` duplicate-face rejects the Windows fontconfig used
to carry. They were redundant under grouping and also unsound: 114 bundled
filenames contain `[ ]` (e.g. `ReemKufi[wght].ttf`), which fontconfig parses as a
character class, so those rejects silently matched nothing.

## The two invariants

**1. Everything reported must be renderable.** Every family the launcher may
report for an OS must be one the packaged browser can draw under that OS's
bundled fontconfig. `font-hijacker.patch` prunes lookups by family name *after*
fontconfig substitution, so a reported name fontconfig cannot resolve measures
as the fallback — a **reverse leak**. The old `fonts.json[mac]` carried 70 such
names (Hiragino etc.); the current lists carry none.

**2. Nothing outside an OS's groups may be reachable.** The converse, and the
one the group layout exists to enforce: a Windows identity must not be able to
render a macOS-only face, or an emoji/CJK glyph can fall back to Segoe UI Emoji
or PingFang on a machine claiming Linux. No reported name reveals this, and no
draw test can see it — it is checked directly, by asking fontconfig for every
file it can reach under each OS's conf and requiring all of them to sit inside
that OS's own groups (810 / 780 / 793 faces, including browser-shipped
`TwemojiMozilla.ttf`).

The reverse direction of invariant 1 is deliberately loose: an OS renders more
families than it ever reports (529 published vs 335 reported on Windows, 872 vs
567 on macOS, 583 vs 358 on Linux; `gen-fonts-json.py --dump-union` lists the
gap). Those are names a real OS never presents as a family — weight-variant
subfamilies DirectWrite folds into their parent ("Barlow Black"), the bare
`Sitka` / `Segoe UI Variable` umbrella names, and CJK families a stock install
does not report. They stay renderable but unreported.

## How `fonts.json` is derived (`scripts/gen-fonts-json.py`)

```
reportable[os] = fc-scan(the groups <os> reads)          families fontconfig publishes
               + SCAN_FAMILIES                           Sitka * / Segoe UI Variable * (scan-time matches)
               + ALIASES                                 names fonts.conf rewrites to a bundled target
               + SHIPPED_BY_BROWSER                      Twemoji Mozilla (from the Firefox build)
               ∩ names(scripts/data/font-manifests.json) bases + additions + marker fonts for that OS
               + ALIASES, REPORTABLE_EXTRA               forced in
```

Namespace matters here and is easy to get wrong: Windows and macOS enumerate the
**legacy family** (nameID 1), while Linux enumerates through **fontconfig**.
`system_profiler` and WPF report *typographic* families (nameID 16), a different
namespace — a list gathered that way will disagree with what a browser sees.

`--print-bases` prints the OS base lists intersected with the result, which is
what the `_ESSENTIAL_FONTS_*` constants are pasted from. Those constants are the
**intersection** of an OS's bases, never a superset: a name present in only one
version's base must not be forced onto every identity, or that version's base
becomes a no-op.

Regenerate together whenever the bundle changes:

```
python3 scripts/gen-font-groups.py          # font-groups.json + font-bases.json
python3 scripts/gen-fonts-json.py           # fonts.json
python3 scripts/gen-fonts-json.py --print-bases   # paste into fingerprints.py
python3 scripts/verify-fonts.py             # must pass before committing
```

Deliberate choices:

- **Windows aliases are unconditional and always reported.** The 13
  GDI-substitution / Light-Semilight rules (`Courier -> Courier New`,
  `Helvetica -> Arial`, `Calibri Light -> Calibri`, ...) are unconditional in
  `bundle/fontconfig/windows/fonts.conf` because there is no per-launch
  fontconfig hook, and the names are in `_ESSENTIAL_FONTS_WINDOWS`. That matches
  reality: every Windows install resolves all of them.
- **macOS TTC weight names are reported.** The confs rewrite `American
  Typewriter Semibold`, `Futura Bold`, `STIX Two Math Regular`, ... to their base
  family. A real Mac registers those as families but `fc-scan` cannot see them,
  so the ones whose target is bundled are forced in.
- **`Twemoji Mozilla` is reportable on Linux** (a CreepJS Linux marker, and
  Firefox exposes its bundled font to content). Not reported on macOS.
- One name renders for every Linux identity but is not always reported
  (`Noto Sans Canadian Aboriginal Regular`) because a real Ubuntu does not report
  it. `verify-fonts.py` warns rather than fails.

## The per-launch draw (`fingerprints._generate_random_font_subset`)

Modelled on how real machines actually differ: one OS-version base, always whole,
plus independent per-unit draws. Not a uniform percentage of a pool.

1. **One base, drawn by weight, always complete.** A real machine has all of its
   OS defaults, so a base is never sampled.

   | OS | bases (weight / families) |
   |----|---------------------------|
   | Windows | `win11` 1.00 / 125 |
   | macOS | `sonoma` 0.20 / 499 · `tahoe26` 0.65 / 364 · `macos27` 0.15 / 361 |
   | Linux | `ubuntu2404` 0.45 / 257 · `ubuntu2604` 0.55 / 266 |

   Windows 10 was dropped entirely. macOS 27 differs from 26.6.2 by only three
   families and is identified by the *absence* of `Noto Sans Brahmi` /
   `Noto Sans CanAborig`.

2. **The essential floor** (`_ESSENTIAL_FONTS_*`: 125 / 369 / 274) — the
   intersection of that OS's bases, so it holds whichever base was drawn.

3. **Per-unit Bernoulli draws, per OS.** Each addition is one independent
   decision at its own measured probability. `kind: bundle` is atomic — it
   installs whole or not at all. `kind: alacarte` is piecemeal: on a hit, a
   size is drawn from its `sizes` distribution and that many families are taken.
   `requiresLocale` gates a unit on the identity's locale (e.g. `cjk-tc` on
   `zh-TW`).

   | unit | kind | Windows | macOS | Linux |
   |------|------|--------:|------:|------:|
   | `office` | bundle | 0.602 | — | — |
   | `apple-optional` | bundle | — | 0.818 | — |
   | `hololens` | bundle | 0.592 | — | — |
   | `distro-i18n` | bundle | — | — | 0.372 |
   | `libreoffice` | bundle | 0.066 | — | 0.112 |
   | `pan-euro` | bundle | 0.028 | — | — |
   | `cascadia` | bundle | 0.100 | 0.060 | 0.080 |
   | `meslo` | bundle | 0.040 | 0.040 | 0.060 |
   | `cjk-tc` | bundle (`zh-TW`) | 0.900 | — | — |
   | `dev` | à la carte | 0.038 | 0.070 | 0.174 |
   | `web` | à la carte | 0.088 | 0.270 | 0.195 |

   `apple-optional` is one atomic unit rather than base because Apple ships those
   57 faces as optional Font Book downloads, and the fpgen corpus puts all of
   them on exactly 81.8% of Macs.

4. **Marker fonts** appended if missing (`_ensure_marker_fonts`).

Resulting list sizes over 20 draws: 125–281 of 335 (Windows), 369–526 of 567
(macOS), 278–319 of 358 (Linux).

For a **native** identity — the host's own OS — on macOS and Windows the draw
claims the OS base only, because the real system fonts are the right ones there
and `font-hijacker.patch` does not activate the bundle. On a Windows host the
Win11 marker families are *subtracted* when the host cannot render them, rather
than added when it can; claiming a marker the host lacks is the leak.

`pythonlib/tests/test_font_distribution.py` covers this: base
completeness and weights, per-unit probability, bundle atomicity, à-la-carte
sizing, locale gating, determinism, renderable-only, and that the draw actually
varies (distinct lists, no single list dominating). Tolerances are binomial, at
5σ, so they fail on a real shift rather than on noise.

## fontconfig parity

Linux: generics resolve as a stock Ubuntu does (`sans-serif` → Noto Sans,
`serif` → Noto Serif, `monospace` → DejaVu Sans Mono, `cursive` → Z003),
`hintstyle` is `hintslight`, and the stock metric aliases (30-metric-aliases),
49-sansserif, urw-base35 and the non-Latin rule files are merged in stock
`conf.d` order. Windows: `sans-serif` → Arial, `serif` → Times New Roman,
`monospace` → Consolas, `cursive` → Comic Sans MS, plus `MS Shell Dlg 2 ->
Tahoma`, the `Sitka` / `Segoe UI Variable` scan-time instance families and the
alias block above. macOS: Helvetica / Times / Menlo / Apple Chancery / Zapfino.
`system-ui` is left to Gecko, which resolves it itself. The
`<dir prefix="cwd">fonts</dir>` line that `utils.py` rewrites is kept in all
three — `verify-fonts.py` fails if it is missing.

## Verifying

```
python3 scripts/verify-fonts.py          # full: builds a fontconfig cache over the bundle, minutes on first run
python3 scripts/verify-fonts.py --quick  # constants, draws and layout only
cd pythonlib && python3 -m pytest -q -k "font or humanize or launch_environment"
```

The full run checks, per OS: `fonts.json[os]` ⊆ what `fc-list` publishes (aliases
resolved via `fc-match`), no file reachable outside that OS's groups, generics
resolve to a reportable family, essential / variant / marker ⊆ `fonts.json`,
20 draws stay inside `fonts.json`, each face stored exactly once, no subfolders,
and no basename collisions within a package's group set.

## Known residue

- **The Linux base over-claims against the recorded corpus.** A draw reports a
  median ~287 families where real Linux machines in the corpus report ~100. The
  cause is that the bundle ships fontconfig's `30-metric-aliases`, so
  Arial/Times/Courier always resolve and must therefore always be reported.
  Closing it needs either distro base variants or a change to which aliases ship.
- **The macOS base weights (0.20 / 0.65 / 0.15) are estimates.** There is no
  version-share data source behind them, unlike the addition probabilities,
  which are measured. Sonoma's base is inherited and not re-verifiable on
  current hardware.
- **Nothing has been checked in a running browser.** Both invariants above are
  verified at the fontconfig layer, which is the gate on Linux packages. On
  macOS and Windows hosts the gate is the allowlist patch instead, and that has
  not been exercised against the flattened group layout.
