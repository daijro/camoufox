# Overview

The name of the game is to get all the patches to firefox applied successfully *and* have firefox compile.  Why?  **So this variant, Camoufox, remains stealthy and undetectable.**

## Critical: Stealth is Everything

**EVERY PATCH EXISTS FOR A REASON - TO KEEP CAMOUFOX STEALTHY**

When a patch fails, you MUST understand:
1. **What is the stealth goal?** What fingerprinting vector or detection method does this patch prevent?
2. **How does the original patch achieve that goal?** What specific code changes make Camoufox harder to detect?
3. **Has Firefox's architecture changed?** The code may have moved, but the stealth requirement hasn't.
4. **Replicate the intent, not just the code.** If Firefox changed how preferences work, you need to hide the same preferences in the new system.

**NEVER just delete a patch because it fails.** That's like removing your car's brakes because they squeak. The stealth requirement still exists - you just need to find where Firefox moved the code and apply the same defensive changes there.

### Camoufox's Purpose

Camoufox makes Firefox look like a normal user's browser to anti-bot systems. Patches do things like:
- Hide preferences that reveal automation (e.g., CFR recommendations that normal users see but are disabled in Camoufox)
- Spoof fingerprinting APIs (geolocation, fonts, media devices, canvas, WebGL)
- Remove telltale signs of modification (custom user-agent strings, automation flags)
- Disable features that leak information (network timing, hardware specs)

If a website can detect ANY mismatch between what the browser claims and what the UI/behavior shows, Camoufox is burned.

The camoufox root contains a Makefile and a ton of patches.  They are applied in alphabetical order by filename (not by directory structure). If there are actual dependencies between patches, they must be satisfied by this alphabetical ordering.

Then there is the firefox sourcecode directory.  This process assumes that it is a seperate git repo.  The author of this workflow file has actually set the repo to the firefox sourcecode repo (as opposed to the camoufox documentation, which starts with a zip file and then does a `git init && git commit` to have a repo with a single commit).

The firefox repo directory starts checked out to the matching git hash that playwright uses.  It gets tagged as `unpatched`.  A `make revert` will reset the repo to that specific tag.

Here are key commands:

```bash
make revert  # Start with clean Firefox source
make tagged-checkpoint  # Tag the current commit as "checkpoint"
make revert-checkpoint # Revert back to the "checkpoint"
make patch <patchfile> # apply the patch file
cd /home/azureuser/camoufox && python3 scripts/next_patch.py patches/<file>.patch # find next patch
make dir # apply all the patches. will bomb once it hits a failure.
```

# Workflow

## General Workflow

Follow the "Inital Workflow" unless the human says it's in a good state.

The general workflow assumes you've checkpointed the last working patch and you can roll back to it via `make revert-checkpoint`

1) Find next: `cd /home/azureuser/camoufox && python3 scripts/next_patch.py patches/<last-patch>.patch`
2) Apply it: `make patch <next-patchfile>`
3) Did it work?  Great!  Do a `make tagged-checkpoint` and go back to step 1
4) If it didn't work, then you need to figure out why.  IF YOU GET HERE, *STOP AND WAIT FOR HUMAN INTERVENTION!  THEY MAY WANT TO SWITCH LLM MODELS!!!!*  This is the hard part that requires actual "thinking".  See the "Fixing a broken patch" below.  The human will no doubt want to summon powerful models to do this....
5) Once you've walked through all the patches and they all work, do a `make revert && make dev`
6) I don't know what happens at this point.... so stop and say "hi".

### Shortcut:

Most of these patches will probably successfully apply... so you can "shortcut" the workflow into a single "opportunistic" command line.  When starting from a tagged checkpoint or the untagged branch you can do something like:

```bash
cd /home/azureuser/camoufox && make patch patches/webgl-spoofing.patch && make tagged-checkpoint && git add FIREFOX_142_UPGRADE_NOTES.md && echo "- \`patches/webgl-spoofing.patch\` - Applied (WebGL fingerprinting spoofing)" >> FIREFOX_142_UPGRADE_NOTES.md && git add FIREFOX_142_UPGRADE_NOTES.md && git commit -m "Document successful application of webgl-spoofing.patch" && python3 scripts/next_patch.py patches/webgl-spoofing.patch
```

it will apply the patch, tag the checkpoint, add notes, commit the mess and then print out the next patch to apply.  If `make patch` fails, it will fail before tagging the checkpoint. Just keep doing this over and over until either something fails or there are no more patches to apply!

## Fixing a broken patch
Fixing a broken patch is where all the thinking happens.  First the rules of engagement:

### STEP ZERO: UNDERSTAND THE STEALTH INTENT
**Before touching ANY code, answer these questions:**

1. **What stealth problem does this patch solve?**
   - Read the patch file. What is it modifying?
   - Is it hiding UI elements? Spoofing APIs? Removing telemetry?
   - Example: `remove-cfrprefs.patch` hides CFR recommendation checkboxes from preferences

2. **Why is this a stealth issue?**
   - What can websites detect if we DON'T apply this patch?
   - Example: CFR prefs are disabled in `camoufox.cfg`, but if the UI checkboxes are visible, automation can detect the mismatch: "disabled functionality with visible controls = modified browser"

3. **Has Firefox moved or refactored this code?**
   - Search the Firefox git history for the files being patched
   - Did they migrate from static XHTML to dynamic JS configs?
   - Did they rename functions or move them to different modules?
   - The STEALTH REQUIREMENT hasn't changed - only Firefox's architecture changed

4. **How do we achieve the same stealth goal in the new Firefox code?**
   - If they moved preferences from XHTML to JS configs, patch the JS config
   - If they renamed an API, patch the new API name
   - If they split functionality across files, patch all the files
   - **The goal is NOT to make the old patch work - it's to achieve the same stealth in the new Firefox**

### Now the code rules:
1) *DO NOT MODIFY THE PATCH FILE!!!*  We will regenerate the patch file!
2) *MODIFY THE SOURCE CODE SO IT IS WHAT WE WANT TO SEE*.  In otherwords, *you* have to do the work of changing the source code to achieve the stealth goal!
3) Once successful and all the hunks have been "recreated" in the source tree you do a `cd {ff_dir} && git diff > {patch_file}` to overwrite the patch file.  But first validate things are as-expected.

Remember, the patch file might have multiple hunks and only one failed.  You are about to overwrite the patch file with a blanket `git diff` so make sure all the hunks are going to be included.  This means the actual source code needs to be "what it should be after running the entire patch".  So `git status && git diff` and analyze the output.... does the changes in the repo reflect the intent of the original patch in it's entirety?  If not, you have work to do.  If you think it's good...

*STOP AND PROMPT THE HUMAN YOU THINK YOU ARE READY TO GENERATE THE NEW PATCH*

explain the research you did and why you are confident you nailed it.  Remember, in many cases you did some hard work, right? (right?)

Then and only then are you ready for this:

Example:

```bash
cd /home/azureuser/camoufox/camoufox-142.0.1-bluetaka.25 && git diff  > ../patches/font-hijacker.patch
```

[BAD EMOJI] You are *not* doing a selective diff (eg `git diff -- layout/style/moz.build > ../patches/font-hijacker.patch`)!  *NO*..  you are creating a patch file to encompass all changes to the *entire* repo!  So do a `git status` to make sure everything the original patch file changed (sans any intentional removals or additions) is included.
4) Validate: Do a `git diff` on the patch file and confirm it changed what you expected.  Did you miss hunks that should have been patched?  If you did, you aren't ready for the next step.  Stop right now and wait for human help.  In short, you missed something!
5) Test: Confirm it works by doing a `make revert-checkpoint` to go back to working state, apply the patch `make patch patchfile`, then a `git status` / `git diff` to confirm it applies as expected
6) Notate: Update the [FIREFOX_142_UPGRADE_NOTES.md] file with the patch you fixed and what your research showed.  This is important because we are intentionally not building firefox each patch.... for all we know we broke the build!
7) Commit: Commit the patch and changes to the upgrade notes with a good description in the main repo.
8) Checkpoint: Do a `make tagged-checkpoint` in the firefox repo since the repo is now at a working good state.
9) Next: `cd /home/azureuser/camoufox && python3 scripts/next_patch.py patches/font-hijacker.patch` to find what's next

### Investigation Guidelines:

1) **Read the patch file and understand the stealth goal**
   - What is it modifying? UI elements? API functions? Build configs?
   - What fingerprinting vector does this prevent?
   - What would an anti-bot system detect without this patch?

2) **Determine why it failed**
   - Mismatched line numbers? (Firefox added/removed code nearby)
   - File doesn't exist? (Firefox moved/renamed the file)
   - Function doesn't exist? (Firefox refactored the API)

3) **Research Firefox's changes**
   - Search git history for the files being patched
   - Look for architectural changes (e.g., XHTML → JS configs, static → dynamic)
   - Find where the functionality moved in the new Firefox

4) **Apply the stealth fix to the new location**
   - Don't just make the old patch apply - achieve the same stealth goal in the new code
   - Example: If preferences moved from `main.inc.xhtml` to `main.js` config, patch `main.js`

5) **Verify the stealth goal is achieved**
   - The UI should match what a normal user would see
   - Disabled features should not have visible controls
   - Spoofed APIs should return consistent values
   - No telltale signs of modification should be detectable

6) **Only delete a patch if Firefox implements the stealth feature natively**
   - Example: If Firefox now hides CFR prefs by default for all users
   - Verify by checking Firefox's default config and UI
   - Document why the feature is now native in `FIREFOX_142_UPGRADE_NOTES.md`

7) Update this doc if you have any new insights

## Initial Workflow
If you start from `unpatched` (no checkpoints exist):

1) `make dir` to start the process
2) Hopefully all the patches apply, but if not then we have work to do....

## Getting to a known state...

Human says "workspace is not in a clean state! clean it up!" or if you aren't sure what state the firefox git repo is but you know the last working patch, you can do the following:

```bash
cd {repodir} && git status # Is there anything outstanding?  If yes, HALT! Summon your human!
make revert
make patch ./patches/patch1.patch && make patch ./patches/patch2.patch ..... # one make per successful patch.  do them all in a single line or you'll annoy the human!
make tagged-checkpoint # boom you are in business
```

Tip: If you know the last successful patch, use `cd /home/azureuser/camoufox && python3 scripts/next_patch.py patches/config.patch` to find what's next.
### How to know which patches succeeded?

Hopefully the human gave you the results of `make dev`.... well look at it and you'll see each patch

eg: `*** -> patch -p1 -i ../patches/librewolf/ui-patches/firefox-view.patch`
Look for the ones like:
```
*** -> patch -p1 -i ../patches/disable-remote-subframes.patch
patch -p1 -i ../patches/disable-remote-subframes.patch
patching file docshell/base/BrowsingContext.cpp
Hunk #1 succeeded at 85 (offset 2 lines).
Hunk #2 succeeded at 1804 (offset 31 lines).
patching file docshell/base/moz.build
```

thats a successful one!  You'll see a whole bunch of those.... collect the patch files and then apply them in the same order as on the command line result...

here is the failed one

```
*** -> patch -p1 -i ../patches/font-hijacker.patch
patch -p1 -i ../patches/font-hijacker.patch
patching file gfx/thebes/gfxPlatformFontList.cpp
Hunk #2 succeeded at 307 (offset 3 lines).
patching file gfx/thebes/moz.build
Hunk #1 succeeded at 303 (offset -2 lines).
patching file layout/style/FontFace.cpp
Hunk #1 succeeded at 243 (offset 6 lines).
Hunk #2 succeeded at 262 (offset 6 lines).
patching file layout/style/FontFaceImpl.cpp
Hunk #1 succeeded at 358 (offset 1 line).
patching file layout/style/FontFaceImpl.h
Hunk #1 succeeded at 8 with fuzz 2.
Hunk #2 succeeded at 33 (offset -3 lines).
patching file layout/style/moz.build
Hunk #1 FAILED at 351.
1 out of 1 hunk FAILED -- saving rejects to file layout/style/moz.build.rej
fatal error: command 'patch -p1 -i ../patches/font-hijacker.patch' failed
make: *** [Makefile:108: dir] Error 1
```