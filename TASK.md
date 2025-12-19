# Firefox v147 Patch Update Task List

**Status**: Firefox upgraded from v135.0.1 to v147.0b3 (12 major versions)
**Date**: 2025-12-19
**Last Updated**: 2025-12-19 (LibreWolf + Playwright patches synced with upstream)
**Total Patches**: 45 (5 LibreWolf patches removed)
**Broken Patches**: 25 (56%)
**Clean Patches**: 20 (44%)

---

## 🔄 Upstream Patches Update (2025-12-19)

### LibreWolf Patches Update
**Action taken**: Updated all LibreWolf patches from upstream repository
**Source**: https://codeberg.org/librewolf/source (Firefox 146.0.1)

### Playwright Patch Update
**Action taken**: Updated 0-playwright.patch from upstream Playwright repository
**Source**: https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff

### ✅ Updated Patches (17 patches)
All LibreWolf patches have been updated to match Firefox 146 upstream versions:
- bootstrap.patch
- bootstrap-without-vcs.patch.opt
- arm.patch.opt
- rust-gentoo-musl.patch
- mozilla_dirs.patch
- dbus_name.patch
- devtools-bypass.patch
- urlbarprovider-interventions.patch
- custom-ubo-assets-bootstrap-location.patch
- 1550_1549.diff.opt
- disable-data-reporting-at-compile-time.patch
- sed-patches/stop-undesired-requests.patch
- ui-patches/firefox-view.patch
- ui-patches/handlers.patch
- ui-patches/hide-default-browser.patch
- ui-patches/remove-cfrprefs.patch
- ui-patches/remove-organization-policy-banner.patch

### ❌ Deleted Patches (5 patches - no longer in LibreWolf upstream)
These patches have been removed as they no longer exist in LibreWolf's repository:
1. **context-menu.patch** - Was broken (1 failed hunk) ✅ Removed .rej file
2. **remove_addons.patch** - Was broken (4 failed hunks) - ⚠️ .rej files still exist (orphaned)
3. **sed-patches/allow-searchengines-non-esr.patch** - Was broken (1 failed hunk) ✅ Removed .rej file
4. **sed-patches/disable-pocket.patch** - Was broken (2 failed hunks) - ⚠️ .rej files still exist (orphaned)
5. **ui-patches/remove-branding-urlbar.patch** - Was working ✅

### ⚠️ New Issues from Updates
1. **mozilla_dirs.patch** (updated from LibreWolf) now has 1 NEW failed hunk:
   - toolkit/xre/nsXREDirProvider.cpp.rej

2. **0-playwright.patch** (updated from Playwright upstream):
   - **MAJOR IMPROVEMENT**: Reduced from 34 → 23 failed hunks (33% improvement!)
   - **Fixed 11 files** that now apply cleanly
   - **Still broken**: 17 files need manual adaptation to Firefox 147

3. **1-leak-fixes.patch** now has 1 NEW failed hunk:
   - toolkit/components/enterprisepolicies/EnterprisePoliciesParent.sys.mjs.rej
   - This broke because upstream Playwright changed how it patches this file

**Net Impact**:
- LibreWolf: Deleted 4 broken patches, added 1 new broken patch (mozilla_dirs)
- Playwright: Improved significantly (11 files fixed), but added 1 broken patch (1-leak-fixes)
- Still have orphaned .rej files from deleted patches (need manual cleanup)
- **Actual broken patches: 25** (was 27, then 24, now 25 after Playwright update)

---

## Summary Statistics

- **Total .rej files**: 58 rejection files across the codebase (after all updates)
  - 6 orphaned .rej files from deleted patches (need manual cleanup)
  - 52 active .rej files from broken patches
- **Total failed hunks**: ~73 individual hunks that need manual resolution (reduced from ~82!)
- **Patches needing updates**: 25 patches
  - 22 patches that were already broken
  - 1 NEW broken patch from LibreWolf update (mozilla_dirs.patch)
  - 1 NEW broken patch from Playwright update (1-leak-fixes.patch)
  - 1 IMPROVED patch (0-playwright.patch: 34 → 23 hunks)
- **Patches working perfectly**: 20 patches

---

## Priority 1: Critical Patches (MUST FIX FIRST)

### 1. 0-playwright.patch ⚠️ **HIGHEST PRIORITY** - ✅ UPDATED FROM UPSTREAM

**Status**: Updated from Playwright upstream (2025-12-19)
**Failed hunks**: ~~34~~ → **23 across 17 files** (33% improvement!)
**Complexity**: Very High
**Strategy**: ~~Sync with upstream~~ ✅ DONE - Now needs manual adaptation to Firefox 147

**Files NOW FIXED** (11 files - no longer have .rej files):
- ✅ accessible/interfaces/nsIAccessibleDocument.idl
- ✅ accessible/xpcom/xpcAccessibleDocument.cpp
- ✅ accessible/xpcom/xpcAccessibleDocument.h
- ✅ browser/installer/package-manifest.in
- ✅ dom/geolocation/Geolocation.cpp
- ✅ dom/geolocation/Geolocation.h
- ✅ docshell/base/nsDocShell.h
- ✅ security/manager/ssl/* (3 files - no longer patched)
- ✅ toolkit/xre/nsAppRunner.cpp (no longer patched)

**Files STILL BROKEN** (17 files need manual fixes):
- docshell/base/BrowsingContext.h.rej (2 hunks - got worse!)
- docshell/base/CanonicalBrowsingContext.cpp.rej (1 hunk)
- docshell/base/nsDocShell.cpp.rej (1 hunk)
- dom/base/Navigator.cpp.rej (2 hunks)
- dom/base/Navigator.h.rej (1 hunk)
- dom/base/nsContentUtils.cpp.rej (4 hunks)
- dom/base/nsContentUtils.h.rej (1 hunk)
- dom/base/nsDOMWindowUtils.cpp.rej (4 hunks - got worse!)
- dom/base/nsDOMWindowUtils.h.rej (1 hunk)
- dom/html/HTMLInputElement.cpp.rej (1 hunk)
- dom/media/systemservices/video_engine/desktop_capture_impl.cc.rej (1 hunk)
- dom/workers/RuntimeService.cpp.rej (2 hunks)
- js/src/vm/DateTime.cpp.rej (1 hunk)
- layout/style/GeckoBindings.h.rej (1 hunk)
- netwerk/base/LoadInfo.cpp.rej (1 hunk)
- toolkit/components/resistfingerprinting/nsUserCharacteristics.cpp.rej (1 hunk)
- widget/InProcessCompositorWidget.cpp.rej (1 hunk)
- widget/gtk/nsFilePicker.cpp.rej (1 hunk)
- widget/headless/HeadlessWidget.cpp.rej (1 hunk)
- widget/nsGUIEventIPC.h.rej (2 hunks)

**Estimated time**: ~~2-4 hours~~ → 1.5-3 hours (reduced due to upstream update)

---

### 2. 1-leak-fixes.patch ⚠️ NEW BROKEN (from Playwright update)
**Failed hunks**: 1
**Complexity**: Low
**Impact**: Fixes memory leaks from Playwright patches

**Affected files**:
- toolkit/components/enterprisepolicies/EnterprisePoliciesParent.sys.mjs.rej (1 hunk)

**Note**: This patch broke because upstream Playwright changed how it patches EnterprisePoliciesParent.sys.mjs

**Estimated time**: 10-15 minutes

---

### 3. fingerprint-injection.patch
**Failed hunks**: 9 across 5 files
**Complexity**: High
**Impact**: Core fingerprinting functionality

**Affected files**:
- browser/app/moz.build.rej (1 hunk)
- dom/base/Element.cpp.rej (1 hunk)
- dom/base/Navigator.cpp.rej (4 hunks) - **overlap with Playwright**
- dom/base/nsScreen.cpp.rej (1 hunk)
- dom/battery/BatteryManager.cpp.rej (1 hunk)

**Note**: Navigator.cpp has conflicts from both Playwright and this patch

**Estimated time**: 1-2 hours

---

### 3. roverfox/font-fingerprinting.context.patch
**Failed hunks**: 8 across 5 files
**Complexity**: High
**Impact**: Per-context font isolation (new feature)

**Affected files**:
- dom/base/nsGlobalWindowInner.cpp.rej (1 hunk)
- dom/canvas/CanvasRenderingContext2D.cpp.rej (1 hunk)
- gfx/thebes/gfxTextRun.cpp.rej (2 hunks)
- layout/generic/MathMLTextRunFactory.cpp.rej (1 hunk)
- layout/mathml/nsMathMLChar.cpp.rej (3 hunks)

**Estimated time**: 1.5-2.5 hours

---

### 4. roverfox/font-fingerprinting.context.patch (renumbered from 3)
**Failed hunks**: 8 across 5 files
**Complexity**: High
**Impact**: Per-context font isolation (new feature)

**Affected files**:
- dom/base/nsGlobalWindowInner.cpp.rej (1 hunk)
- dom/canvas/CanvasRenderingContext2D.cpp.rej (1 hunk)
- gfx/thebes/gfxTextRun.cpp.rej (2 hunks)
- layout/generic/MathMLTextRunFactory.cpp.rej (1 hunk)
- layout/mathml/nsMathMLChar.cpp.rej (3 hunks)

**Estimated time**: 1.5-2.5 hours

---

### 5. roverfox/webrtc-ip.context.patch
**Failed hunks**: 2 across 2 files
**Complexity**: Medium
**Impact**: Per-context WebRTC IP isolation

**Affected files**:
- dom/base/nsGlobalWindowInner.cpp.rej (1 hunk) - **overlap with font patch**
- dom/media/webrtc/jsapi/PeerConnectionImpl.cpp.rej (1 hunk)

**Estimated time**: 30-60 minutes

---

## Priority 2: Stealth/Spoofing Patches

### 5. webgl-spoofing.patch
**Failed hunks**: 3 across 1 file
**Complexity**: Medium

**Affected files**:
- dom/canvas/ClientWebGLContext.cpp.rej (3 hunks)

**Estimated time**: 30-45 minutes

---

### 6. font-hijacker.patch
**Failed hunks**: 2 across 2 files
**Complexity**: Medium

**Affected files**:
- layout/style/FontFaceImpl.h.rej (1 hunk)
- layout/style/moz.build.rej (1 hunk)

**Estimated time**: 20-30 minutes

---

### 7. audio-context-spoofing.patch
**Failed hunks**: 1 across 1 file
**Complexity**: Low

**Affected files**:
- dom/media/moz.build.rej (1 hunk)

**Estimated time**: 10-15 minutes

---

### 8. geolocation-spoofing.patch
**Failed hunks**: 1 across 1 file
**Complexity**: Low

**Affected files**:
- dom/geolocation/moz.build.rej (1 hunk)

**Estimated time**: 10-15 minutes

---

### 9. voice-spoofing.patch
**Failed hunks**: 1 across 1 file
**Complexity**: Low

**Affected files**:
- dom/media/webspeech/synth/nsSynthVoiceRegistry.cpp.rej (1 hunk)

**Estimated time**: 10-15 minutes

---

### 10. webrtc-ip-spoofing.patch
**Failed hunks**: 1 across 1 file
**Complexity**: Low

**Affected files**:
- dom/media/webrtc/jsapi/PeerConnectionImpl.cpp.rej (1 hunk)

**Estimated time**: 10-15 minutes

---

## Priority 3: LibreWolf UI/Config Patches (Lower Impact)

### 11. ~~allow-searchengines-non-esr.patch~~ ❌ DELETED (no longer in LibreWolf upstream)
~~**Failed hunks**: 1~~
~~**Affected files**: browser/components/enterprisepolicies/schemas/policies-schema.json.rej~~
~~**Estimated time**: 10 minutes~~

### 12. ~~context-menu.patch~~ ❌ DELETED (no longer in LibreWolf upstream)
~~**Failed hunks**: 1~~
~~**Affected files**: browser/base/content/browser-context.inc.rej~~
~~**Estimated time**: 10 minutes~~

### 13. custom-ubo-assets-bootstrap-location.patch
**Failed hunks**: 1
**Affected files**: toolkit/components/extensions/parent/ext-storage.js.rej
**Estimated time**: 10 minutes

### 14. ~~disable-pocket.patch~~ ❌ DELETED (no longer in LibreWolf upstream)
~~**Failed hunks**: 2~~
~~**Affected files**:~~
~~- browser/base/content/browser.js.rej (1 hunk)~~
~~- browser/components/BrowserGlue.sys.mjs.rej (1 hunk)~~
~~**Estimated time**: 15-20 minutes~~

### 15. hide-default-browser.patch ✅ FIXED (updated from LibreWolf upstream)
~~**Failed hunks**: 2~~
~~**Affected files**: browser/components/preferences/main.inc.xhtml.rej~~
**Status**: Updated patch from LibreWolf Firefox 146 - now applies cleanly!
~~**Estimated time**: 15 minutes~~

### 16. mozilla_dirs.patch ⚠️ NEW BROKEN (from LibreWolf update)
**Failed hunks**: 1
**Affected files**: toolkit/xre/nsXREDirProvider.cpp.rej
**Estimated time**: 10-15 minutes
**Note**: This patch was working before, but the updated version from LibreWolf (Firefox 146) introduced a conflict with Firefox 147

### 17. network-patches.patch
**Failed hunks**: 1
**Affected files**: netwerk/protocol/http/nsHttpHandler.cpp.rej
**Estimated time**: 15 minutes

### 18. no-search-engines.patch
**Failed hunks**: 2
**Affected files**:
- browser/components/urlbar/UrlbarProviderInterventions.sys.mjs.rej (1 hunk)
- toolkit/components/search/SearchEngineSelector.sys.mjs.rej (1 hunk)
**Estimated time**: 15-20 minutes

### 19. remove-cfrprefs.patch ✅ FIXED (updated from LibreWolf upstream)
~~**Failed hunks**: 2~~
~~**Affected files**: browser/components/preferences/main.inc.xhtml.rej~~
**Status**: Updated patch from LibreWolf Firefox 146 - now applies cleanly!
~~**Estimated time**: 15 minutes~~

### 19. ~~remove_addons.patch~~ ❌ DELETED (no longer in LibreWolf upstream)
~~**Failed hunks**: 4~~
~~**Affected files**:~~
~~- browser/locales/Makefile.in.rej (2 hunks)~~
~~- browser/locales/filter.py.rej (1 hunk)~~
~~- browser/locales/l10n.ini.rej (1 hunk)~~
~~**Estimated time**: 20-30 minutes~~

### 20. windows-theming-bug-modified.patch
**Failed hunks**: 1
**Affected files**: browser/app/Makefile.in.rej
**Estimated time**: 10 minutes

### 📊 LibreWolf Patches Summary After Update:
- ✅ **2 patches FIXED**: hide-default-browser.patch, remove-cfrprefs.patch
- ⚠️ **1 patch BROKE**: mozilla_dirs.patch (new conflict)
- ❌ **4 patches DELETED**: context-menu, remove_addons, allow-searchengines-non-esr, disable-pocket
- **Net result**: -3 broken patches (27 → 24)

---

## Patches That Applied Successfully ✅

These 21 patches need **NO UPDATES**:

1. ~~✅ 1-leak-fixes.patch~~ ⚠️ NOW BROKEN (1 new hunk from Playwright update)
2. ✅ Disable-Onboarding-Messages.patch (Ghostery)
3. ✅ all-addons-private-mode.patch
4. ✅ anti-font-fingerprinting.patch
5. ✅ bootstrap.patch (LibreWolf)
6. ✅ browser-init.patch
7. ✅ chromeutil.patch
8. ✅ config.patch
9. ✅ dbus_name.patch (LibreWolf)
10. ✅ devtools-bypass.patch (LibreWolf)
11. ✅ disable-data-reporting-at-compile-time.patch (LibreWolf)
12. ✅ disable-extension-newtab.patch
13. ✅ disable-remote-subframes.patch
14. ✅ force-default-pointer.patch
15. ✅ global-style-sheets.patch
16. ✅ handlers.patch (LibreWolf)
17. ✅ locale-spoofing.patch
18. ✅ media-device-spoofing.patch
19. ✅ mozilla_dirs.patch (LibreWolf)
20. ✅ no-css-animations.patch
21. ✅ pin-addons.patch
22. ~~✅ remove-branding-urlbar.patch (LibreWolf)~~ ❌ DELETED (no longer in LibreWolf upstream)
23. ✅ remove-organization-policy-banner.patch (LibreWolf)
24. ✅ rust-gentoo-musl.patch (LibreWolf)
25. ✅ screen-hijacker.patch
26. ✅ shadow-root-bypass.patch
27. ✅ stop-undesired-requests.patch (LibreWolf)
28. ✅ timezone-spoofing.patch
29. ✅ urlbarprovider-interventions.patch (LibreWolf)

---

## Execution Plan

### Phase 1: Preparation (10 min)
1. ✅ **DONE**: Identified all broken patches (27 patches)
2. ✅ **DONE**: Categorized by priority
3. **TODO**: Clean workspace: `make revert`
4. **TODO**: Create backup of current patches directory

### Phase 2: Critical Patches (4-8 hours)

#### Step 1: Update Playwright Patch (2-4 hours)
1. Download Playwright's latest bootstrap.diff
2. Compare with current 0-playwright.patch
3. Strategy decision:
   - If Playwright has v147: Replace entire patch
   - If not: Manual update of all 34 failed hunks
4. Test standalone: Apply only Playwright patches, verify build
5. **Success criteria**: Zero .rej files for Playwright

#### Step 2: Fix fingerprint-injection.patch (1-2 hours)
1. Use `make workspace ./patches/fingerprint-injection.patch`
2. Resolve 9 failed hunks across 5 files
3. Pay special attention to Navigator.cpp (overlaps with Playwright)
4. Test: Basic build + browser launch
5. **Success criteria**: Core fingerprinting loads without errors

#### Step 3: Fix Roverfox Context Patches (2-3 hours)
1. Fix font-fingerprinting.context.patch (8 hunks)
2. Fix webrtc-ip.context.patch (2 hunks)
3. Note: Both patches touch nsGlobalWindowInner.cpp
4. Test: Verify RoverfoxStorageManager integration
5. **Success criteria**: Per-context isolation works

### Phase 3: Stealth Patches (2-3 hours)

Fix in order:
1. webgl-spoofing.patch (3 hunks, 30-45 min)
2. font-hijacker.patch (2 hunks, 20-30 min)
3. audio-context-spoofing.patch (1 hunk, 10-15 min)
4. geolocation-spoofing.patch (1 hunk, 10-15 min)
5. voice-spoofing.patch (1 hunk, 10-15 min)
6. webrtc-ip-spoofing.patch (1 hunk, 10-15 min)

**Success criteria**: All spoofing features functional

### Phase 4: LibreWolf Patches (30-45 minutes)

✅ **MOSTLY COMPLETE**: LibreWolf patches updated from upstream (Firefox 146)
- 17 patches updated to latest versions
- 4 broken patches deleted (no longer needed)
- 2 patches auto-fixed by update (hide-default-browser, remove-cfrprefs)
- Only 4 LibreWolf patches remaining to fix:
  - custom-ubo-assets-bootstrap-location.patch (1 hunk) - 10 min
  - mozilla_dirs.patch (1 hunk) ⚠️ NEW - 10-15 min
  - network-patches.patch (1 hunk) - 15 min
  - no-search-engines.patch (2 hunks) - 15-20 min
  - windows-theming-bug-modified.patch (1 hunk) - 10 min

**Total estimated time**: 60-70 minutes for 5 patches

**Success criteria**: Browser builds with all UI customizations

### Phase 5: Integration Testing (2-3 hours)

1. **Clean apply all patches**: `make revert && make dir`
2. **Verify zero .rej files**: `find . -name "*.rej"`
3. **Full build**: `make build` (30-60 min build time)
4. **Smoke tests**:
   - Browser launches
   - Navigation works
   - Console has no errors
5. **Automated tests**: `make tests` (run all 51 test files)
6. **Manual fingerprinting tests**:
   - WebGL spoofing
   - Canvas fingerprinting
   - Font fingerprinting
   - Audio context
   - Screen dimensions
   - Geolocation
   - WebRTC IP handling

**Success criteria**: All tests pass, all features work

### Phase 6: Cleanup & Documentation (30 min)

1. Remove all .rej, .orig, .bak files
2. Document changes made to each patch
3. Update changelog/release notes
4. Git commit updated patches
5. Tag release (if applicable)

---

## Time Estimates

| Phase | Optimistic | Realistic | Pessimistic |
|-------|-----------|-----------|-------------|
| Phase 1: Prep | ~~10 min~~ ✅ DONE | ~~15 min~~ ✅ DONE | ~~30 min~~ ✅ DONE |
| Phase 2: Critical | 4 hours | 6 hours | 8 hours |
| Phase 3: Stealth | 1.5 hours | 2.5 hours | 3.5 hours |
| Phase 4: LibreWolf | ~~1.5 hours~~ 30 min | ~~2.5 hours~~ 45 min | ~~3.5 hours~~ 70 min |
| Phase 5: Testing | 2 hours | 3 hours | 4 hours |
| Phase 6: Cleanup | 20 min | 30 min | 45 min |
| **TOTAL** | **8 hours** | **12.5 hours** | **17.75 hours** |

**Realistic estimate**: 1.5 work days (12-13 hours) - saved ~1.5 hours by updating LibreWolf patches

**Update**: LibreWolf update had mixed results:
- ✅ Fixed 2 patches automatically
- ❌ Introduced 1 new broken patch (mozilla_dirs)
- ❌ Net benefit: ~1.5 hours saved (not 2 hours as initially hoped)

---

## Tools & Commands Reference

### Reset workspace
```bash
make revert                    # Reset to unpatched state
```

### Developer GUI
```bash
make edits                     # Launch developer.py GUI
python3 scripts/developer.py 147.0b3 beta.25
```

### Edit single patch
```bash
make workspace ./patches/<patch-name>.patch
```

### Apply all patches
```bash
make dir
```

### Check for reject files
```bash
find camoufox-147.0b3-beta.25 -name "*.rej" -type f
```

### Build and test
```bash
make build                     # Full Firefox build
make run                       # Launch browser
make tests                     # Run automated tests
```

### Write updated patch
Use developer.py GUI: "Write workspace to patch"

---

## Success Criteria Checklist

- [ ] All 27 broken patches updated
- [ ] Zero .rej files after `make dir`
- [ ] Clean build with no compilation errors
- [ ] Browser launches successfully
- [ ] All 51 automated tests pass
- [ ] Manual fingerprinting tests verify features work:
  - [ ] WebGL spoofing active
  - [ ] Canvas fingerprinting working
  - [ ] Font fingerprinting working
  - [ ] Audio context spoofing working
  - [ ] Screen dimension spoofing working
  - [ ] Geolocation spoofing working
  - [ ] WebRTC IP handling working
  - [ ] Per-context isolation (Roverfox) working
- [ ] No console errors during normal browsing
- [ ] Updated patches committed to git
- [ ] Documentation updated

---

## Notes & Warnings

⚠️ **File Overlap Conflicts**:
- `dom/base/Navigator.cpp` - Modified by both Playwright AND fingerprint-injection
- `dom/base/nsGlobalWindowInner.cpp` - Modified by BOTH roverfox patches
- `dom/media/webrtc/jsapi/PeerConnectionImpl.cpp` - Modified by both WebRTC patches

These files need careful attention to ensure all patch intents are preserved.

⚠️ **Playwright Upstream Sync**:
The 0-playwright.patch is critical infrastructure. Check if Playwright has already updated for Firefox 147:
- https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff
- Check their supported Firefox versions

⚠️ **Build Time**:
Full Firefox builds can take 30-90 minutes depending on hardware. Plan accordingly.

⚠️ **Backup**:
Before starting, backup the current patches directory:
```bash
cp -r patches patches.backup.v135
```

---

**Document created**: 2025-12-19
**Firefox version**: v147.0b3-beta.25
**Previous version**: v135.0.1-beta.24
**Status**: Planning complete, ready for execution
