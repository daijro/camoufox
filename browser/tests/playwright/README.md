# Tests

Two things live here, and neither is a copy of anyone else's suite.

### `patches/` — patch guards

One standalone script per shipped behaviour. Each exits 0 or 1 and drives the
browser through the Python package. Whether the patches *apply* is the build's
check; these are the most direct evidence that a Firefox bump did not quietly
neuter a patch that still applies cleanly — the failure a compile check cannot
catch.

Each guard belongs to one of three groups (`GROUPS` in
`ci/run_patch_guards.py`), and CI runs each group as its own job:

- **spoofing**: a spoofed value still reaches the page and holds together (media devices, voices, fonts, the touchscreen digitizer, the sealed setters, …);
- **automation**: Playwright stays invisible to the page and never deadlocks it (isolated evaluate, trusted events, humanized and edge-case mouse input, …);
- **parity**: what a page or the OS can observe matches stock Firefox (content-accessible files, GPU probes, browser-owned WebGL and WebGPU values against stock Firefox of the same version, the popup blocker, the Windows manifest, …).

A new guard must be added to a group; `ci/tests` fails until it is.

```bash
python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin --group automation
python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin --only isolated-evaluate
```

### `camoufox/` — Camoufox's own Playwright tests

Tests for behaviour upstream Playwright has no equivalent for, or asserts the
opposite of on purpose. `ci/suite.py` overlays them onto the upstream checkout
so they run against its harness. See `camoufox/README.md` for when to add one.

---

## Why there is no vendored suite

This directory used to hold a fork of a v1.55-era playwright-python suite. It
was deleted because it was weaker than upstream's own: 73 of the 74 tests it
skipped as "Not supported by Camoufox" passed in upstream's copy, and only eight
of its passing tests had no upstream counterpart (six now live in `camoufox/`,
the other two had been renamed upstream).

`ci/run_playwright.py` instead fetches playwright-python at the tag
`ci/versions.py` resolves, applies `ci/skiplist.yml` and overlays `camoufox/`.
A suite fetched every run cannot go stale, and a deliberate difference from
upstream has to be written in the skiplist with a reason. How the suite runs:
[`ci/README.md`](../../../ci/README.md#the-playwright-suite).

```bash
make -C browser tests                  # the whole suite
make -C browser tests headful=true     # ... headed
python3 -m ci.run_playwright --binary /path/to/camoufox-bin --shard 3/6
```
