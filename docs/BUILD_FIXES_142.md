# Build Fixes for Firefox 142 Upgrade

This document tracks all build errors encountered and fixed during the Firefox 142 upgrade. These fixes need to be backported into their respective patches.

## Workflow

### Current Strategy (Iterate Then Backport)

We've checkpointed the Firefox source at the state where **all patches applied successfully** (tag: `checkpoint`). Now we're iterating on build fixes directly in the source code without reverting/reapplying patches each time.

**Rationale**: Firefox builds take a long time. Doing a full "clean workspace on every break" cycle would be too slow. Instead:

1. **Fix in place** - Modify source files directly to fix build errors
2. **Track changes** - Document each fix in this file
3. **Continue building** - Let the build continue to find all errors
4. **Backport when done** - Once build succeeds, unpack changes back into their respective patches

### End Game (When Build Succeeds)

Once the build completes successfully:

1. **Review all changes**: `cd camoufox-142.0.1-bluetaka.25 && git diff checkpoint`
   - This shows all the build fixes we made
   - Consider committing the changes and tagging with something like "known-buildable"

2. **Backport each fix into its patch** (treating it like a broken patch per WORKFLOW.md):

   For each patch that needs a build fix:

   a. `make revert` - Go all the way back to unpatched Firefox

   b. `make patch patches/<broken-patch>.patch` - Apply ONLY this one patch
      - Patches are independent, no need to apply others first

   c. **Manually apply the build fix** - Edit the source file(s) to add the build fix
      - Use this tracking document to know exactly what to change
      - Example: Add the `static_cast<uint8_t>()` casts to ClientWebGLContext.cpp

   d. **Verify all hunks are present** - `git status && git diff` to confirm:
      - All original patch hunks are there
      - Plus the new build fix
      - Nothing else has leaked in

   e. **Regenerate the patch**: `cd camoufox-142.0.1-bluetaka.25 && git diff > ../patches/<broken-patch>.patch`
      - Since we only applied this one patch, `git diff` will only contain this patch's changes + build fix

   f. **Test it**: `make revert && make patch patches/<broken-patch>.patch`
      - Confirm it applies cleanly
      - `git diff` to verify all changes are correct

   g. **Update notes**: Add entry to `FIREFOX_142_UPGRADE_NOTES.md` about the build fix

   h. **Commit**: Commit the updated patch to the Camoufox repo with a descriptive message

   i. Move to next patch that needs fixing (repeat from step a)

3. **Alternative: Validate all patches at once** (if only one or two patches need fixing):
   - `make revert-checkpoint` - Go back to clean state
   - `make patch <updated-patch>` - Apply the regenerated patch
   - Verify with `git diff` that it applies correctly
   - `make tagged-checkpoint` - Tag the working state

4. **Test full patch sequence**:
   - `make revert` - Start completely fresh
   - `make dev` - Apply all patches and build
   - Confirm everything applies and compiles

5. **Commit the updated patches**:
   - Commit each updated patch to the Camoufox repo
   - Update `FIREFOX_142_UPGRADE_NOTES.md` with notes about build fixes

---

## Build Errors Found

### 1. ClientWebGLContext.cpp - Narrowing Conversion Error
**File**: `dom/canvas/ClientWebGLContext.cpp`
**Lines**: 3048-3050
**Patch**: `patches/webgl-spoofing.patch`
**Error**: `non-constant-expression cannot be narrowed from type 'value_type' (aka 'int') to 'uint8_t' (aka 'unsigned char') in initializer list [-Wc++11-narrowing]`

**Root Cause**: Firefox's compiler has gotten stricter about implicit type conversions. The `format` array contains `int` values but `ShaderPrecisionFormat` expects `uint8_t` fields.

**Fix Required**: Add explicit casts:
```cpp
webgl::ShaderPrecisionFormat{
    static_cast<uint8_t>(format[0]),  // rangeMin
    static_cast<uint8_t>(format[1]),  // rangeMax
    static_cast<uint8_t>(format[2])   // precision
}
```

**Status**: ✅ Fixed - Added explicit `static_cast<uint8_t>()` around format[0], format[1], format[2]

---

### 2. nsScreencastService.cpp - Missing Include
**File**: `juggler/screencast/nsScreencastService.cpp`
**Line**: 47
**Location**: `additions/juggler/screencast/nsScreencastService.cpp` (not a patch, but an added file)
**Error**: `use of undeclared identifier 'gfxPlatform'`

**Root Cause**: The file uses `gfxPlatform::IsHeadless()` but is missing the include for `gfxPlatform.h`.

**Fix Required**: Add include near top of file:
```cpp
#include "gfxPlatform.h"
```

**Status**: ✅ Fixed - Added `#include "gfxPlatform.h"` after HeadlessWindowCapturer.h include

**Note**: This is in the `additions` directory (not a patch). Fixed in both locations:
- ✅ `camoufox-142.0.1-bluetaka.25/juggler/screencast/nsScreencastService.cpp` (Firefox source)
- ✅ `additions/juggler/screencast/nsScreencastService.cpp` (Camoufox repo)

For additions files, fix them directly and commit the change to the Camoufox repo. No patch regeneration needed.

---

### 3. Juggler ESM Migration - Actor Registration
**Files**: `additions/juggler/components/Juggler.sys.mjs`
**Lines**: 24-28
**Error**: `NotSupportedError: ChromeUtils.registerWindowActor: Either moduleURI or esModuleURI is required.`

**Root Cause**: Firefox 142 migrated from JSM (JavaScript Modules) to ESM (ECMAScript Modules). Actor registration now requires `esModuleURI` instead of `moduleURI` for `.sys.mjs` files.

**Fix Required**: Change actor registration property names:
```javascript
ActorManagerParent.addJSWindowActors({
  JugglerFrame: {
    parent: {
      esModuleURI: 'chrome://juggler/content/JugglerFrameParent.sys.mjs',  // was: moduleURI
    },
    child: {
      esModuleURI: 'chrome://juggler/content/content/JugglerFrameChild.sys.mjs',  // was: moduleURI
```

**Status**: ✅ Fixed - Changed `moduleURI` to `esModuleURI` for both parent and child actors

**Note**: This is in `additions/juggler/` so the fix was committed directly to the Camoufox repo.

---

### 4. Juggler ESM Migration - Dynamic Import Syntax
**File**: `additions/juggler/content/PageAgent.sys.mjs`
**Line**: 578
**Error**: `SyntaxError: import declarations may only appear at top level of a module`

**Root Cause**: ESM modules don't allow static `import` statements inside functions. The `_crash()` method used a static import which worked in JSM but fails in ESM.

**Fix Required**: Use dynamic import syntax:
```javascript
async _crash() {
  // Old (JSM):
  // import { ctypes } from "resource://gre/modules/ctypes.sys.mjs";

  // New (ESM):
  const { ctypes } = await import("resource://gre/modules/ctypes.sys.mjs");
```

**Status**: ✅ Fixed - Changed static import to dynamic `import()` function call

**Note**: This is in `additions/juggler/` so the fix was committed directly to the Camoufox repo.

---

### 5. Juggler ESM Migration - Debugger Initialization
**File**: `additions/juggler/content/Runtime.sys.mjs`
**Lines**: 9-13
**Error**: `TypeError: can't access property "Debugger" of undefined`

**Root Cause**: In ESM modules, `this` is `undefined` at the top level (unlike JSM where `this` refers to the global object). Also, `ChromeUtils.import()` is deprecated in favor of `ChromeUtils.importESModule()`.

**Fix Required**: Multiple ESM compatibility fixes:
```javascript
// Old (JSM):
if (!this.Debugger) {
  const {addDebuggerToGlobal} = ChromeUtils.import("resource://gre/modules/jsdebugger.jsm", {});
  addDebuggerToGlobal(Components.utils.getGlobalForObject(this));
}

// New (ESM):
if (typeof Debugger === 'undefined') {
  const {addDebuggerToGlobal} = ChromeUtils.importESModule("resource://gre/modules/jsdebugger.sys.mjs");
  addDebuggerToGlobal(globalThis);
}
```

**Changes**:
1. `!this.Debugger` → `typeof Debugger === 'undefined'`
2. `ChromeUtils.import()` → `ChromeUtils.importESModule()`
3. `.jsm` → `.sys.mjs`
4. `Components.utils.getGlobalForObject(this)` → `globalThis`

**Status**: ✅ Fixed - Updated to ESM-compatible Debugger initialization

**Note**: This is in `additions/juggler/` so the fix was committed directly to the Camoufox repo.

---

## Runtime Errors (Non-Breaking)

### SearchService Errors
**Error**: `JSON error: missing field 'recordType' at line 1 column 114`

**Root Cause**: The `patches/no-search-engines.patch` intentionally returns a minimal/dummy search engine configuration to disable search engines for anti-fingerprinting purposes. This configuration is incomplete and causes SearchService to fail initialization.

**Status**: ⚠️ **Expected behavior** - These errors are intentional and don't affect Juggler/Playwright functionality. The search service is not needed for headless automation.

---

## Summary
- Total build errors found: 2 (compile-time)
- Total build errors fixed: 2
- Total runtime errors found: 3 (ESM migration)
- Total runtime errors fixed: 3
- Patches requiring regeneration: 1
  - `patches/webgl-spoofing.patch`
- Additions requiring updates: 4
  - `additions/juggler/screencast/nsScreencastService.cpp` (compile fix)
  - `additions/juggler/components/Juggler.sys.mjs` (ESM migration)
  - `additions/juggler/content/PageAgent.sys.mjs` (ESM migration)
  - `additions/juggler/content/Runtime.sys.mjs` (ESM migration)

