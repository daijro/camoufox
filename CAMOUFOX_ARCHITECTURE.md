# Camoufox Architecture & Design Decisions

This document explains Camoufox's architectural decisions, particularly how it differs from other Firefox forks and how patches should interact with Firefox's built-in features.

## Core Mission: Stealth Over Privacy

**Camoufox is NOT a privacy browser - it's a STEALTH browser.**

- **Privacy browsers** (LibreWolf, Tor Browser): Remove telemetry, block tracking, protect user privacy
- **Stealth browsers** (Camoufox): Look identical to vanilla Firefox to avoid detection by anti-bot systems

This difference is critical when deciding whether to keep or modify patches.

### Decision Framework: Keep or Delete a Patch?

When evaluating patches (especially LibreWolf patches):

**✅ KEEP if it prevents detection:**
- Hides disabled features from UI (e.g., removing CFR preference checkboxes)
- Spoofs fingerprinting APIs to return believable fake data
- Removes telltale signs of automation/modification

**❌ DELETE if it breaks vanilla Firefox compatibility:**
- Removes features that normal Firefox users have (e.g., "Report Broken Site")
- Creates detectable differences in behavior or UI
- Prioritizes privacy over looking normal

**Example: `remove_addons.patch`**
- **What it does:** Removes "Report Broken Site" feature
- **LibreWolf rationale:** Prevents telemetry to Mozilla (privacy)
- **Camoufox decision:** DELETE - Normal Firefox has this feature; removing it is detectable
- **Trade-off:** Accept some telemetry risk to maintain perfect vanilla Firefox appearance

## Firefox's Resist Fingerprinting (RFP) vs. Camoufox's MaskConfig

### What is RFP?

Firefox's `privacy.resistFingerprinting` (RFP) is a **holistic anti-fingerprinting mode** that:
- Returns generic values for ~50+ fingerprinting vectors
- WebGL: Returns "Mozilla" for vendor/renderer
- Canvas: Adds randomization
- Timers: Reduces precision
- Screen: Spoofs resolution
- Fonts: Blocks enumeration
- And many more...

**Default:** `false` (disabled) for 99%+ of Firefox users
**Mozilla's stance:** "Undocumented, not-recommended footgun" (firefox.js:1681)

### Camoufox's RFP Policy

**Camoufox disables RFP by default** (`camoufox.cfg` line 335):
```javascript
defaultPref("privacy.resistFingerprinting", false);
```

**Why?**
1. RFP's generic values ("Mozilla") are themselves fingerprintable
2. Most Firefox users don't use RFP - Camoufox should match the majority
3. Camoufox uses MaskConfig for **believable, varied spoofing** instead of RFP's fixed values

### MaskConfig vs. RFP: Design Pattern

**CRITICAL RULE: MaskConfig Takes Precedence Over RFP**

When patching Firefox code that has both RFP and real values:

```cpp
// CORRECT PATTERN: MaskConfig first, then RFP, then real
if (auto value = MaskConfig::GetSomething("key")) {
  return value.value();  // Camoufox config wins
}
if (ShouldResistFingerprinting(RFPTarget::Something)) {
  return "Mozilla";  // Firefox RFP if enabled
}
return GetRealValue();  // Normal Firefox behavior
```

**Why MaskConfig takes precedence:**

1. **User is being explicit:** Setting MaskConfig values is a deliberate action
2. **RFP is disabled by default in Camoufox:** Most users never have RFP enabled anyway
3. **Consistency with existing patches:** `screen-hijacker.patch`, `media-device-spoofing.patch` all check MaskConfig first
4. **Principle of least surprise:** "I set webGl:renderer, it should use that value"

**Edge case: What if someone enables RFP=true in Camoufox?**
- If they DON'T set MaskConfig values: RFP works normally (returns "Mozilla")
- If they DO set MaskConfig values: MaskConfig overrides RFP (user's explicit choice)
- This is probably a misconfiguration anyway - they should use Tor Browser for that

**Why NOT put MaskConfig inside the RFP `else` block?**

If we did this:
```cpp
// WRONG PATTERN: MaskConfig only when RFP is off
if (ShouldResistFingerprinting(...)) {
  return "Mozilla";
} else {
  if (auto value = MaskConfig::GetSomething("key")) {
    return value.value();
  }
  return GetRealValue();
}
```

**Problems:**
- ❌ Inconsistent with other Camoufox patches
- ❌ User's explicit MaskConfig settings get ignored if RFP is enabled
- ❌ Less flexible for advanced use cases

**But wait, doesn't this create inconsistent fingerprints if RFP is enabled?**

Yes! If someone enables RFP=true AND sets MaskConfig values, you could get:
- Timer precision: 100µs (RFP enabled)
- Canvas: Randomized (RFP enabled)
- WebGL: Custom spoofed values (MaskConfig override)

**This is detectable!** However:
1. Camoufox disables RFP by default, so this edge case rarely happens
2. If someone enables RFP AND sets MaskConfig, they're making an advanced/intentional choice
3. The alternative (ignoring MaskConfig when RFP is on) breaks user expectations

**Trade-off:** Accept potential RFP inconsistency edge case to maintain user control and pattern consistency.

## WebGL Spoofing Strategy

### Why Spoof WebGL Instead of Using RFP?

**Firefox RFP WebGL behavior:**
- Returns "Mozilla" for vendor/renderer
- Fixed, hardcoded values
- Detectable: `if (renderer === "Mozilla") { /* This is RFP/Tor Browser */ }`

**Camoufox WebGL approach:**
- Returns believable fake GPU data from research database
- Per-session variation (looks like different real users)
- Internally consistent (vendor + renderer + extensions + parameters all match real GPUs)

**Stealth comparison:**

| Approach | Vendor | Renderer | Detectable? |
|----------|--------|----------|-------------|
| Normal Firefox (RFP=false) | "Google Inc. (NVIDIA)" | "ANGLE (NVIDIA, GTX 980...)" | No (this is normal) |
| Firefox RFP (RFP=true) | "Mozilla" | "Mozilla" | Yes (known RFP signature) |
| **Camoufox (MaskConfig)** | "Google Inc. (NVIDIA)" | "ANGLE (NVIDIA, GTX 980...)" | **No (indistinguishable from normal)** |

### WebGL Research Database

Camoufox maintains a database of real-world Firefox WebGL fingerprints at:
- https://camoufox.com/webgl-research/
- https://camoufox.com/tests/webgl

**Key requirement:** Spoofed values must be **internally consistent**:
- Vendor + Renderer must be a real combination
- Supported extensions must match that GPU
- Shader precision formats must match that GPU's capabilities
- GL parameters must be consistent with that GPU

**Without consistency:**
```
Anti-bot: "You claim to have Intel HD Graphics, but your shader precision
           formats match NVIDIA hardware. BLOCKED!"
```

**With consistency (Camoufox's approach):**
```
Anti-bot: "Intel HD Graphics + matching extensions + matching shaders +
           matching parameters = Looks like a real Intel user."
```

### Supported WebGL Properties

See the full list in Camoufox documentation, but key properties:
- `webGl:renderer` / `webGl:vendor` - GPU identification
- `webGl:supportedExtensions` - GPU capabilities
- `webGl:contextAttributes` - WebGL context config
- `webGl:parameters` - GL state parameters
- `webGl:shaderPrecisionFormats` - Shader capabilities

## Canvas Fingerprinting

TODO: Document canvas fingerprinting strategy

## Timezone & Geolocation Spoofing

TODO: Document timezone/geolocation strategy

## Font Fingerprinting

TODO: Document font enumeration strategy

## Historical Context: Firefox 141 RFP Changes

### Bug 1966860 (Firefox 141)

**What happened:**
- Website `chat.qwen.ai` broke when RFP was enabled
- Firefox was blocking `WEBGL_debug_renderer_info` extension entirely
- Firefox 141 changed to: **enable the extension but spoof the vendor/renderer values**

**Code change:**
```cpp
// OLD: Extension blocked when RFP enabled
case UNMASKED_RENDERER_WEBGL:
  ret = GetUnmaskedRenderer();

// NEW: Extension enabled, values spoofed
case UNMASKED_RENDERER_WEBGL:
  if (ShouldResistFingerprinting(RFPTarget::WebGLRenderInfo)) {
    ret = Some("Mozilla"_ns);  // Generic value
  } else {
    ret = GetUnmaskedRenderer();  // Real GPU
  }
```

**Impact on Camoufox:**
- Previous patches could inject MaskConfig before the direct `GetUnmaskedRenderer()` call
- New code needs MaskConfig injected **inside the conditional structure**
- Pattern: MaskConfig first, then RFP, then real value

## Patch Compatibility Patterns

### Pattern 1: Simple Injection (Pre-Firefox 141)

```cpp
// OLD Firefox code (no RFP conditional)
value = GetRealValue();

// Camoufox patch (simple injection)
if (auto spoofed = MaskConfig::Get("key")) {
  value = spoofed.value();
} else {
  value = GetRealValue();
}
```

### Pattern 2: RFP-Aware Injection (Post-Firefox 141)

```cpp
// NEW Firefox code (with RFP conditional)
if (ShouldResistFingerprinting(...)) {
  value = "Generic";
} else {
  value = GetRealValue();
}

// Camoufox patch (inject before RFP)
if (auto spoofed = MaskConfig::Get("key")) {
  value = spoofed.value();  // MaskConfig first!
} else if (ShouldResistFingerprinting(...)) {
  value = "Generic";
} else {
  value = GetRealValue();
}
```

### Pattern 3: Complete RFP Replacement

Some patches completely remove Firefox's RFP logic:

```cpp
// Example: media-device-spoofing.patch
// Removes entire RFP block, replaces with MaskConfig logic
if (!MaskConfig::GetBool("mediaDevices:enabled")) {
  return exposed;  // Bypass all spoofing
}
// Custom device spoofing logic here...
```

**When to use:**
- When Camoufox's spoofing is more sophisticated than RFP
- When RFP's behavior doesn't align with stealth goals
- When you need fine-grained control beyond RFP's all-or-nothing approach

## Future Firefox Upgrades

### Common RFP-Related Failures

When upgrading Firefox, RFP-related patches may fail if:

1. **Firefox adds RFP to new areas**
   - New `ShouldResistFingerprinting(RFPTarget::NewThing)` calls
   - Solution: Inject MaskConfig before the RFP check

2. **Firefox refactors RFP implementation**
   - Code structure changes (like Firefox 141's WebGL refactor)
   - Solution: Adapt patch to new structure, maintaining MaskConfig-first precedence

3. **Firefox removes features entirely**
   - Check if feature was replaced or truly removed
   - Verify stealth impact before deleting patch

### Debugging RFP Conflicts

```bash
# Find all RFP calls in a file
grep -n "ShouldResistFingerprinting\|ResistFingerprinting" path/to/file.cpp

# Check Firefox's git history for RFP changes
cd camoufox-142.0.1-bluetaka.25
git log --all --grep="RFP\|ResistFingerprinting" --oneline -- path/to/file.cpp

# See what changed between versions
git diff OLD_COMMIT..NEW_COMMIT -- path/to/file.cpp
```

## LibreWolf Patches: Compatibility Analysis

Camoufox inherits many patches from LibreWolf, but they serve different purposes:

| Patch Type | LibreWolf Goal | Camoufox Goal | Keep? |
|------------|----------------|---------------|-------|
| Remove telemetry | Privacy | May hurt stealth if detectable | Evaluate case-by-case |
| Remove Mozilla services | Privacy | May hurt stealth | Evaluate case-by-case |
| Hide preference UI | Privacy | **Stealth** (if feature is disabled) | ✅ Keep |
| Spoof APIs | Not typical | **Stealth** (core mission) | ✅ Keep |
| Remove features | Privacy | May hurt stealth | ⚠️ Usually delete |

**Example decisions:**
- ✅ `remove-cfrprefs.patch` - KEEP (hides disabled UI, prevents mismatch detection)
- ❌ `remove_addons.patch` - DELETE (removes "Report Broken Site" that normal users have)

## MaskConfig System

### What is MaskConfig?

MaskConfig is Camoufox's C++ configuration system located in `/camoucfg/MaskConfig.hpp`.

It provides:
- `GetString(key)` - Get string values
- `GetInt32(key)` - Get integer values
- `GetDouble(key)` - Get double values
- `GetBool(key)` - Get boolean values
- `CheckBool(key)` - Check if boolean is true
- `GetStringList(key)` - Get array of strings
- `GetAttribute<T>(key, isWebGL2)` - Get WebGL-specific attributes
- `MParamGL<T>(glenum, default, isWebGL2)` - Get GL parameters
- `MShaderData(shadertype, precisiontype, isWebGL2)` - Get shader precision data

### Configuration Sources

MaskConfig reads from:
1. Command-line arguments passed to Camoufox
2. Environment variables
3. Configuration files (exact mechanism TBD - needs documentation)

Values are set by the Camoufox Python library when launching browser instances.

### Integration Pattern

When adding MaskConfig to Firefox code:

1. **Include the header:**
   ```cpp
   #include "MaskConfig.hpp"
   ```

2. **Add to build system:**
   ```python
   LOCAL_INCLUDES += ["/camoucfg"]
   ```

3. **Check values before using real APIs:**
   ```cpp
   if (auto spoofed = MaskConfig::GetString("key")) {
     return spoofed.value();
   }
   return GetRealValue();
   ```

## Patch Update Checklist

When a patch fails during Firefox upgrade:

- [ ] Read the patch file - understand what it's doing
- [ ] Identify the stealth goal - what fingerprinting vector does it prevent?
- [ ] Check Firefox git history - what changed?
- [ ] Search for RFP involvement - did Firefox add `ShouldResistFingerprinting` calls?
- [ ] Determine the fix:
  - Simple line number shift? → Update line numbers
  - Code refactored? → Adapt to new structure
  - Architecture changed? → Replicate intent in new architecture
  - Feature removed? → Check if it was replaced or truly removed
  - Conflicts with RFP? → Inject MaskConfig before RFP checks
- [ ] Fix the source code (don't modify patch file yet)
- [ ] Verify all hunks are represented in the changes
- [ ] Regenerate patch: `git diff > ../patches/patch-name.patch`
- [ ] Test: `make revert-checkpoint && make patch patches/patch-name.patch`
- [ ] Document in commit message (details) and FIREFOX_142_UPGRADE_NOTES.md (summary)
- [ ] Commit: `git add patches/patch-name.patch FIREFOX_142_UPGRADE_NOTES.md && git commit -m "..."`
- [ ] Checkpoint: `make tagged-checkpoint`

## Case Study: WebGL Spoofing and Firefox 141 RFP Changes

### The Challenge

**Firefox 141 (Bug 1966860)** changed WebGL's RFP implementation:

**Before Firefox 141:**
```cpp
case UNMASKED_RENDERER_WEBGL:
  ret = GetUnmaskedRenderer();  // Simple, direct call
```

**After Firefox 141:**
```cpp
case UNMASKED_RENDERER_WEBGL:
  if (ShouldResistFingerprinting(RFPTarget::WebGLRenderInfo)) {
    ret = Some("Mozilla"_ns);  // RFP path
  } else {
    ret = GetUnmaskedRenderer();  // Normal path
  }
```

### The Camoufox Fix

**Goal:** Inject MaskConfig to return believable fake GPU names (not "Mozilla")

**Implementation:**
```cpp
case UNMASKED_RENDERER_WEBGL:
  // STEP 1: Check MaskConfig first (takes precedence)
  if (auto value = MaskConfig::GetString("webGl:renderer")) {
    ret = Some(value.value());
    break;
  }
  // STEP 2: Then Firefox's RFP (if user enabled it)
  if (ShouldResistFingerprinting(RFPTarget::WebGLRenderInfo)) {
    ret = Some("Mozilla"_ns);
  } else {
    // STEP 3: Finally, real GPU (vanilla Firefox behavior)
    ret = GetUnmaskedRenderer();
    if (ret && StaticPrefs::webgl_sanitize_unmasked_renderer()) {
      ret = Some(webgl::SanitizeRenderer(*ret));
    }
  }
  break;
```

### Why This Approach?

**Stealth analysis:**

| Scenario | MaskConfig Set? | RFP Enabled? | Returns | Stealth Impact |
|----------|----------------|--------------|---------|----------------|
| Normal Camoufox user | ✅ Yes | ❌ No (default) | Fake GPU from research DB | ✅ Looks like normal Firefox user with that GPU |
| Camoufox without config | ❌ No | ❌ No (default) | Real GPU | ✅ Looks like normal Firefox user |
| Advanced user | ✅ Yes | ✅ Yes (manual) | Fake GPU (MaskConfig wins) | ⚠️ Inconsistent RFP, but user chose this |
| Misconfigured | ❌ No | ✅ Yes (manual) | "Mozilla" | ✅ Looks like Firefox/Tor with RFP |

**The pattern respects user intent while maintaining stealth for the default use case.**

### Alternative Considered and Rejected

**Option B: MaskConfig only when RFP=false**
```cpp
if (ShouldResistFingerprinting(...)) {
  ret = Some("Mozilla"_ns);  // RFP always wins
} else {
  if (auto value = MaskConfig::GetString("webGl:renderer")) {
    ret = Some(value.value());
  }
  ret = GetUnmaskedRenderer();
}
```

**Why rejected:**
- Violates user expectations ("I set webGl:renderer, why doesn't it work?")
- Inconsistent with other Camoufox patches (screen-hijacker, media-device-spoofing)
- Less flexible for advanced users who want MaskConfig + RFP for specific scenarios

## When to Delete vs. Fix Patches

### Delete a Patch When:

1. **Firefox implements the stealth feature natively FOR ALL USERS**
   - Example: `allow-searchengines-non-esr.patch` (Firefox 142 added SearchEngines support)
   - Verify: Check Firefox's default config, not just RFP mode

2. **Patch conflicts with stealth mission**
   - Example: `remove_addons.patch` (removing features makes Camoufox detectable)
   - Test: Does removing this feature make Camoufox look different from vanilla Firefox?

3. **Feature is completely obsolete**
   - Firefox removed the entire subsystem
   - No replacement exists
   - Feature was never about stealth (e.g., build system optimization)

### Fix a Patch When:

1. **Firefox refactored but feature still exists**
   - Example: Preferences moved from XHTML to JS config → patch the JS config
   - Example: WebGL code added RFP conditionals → inject MaskConfig before RFP

2. **Line numbers shifted**
   - Firefox added/removed code nearby
   - Simple offset, no logic changes

3. **Firefox changed implementation but stealth goal remains**
   - Example: Component registration moved from BrowserGlue to BrowserComponents.manifest
   - Find new location, apply same modification

### Red Flags (Stop and Ask)

- Patch modifies 10+ files and all fail
- Can't find where Firefox moved the functionality
- Unsure if feature still exists in any form
- Multiple LibreWolf privacy patches failing (may conflict with stealth)
- Build system changes you don't understand

## Notes for Future Maintainers

### Firefox ESR vs. Release Cycle

- Camoufox targets Firefox Release (not ESR)
- Some LibreWolf patches are ESR-specific (e.g., SearchEngines)
- Check patch applicability for Release channel

### Playwright Dependency

- Camoufox uses Playwright's Firefox fork
- Playwright patches must apply cleanly
- Don't modify Playwright patches without understanding impact

### Testing Philosophy

**We intentionally DON'T build Firefox after every patch** because:
- Build takes ~1 hour
- Most patches are low-risk
- Final build test happens at the end

**Risk:** A patch might apply cleanly but break the build
**Mitigation:** Document each patch's changes in FIREFOX_142_UPGRADE_NOTES.md

## Contributing

When adding new patches:

1. **Document the stealth goal** - Why does this patch exist?
2. **Check for RFP conflicts** - Does Firefox already do something similar?
3. **Follow MaskConfig patterns** - Consistent with existing patches
4. **Test with WebGL research data** - Ensure spoofed values are believable
5. **Consider detection vectors** - How could anti-bot systems detect this?

When you're building something that normal Firefox users would never have, **stop and reconsider** - you might be creating a fingerprinting vector instead of preventing one.

