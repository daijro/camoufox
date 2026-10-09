# Firefox Patch Upgrading Guide

How to update Camoufox's patches when `browser/upstream.sh` moves to a new Firefox
version. Patches break because Firefox renames APIs, moves code and shifts line
numbers; this guide covers finding and fixing those rejects.

## Table of Contents

1. [Understanding the Patch System](#understanding-the-patch-system)
2. [The Source Tree and Its Make Targets](#the-source-tree-and-its-make-targets)
3. [General Workflow](#general-workflow)
4. [Fixing Common Reject Types](#fixing-common-reject-types)
5. [Per-Context Machinery](#per-context-machinery)
6. [Testing and Validation](#testing-and-validation)
7. [Pitfalls](#pitfalls)

---

## Understanding the Patch System

### Patch Categories

All patches live under `browser/patches/`, and `browser/scripts/patch.py` applies every
`*.patch` in it (subdirectories included), sorted by file name:

- **Playwright**: `playwright/0-playwright.patch` (Juggler integration) and
  `playwright/1-leak-fixes.patch`. Their names sort first, and every other
  patch is written against a tree that already has them.
- **Feature patches**: `webrtc-ip-spoofing.patch`,
  `anti-font-fingerprinting.patch`, etc. Per-user-context (per-Playwright-context)
  support is built into each one.
- **`librewolf/`, `ghostery/`**: patches taken from those projects.

Compile-time dependencies between patches (MaskConfig, RoverfoxStorageManager)
are listed in [`browser/patches/patch-dependencies.md`](../browser/patches/patch-dependencies.md).

### Key Infrastructure Files

- **RoverfoxStorageManager.cpp/h**: Thread-safe key-value storage for per-context data
- **Manager Classes**: AudioFingerprintManager, WebRTCIPManager, etc.
- **Window.webidl**: Exposes the per-context setters to Playwright

---

## The Source Tree and Its Make Targets

The Firefox tree is `browser/camoufox-<version>-<release>/` (from
`browser/upstream.sh`). It is a git repository whose `unpatched` tag is plain
Firefox plus `browser/additions/` and `browser/settings/`. Run every target, and
every command in this guide, from `browser/`:

| Target | What it does |
|---|---|
| `make dir` | Fetches and extracts Firefox if the tree is missing. Otherwise resets it to `unpatched`, runs `mach clobber` and `git clean -fdx` (the object directory goes too), re-copies additions, then applies every patch and lists the ones that left rejects. |
| `make revert` | `git reset --hard unpatched`. Untracked files stay, including new files that patches created. |
| `make clean` | `mach clobber`, `git clean -fdx`, then `make revert`: unpatched Firefox with nothing left over, without re-fetching. |
| `make patch ./patches/x.patch` | Applies one patch (`patch -p1`). |
| `make unpatch ./patches/x.patch` | Reverses one patch. |
| `make first-checkpoint` | Commits the current tree and tags it `first-checkpoint`. |
| `make workspace ./patches/x.patch` | Unapplies `x` if it is applied, runs `first-checkpoint`, then applies `x` again, so the working tree differs from the checkpoint by exactly that patch. |
| `make diff` | `git diff first-checkpoint`. Redirect it into the patch file. |
| `make checkpoint` | Commits tracked changes, keeping the `first-checkpoint` tag where it is. |
| `make grep <text>` | Searches the top-level patches for a string. |
| `make build` | `./mach build` (runs `make dir` first if the tree was never prepared). |
| `make run` | Runs the build with `debug` on in `CAMOU_CONFIG`; wipes `~/.camoufox`. `args="..."` passes arguments. |
| `make path` | Prints the built `camoufox-bin`. |
| `make stage-fonts` | Stages the font bundle into the unpackaged build, which tests through the launchers need. |
| `make tests` | The Playwright suite against the build (`headful=true` for headed). |
| `make help` | Lists every target. |

`git diff` does not show untracked files. Before `make diff`, mark new files
with `git add -N <file>` inside the source tree, or they will be missing from
the patch.

---

## General Workflow

### Step 1: Bump the Version and Find the Broken Patches

Update `version` and `release` in `browser/upstream.sh`, then:

```bash
make dir
```

`patch.py` applies every patch and ends with a list of the ones that failed and
their reject files. It deletes the `.rej` files after listing them, so reproduce
each failure one patch at a time (Step 2).

### Step 2: Set Up One Patch

Start from a clean unpatched tree, apply what the patch builds on (at least the
Playwright patches, plus anything from `browser/patches/patch-dependencies.md`),
checkpoint, then apply the broken patch. Use `make clean` rather than
`make revert` here: files that other patches created survive a revert and make
`patch` stop on "previously applied" prompts.

```bash
make clean
make patch ./patches/playwright/0-playwright.patch
make patch ./patches/playwright/1-leak-fixes.patch
make first-checkpoint
make patch ./patches/patch-name.patch     # fails, leaving .rej files
```

Find the reject files:

```bash
cd camoufox-<version>-<release>
find . -name '*.rej' -type f
```

### Step 3: Analyze Each Reject File

Read the reject file to understand what failed:

```bash
cat path/to/file.cpp.rej
```

Reject files show:
- `@@` lines: Line numbers where patch expected to apply
- `-` lines: What the patch expected to find (old code)
- `+` lines: What the patch wanted to add (new code)

### Step 4: Locate the Correct Position in Firefox Code

The line numbers in rejects are usually wrong for the new Firefox version. You need to:

1. **Search for unique context** around the reject
2. **Understand what the patch is doing**
3. **Find equivalent location** in new Firefox code

### Step 5: Apply Changes Manually

Edit the file to make the rejected change at the correct location.

### Step 6: Remove Reject Files

After fixing all rejects, delete the `.rej` files and any `.orig` backups
`patch` left, so they do not end up in the diff:

```bash
find . -name '*.rej' -o -name '*.orig' | xargs rm -f
```

### Step 7: Write the Updated Patch

From `browser/`:

```bash
(cd camoufox-<version>-<release> && git add -N path/to/new/file.cpp)   # new files only
make diff > patches/patch-name.patch
```

### Step 8: Verify

Run `make dir` again. The patch should no longer be listed as failing.

---

## Fixing Common Reject Types

### Type 1: Include Directive Rejects

**Symptom**: Reject shows failed `#include` additions

**Example Reject**:
```
@@ -325,6 +325,7 @@
 #include "xpcpublic.h"

+#include "WebRTCIPManager.h"
 #include "nsDocShell.h"
```

**How to Fix**:

1. Read the actual file to find the includes section
2. Search for nearby includes (e.g., `xpcpublic.h`)
3. Add the new include in the appropriate location
4. Firefox include order: system headers, then Mozilla headers, alphabetically within groups

**Example**:

```cpp
// Find this in the actual file:
#include "xpcpublic.h"

// Add the missing includes after it:
#include "xpcpublic.h"

#include "WebRTCIPManager.h"
#include "nsDocShell.h"
#include "mozilla/OriginAttributes.h"
```

### Type 2: Function Signature Changes

**Symptom**: Reject shows function call with changed parameters

**Example Reject**:
```
-  mouseOrPointerEvent.mButton = aButton;
+  mouseOrPointerEvent.mJugglerEventId = aMouseEventData.mJugglerEventId;
```

**Common Causes**:
- Firefox refactored the API
- Parameters moved from individual args to struct/data object
- Parameter order changed

**How to Fix**:

1. Search for the function definition in Firefox source
2. Understand the new API structure
3. Port the patch logic to the new API

**Example - Firefox 146 Mouse Event Refactoring**:

Old Firefox 144 API (individual parameters):
```cpp
void SynthesizeMouseEvent(int x, int y, int button, ...)
```

New Firefox 146 API (structured data):
```cpp
void SynthesizeMouseEvent(SynthesizeMouseEventData& aData,
                         SynthesizeMouseEventOptions& aOptions)
```

Port the patch:
```cpp
// Old patch code:
mouseEvent.mButton = aButton;
mouseEvent.jugglerEventId = aJugglerEventId;

// New patch code for Firefox 146:
mouseOrPointerEvent.mButton = aMouseEventData.mButton;
mouseOrPointerEvent.mJugglerEventId = aMouseEventData.mJugglerEventId;
mouseOrPointerEvent.convertToPointer = aOptions.mConvertToPointer;
```

### Type 3: Missing Context - Code Moved

**Symptom**: Reject shows context that doesn't exist in the file

**How to Fix**:

1. Use grep to search for unique function names or variables in the reject
2. Find where Firefox moved the code
3. Apply the patch to the new location

```bash
# Search across the codebase
grep -r "FunctionName" camoufox-<version>/ --include="*.cpp"
```

### Type 4: New Parameter Added to Function Calls

**Symptom**: Reject shows function call, but Firefox added/removed parameters

**Example - MakeTextRun userContextId**:

Old call:
```cpp
MakeTextRun(text, len, drawTarget, appUnitsPerDevPixel, flags, recorder);
```

New Firefox expects:
```cpp
MakeTextRun(text, len, drawTarget, appUnitsPerDevPixel, flags, recorder, userContextId);
```

**How to Fix**:

1. Extract userContextId from available context (Document, PresContext, etc.)
2. Add proper extraction code before the call
3. Pass userContextId as the last parameter

**userContextId extraction**: the per-context patches resolve it from the
`BrowsingContext`, which exists before the document's attributes are set:

```cpp
uint32_t userContextId = 0;
if (BrowsingContext* bc = win->GetBrowsingContext()) {
  userContextId = bc->OriginAttributesRef().mUserContextId;
}
MakeTextRun(..., userContextId);
```

Workers use `WorkerPrivate::GetOriginAttributes()` instead.

### Type 5: Line Number Shifts (No Code Changes)

**Symptom**: Reject shows patch tried to apply at wrong line number, but code is identical

**How to Fix**:

Simply apply the patch manually at the correct line number. The code hasn't changed, just the location.

---

## Per-Context Machinery

Most spoofing patches carry per-context support. When porting one, expect these
pieces:

1. **Manager classes** (e.g., AudioFingerprintManager, WebRTCIPManager):
   - Store per-context settings using RoverfoxStorageManager
   - Gate their setter with `RoverfoxStorageManager::IsSetterOffered` and
     `MarkSetterUsed`

2. **Window.webidl functions**:
   - JavaScript APIs exposed to Playwright
   - Examples: `setAudioFingerprintSeed()`, `setWebRTCIPv4()`

3. **nsGlobalWindowInner.cpp implementations**:
   - Extract userContextId from window/document/docshell
   - Call manager classes
   - Remove the setter after use with `RoverfoxStorageManager::RemoveSetter`

4. **Core logic changes**:
   - Consult the per-context manager before the global config (MaskConfig)
   - Pass userContextId through call chains

See [`per-context-patches.md`](per-context-patches.md) for the full list.

---

## Testing and Validation

### Minimal Verification

After updating a patch, always verify:

1. **Every patch applies cleanly**: `make dir` lists no failures.

2. **Build compiles** (if feasible):
   ```bash
   make build
   ```

### Full Testing

Run the suites that cover the patch (see [`ci/README.md`](../ci/README.md)):
`python3 -m ci.run_patch_guards --binary <camoufox-bin>` is the most direct
evidence that a patch which still applies was not neutered by the upgrade.

### Browser-Owned GPU Values

The launchers build WebGL from fpgen's recordings, which an older Firefox made.
Some values are the browser's rather than the GPU's, and an upgrade can change
them on every device: Firefox 156 added `EXT_depth_clamp` on Windows and fixed
WebGL1's `ALIASED_LINE_WIDTH_RANGE` at `[1, 1]` on Linux
([`webgl-browser-owned-values-follow-firefox`](../ci/tribal-rules.yml)). The
`stock-gpu-parity` guard finds them. It runs stock Firefox of the new version,
stock Firefox of the release fpgen's model recorded, and Camoufox claiming the
machine's GPU, and fails where the two stock releases differ and Camoufox does
not follow the new one:

```bash
python3 -m ci.run_patch_guards --binary <camoufox-bin> --only stock-gpu-parity
```

CI runs it on Linux with a software renderer. Run it on Windows and macOS too,
passing the stock binaries by hand, because each OS has its own graphics
backend:

```bash
python browser/tests/playwright/patches/stock-gpu-parity.py --binary <camoufox-bin> \
    --stock <Firefox of upstream.sh's version> --recorded-stock <Firefox of fpgen's release>
```

For each failure, find in the Firefox source why the value changed and whether
it holds on every device of that backend, then follow it where the launchers
convert a recording (`to_config` in `python/src/camoufox/webgl.py` and
`typescript/src/webgl.ts`).

---

## Pitfalls

| Pitfall | Avoid it by |
|---|---|
| Trusting reject line numbers | Searching for the context lines instead |
| Hand-editing a `.patch` file | Editing the tree and running `make diff` |
| Missing new files in the patch | `git add -N` them before `make diff` |
| A diff that includes the patch's dependencies | Running `make first-checkpoint` after applying them and before the patch being fixed |
| `.rej` and `.orig` files in the diff | Deleting them first (Step 6) |
| Guessing a value a refactored API now needs | Reading the new Firefox code, or the release notes |
| Fixing several patches in one pass | One patch at a time, each from `make clean` |

## Appendix: Firefox Source Navigation

### Finding Files

```bash
# Find files by name
find . -name "Navigator.cpp" -type f

# Find files containing a symbol
grep -r "GetAcceptLanguages" . --include="*.cpp"

# Find class definitions
grep -r "class Navigator" . --include="*.h"
```

### Understanding Firefox Code Structure

- `dom/`: DOM implementation
  - `dom/base/`: Core DOM classes (Window, Document, Navigator, etc.)
  - `dom/webidl/`: WebIDL interface definitions
  - `dom/media/webrtc/`: WebRTC implementation
- `gfx/`: Graphics and font rendering
  - `gfx/thebes/`: Text rendering (fonts, glyphs, shaping)
- `layout/`: Layout engine
  - `layout/generic/`: Text frames
  - `layout/mathml/`: MathML rendering

---

## Checklist

- [ ] Bump `browser/upstream.sh` and run `make dir` to list the failing patches
- [ ] For each: `make clean`, apply its dependencies, `make first-checkpoint`, `make patch` it
- [ ] Port each reject to the new Firefox code
- [ ] Remove `.rej` and `.orig` files, `git add -N` new files
- [ ] `make diff > patches/<name>.patch`
- [ ] `make dir` applies the whole stack cleanly
- [ ] `make build`, then run the patch guards
- [ ] Run `stock-gpu-parity` on Linux, Windows and macOS ([Browser-Owned GPU Values](#browser-owned-gpu-values))

---

## Additional Resources

- Firefox source: https://searchfox.org/
- Firefox API documentation: https://firefox-source-docs.mozilla.org/
- Mercurial repository: https://hg.mozilla.org/mozilla-central/
