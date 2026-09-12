# Tests

Two things live here, and neither is a copy of anyone else's suite.

### `patches/` — patch guards

One standalone script per shipped spoofing behaviour: isolated evaluate, trusted
events, font spoofing, mouse trajectories, the touchscreen digitizer, and so on.
Each exits 0 or 1 and drives the browser through the Python package.

These are the most direct evidence that a Firefox bump did not quietly neuter a
patch that still *applies* cleanly — the failure a compile check cannot catch.

```bash
python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin
python3 -m ci.run_patch_guards --binary /path/to/camoufox-bin --only isolated-evaluate
```

### `camoufox/` — Camoufox's own Playwright tests

Tests for behaviour upstream Playwright has no equivalent for, or asserts the
opposite of on purpose. `ci/suite.py` overlays them onto the upstream checkout
so they run against its harness. See `camoufox/README.md` for when to add one.

---

## Where the Playwright suite went

This directory used to hold a fork of a ~v1.55-era playwright-python suite. It
was deleted, because measuring it showed it was strictly weaker than running
upstream's own suite:

- **73 of the 74 tests it skipped as "Not supported by Camoufox" pass** when the
  same binary runs upstream's copy. The skips predated main-world execution and
  were never revisited; the suite was asserting that Camoufox was worse than it
  is.
- Of its passing tests, **eight had no upstream counterpart**. Six of those were
  Camoufox-specific and are now the three modules in `camoufox/`; the other two
  were tests upstream had since renamed.
- Everything else was upstream code, one generation stale.

`ci/run_playwright.py` fetches playwright-python at the tag `ci/versions.py`
resolves for the browser under test, applies `ci/skiplist.yml`, and overlays
`camoufox/`. A suite that is re-fetched every run cannot go stale, and a
deliberate difference from upstream now has to be written down in the skiplist
with a reason instead of being encoded as a silent fork.

```bash
make tests                  # the whole suite
make tests headful=true     # ... headed
python3 -m ci.run_playwright --binary /path/to/camoufox-bin --shard 3/6
```
