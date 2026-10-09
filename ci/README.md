# The test pipeline

Everything that runs a suite against Camoufox. The same definition runs on a
pull request, on a push to `main` (through `release.yml`), and for any caller of
the `workflow_call` trigger that wants a specific browser version, so there is
one meaning of "the tests pass". Every job can be run locally
([Running a piece by hand](#running-a-piece-by-hand)).

```
resolve ── static ─────────────── lint, tribal rules, skiplist, self-tests  (seconds)
             ├─ typescript ────── type check, lint, vitest, golden parity
             ├─ install ───────── packed packages + a real `camoufox fetch`
             └─ pythonlib ─────── the package's own tests                   (a minute)
                  └─ build or fetch ─┬─ patch guards × 3 + skiplist audit
                                     ├─ build-tester ─────── 8 fingerprint profiles
                                     ├─ typescript-browser ─ the npm launcher end to end
                                     └─ once guards and build-tester pass:
                                          ├─ playwright × 6 shards   (upstream suite + our own)
                                          ├─ native ───────── leaks, contexts, crash recovery
                                          ├─ sundial ──────── stealth grade
                                          └─ growth × 7 shards  memory growth, one test per runner
                                  │
                               summary ──► one comment on the PR ──► gate: "All tests passed"
```

## Jobs

| Job | Runner | What it proves |
|---|---|---|
| `static` | `ci.run_native --subset rules`, `pytest ci/tests`, `browser/scripts/check-input-dispatch.py` | Settled decisions still hold, the skiplist is valid, input goes through one chokepoint, the pipeline reports honestly |
| `pythonlib` | `ci.run_pythonlib` | `python/`'s own tests |
| `typescript` | `ci.run_typescript` | Type check, lint, vitest, byte-for-byte parity with `python/` |
| `install` | `ci.run_install` | The packed packages install into clean environments and fetch a real browser |
| `build` / `fetch-browser` | `ci.run_prepare`, `ci.run_build` | The browser under test: compiled from this branch, or the published release built from the same sources |
| `patch-guards` | `ci.run_patch_guards --group spoofing\|automation\|parity`, `ci.run_skiplist_audit` | One guard per shipped behaviour ([`browser/tests/playwright/`](../browser/tests/playwright/README.md)); every skiplist entry still fails |
| `build-tester` | `ci.run_build_tester` | The raw binary against the anti-detect checks ([README](../browser/tests/build-tester/README.md)) |
| `typescript-browser` | `ci.run_typescript --browser` | The npm launcher against a real browser |
| `playwright` | `ci.run_playwright --shard i/6` | Upstream playwright-python's suite, plus [`browser/tests/playwright/camoufox/`](../browser/tests/playwright/camoufox/README.md) |
| `native` | `ci.run_native --subset browser` | Leaks, context isolation, crash recovery ([below](#camoufoxs-own-suite)) |
| `growth` | `ci.run_native --subset growth --shard i/7` | Memory growth, one test per runner |
| `sundial` | `ci.run_sundial` | The stealth grade ([below](#stealth-grade)) |
| `summary` | `ci.summarize` | Folds every result into one table and a pull request comment |
| `gate` | | The required check, **`All tests passed`** |

## Which browser, which suite

`ci/versions.py` answers both, and every entry point uses it:

| Question | Answer |
|---|---|
| Browser | `browser/upstream.sh`, or the version a caller passes |
| Suite | The newest released playwright-python tag whose pinned Firefox is not ahead of that browser, and which is below the Playwright ceiling in `python/pyproject.toml` |

Playwright trails Firefox and skips versions, so the suite's Firefox is often a
release or two behind the browser. That is the normal case; the summary says
which rule picked the tag. The ceiling exists because `camoufox.server` imports
a private Playwright API and every Playwright minor may change Juggler.

```bash
python3 -m ci.versions --json
python3 -m ci.versions --browser-version 153.0.4 --json
```

Only suite selection follows `--browser-version`; the build always reads
`upstream.sh`. `--check-upstream`, which the workflow passes, refuses a version
the branch does not pin, so an old browser is never judged against a new suite.
An upgrade to a new Firefox is therefore a branch that edits `upstream.sh`.

## The Playwright suite

Upstream playwright-python at the resolved tag, fetched fresh every run and run
unmodified. `ci/pw_camoufox_plugin.py` adapts the environment around it, and
`ci/suite.py` overlays [`browser/tests/playwright/camoufox/`](../browser/tests/playwright/camoufox/README.md).
Why there is no vendored copy: [`browser/tests/playwright/README.md`](../browser/tests/playwright/README.md#why-there-is-no-vendored-suite).

`ci/run_playwright.py` names its targets explicitly, so nothing is left out
silently:

| Targets | How they run |
|---|---|
| `tests/async/`, `tests/sync/` | One pytest process |
| `tests/common/`, `tests/test_reference_count_async.py` | Their own process: they start their own event loop |
| `tests/test_installation.py` | Excluded, with a reason |

`unclaimed()` fails the run if upstream adds a test path that is neither in
`TARGETS` nor in `EXCLUDED`.

### Isolated world first

Camoufox ships with Playwright's code in an isolated world, but upstream's tests
assume the main world (they read globals their own page scripts defined). Each
group therefore runs in up to three passes:

| Pass | `CI_WORLD` | What it establishes |
|---|---|---|
| 1 | `isolated` | The browser as users run it |
| 2 | `main` | The pass-1 failures again, isolation off |
| 3 | `main` | What failed in both, once more; normally empty |

A test that passes only in pass 2 is a **main-world fallback**: it counts as a
pass, and the summary reports `main_world_fallback_count`. That number is the
isolated-world conformance gap; a jump means the isolation boundary moved. Both
rerun passes run only when the failure set is non-empty, because pytest's
`--last-failed` with nothing to filter reruns the whole group.

Pass 1 is cost-bounded: a 90 s per-test timeout, and upstream's own reruns off
(`CI=""`, because upstream's conftest overrides `--reruns`).

Some modules **hang** rather than fail under isolation. A Playwright feature
that works by replacing a page global, such as `route_web_socket` (which
replaces `window.WebSocket`) or a binding the page calls, lands in the isolated
world, so anything the page itself does never reaches it. In the sync API no
timeout can stop such a hang cleanly. Those modules are listed in
`ISOLATION_HANGS` in `ci/run_playwright.py` and run directly in the main world,
counted as fallbacks. The `route_web_socket` gap is real for users too:
[#775](https://github.com/daijro/camoufox/issues/775).

### The skiplist

[`ci/skiplist.yml`](skiplist.yml) deselects the upstream tests Camoufox fails on
purpose, each with a reason (`ci/summarize.py` rejects an entry without one).
A reason is not evidence, so `ci/run_skiplist_audit.py` runs every entry in the
main world with the skiplist off and **fails the build if a skipped test
passes**. `ISOLATION_HANGS` is a different list: those tests pass in the main
world, so they would fail the audit, and `test_isolation_hangs_are_not_in_the_skiplist`
keeps the two apart.

The entries cover keyboard input Camoufox presses as a real keyboard would,
client certificates the browser must present during the TLS handshake,
stock-Firefox quirks that `browser/tests/playwright/camoufox/` replaces, the popup blocker Camoufox
keeps on, and scrollbars Camoufox does not hide in headless mode. CI is the
authority on what fails; a local run is a hypothesis.

## Camoufox's own suite

`browser/tests/native/` covers what the Playwright suite cannot ask about:

| Area | What it checks |
|---|---|
| Leaks | Launching and killing browsers leaves no file descriptors, sockets, child processes or X11 lock files, and the cost does not grow with launch count |
| Contexts versus browsers | Two contexts in one browser get different fingerprints; two pages in one context get the same one |
| Crashes | Killing the browser, the X server, a content process or the driver mid-run leaves nothing behind, and the next launch works (`test_crash_recovery.py`) |
| Memory growth | One mechanism (iframes, canvas readback, WebGL contexts, workers, script compilation, font measurement) driven N and 4N times grows by a bounded amount (`test_memory_growth.py`, the `growth` job) |
| Settled decisions | Every mechanically checkable rule in [`ci/tribal-rules.yml`](tribal-rules.yml) (`test_tribal_rules.py`) |

## Stealth grade

`ci/run_sundial.py` reports **a letter grade and a count**, nothing else: no
vector name, value or source, and no per-category breakdown. Everything that
leaves `redact()` is checked against a whitelist (`_PUBLISHABLE`), so adding a
field fails the run. The request asks for the score only (`?auto=1&score=1`),
and a full report arriving anyway fails the run.

```json
{ "grade": "A", "checks_total": 412, "checks_passed": 403, "pass_rate": 0.978,
  "out_of_scope_failed": 6, "cross_os_total": 24, "cross_os_passed": 5,
  "os": "linux", "sundial_version": "0.3.1", "schema_version": 1 }
```

| Setting | Where |
|---|---|
| On/off switch, gated categories, `min_pass_rate` | [`ci/sundial.yml`](sundial.yml) |
| Credential | `SUNDIAL_AUTOMATION_KEY` secret; `SUNDIAL_USERNAME` is optional |
| Keep an encrypted full report for yourself | `SUNDIAL_REPORT_AGE_RECIPIENT` (an `age` public key) |

Cross-OS checks read the host rather than the disguise, so they are counted
separately and never scored. Without a credential (a fork pull request) the job
is skipped and the summary says so.

To see which category fails, run locally; `--explain` is refused under GitHub
Actions:

```bash
python3 -m ci.run_sundial --explain --binary /path/to/camoufox-bin
```

## Blocking a merge

Branch protection on `main` requires one check, **`All tests passed`** (the
`gate` job), so the list does not change when a suite is added or resharded.
Anything that is not `success` fails it, including `skipped`, except:

| May be skipped | When |
|---|---|
| `build` | The browser was fetched, not compiled |
| `fetch-browser` | The browser was compiled, not fetched |
| `sundial` | Disabled in `ci/sundial.yml`, or no credential |

`sundial` may also record a `skip` result when the sundial service is
unreachable. A rejected credential, a full report, or a score under the floor
still fails.

The settings are in [`ci/branch-protection.json`](branch-protection.json). To
apply them (needs admin):

```bash
gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input ci/branch-protection.json
```

| Setting | Why |
|---|---|
| `enforce_admins: false` | A maintainer can still merge when CI itself is broken |
| `strict: false` | A pull request need not be rebased onto `main` before merging; otherwise every push to `main` would force a rebuild of every open pull request |
| No required reviews | A solo maintainer cannot approve their own pull request |

## Cost control

Each tier gates the next, so a lint failure never reaches the build:

| Tier | Jobs | Time |
|---|---|---|
| 0 static | lint, self-tests, settled decisions | seconds |
| 1 unit | pythonlib, typescript, install | about a minute |
| 2 browser | build (browser sources changed) or fetch (they did not) | minutes to hours |
| 3a smoke | patch guards, skiplist audit, build-tester, typescript-browser | about 15 min |
| 3b full | Playwright × 6, native, growth × 7, stealth | about 40 min |
| 4 gate | the required check | seconds |

| Mechanism | Effect |
|---|---|
| **Fetch instead of build** | A pull request that does not touch browser sources tests the published release built from exactly this tree's sources (`ci.release paired`). With no such release, it builds. |
| **Compiled-input cache** | The build cache is keyed on a hash of the compiled inputs only (`ci/browser_inputs.py`). On a hit the browser is restored and this branch's Juggler JavaScript and other resources, the files `jar.mn` lists, are laid over it. Everything else, including any new file type, counts as native and forces a build. |
| **No partial restore** | That cache has no `restore-keys`: a partial match would hand the tests a browser built from different sources. A self-test checks the key covers every browser-affecting path. |
| **Warm ccache** | Pushes to `main` and a twice-weekly schedule keep the ccache from being evicted; pull requests restore it. |
| **Network retries only** | `ci.run_prepare` (`setup-minimal`, `dir`, `mozbootstrap`) retries only failures that read as transient network errors. A failed hunk or compile error fails at once. |

Pushing to a branch cancels its running build (`cancel-in-progress`).

## Releases

One workflow, [`release.yml`](../.github/workflows/release.yml), makes every
release. Every tested merge to `main` is released as a **prerelease**; a
maintainer promotes one to **stable** by pushing a tag. Each library release is
paired with exactly one browser build.

```
merge to main ─► tests ─► plan ─┬─► build-browser ─► publish-browser ─┐
               (tests.yml,      │   (only if its      v156.0.1-beta.N  │
                this commit)    │    sources changed)                  ├─► publish-pypi ─► publish-npm ─► tag-library
                                └─► build-library ─────────────────────┘   0.5.8bN          0.5.8-beta.N    v0.5.8bN
                                    (only if what it ships changed)        (pip: --pre)     @next

git tag v0.5.8 <tested main commit> && git push origin v0.5.8
               ─► plan ─► build-library ─► promote-browser ─► publish-pypi ─► publish-npm
                  (checks)                 paired → stable       0.5.8           0.5.8 @latest
```

| Rule | Detail |
|---|---|
| Only a tested commit is released | On a push to `main`, `release.yml` calls `tests.yml` on that commit and continues only if it passes. |
| The browser is built only when its sources changed | `ci.browser_inputs.source_digest()` hashes the browser's sources. Each browser release carries a `manifest.json` with that digest, its commit, and the browser interface it speaks (`CONSTRAINTS.INTERFACE` in `python/src/camoufox/__version__.py`). A matching release is reused; otherwise `plan` takes the next unused `beta.N`. Nothing is committed: `ci.release set-build` writes the number into the build's tree. |
| Builds are attested | `gh attestation verify <file> --repo daijro/camoufox` |
| Packages are built once | `publish-pypi` and `publish-npm` upload the files `build-library` made: `0.5.8b2` on PyPI, `0.5.8-beta.2` on npm. `pip install camoufox` skips prereleases without `--pre`; npm installs `latest`, not `next`. |
| The pairing | `ci.release stamp` writes the paired browser release into `python/src/camoufox/browser-pin.json`, which both launchers read. On `main` the file is `{}`, so a development checkout follows its channel. |
| Promotion | A `vX.Y.Z` tag is refused unless the commit is on `main`, `All tests passed` succeeded on it, X.Y.Z is newer than every release, and a browser release was built from its sources. The paired browser becomes the stable release without a rebuild. |
| Failed publish | Re-run the failed jobs; every version and tag comes from `plan`. |
| Credentials | None stored. PyPI and npm use trusted publishing (OIDC) from `release.yml`. |

Releases cut before manifests existed (up to `v156.0.1-beta.32`) pair by the tag
`upstream.sh` names.

## Running a piece by hand

| Command | Needs a browser | What it runs |
|---|---|---|
| `python3 -m ci.run_prepare` | | `make setup-minimal`, `dir`, `mozbootstrap` |
| `python3 -m ci.run_build` | | The browser build |
| `python3 -m ci.run_pythonlib` | | `python/`'s tests |
| `python3 -m ci.run_typescript` | | `typescript/`'s tests |
| `python3 -m ci.run_typescript --browser <bin>` | yes | The npm launcher end to end |
| `python3 -m ci.run_install --tmpdir /mnt/tmpfs` | | Packed packages and a real fetch; the tmpdir must be its own filesystem |
| `python3 -m ci.run_patch_guards --binary <bin>` | yes | Patch guards; `--group spoofing\|automation\|parity`, `--only <name>` |
| `python3 -m ci.run_patch_guards --binary <bin> --only stock-gpu-parity` | yes | WebGL and WebGPU against stock Firefox of the same version, downloaded into `.ci-work` ([upgrade step](../docs/patch-upgrading-guide.md#browser-owned-gpu-values)) |
| `python3 -m ci.run_build_tester --binary <bin>` | yes | build-tester |
| `python3 -m ci.run_skiplist_audit --binary <bin>` | yes | Every skiplist entry still fails |
| `python3 -m ci.run_playwright --binary <bin>` | yes | The Playwright suite; `--shard 3/6` for one shard |
| `python3 -m ci.run_native --subset rules` | | Settled decisions |
| `python3 -m ci.run_native --subset browser --binary <bin>` | yes | Leaks, contexts, crashes |
| `python3 -m ci.run_native --subset growth --binary <bin>` | yes | Memory growth; `--shard 3/7` for one test |
| `python3 -m ci.run_sundial --binary <bin>` | yes | The stealth grade (needs the credential) |
| `python3 -m ci.summarize --results-dir .ci-work/results` | | The summary table |
| `python3 -m ci.release browser-plan` | | Whether a browser would be built or reused |
| `python3 -m ci.release paired` | | The release built from this tree |
| `python3 -m ci.release lib-plan --channel prerelease` | | The next library version |
| `python3 -m pytest ci/tests -q` | | The pipeline's own tests |

`<bin>` is a `camoufox-bin`; `make -C browser path` prints the one in your
build tree. Each runner writes one result file to `.ci-work/results/`
(`run_prepare` writes none). A required suite with no result file is a
**failure**, never a skip.

## Self-tests

`ci/tests/` asserts the pipeline reports honestly: redaction leaks nothing,
skips carry reasons, shards partition exactly once, and version resolution never
picks a suite newer than the browser. They run in the `static` job.
