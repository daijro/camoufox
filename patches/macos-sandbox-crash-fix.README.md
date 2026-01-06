# macOS Sandbox Crash Fix

## Purpose

Fixes a crash on macOS where Camoufox segfaults during content process launch due to `MOZ_CRASH` being triggered when `GetRepoDir()` or `GetObjDir()` fail in non-packaged builds.

## Problem

In `CacheSandboxParams()`, the code attempts to get repository and object directory paths for sandbox whitelisting in non-packaged builds:

```cpp
if (!mozilla::IsPackagedBuild()) {
  rv = nsMacUtilsImpl::GetRepoDir(getter_AddRefs(repoDir));
  if (NS_FAILED(rv)) {
    MOZ_CRASH("Failed to get path to repo dir");  // ← CRASH HERE
  }
  // ...
}
```

These functions (`GetRepoDir` and `GetObjDir`) read paths from the `.app` bundle's `Info.plist` file. In cross-compiled builds or unusual build configurations, these plist keys may not exist, causing the functions to fail and trigger `MOZ_CRASH`.

## Root Cause

1. **Cross-compilation from Ubuntu to macOS**: The build process may not populate the development-specific plist keys (`MAC_DEV_REPO_KEY`, `MAC_DEV_OBJ_KEY`)
2. **IsPackagedBuild() detection**: In some build configurations, `IsPackagedBuild()` may incorrectly return `false`
3. **Missing plist keys**: The Info.plist doesn't contain the required development directory keys

When any of these occur, the code crashes instead of gracefully handling the missing paths.

## Solution

Changed the code from crashing on failure to logging a warning and continuing without those sandbox paths:

```cpp
if (NS_SUCCEEDED(rv)) {
  nsCString repoDirPath;
  (void)repoDir->GetNativePath(repoDirPath);
  info.testingReadPath3 = repoDirPath.get();
} else {
  NS_WARNING("Failed to get repo dir path for sandbox, skipping testingReadPath3");
}
```

Since `testingReadPath3` and `testingReadPath4` are optional sandbox parameters (only used for whitelisting in development builds), it's safe to skip them if they can't be determined.

## Files Modified

- `dom/ipc/ContentParent.cpp`: Changed `MOZ_CRASH` to `NS_WARNING` for `GetRepoDir()` and `GetObjDir()` failures

## Platform

macOS only (wrapped in `#if defined(XP_MACOSX) && defined(MOZ_SANDBOX)`)

## Apply Order

Apply after the Playwright patches (0-playwright.patch, 1-leak-fixes.patch) in the build sequence.

## Testing

The fix can be verified by:

1. Building Camoufox with the patch via cross-compilation from Ubuntu
2. Running the macOS binary without `MOZ_DISABLE_CONTENT_SANDBOX=1`
3. Verifying the browser launches without crashing
4. Checking that content processes spawn correctly via `about:processes`
5. Looking for warning messages in console output (if running from terminal)

## Notes

- This is a defensive fix that handles missing development directory paths gracefully
- The sandbox will still function correctly without `testingReadPath3` and `testingReadPath4`
- These paths are only used in non-packaged builds for development/testing purposes
- Production/packaged builds won't even reach this code path due to `IsPackagedBuild()` check
