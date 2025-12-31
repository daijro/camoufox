# macOS Sandbox Initialization Fix

## Purpose

Fixes a crash on macOS where Camoufox would segfault with `KERN_INVALID_ADDRESS at 0x0000000000000000` during content process launch due to a null pointer dereference in `ContentParent::AppendSandboxParams()`.

## Problem

The `sMacSandboxParams` static variable was null when `AppendSandboxParams()` was called during content process launch, causing a null pointer write crash. While `sMacSandboxParams` should be initialized in `ContentParent::StartUp()`, there appear to be edge cases or race conditions where the function is called before proper initialization.

## Solution

Adds a defensive null check at the beginning of `AppendSandboxParams()` that initializes `sMacSandboxParams` if it's unexpectedly null, preventing the crash while maintaining normal operation.

## Files Modified

- `dom/ipc/ContentParent.cpp`: Added null safety check in `AppendSandboxParams()`

## Platform

macOS only (wrapped in `#if defined(XP_MACOSX) && defined(MOZ_SANDBOX)`)

## Apply Order

Apply after the Playwright patches (0-playwright.patch, 1-leak-fixes.patch) in the build sequence.

## Testing

The fix can be verified by:

1. Building Camoufox with the patch
2. Running `./camoufox` without `MOZ_DISABLE_CONTENT_SANDBOX=1`
3. Verifying the browser launches without crashing
4. Checking that content processes spawn correctly via `about:processes`

## Notes

- This is a defensive fix that handles an edge case in initialization order
- The NS_WARNING will log if the fallback initialization is triggered
- Normal Firefox builds initialize sMacSandboxParams in StartUp(), so this is Camoufox-specific
