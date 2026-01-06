# Playwright Maintenance Guide

This document describes how to maintain Playwright integration in Camoufox.

## Overview

Camoufox integrates Playwright's browser automation capabilities through patches and additional files. These need to be kept in sync with upstream Playwright development.

## Patch Files

Location: `patches/playwright/`

| File                   | Purpose                                                                                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0-playwright.patch`   | Playwright's upstream patches. Must be kept up to date with [bootstrap.diff](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff) |
| `1-leak-fixes.patch`   | Undos certain patches from `0-playwright.patch` to fix memory leaks                                                                                    |

## Addition Files

Location: `additions/juggler/`

The `juggler` directory contains Playwright's Juggler protocol implementation. These files must be kept in sync with:

**Upstream Source:** https://github.com/microsoft/playwright/tree/main/browser_patches/firefox/juggler

### Key Files

- **`components/Juggler.js`** - Main Juggler component (legacy JSM format)
- **`components/Juggler.sys.mjs`** - ESM wrapper for Firefox 146+ compatibility
- **`components/components.conf`** - XPCOM component registration

### Firefox 146 ESM Migration

Firefox 146 removed JSM (JavaScript Module) support in favor of ESM (ES Modules). To maintain compatibility:

1. **`components.conf`** uses `esModule` field instead of deprecated `jsm` field:
   ```python
   {
       "esModule": "chrome://juggler/content/components/Juggler.sys.mjs",
       "constructor": "JugglerFactory",
   }
   ```

2. **`Juggler.sys.mjs`** acts as an ESM wrapper that imports the legacy JSM file:
   ```javascript
   const { JugglerFactory } = ChromeUtils.import(
     "chrome://juggler/content/components/Juggler.js"
   );
   export { JugglerFactory };
   ```

This maintains backward compatibility while satisfying Firefox 146's static component generator requirements.

## Updating Playwright Integration

### 1. Update Upstream Patches

Compare the current `patches/playwright/0-playwright.patch` with Playwright's [bootstrap.diff](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff).

If changes are needed:
```bash
# Download latest bootstrap.diff
curl -o patches/playwright/0-playwright.patch \
  https://raw.githubusercontent.com/microsoft/playwright/main/browser_patches/firefox/patches/bootstrap.diff

# Test the build
make clean && make dir && make build
```

### 2. Update Juggler Files

Sync `additions/juggler/` with upstream:

```bash
# Clone Playwright repository
git clone https://github.com/microsoft/playwright.git /tmp/playwright

# Compare directories
diff -r additions/juggler/ /tmp/playwright/browser_patches/firefox/juggler/

# Copy updated files (example)
cp -r /tmp/playwright/browser_patches/firefox/juggler/* additions/juggler/

# IMPORTANT: Preserve Firefox 146 ESM compatibility
# - Keep additions/juggler/components/Juggler.sys.mjs
# - Keep additions/juggler/components/components.conf with esModule field
```

### 3. Verify ESM Wrapper Compatibility

After updating from upstream, ensure the ESM wrapper remains functional:

1. Check that `Juggler.js` still exports `JugglerFactory`:
   ```javascript
   var EXPORTED_SYMBOLS = ["Juggler", "JugglerFactory"];
   var JugglerFactory = function() { /* ... */ };
   ```

2. If upstream changed the export name, update `Juggler.sys.mjs` accordingly.

3. Verify `components.conf` matches the format above (not upstream's format).

### 4. Test Build

```bash
# Clean build to verify component registration
cd camoufox-146.0.1-beta.25
make clean
cd ..
make dir
cd camoufox-146.0.1-beta.25
./mach build
```

**Expected:** No linker errors about `mozCreateComponent<nsICommandLineHandler>`.

**Common Error:** If you see:
```
ld64.lld: error: undefined symbol: already_AddRefed<nsISupports> mozCreateComponent<nsICommandLineHandler>()
```

This means `components.conf` is not using ESM format. Fix by ensuring it has:
- `"esModule"` field (not `"jsm"`)
- `"constructor": "JugglerFactory"` field (not `"type"`)

## Troubleshooting

### Component Registration Errors

**Error:** `Externally-constructed components may not specify 'constructor' or 'legacy_constructor' properties`

**Cause:** Using `"jsm"` field which is unsupported in Firefox 146.

**Fix:** Use `"esModule"` field instead.

---

**Error:** `Externally-constructed components must specify a type other than nsISupports`

**Cause:** Using external component without proper type specification.

**Fix:** Convert to ESM component with constructor.

---

**Error:** `JavaScript components must specify a constructor`

**Cause:** ESM component missing constructor field.

**Fix:** Add `"constructor": "JugglerFactory"` to components.conf.

### Build Failures

If the build fails after updating Juggler files:

1. Check that all JSM imports in `Juggler.js` are still valid
2. Verify the ESM wrapper exports match what's imported
3. Ensure no file paths changed in upstream
4. Check for Firefox API changes that might require patches

## References

- [Playwright Firefox Patches](https://github.com/microsoft/playwright/tree/main/browser_patches/firefox)
- [Firefox 146 Component Registration](https://firefox-source-docs.mozilla.org/toolkit/components/extensions/webextensions/basics.html)
- [Firefox ESM Migration Guide](https://firefox-source-docs.mozilla.org/dom/script_loader/index.html)
