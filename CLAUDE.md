# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Camoufox?

Camoufox is an **open-source anti-detect browser** built on Firefox with robust fingerprint injection capabilities. Unlike competitors that use JavaScript injection, Camoufox intercepts fingerprinting at the **C++ implementation level**, making spoofed properties undetectable through JavaScript inspection.

**Key differentiators:**
- **Firefox-based** (not Chromium): Juggler operates at a lower level than CDP, more resistant to JS leaks, better fingerprinting resistance research
- **No JS injection**: All fingerprint spoofing happens in C++ before JavaScript can observe it
- **Crowdblending**: Uses BrowserForge for statistical fingerprint distribution matching real traffic
- **Proven stealth**: Passes DataDome, Cloudflare, Imperva, reCaptcha with high scores
- **Open core**: Most code is public; some advanced features (canvas rotation) are closed-source to prevent reverse engineering by bot detection providers

**Use case**: Web scraping, automation, and testing that requires avoiding bot detection systems while maintaining indistinguishable browser fingerprints.

## Critical Context: Dual Repository Structure

**Camoufox uses TWO git repositories:**

1. **Outer Repo** (`/home/azureuser/camoufox/`): Tracks patches, scripts, docs, Makefile
2. **Inner Repo** (`camoufox-142.0.1-bluetaka.25/`): Firefox source code with full git history

The inner repo is **NOT** a submodule. It's a standalone Firefox git repository cloned from the exact commit that Playwright targets. This enables `git log`, `git blame`, and `git diff` on Firefox code to understand upstream changes.

## Repository Philosophy: Git-Based vs Tarball

**CRITICAL:** This repo uses Playwright's exact Firefox git commit, not Mozilla's release tarballs. This provides full Firefox git history for debugging upstream changes.

**Key implications:**
- `make refresh-baseline` ONLY works with git repo approach (requires `unpatched^` parent)
- `make setup` is INCOMPATIBLE with git repo approach (destroys Firefox history)
- When fixing `additions/`, use `make refresh-baseline` to update the baseline

**For details, see [FIREFOX_UPGRADE_WORKFLOW.md](FIREFOX_UPGRADE_WORKFLOW.md)**

## Essential Commands

```bash
# Patch workflow
make revert                              # Start fresh from baseline
make patch patches/foo.patch             # Apply single patch
make dir                                 # Apply all patches
make tagged-checkpoint                   # Save checkpoint
make revert-checkpoint                   # Return to checkpoint
python3 scripts/next_patch.py <patch>    # Find next patch alphabetically

# Building & running
make bootstrap                           # Bootstrap build environment (first time)
make build                               # Build Firefox
make run                                 # Run built browser
make run args="--headless https://..."   # Run headless

# Additions management
make refresh-baseline                    # Rebuild 'unpatched' tag with updated additions/

# Development
make edits                               # Open developer UI (patch manager)
make edit-cfg                            # Edit camoufox.cfg
make ff-dbg                              # Setup vanilla Firefox for debugging

# Release
python3 multibuild.py --target linux windows macos --arch x86_64 arm64
```

**See [WORKFLOW.md](WORKFLOW.md) for detailed patch workflow instructions.**

## Architecture Overview

### Three-Layer Design

**Every patch exists to prevent bot detection.** Camoufox's architecture ensures fingerprints are spoofed before JavaScript can observe them:

#### Layer 1: MaskConfig System (`additions/camoucfg/`)
Header-only C++ system that injects spoofing config at compile time. Firefox's internal APIs read from MaskConfig instead of real system values. Enables spoofing:
- Navigator (userAgent, platform, hardwareConcurrency, languages, etc.)
- Screen/window dimensions, devicePixelRatio
- WebGL (renderer, vendor, parameters, extensions, shader precision)
- AudioContext (sampleRate, outputLatency, maxChannelCount)
- Geolocation, timezone, locale, Intl
- Battery API, voices, media devices

**Key insight:** Firefox's C++ code reads spoofed values from MaskConfig headers, so JavaScript sees spoofed properties natively—no runtime injection required.

#### Layer 2: Juggler (`additions/juggler/`)
Custom Playwright protocol for Firefox. Forked from Puppeteer/Juggler with critical patches:
- Sandboxed page agent JS (invisible to page context)
- No frame execution context leaks
- `navigator.webdriver` fixed
- Component registration compatible with modern Firefox (e.g., `external: False` for Firefox 142+)

**Why not CDP?** Juggler operates at a lower level than Chrome DevTools Protocol, making it harder to detect through JavaScript inspection.

#### Layer 3: Patches (`patches/`)
Applied in **alphabetical filename order** (not directory structure). Categories:
- **Fingerprint spoofing**: `webgl-spoofing.patch`, `font-hijacker.patch`, `audio-context-spoofing.patch`, `geolocation-spoofing.patch`
- **Stealth fixes**: `force-default-pointer.patch` (headless pointer detection), `shadow-root-bypass.patch`, `disable-remote-subframes.patch`
- **Debloat/optimizations**: LibreWolf patches, `no-css-animations.patch`, telemetry removal
- **Playwright integration**: `patches/playwright/*.patch` (bootstrap, leak fixes)

**Critical rule:** Patches apply alphabetically. If B depends on A, A's filename must come first.

## Fixing Broken Patches (Critical Workflow)

**Rule #1:** NEVER delete a patch without understanding its stealth goal.

When a patch fails, you MUST:
1. **Understand stealth intent**: What fingerprinting vector or bot detection does this prevent?
2. **Determine why it failed**: File moved? Code refactored? API changed?
3. **Find new location**: Search Firefox git history to see where code moved
4. **Replicate stealth goal**: Achieve same protection in new Firefox architecture

**Example stealth goals:**
- `remove-cfrprefs.patch`: Hide CFR recommendation checkboxes (disabled in camoufox.cfg but still visible = detectable mismatch)
- `force-default-pointer.patch`: Report "fine" pointer even in headless (prevents headless detection)
- `webgl-spoofing.patch`: Make MaskConfig take precedence over Firefox's RFP for WebGL (avoids fingerprint inconsistencies)

### Regenerating a Patch:
```bash
# 1. Fix code in Firefox source (inner repo)
cd camoufox-142.0.1-bluetaka.25
vim browser/components/preferences/main.js  # Fix the code

# 2. Verify ALL hunks from original patch are recreated
git status && git diff  # Does this match the original patch's intent?

# 3. Generate new patch (ENTIRE repo diff, not selective!)
git diff > ../patches/remove-cfrprefs.patch

# 4. Test it applies cleanly
cd .. && make revert-checkpoint && make patch patches/remove-cfrprefs.patch

# 5. Commit to outer repo
git add patches/remove-cfrprefs.patch
git commit -m "Fix remove-cfrprefs for FF142 JS config migration"
```

**See [WORKFLOW.md](WORKFLOW.md) for detailed investigation guidelines and examples.**

## Common Gotchas

1. **Alphabetical patch order**: Patches apply by filename sort order (not directory). Dependencies must be encoded in filenames.

2. **Offset vs FAILED hunk**:
   - Offset/fuzz = patch applied but line numbers shifted (usually safe)
   - FAILED hunk = patch could not apply (MUST investigate stealth intent)

3. **Component registration (Firefox 142+)**: Components with `categories` + `constructor` + no `headers` default to `external: True`, which can't have constructors. Fix: `"external": False` in components.conf.

4. **Additions vs patches**:
   - **Additions** (`additions/`): Copied at baseline creation (`unpatched` tag)
   - **Patches** (`patches/`): Applied after baseline
   - If you modify `additions/`, run `make refresh-baseline` to update baseline

5. **Two git repos**: Changes to Firefox source go in inner repo (for generating patches). Changes to patch files go in outer repo (for version control).

## Firefox Upgrade Process

**High-level steps** (see [FIREFOX_UPGRADE_WORKFLOW.md](FIREFOX_UPGRADE_WORKFLOW.md) for details):

1. Find Playwright's target commit from `browser_patches/firefox/UPSTREAM_CONFIG.sh` (use release branch)
2. Clone that exact Firefox commit with git history
3. Copy additions, commit, tag as `unpatched`
4. Apply patches with `make dir`, fix breaks one-by-one
5. Document changes in upgrade notes

**Why Playwright's commit?** Their patches expect specific line numbers from their commit. Using Mozilla's tarball causes 88+ reject files.

## Key Documentation

- **[FIREFOX_UPGRADE_WORKFLOW.md](FIREFOX_UPGRADE_WORKFLOW.md)**: Why git-based approach, how `refresh-baseline` works, repo-in-repo structure
- **[WORKFLOW.md](WORKFLOW.md)**: Patch investigation process, stealth intent analysis, checkpoint workflow
- **[FIREFOX_142_UPGRADE_NOTES.md](FIREFOX_142_UPGRADE_NOTES.md)**: Version-specific changes and patch fixes
- **[README.md](README.md)**: User-facing documentation (fingerprint injection, features, testing sites)
- **`Makefile`**: Build system targets and their purposes

## Testing & Validation

After fixes, validate against bot detection systems:
```bash
make tests  # Run automated Playwright tests
make build && make run  # Manual testing
```

**Production testing sites:**
- WAFs: DataDome, Cloudflare (Turnstile/Interstitial), Imperva
- Fingerprinting: CreepJS, BrowserScan, Browserleaks
- Scores: reCaptcha (target: 0.9+), Incolumitas (0.8-1.0)