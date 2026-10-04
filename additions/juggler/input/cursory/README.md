# cursory-js (vendored)

Camoufox's copy of [cursory-js](https://github.com/JWriter20/cursory-js) v2.0.2,
a TypeScript port of [Vinyzu's Cursory](https://github.com/Vinyzu/cursory)
v2.0.1. It generates the cursor paths `humanize=True` moves along.

Licensing and provenance are in `NOTICE`; the licence text is in `LICENSE`.
**These files are LGPLv3-or-later, not MPL-2.0 like the rest of Camoufox.**

## What it does

Cursory does not draw a curve. It holds 2356 mouse movements recorded from real
people, picks one whose direction, distance and wander suit the requested move,
then morphs, knots, jitters and resamples it onto the requested endpoints. What
comes back is a real hand's path and a real hand's timing — including its
hesitations — rather than a shape from an equation.

That is the reason for the swap. A Bézier curve is smooth in a way hands are
not: constant-cadence samples along an analytic curve give velocity and jerk
profiles that a classifier can separate from human movement without much
trouble. Replayed recordings do not have that tell.

## How Camoufox calls it

`../CursorTrajectory.js` is the only caller. Nothing else should import from
this directory.

## Local modifications

Kept to the minimum, so refreshing from upstream stays a copy-and-strip:

- **TypeScript stripped.** These are the upstream `src/*.ts` with type
  annotations, interfaces and `as` casts removed and nothing else changed.
  Import specifiers gained `.js` so Firefox's module loader resolves them.
- **`data.js`** reads the database over a `chrome://` channel instead of with
  `node:fs`/`node:zlib`, and `trajectories.json` is stored uncompressed.
- **`random/pcg64.js`** seeds itself from the Web Crypto API rather than
  `node:crypto`.
- **`index.ts` is not vendored.** `CursorTrajectory.js` imports `cursory.js`
  directly.

Both API substitutions are marked `CAMOUFOX:` in the files themselves.

## Updating

1. `npm pack cursory-js@<version>`, or clone the repo for the `src/` tree.
2. Replace each `.js` here with the matching `src/*.ts`, stripping the types.
3. Re-apply the two `CAMOUFOX:` substitutions and the `.js` import suffixes.
4. `gunzip -c src/trajectories.json.gz > trajectories.json`.
5. Re-run the parity check below, then
   `python3 tests/patches/humanize-mouse-trajectory.py` against a build.

## Parity

The port reproduces the Python original bit for bit, which is worth keeping
true: it is what lets a bug here be reproduced against `pip install cursory`.
Upstream's `test/fixtures/parity.json` is recorded Python output — run this
port against it after any change to these files. Last checked against cursory
2.0.1 / numpy 2.3.5: RNG streams identical for all 12 seeds, all 149 recorded
trajectories' timings identical, worst coordinate gap 1.36e-12 px (V8 and
glibc round `exp`, `atan2` and friends differently; nothing a cursor can
express).
