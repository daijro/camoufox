# Firefox 142 Upgrade Notes

## Current Status

✅ **Fixed Patches:**
- `patches/playwright/0-playwright.patch` - Playwright base integration (applied cleanly)
- `patches/playwright/1-leak-fixes.patch` - Stealth fixes (fixed manually, navigator.webdriver + enterprise policies)
- `patches/ghostery/Disable-Onboarding-Messages.patch` - Applied with offset
- `patches/all-addons-private-mode.patch` - Applied with fuzz
- `patches/anti-font-fingerprinting.patch` - Applied with offset
- `patches/audio-context-spoofing.patch` - **FIXED** - Updated for new SPHINX_TREES line in dom/media/moz.build
- `patches/font-hijacker.patch` - **FIXED** - Updated for Firefox 142 build system changes (CONFIGURE_SUBST_FILES block removed from layout/style/moz.build)
- `patches/force-default-pointer.patch` - Applied with 23-line offset (forces browser to always report fine pointer capabilities)
- `patches/geolocation-spoofing.patch` - **FIXED** - Updated for Firefox 142 GTK configuration block changes and corrected LOCAL_INCLUDES alphabetical ordering ("/camoucfg" must come before "/dom/base" and "/dom/ipc") in dom/geolocation/moz.build
- `patches/global-style-sheets.patch` - Applied with 20-line offset
- `patches/librewolf/ui-patches/handlers.patch` - Applied cleanly (removes 190 lines of default handlers)
- `patches/librewolf/ui-patches/hide-default-browser.patch` - Applied with 6-line offset
- `patches/locale-spoofing.patch` - Applied with fuzz 2 and 22-line offset (implements locale spoofing)
- `patches/media-device-spoofing.patch` - Applied with 3-line offset
- `patches/librewolf/mozilla_dirs.patch` - Applied with fuzz and offsets (modifies Mozilla directory paths)
- `patches/network-patches.patch` - Applied with significant offsets (25-153 lines)
- `patches/no-css-animations.patch` - Applied with 1-line offsets (disables/modifies CSS animations)
- `patches/no-search-engines.patch` - **FIXED** - Updated for Firefox 142 UrlbarProviderInterventions.sys.mjs line number shifts
- `patches/pin-addons.patch` - Applied with significant offsets (937 and 163 lines)
- `patches/librewolf/ui-patches/remove-branding-urlbar.patch` - Applied with 203-line offset

- `patches/librewolf/ui-patches/remove-cfrprefs.patch` - **FIXED** - Updated for Firefox 142 dynamic settings system (removes CFR preferences from main.js config)
- `patches/librewolf/ui-patches/remove-organization-policy-banner.patch` - Applied with 8-line offset
- `patches/camoufox-branding.patch` - Added new patch to fix the MOZ_APP_VENDOR, MOZ_APP_PROFILE build error by adapting to Firefox 142's configuration system changes (Bug 1898177), following the "broken patch" workflow for creating patches.
- `patches/webgl-spoofing.patch` - **FIXED** - Added explicit `static_cast<uint8_t>()` casts for GetShaderPrecisionFormat to fix narrowing conversion errors (Firefox 142 changed ShaderPrecisionFormat fields to uint8_t while MaskConfig returns int32_t)

✅ **Removed/Obsolete Patches:**
- `patches/librewolf/sed-patches/allow-searchengines-non-esr.patch` - **DELETED** - Firefox 142 natively supports SearchEngines in non-ESR builds (Bug 1961839, April 2025)
- `patches/librewolf/remove_addons.patch` - **DELETED** - LibreWolf privacy patch that conflicts with Camoufox stealth mission (removing "Report Broken Site" makes browser detectably different from vanilla Firefox).  Plus the entire subsystem in firefox has changed and updating to that is out of scope for this mission.
❌ **Remaining Patches (need testing):**
- All other Camoufox patches (40 remaining - testing in progress)

**Next Step:** Continue testing remaining patches with `make dir`.

## The Problem

Playwright's `bootstrap.diff` patch for Firefox 142.0.1 is designed for a specific git commit from the Firefox GitHub mirror, **NOT** Mozilla's official release tarball.

- **Mozilla's tarball**: `https://archive.mozilla.org/pub/firefox/releases/142.0.1/source/firefox-142.0.1.source.tar.xz`
- **Playwright's source**: GitHub mirror commit `361373160356d92cb5cd4d67783a3806c776ee78`

Even though both are "Firefox 142.0.1", they're slightly different, causing **88 reject files** when applying Playwright's patch to Mozilla's tarball.

## The Solution

**Use Playwright's exact Firefox source** instead of Mozilla's tarball.

### What We Did

1. **Cloned Playwright's exact Firefox commit:**
   ```bash
   git clone --filter=blob:none --no-checkout git@github.com:mozilla-firefox/firefox.git camoufox-142.0.1-bluetaka.25
   cd camoufox-142.0.1-bluetaka.25
   git checkout 361373160356d92cb5cd4d67783a3806c776ee78
   ```

2. **Created the `unpatched` tag** (for `make revert`):
   ```bash
   git tag -a unpatched -m "Initial commit"
   ```

3. **Copied Camoufox additions** (spices & herbs):
   ```bash
   bash ../scripts/copy-additions.sh 142.0.1 bluetaka.25
   ```

4. **Committed additions and updated tag:**
   ```bash
   git add -A
   git commit -m "Add Camoufox additions"
   git tag -f -a unpatched -m "Initial commit with additions"
   ```

5. **Applied patches:**
   ```bash
   make dir  # Should now work cleanly with Playwright's patch
   ```

## Why This Works

- Playwright's `bootstrap.diff` expects specific line numbers and code structure from their exact commit
- By using the same source Playwright uses, the patch applies cleanly (no rejects)
- The other Camoufox patches (fingerprinting, spoofing, etc.) still apply fine since they target Firefox APIs, not specific line numbers

## The Trade-off

**Normal approach (what Camoufox used before):**
- Download Mozilla's official tarball
- Manually fix patch conflicts when upgrading
- More work, but using "official" Firefox releases

**Our approach (what we're doing now):**
- Use Playwright's git commit
- Patches apply cleanly
- Less work, but using GitHub mirror instead of Mozilla's official source

## Finding the Right Commit

For future upgrades, find Playwright's Firefox commit:

1. Check Playwright's `UPSTREAM_CONFIG.sh`:
   ```bash
   curl -s https://raw.githubusercontent.com/microsoft/playwright/release-1.XX/browser_patches/firefox/UPSTREAM_CONFIG.sh
   ```

2. Look for `BASE_REVISION`:
   ```
   REMOTE_URL="https://github.com/mozilla-firefox/firefox"
   BASE_BRANCH="release"
   BASE_REVISION="<COMMIT_HASH_HERE>"
   ```

3. Use that commit hash when cloning.

## Backup Plan

If this approach causes issues, we still have:
- **Backup directory**: `camoufox-142.0.1-bluetaka.25.bak` (Mozilla tarball source)
- **Downloaded tarball**: `firefox-142.0.1-playwright.tar.gz` (Playwright's commit as tarball)
- Can go back to manual patch fixing if needed

## Understanding the Dual-Repo Structure

**Camoufox uses TWO git repositories:**

1. **Camoufox Project Repo** (outer repo at `/home/azureuser/camoufox/`)
   - Contains: patches, scripts, Makefile, documentation
   - `.git/` tracks: patch files, build scripts, configuration
   - **Commit patch changes here** after fixing them

2. **Firefox Source Repo** (inner repo at `camoufox-142.0.1-bluetaka.25/`)
   - Contains: Firefox source code
   - `.git/` tracks: Firefox code + Camoufox additions
   - Used for: generating patches via `git diff`, reverting with `make revert`

**Key workflow:**
- Fix broken Firefox files → `cd camoufox-142.0.1-bluetaka.25 && git diff > ../patches/foo.patch`
- Commit the patch file → `cd .. && git add patches/foo.patch && git commit`

## Patch Application Workflow

For the general workflow of applying patches, fixing broken patches, and using checkpoints, see [WORKFLOW.md](../WORKFLOW.md).

The following sections document Firefox-specific upgrade challenges and solutions.

## Firefox Upgrade Challenges

When upgrading Firefox versions, patches often fail due to Firefox code changes. Here are the common patterns and solutions:

### Example: Firefox 142 Font Hijacker Patch Fix

The `font-hijacker.patch` failed in Firefox 142 because Firefox removed the `CONFIGURE_SUBST_FILES` block from `layout/style/moz.build` in commit `0d9b7da75a8a` (Bug 1950258).

**Problem:** The patch expected to add `LOCAL_INCLUDES += ["/camoucfg"]` after the `CONFIGURE_SUBST_FILES` block at line 351, but that block no longer exists.

**Solution:** Updated the patch to add the includes after the `CbindgenHeader` block at line 360 instead.

**Investigation Steps:**
1. Patch failed on `layout/style/moz.build` hunk
2. Checked git history: `git log --oneline layout/style/moz.build`
3. Found commit `0d9b7da75a8a` that removed `CONFIGURE_SUBST_FILES` block
4. Manually fixed source code to add includes at new location
5. Regenerated patch with `git diff > ../patches/font-hijacker.patch`
6. Tested fix by reverting to checkpoint and reapplying patch

### Example: Firefox 142 No Search Engines Patch Fix

The `no-search-engines.patch` failed in Firefox 142 because the line numbers in `browser/components/urlbar/UrlbarProviderInterventions.sys.mjs` had shifted.

**Problem:** The patch expected the `isActive` method's `if` condition to start at line 494, but Firefox 142 had the condition starting at line 491, causing the patch to fail when trying to modify line 494.

**Solution:** Updated the patch to modify the correct line where the `if (` statement begins, changing it to `if (true ||` to make the provider always active.

**Investigation Steps:**
1. Patch failed on `browser/components/urlbar/UrlbarProviderInterventions.sys.mjs` hunk at line 494
2. Examined the reject file showing the expected change from `if (` to `if (true ||`
3. Found the actual `if (` statement was at line 491, not 494
4. Manually changed the condition to `if (true ||` to make the provider always active
5. Verified the second hunk in `toolkit/components/search/SearchEngineSelector.sys.mjs` applied successfully
6. Regenerated patch with `git diff > ../patches/no-search-engines.patch`
7. Tested fix by reverting to checkpoint and reapplying patch

### Common Patch Failure Causes

1. **Firefox API Changes**: Functions move, get renamed, or change signatures
2. **Component Registration Changes**: Firefox migrates from explicit initialization to category-based registration
3. **File Structure Changes**: Files move or get reorganized
4. **Feature Obsolescence**: Firefox implements features natively, making patches redundant

### Patch Investigation Steps

When a patch fails:

1. **Review the patch intent** - understand what it's trying to accomplish
2. **Search Firefox git history** - look for commits that changed the relevant code
3. **Check Mozilla Bugzilla** - see if features became native
4. **Test alternative approaches** - the same goal might be achievable differently

### Example: Firefox 142 Component Migration

In Firefox 142, many components migrated from explicit initialization to category-based registration. Patches trying to remove `lazy.Component.init()` calls failed because Firefox removed those calls entirely.

**Solution**: Update patches to remove component registrations from `BrowserComponents.manifest` instead.

## When Deleting Obsolete Patches

If a patch is obsolete (Firefox now has the feature natively):

```bash
# VERIFY what the patch does before deleting
cat patches/path/to/patch.patch  # Review all hunks!

# Check Firefox changelog/bugs to confirm it's truly obsolete
# Example: Bug 1961839 added SearchEngines support natively

# Delete the patch
rm patches/path/to/patch.patch

# Commit the deletion with explanation
git add patches/path/to/patch.patch
git commit -m "Remove obsolete patch - Firefox now has this natively (Bug XXXXX)"
```

For Makefile commands and general patch workflow, see [WORKFLOW.md](../WORKFLOW.md).

## Example: Firefox Build System Changes

When upgrading Firefox, build system changes often break patches. For example, the `audio-context-spoofing.patch` failed in Firefox 142 because the build system added a new `SPHINX_TREES` line to `dom/media/moz.build`.

**Investigation**: The patch added `LOCAL_INCLUDES += ['/media/audio']` but Firefox 142 inserted a new line that shifted all the context, breaking the patch.

**Solution**: Updated the patch context to match the new Firefox 142 build file structure.

**General Pattern**: When patches fail on build files (`.mozbuild`, `Makefile.*`, etc.), always check if Firefox added/removed/changed lines that affect the patch context.

## Related Issues

- GitHub issue #230: Playwright 1.51 breaks with "method 'Browser.setContrast' is not supported"
- This is why the previous maintainer merged Playwright patches in March 2025

- `patches/librewolf/rust-gentoo-musl.patch` - Applied with fuzz 1 and 8-line offset
- `patches/screen-hijacker.patch` - Applied with offsets (screen fingerprinting spoofing)
- `patches/shadow-root-bypass.patch` - Applied with -3-line offset
- `patches/librewolf/sed-patches/stop-undesired-requests.patch` - Applied with fuzz and offsets
- `patches/timezone-spoofing.patch` - Applied with -2-line offset (timezone fingerprinting spoofing)
- `patches/librewolf/urlbarprovider-interventions.patch` - Applied with -5-line offset
- `patches/voice-spoofing.patch` - Applied cleanly (Web Speech API voice spoofing)
- `patches/webgl-spoofing.patch` - **FIXED** - Updated for Firefox 141 RFP WebGL changes (MaskConfig takes precedence over RFP)
- `patches/webrtc-ip-spoofing.patch` - Applied (WebRTC IP spoofing)
- `patches/windows-theming-bug-modified.patch` - Applied (Windows theming and branding modifications)
