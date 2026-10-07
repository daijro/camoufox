# Playwright Maintenance Guide

This document describes how to maintain Playwright integration in Camoufox.

## Overview

Camoufox integrates Playwright's browser automation through a patch and a copy of
Playwright's Juggler protocol. Both started from upstream Playwright and both
carry Camoufox changes, so upstream updates are ported into them, never copied
over them.

## Patch Files

Location: `browser/patches/playwright/`

| File                   | Purpose                                                                                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0-playwright.patch`   | Playwright's [bootstrap.diff](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff), ported to the Firefox version in `browser/upstream.sh`, plus Camoufox fixes to the Juggler input and navigation paths |
| `1-leak-fixes.patch`   | Undoes two changes from `0-playwright.patch` that expose automation: `navigator.webdriver` always reports `false`, and enterprise policies load from Firefox's normal provider instead of Playwright's |

Both sort ahead of every other patch, so `browser/scripts/patch.py` applies them first.

## Addition Files

Location: `browser/additions/juggler/`

Camoufox's Juggler, started from
[upstream](https://github.com/microsoft/playwright/tree/main/browser_patches/firefox/juggler).
Camoufox changes include the isolated-world page agent and the human cursor
(`input/`), so a straight copy from upstream would remove them.

### Key Files

- **`components/Juggler.js`** - Main Juggler component, an ES module that exports `JugglerFactory`
- **`components/components.conf`** - XPCOM component registration
- **`jar.mn`** - What gets packaged into `chrome://juggler/content/`

`components.conf` registers the component with the `esModule` field (Firefox
no longer supports `jsm`):

```python
{
    "esModule": "chrome://juggler/content/components/Juggler.js",
    "constructor": "JugglerFactory",
}
```

## Updating Playwright Integration

Every command in this section runs from `browser/`.

### 1. Port Upstream Patch Changes

Compare what changed in Playwright's
[bootstrap.diff](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff)
since the last sync and apply those changes to the tree, then regenerate the
patch with the make targets described in
[patch-upgrading-guide.md](patch-upgrading-guide.md):

```bash
make dir
make workspace ./patches/playwright/0-playwright.patch
# port the upstream changes into camoufox-<version>-<release>/
make diff > patches/playwright/0-playwright.patch
```

### 2. Port Juggler Changes

```bash
git clone https://github.com/microsoft/playwright.git /tmp/playwright
diff -r additions/juggler/ /tmp/playwright/browser_patches/firefox/juggler/
```

Port the upstream hunks one by one, keeping the Camoufox changes. After an
update, check that:

1. `Juggler.js` still exports `JugglerFactory`, and `components.conf` still
   names it as the `constructor`.
2. `components.conf` uses `esModule`, not `jsm`.
3. Every file upstream added or renamed is listed in `jar.mn`.

### 3. Test

```bash
make dir && make build
make tests
```

`make dir` resets the tree, clobbers the object directory and reapplies every
patch, so this is a clean build.

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

**Cause:** Using the `"jsm"` field, which Firefox no longer supports.

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

1. Check that every `ChromeUtils.importESModule()` path in the Juggler files still exists
2. Check that new or renamed files are listed in `jar.mn`
3. Check for Firefox API changes that might require patches

## References

- [Playwright Firefox Patches](https://github.com/microsoft/playwright/tree/main/browser_patches/firefox)
- [Firefox ESM Migration Guide](https://firefox-source-docs.mozilla.org/dom/script_loader/index.html)
