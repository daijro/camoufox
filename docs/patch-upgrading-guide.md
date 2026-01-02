# Firefox Patch Upgrading Guide for LLMs

This guide provides step-by-step instructions for updating Camoufox patches when upgrading Firefox versions. Patches frequently break due to Firefox API changes, file reorganizations, and line number shifts.

**All patches are located in the `patches/` directory.** There are no separate context patches to merge—per-context functionality is already built into the patches.

## Table of Contents

1. [Understanding the Patch System](#understanding-the-patch-system)
2. [Preparation](#preparation)
3. [General Workflow](#general-workflow)
4. [Fixing Common Reject Types](#fixing-common-reject-types)
5. [Context Patch Merging](#context-patch-merging) *(Historical - skip for future updates)*
6. [Testing and Validation](#testing-and-validation)
7. [Best Practices](#best-practices)

---

## Understanding the Patch System

### Patch Categories

All Camoufox patches are in the `patches/` directory:

- **Core Patches**: `0-playwright.patch`, `1-leak-fixes.patch`, etc.
- **Feature Patches**: `webrtc-ip-spoofing.patch`, `anti-font-fingerprinting.patch`, etc.
- All patches now include per-user-context (per-Playwright-context) support built-in

**Historical Note**: Context patches (e.g., `font-fingerprinting.context.patch`, `webrtc.context.patch`) were previously separate but have been merged into their base patches as of Firefox 146. You will not find `.context.patch` files in the repository.

### Key Infrastructure Files

- **RoverfoxStorageManager.cpp/h**: Thread-safe key-value storage for per-context data
- **Manager Classes**: FontSpacingSeedManager, WebRTCIPManager, etc.
- **Window.webidl**: Exposes JavaScript APIs to Playwright

---

## Preparation

### 1. Reset to Clean State

**IMPORTANT**: Always use `make clean` to reset to fresh Firefox source:

```bash
make clean
```

**DO NOT** use `git reset` or `git clean` commands directly in the Firefox source directory - these can delete untracked files needed for the build.

### 2. Identify Patches to Update

Check which patches exist:

```bash
ls patches/*.patch
```

### 3. Understand Patch Dependencies

Some patches depend on others being applied first:
- `1-leak-fixes.patch` requires `0-playwright.patch`
- Check the Makefile or patch comments for dependency chains

---

## General Workflow

### Step 1: Apply Base Patch and Identify Rejects

```bash
cd camoufox-<version>
patch -p1 < ../patches/patch-name.patch
```

Find reject files:

```bash
find . -name '*.rej' -type f
```

### Step 2: Analyze Each Reject File

Read the reject file to understand what failed:

```bash
cat path/to/file.cpp.rej
```

Reject files show:
- `@@` lines: Line numbers where patch expected to apply
- `-` lines: What the patch expected to find (old code)
- `+` lines: What the patch wanted to add (new code)

### Step 3: Locate the Correct Position in Firefox Code

The line numbers in rejects are usually wrong for the new Firefox version. You need to:

1. **Search for unique context** around the reject
2. **Understand what the patch is doing**
3. **Find equivalent location** in new Firefox code

### Step 4: Apply Changes Manually

Use the Edit tool to apply the rejected changes to the correct location.

### Step 5: Remove Reject Files

After fixing all rejects:

```bash
rm -f path/to/file.cpp.rej
find . -name '*.rej' -type f  # Verify all removed
```

### Step 6: Generate Updated Patch

```bash
# Add any new files first
git add new/file.cpp new/file.h

# Generate patch with both staged and unstaged changes
git diff --cached --binary > /tmp/patch-name.patch
git diff --binary >> /tmp/patch-name.patch

# Copy to patches directory
cp /tmp/patch-name.patch ../patches/patch-name.patch
```

### Step 7: Verify Patch Applies Cleanly

```bash
cd ..
make clean
cd camoufox-<version>
patch -p1 < ../patches/patch-name.patch
find . -name '*.rej' -type f  # Should return nothing
```

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

**Standard userContextId Extraction Pattern**:

```cpp
uint32_t userContextId = 0;
if (mozilla::dom::Document* doc = presContext->Document()) {
  if (nsIPrincipal* principal = doc->NodePrincipal()) {
    auto* bp = mozilla::BasePrincipal::Cast(principal);
    if (bp) {
      userContextId = bp->OriginAttributesRef().mUserContextId;
    }
  }
}

// Now pass userContextId to the function
MakeTextRun(..., userContextId);
```

### Type 5: Line Number Shifts (No Code Changes)

**Symptom**: Reject shows patch tried to apply at wrong line number, but code is identical

**How to Fix**:

Simply apply the patch manually at the correct line number. The code hasn't changed, just the location.

---

## Context Patch Merging (Historical - Not Applicable for Future Updates)

**NOTE**: As of Firefox 146, all context patches have been merged into their base patches. This section is kept for historical reference and understanding how the patches evolved. Future Firefox updates will only need to update patches in the `patches/` directory.

---

**Historical Context**: Context patches previously added per-user-context functionality to base patches. The workflow was different from simple patch updates.

### Historical Goal

Merge all changes from `*.context.patch` into the corresponding base patch so there's only one comprehensive patch file.

### Historical Example: font-fingerprinting.context.patch → anti-font-fingerprinting.patch

### Workflow

1. **Reset to clean Firefox**:
   ```bash
   make clean
   ```

2. **Apply base patch first**:
   ```bash
   cd camoufox-<version>
   patch -p1 < ../patches/anti-font-fingerprinting.patch
   ```

3. **Apply context patch on top**:
   ```bash
   patch -p1 < ../font-fingerprinting.context.patch
   ```

4. **Fix any rejects** (usually include conflicts since base patch may have some overlapping changes)

5. **Generate combined patch**:
   ```bash
   # Add new files (e.g., FontSpacingSeedManager.cpp/h)
   git add dom/base/FontSpacingSeedManager.cpp
   git add dom/base/FontSpacingSeedManager.h
   git add dom/base/RoverfoxStorageManager.cpp
   git add dom/base/RoverfoxStorageManager.h

   # Generate combined patch
   git diff --cached --binary > /tmp/anti-font-fingerprinting.patch
   git diff --binary >> /tmp/anti-font-fingerprinting.patch

   # Replace base patch
   cp /tmp/anti-font-fingerprinting.patch ../patches/anti-font-fingerprinting.patch
   ```

6. **Verify combined patch**:
   ```bash
   cd ..
   make clean
   cd camoufox-<version>
   patch -p1 < ../patches/anti-font-fingerprinting.patch
   find . -name '*.rej' -type f  # Should be empty
   ```

### What Context Patches Add

Context patches typically add:

1. **Manager classes** (e.g., FontSpacingSeedManager, WebRTCIPManager):
   - Store per-context settings using RoverfoxStorageManager
   - Provide WebIDL-compatible enable/disable checks
   - Handle self-destructing functions

2. **Window.webidl functions**:
   - JavaScript APIs exposed to Playwright
   - Examples: `setFontSpacingSeed()`, `setWebRTCIPv4()`

3. **nsGlobalWindowInner.cpp implementations**:
   - Extract userContextId from window/document/docshell
   - Call manager classes
   - Self-destruct logic (remove function after first use)

4. **Core logic changes**:
   - Replace global config (MaskConfig) with per-context manager
   - Pass userContextId through call chains
   - Query manager for per-context values

---

## Testing and Validation

### Minimal Verification

After updating a patch, always verify:

1. **Patch applies cleanly**:
   ```bash
   make clean
   cd camoufox-<version>
   patch -p1 < ../patches/patch-name.patch
   find . -name '*.rej' -type f
   ```

2. **No reject files remain**

3. **Build compiles** (if feasible):
   ```bash
   cd ..
   make build
   ```

### Full Testing

For critical patches, test with actual Playwright scenarios after building.

---

## Best Practices

### DO:

1. ✅ **Always use `make clean`** to reset Firefox source
2. ✅ **Read and understand** what the patch is trying to do before fixing rejects
3. ✅ **Search for API changes** in Firefox release notes when functions have changed
4. ✅ **Use grep/search** extensively to find where code moved
5. ✅ **Extract userContextId properly** using the standard pattern
6. ✅ **Test patches apply cleanly** before considering them done
7. ✅ **Keep commits atomic** - one patch fix per session
8. ✅ **Document major API changes** you discover

### DON'T:

1. ❌ **Don't use `git reset` or `git clean`** on Firefox source directory
2. ❌ **Don't leave TODO comments** - fix things properly as you go
3. ❌ **Don't guess parameter values** - extract them properly or investigate
4. ❌ **Don't skip verification** - always test the patch applies cleanly
5. ❌ **Don't batch multiple patch updates** - do them one at a time
6. ❌ **Don't assume line numbers are correct** in reject files
7. ❌ **Don't ignore warnings** during patch application

### Common Pitfalls

1. **Assuming reject line numbers are accurate**: They're usually wrong in new Firefox versions
2. **Not understanding API changes**: Firefox refactors often - read the new code
3. **Forgetting to add new files**: Use `git add` before generating patch
4. **Not testing on clean source**: Always verify with `make clean`
5. **Leaving reject files**: Remove all `.rej` files after fixing

---

## Example: Complete Patch Update Session

Here's a complete example of updating `0-playwright.patch` from Firefox 144 to Firefox 146:

### 1. Reset and Apply

```bash
make clean
cd camoufox-146.0.1-beta.25
patch -p1 < ../patches/0-playwright.patch
```

### 2. Find Rejects

```bash
find . -name '*.rej' -type f
```

Output shows 20 reject files.

### 3. Analyze First Reject

```bash
cat dom/base/Navigator.cpp.rej
```

Shows parameter order changed in `GetAcceptLanguages`.

### 4. Fix the Reject

Search for the function in the actual file, understand the new signature, apply changes manually.

### 5. Repeat for All Rejects

Work through each reject systematically.

### 6. Discover API Change

Firefox 146 refactored mouse events from individual parameters to `SynthesizeMouseEventData` and `SynthesizeMouseEventOptions`. Port all mouse event logic to new API.

### 7. Remove Rejects

```bash
rm -f dom/base/Navigator.cpp.rej dom/base/Element.cpp.rej ...
find . -name '*.rej' -type f  # Verify empty
```

### 8. Generate New Patch

```bash
git diff --binary > /tmp/0-playwright.patch
cp /tmp/0-playwright.patch ../patches/0-playwright.patch
```

### 9. Verify

```bash
cd ..
make clean
cd camoufox-146.0.1-beta.25
patch -p1 < ../patches/0-playwright.patch
find . -name '*.rej' -type f  # Should be empty
```

---

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

### Common Firefox Patterns

**User Context ID Extraction**:
```cpp
uint32_t userContextId = 0;
if (Document* doc = GetDocument()) {
  if (nsIPrincipal* principal = doc->NodePrincipal()) {
    auto* bp = mozilla::BasePrincipal::Cast(principal);
    if (bp) {
      userContextId = bp->OriginAttributesRef().mUserContextId;
    }
  }
}
```

**Three-tier userContextId fallback** (for WebIDL functions):
```cpp
// 1) Document's principal (preferred)
if (Document* doc = win->GetDoc()) {
  if (nsIPrincipal* p = doc->NodePrincipal()) {
    userContextId = p->OriginAttributesRef().mUserContextId;
  }
}

// 2) DocShell origin attributes
if (userContextId == 0) {
  if (nsIDocShell* ds = win->GetDocShell()) {
    auto* concrete = static_cast<nsDocShell*>(ds);
    userContextId = concrete->GetOriginAttributes().mUserContextId;
  }
}

// 3) Top browsing context
if (userContextId == 0) {
  if (BrowsingContext* bc = win->GetBrowsingContext()) {
    RefPtr<BrowsingContext> top = bc->Top();
    // ... extract from top window
  }
}
```

---

## Summary Checklist

When updating patches for a new Firefox version:

- [ ] Use `make clean` to reset to fresh Firefox source
- [ ] Apply patch and identify all reject files
- [ ] Analyze each reject to understand what changed
- [ ] Search Firefox source for moved/refactored code
- [ ] Fix rejects by porting logic to new Firefox APIs
- [ ] Extract userContextId properly using standard patterns
- [ ] Don't leave TODO comments - fix everything immediately
- [ ] Remove all `.rej` files after fixing
- [ ] Add any new files with `git add`
- [ ] Generate new patch with `git diff --cached --binary` + `git diff --binary`
- [ ] Verify patch applies cleanly to fresh source
- [ ] Document any major API changes discovered

---

## Additional Resources

- Firefox source: https://searchfox.org/
- Firefox API documentation: https://firefox-source-docs.mozilla.org/
- Mercurial repository: https://hg.mozilla.org/mozilla-central/

---

**Last Updated**: December 2025 (Firefox 146 upgrade)
