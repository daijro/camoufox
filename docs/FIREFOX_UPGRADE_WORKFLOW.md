# Firefox Upgrade Workflow (Git Repository Method)

## Overview

This documents Cory's git-based workflow for Firefox upgrades, which differs significantly from the original maintainer's tarball-based approach.

**Key Innovation:** Using Firefox's actual git repository instead of Mozilla's release tarballs provides full version control history, making debugging and upgrades significantly easier.

## Why This Approach?

### Original Approach (Tarball-based)

The original Camoufox workflow:
```bash
make fetch        # Downloads tarball
make setup        # Extracts → git init → single commit
```

**Problems:**
- ❌ No Firefox git history to debug upstream changes
- ❌ Can't use `git log` / `git blame` on Firefox code
- ❌ Can't use `git diff` to see what changed between versions
- ❌ Can't use `retag-baseline` to update additions/
- ❌ `unpatched` tag has no parent (first commit in repo)
- ❌ Harder to understand why patches break

### Git Repo Approach (This Workflow)

```bash
git clone firefox-repo
git checkout <playwright-commit>
bash scripts/copy-additions.sh
git commit && git tag unpatched
```

**Benefits:**
- ✅ Full Firefox git history for debugging
- ✅ Can trace Firefox changes between versions with `git log`
- ✅ Can use `git diff OLD_VERSION..NEW_VERSION` to see what changed
- ✅ Can use `make retag-baseline` when fixing additions/
- ✅ `unpatched` tag has a parent (pristine Firefox commit)
- ✅ Better for understanding upstream changes that break patches

## Makefile Limitations & Incompatibilities

The Makefile was designed for the tarball-based setup. **Important assumptions to be aware of:**

### 1. `make setup` - Incompatible with Git Repo Approach

**What it does:**
```makefile
setup: setup-minimal
    cd $(cf_source_dir) && \
        git init -b main && \              # Creates NEW repo
        git add -f -A && \
        git commit -m "Initial commit" && \ # First commit (no parent!)
        git tag -a unpatched -m "Initial commit"
```

**Why it breaks:**
- Runs `git init`, destroying existing Firefox git history
- Creates `unpatched` tag with NO parent commit
- Makes `make retag-baseline` unusable

**Don't use this with git repo approach!**

### 2. `make fetch` - Unnecessary with Git Repo

Downloads Mozilla's tarball. Skip this entirely when using git clone.

### 3. `make retag-baseline` - ONLY Works with Git Repo

```makefile
retag-baseline:
    cd $(cf_source_dir) && \
        git reset --hard unpatched^ && \  # Requires parent commit!
        git clean -dxf
    $(MAKE) copy-additions
    cd $(cf_source_dir) && \
        git add -A && \
        git commit -m "Add Camoufox additions" && \
        git tag -f -a unpatched -m "Initial commit with additions"
```

**Requirements:**
- `unpatched^` must exist (parent of unpatched tag)
- Only works with git repo approach (tarball setup has no parent)
- Will fail loudly if repository structure is incompatible
- Calls `make copy-additions` to sync additions/ and settings/ files

### 4. Other Make Targets - Compatible

These work fine with both approaches:
- ✅ `make dir` - Applies patches
- ✅ `make build` - Builds Firefox
- ✅ `make revert` - Resets to `unpatched` tag
- ✅ `make tagged-checkpoint` - Saves checkpoint
- ✅ `make patch <file>` - Applies individual patch

## Setting Up for a New Firefox Version

### Step 1: Find Playwright's Firefox Commit

Playwright maintains their Firefox patches in their browser_patches directory. To find the exact Firefox commit they target:

**A. Find the Playwright version that supports your target Firefox version**

```bash
# Check Playwright's browsers.json for Firefox version support
curl -s 'https://raw.githubusercontent.com/microsoft/playwright/main/packages/playwright-core/browsers.json' \
    | grep -A 5 -B 5 '"firefox"'

# Example output:
# "name": "firefox",
# "revision": "1495",
# "installByDefault": true,
# "browserVersion": "142.0.1"    # ← Target Firefox version
```

**B. Get Playwright's exact Firefox commit hash**

```bash
# For Playwright 1.56 (which supports Firefox 142.0.1):
curl -s https://raw.githubusercontent.com/microsoft/playwright/release-1.56/browser_patches/firefox/UPSTREAM_CONFIG.sh

# Output:
# REMOTE_URL="https://github.com/mozilla-firefox/firefox"
# BASE_BRANCH="release"
# BASE_REVISION="361373160356d92cb5cd4d67783a3806c776ee78"  # ← This is the commit!
```

**Important:** Use the release branch (e.g., `release-1.56`), not `main`. The `main` branch tracks the latest nightly and may target a different Firefox version.

**C. Verify the commit exists**

```bash
# Check what this commit corresponds to
curl -s "https://api.github.com/repos/mozilla-firefox/firefox/commits/361373160356d92cb5cd4d67783a3806c776ee78" \
    | python3 -c "import sys, json; data = json.load(sys.stdin); \
        print('Commit:', data.get('commit', {}).get('message', '').split('\n')[0]); \
        print('Date:', data.get('commit', {}).get('author', {}).get('date'))"

# Example output:
# Commit: Bug 1974259 - Hold an OwnedHandle in an OverlappedOperation a=pascalc
# Date: 2025-06-26T19:17:50Z
```

**Why this matters:** Mozilla's official release tarballs differ slightly from specific git commits. Playwright's patches are designed for their specific commit, so using that exact commit ensures patches apply cleanly.

### Step 2: Clone and Setup Git Repo

**A. Clone Firefox repository and checkout Playwright's commit**

```bash
# Change to your workspace
cd /path/to/camoufox

# Clone Firefox repo with partial clone (faster, smaller)
git clone --filter=blob:none --no-checkout \
    git@github.com:mozilla-firefox/firefox.git \
    camoufox-142.0.1-bluetaka.25

# Checkout the exact commit Playwright targets
cd camoufox-142.0.1-bluetaka.25
git checkout 361373160356d92cb5cd4d67783a3806c776ee78
```

**Note:** Use SSH URL (`git@github.com:...`) to leverage your SSH keys for faster cloning.

**B. Copy Camoufox additions into Firefox source**

```bash
# From within the Firefox source directory
bash ../scripts/copy-additions.sh 142.0.1 bluetaka.25
```

This copies:
- Juggler (Playwright protocol integration)
- Camoufox branding (logos, icons)
- Build configs and search settings
- MaskConfig system headers

**C. Commit and tag as baseline**

```bash
# Stage all additions
git add -A

# Commit the additions
git commit -m "Add Camoufox additions"

# Tag this commit as the unpatched baseline
git tag -a unpatched -m "Initial commit with additions"
```

**Verify the setup:**
```bash
# Check git history (should have parent commit)
git log --oneline -3
# Output:
# 4286358a69 (HEAD -> main, tag: unpatched) Add Camoufox additions
# 361373160356 Bug 1974259 - Hold an OwnedHandle in an OverlappedOperation a=pascalc
# 373c7e838797 Automatic version bump NO BUG a=release CLOSED TREE DONTBUILD

# Verify unpatched tag has a parent
git log --oneline unpatched^
# Should show Firefox commit (361373160356...)
```

**Now you can use `make dir` to apply patches!**

### Step 3: When Additions Need Fixing

**Scenario:** During build or patch application, you discover a Firefox version compatibility issue in the `additions/` directory (e.g., Juggler component registration, branding configuration).

**Problem:** The `additions/` directory is copied into the Firefox source when the `unpatched` baseline is created. If you fix something in `additions/` but the Firefox source still has the old broken version, every `make revert` restores the broken state.

**Solution:** Use `make retag-baseline` to rebuild the `unpatched` tag with updated additions, or use `make copy-additions` for a quick sync without git operations.

#### Example: Firefox 142 Juggler Component Fix

**What broke:**
```
Exception: Error defining component f7a74a33-e2ab-422d-b022-4fb213dd2639
('@mozilla.org/remote/juggler;1'): Externally-constructed components may
not specify 'constructor' or 'legacy_constructor' properties
```

**Root cause:** Firefox 142 tightened component registration rules. Components with `categories` + `constructor` + no `headers` are marked as "external" by default, and external components can't have constructors.

**Investigation:**
```bash
# Read the Firefox build error to understand the constraint
# Find the failing component definition
grep -r "f7a74a33-e2ab-422d-b022-4fb213dd2639" additions/

# Found: additions/juggler/components/components.conf
# Firefox's gen_static_components.py line 296-298:
#   self.external = data.get("external", not (self.headers or self.legacy_constructor))
# Since Juggler has no 'headers', defaults to external=True
```

**The fix:**
```python
# additions/juggler/components/components.conf
Classes = [
    {
        "cid": "{f7a74a33-e2ab-422d-b022-4fb213dd2639}",
        "contract_ids": ["@mozilla.org/remote/juggler;1"],
        "categories": {
            "command-line-handler": "m-remote",
            "profile-after-change": "Juggler",
        },
        "jsm": "chrome://juggler/content/components/Juggler.js",
        "constructor": "JugglerFactory",
        "external": False,  # ← Add this to override the default
    },
]
```

**Apply the fix to baseline:**
```bash
# 1. Edit the file in additions/
vim additions/juggler/components/components.conf

# 2. Rebuild the unpatched baseline
make retag-baseline

# Output:
# Rebuilding 'unpatched' baseline with latest additions...
# HEAD is now at 361373160356 Bug 1974259 - Hold an OwnedHandle...
# Copying additions/ and settings/ to source tree...
# ✓ Files copied. Run 'make build' for incremental rebuild.
# [detached HEAD 39cf2dd] Add Camoufox additions (Firefox 142 compatibility)
# Updated tag 'unpatched' (was 415a013b)
# ✓ Baseline refreshed. 'unpatched' tag updated with latest additions.
```

**What `retag-baseline` does:**
1. Resets Firefox repo to `unpatched^` (pristine Firefox commit before additions)
2. Runs `git clean -dxf` to remove all untracked files
3. Calls `make copy-additions` to re-copy `additions/` with the fix
4. Commits the new additions
5. Force-updates the `unpatched` tag to point to this new commit

**Result:** Now `make revert` will reset to a baseline that includes the fix!

**Verify:**
```bash
make revert  # Should now include the fix
make build   # Should build successfully
```

#### When to Use `retag-baseline` vs `copy-additions`

**Use `make copy-additions` when:**
- You want to quickly test additions/ changes without git operations
- You're iterating on Juggler or MaskConfig code
- You want to preserve your current git state and build artifacts
- You just need files synced for an incremental rebuild

**Use `make retag-baseline` when:**
- You want to update the `unpatched` baseline tag permanently
- You're done iterating and want `make revert` to include your fixes
- You need a clean state after fixing component registration or build configs

**Files to fix with these commands:**
- Component registration issues (`.conf` files)
- Build configuration problems (`configure.sh`, `moz.build` in additions/)
- Branding/configuration files in `additions/browser/branding/`
- MaskConfig header files (`additions/camoucfg/`)
- Juggler integration files (`additions/juggler/`)

**Don't use these for:**
- Fixing patches in `patches/` directory (those are applied after baseline)
- Changing Firefox source code directly (use git commits + checkpoints instead)

## Repository Structure

Understanding the dual-repo structure:

```
/home/user/camoufox/                          # Camoufox Project Repo
├── .git/                                      # Tracks: patches, scripts, docs
├── Makefile
├── patches/                                   # Patch files
├── additions/                                 # Copied into Firefox source
│   ├── juggler/                              # Playwright integration
│   ├── camoucfg/                             # MaskConfig system
│   └── browser/branding/camoufox/            # Branding files
├── scripts/
│   └── copy-additions.sh                     # Copies additions/ → Firefox
└── camoufox-142.0.1-bluetaka.25/             # Firefox Source Repo
    ├── .git/                                  # Full Firefox git history!
    │   └── refs/tags/unpatched → commit      # Points to additions commit
    │                              └─ parent → # Pristine Firefox (Playwright's commit)
    ├── browser/
    ├── dom/
    └── ... Firefox source code ...
```

**Key insight:** The Firefox source directory is its own git repo with full history, NOT just extracted files.

## Gotchas & Best Practices

### ❌ Don't Do This

1. **Don't run `make setup`** - It will destroy your Firefox git history
2. **Don't run `make fetch`** - Unnecessary with git clone approach
3. **Don't manually copy additions to Firefox source** - Use `copy-additions` or `retag-baseline`
4. **Don't modify Firefox source without committing** - You'll lose work on `git reset`

### ✅ Do This

1. **Use `make copy-additions`** - For quick iteration on `additions/` files
2. **Use `make retag-baseline`** - After fixing anything in `additions/` permanently
3. **Use `make tagged-checkpoint`** - After successfully applying patches
4. **Use `git log` in Firefox repo** - To understand upstream changes
5. **Use `git diff OLD..NEW` in Firefox repo** - To see what changed between versions
6. **Commit additions changes to Camoufox repo** - After testing they work

### Workflow Checklist

**When fixing an additions/ issue (quick iteration):**
```bash
# 1. Identify the problem (build error, component registration, etc.)
# 2. Edit the file in additions/ directory
vim additions/path/to/file

# 3. Quickly sync the fix to source
make copy-additions

# 4. Test with incremental build
make build

# 5. Once confirmed working, update baseline permanently
make retag-baseline

# 6. Commit the fix to Camoufox repo
git add additions/path/to/file
git commit -m "Fix: Description of what broke and how we fixed it"
```

## Comparison Table

| Aspect | Tarball Approach | Git Repo Approach |
|--------|------------------|-------------------|
| **Setup Command** | `make setup` | Manual `git clone` + `copy-additions.sh` |
| **Firefox History** | None (single commit) | Full git history |
| **`unpatched` Tag** | No parent commit | Has parent (pristine Firefox) |
| **`make retag-baseline`** | ❌ Fails (no parent) | ✅ Works |
| **`make copy-additions`** | ✅ Works | ✅ Works |
| **Debugging Patches** | Harder (no context) | Easier (can see Firefox changes) |
| **Version Comparison** | Manual diff of tarballs | `git diff OLD..NEW` |
| **Disk Space** | Smaller (~500MB) | Larger (~2GB with history) |
| **Original Maintainer** | ✅ Designed for this | ❌ Not designed for this |
| **Cory's Preference** | ❌ Abandoned | ✅ Current workflow |

## For Future Maintainers

If you're continuing this work, **strongly consider the git repo approach** despite the Makefile being designed for tarballs.

**Why?**
- Firefox versions break patches constantly
- Understanding WHY patches break requires seeing what Firefox changed
- The git history is invaluable for debugging
- The disk space trade-off (2GB vs 500MB) is worth it

**Migration Path:**
If you inherit a tarball-based setup and want to switch:
1. Find the pristine Firefox commit (from Playwright's `UPSTREAM_CONFIG.sh`)
2. Clone Firefox repo and checkout that commit
3. Run `copy-additions.sh` to add Camoufox additions
4. Commit and tag as `unpatched`
5. Apply your patches with `make dir`
6. You now have a git-repo-based setup with `retag-baseline` and `copy-additions` support!

## Investigating Patch Failures: Is It a Bug or Expected Behavior?

When upgrading Firefox, patches break. But before "fixing" them, you must ask: **Is this actually broken, or is this how vanilla Firefox is supposed to work?**

### The Question Framework

When you see unexpected behavior or API mismatches:

1. **What does vanilla Firefox return?**
   - Run stock Firefox (not Camoufox) on a real machine
   - Compare with `firefox --headless` (often different!)
   - Test with RFP enabled vs disabled

2. **Check Mozilla's test files**
   - Search `dom/canvas/test/` for relevant tests
   - Example: `test_renderer_strings.html` shows expected WebGL behavior
   - Mozilla's tests are ground truth for "correct" behavior

3. **Only patch if:**
   - ✅ Camoufox diverges from vanilla Firefox (detection risk)
   - ✅ You're intentionally spoofing for stealth
   - ❌ Don't patch just to "fix" Firefox quirks!

### Case Study: WebGL Standard API Investigation

**Observed behavior:**
```
gl.VENDOR:              "Mozilla"
gl.RENDERER:            "llvmpipe, or similar"
UNMASKED_VENDOR_WEBGL:  "Mesa"
UNMASKED_RENDERER_WEBGL: "llvmpipe, or similar"
```

**Initial assumption:**
> "This is a leak! Standard API returns 'Mozilla' but deprecated API returns 'Mesa'. They should match!"

**Investigation process:**

1. **Check Mozilla's test file:**
```bash
cat dom/canvas/test/webgl-mochitest/test_renderer_strings.html
```

Found (lines 174-183):
```javascript
const EXPECTED = {
  renderer:           "ANGLE (...), or similar",  // Sanitized
  vendor:             "Mozilla",                   // Always this!
  unmasked_renderer:  "ANGLE (...), or similar",  // Also sanitized
  unmasked_vendor:    "Google Inc.",               // Real vendor exposed
};
```

2. **Checked when APIs were added:**
```bash
git log --all --oneline --grep="renderer.query" -- dom/canvas/
# Output: Added in Firefox 92 (July 2021)
```

3. **Verified vanilla Firefox behavior:**
- Standard `gl.VENDOR`: **Always "Mozilla"** (hardcoded)
- Deprecated `UNMASKED_VENDOR_WEBGL`: **Real vendor** when RFP=false

**Conclusion:**
- ✅ Mismatch is EXPECTED in vanilla Firefox!
- ✅ Standard API wasn't reading MaskConfig (actual bug to fix)
- ❌ Making them "consistent" would break vanilla Firefox emulation!

**The fix:**
Only patch the standard API to read MaskConfig when configured. When unconfigured, maintain vanilla Firefox behavior (including the mismatch).

### Using Mozilla Test Files

**Where to find them:**
```bash
# WebGL tests
find camoufox-*/dom/canvas/test -name "*.html"

# Common test directories
dom/canvas/test/webgl-mochitest/
dom/canvas/test/chrome/
dom/base/test/
```

**How to read them:**
```javascript
// test_renderer_strings.html shows expected behavior
const EXPECTED = {
  renderer: RTX3070_R_SANITIZED,  // What Firefox should return
  vendor: 'Mozilla',               // Always this value
  // ...
};

expectJsonEqual(was, EXPECTED, 'v92 behavior');
```

**What to look for:**
- Expected values for different Firefox versions
- RFP enabled vs disabled behavior
- Pref-controlled variations
- Known CI/test environment values

### Validation Checklist

Before considering a patch "fixed":

- [ ] Test with MaskConfig configured (spoofed values work)
- [ ] Test WITHOUT MaskConfig (matches vanilla Firefox fallback)
- [ ] Compare to Mozilla's test expectations
- [ ] Verify both APIs return consistent story (when configured)
- [ ] Check that quirks/inconsistencies match vanilla Firefox
- [ ] Test with `--headless` and without (may differ)
- [ ] Verify behavior matches claimed hardware (no llvmpipe on Windows!)

### Common Pitfalls

**❌ Wrong: "Let's make all APIs consistent"**
- Vanilla Firefox has intentional inconsistencies
- Bot detectors expect these quirks
- "Fixing" them makes you detectable

**✅ Right: "Let's match vanilla Firefox exactly"**
- Keep Firefox's quirks and bugs
- Only spoof what MaskConfig configures
- Fallback to vanilla Firefox behavior otherwise

---

## Related Documentation

- **WORKFLOW.md** - General patch application workflow
- **CAMOUFOX_ARCHITECTURE.md** - Understanding Camoufox's stealth design
- **FIREFOX_142_UPGRADE_NOTES.md** - Version-specific upgrade notes
- **Makefile** - Build system (assumes tarball approach)

---

**Document History:**
- Created: October 2025 (Firefox 142 upgrade)
- Purpose: Preserve Cory's git-based workflow for future Firefox upgrades

