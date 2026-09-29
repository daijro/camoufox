# The test pipeline

Everything that runs a suite against Camoufox. Driven identically from a pull
request, a push to main, and — through `workflow_call` — any caller that needs
to test a specific browser version, so there is one definition of "the tests
pass", not two.

```
resolve ── static ─────────────── lint, tribal rules, skiplist, self-tests  (seconds)
             ├─ typescript ────── type check, lint, vitest, golden parity
             └─ pythonlib ─────── the package's own tests                   (a minute)
                  └─ build or fetch ─┬─ patch guards × 3 ─── spoofing, automation, stock parity
                                     ├─ skiplist audit ───── every skip still fails
                                     ├─ build-tester ─────── 8 fingerprint profiles
                                     ├─ typescript-browser ─ the npm launcher end to end
                                     └─ once guards and build-tester pass:
                                          ├─ playwright × 6 shards   (conformance + our own)
                                          ├─ native ───────── leaks, contexts, crash recovery
                                          ├─ sundial ──────── stealth grade
                                          └─ growth × 7 shards  memory growth, one test per runner
                                  │
                               summary ──► one comment on the PR
```

## Which browser, which suite

`ci/versions.py` answers both, and every entry point uses it:

- **browser** — from `upstream.sh`, or whatever a caller passes in. A caller
  moving to a new Firefox passes the version it is moving to, which is what lets
  one pipeline test both a pull request and an upgrade.
- **suite** — the newest *released* playwright-python tag whose pinned Firefox is
  not ahead of that browser, and which is below the Playwright ceiling
  `pythonlib/pyproject.toml` pins.

Newest-not-ahead, rather than an exact match, because Playwright trails Firefox
and skips generations: it pinned Firefox 151 and then 153, never 152, so a
browser built on 152 has no exact suite and never will. Requiring a match would
leave most of a release cycle with no suite at all, and taking a newer one would
test against an automation contract that assumes engine work the build does not
have. **So the suite's Firefox pin being a release or two behind the browser is
the normal case, not a misconfiguration** — the summary line says which rule
picked the tag.

The ceiling matters for the same reason it exists in `pythonlib`: `camoufox.server`
imports `playwright._impl._driver`, a private API, and every Playwright minor is
free to change Juggler. Testing above the ceiling would exercise a client the
shipped package will not install.

```bash
python3 -m ci.versions --json                          # what would run
python3 -m ci.versions --browser-version 153.0.4 --json
```

**The version under test has to be the version that gets built.** Only *suite
selection* follows `--browser-version`; the build reads `upstream.sh` and the
fetch path downloads whatever pythonlib considers current. Asking for a version
the branch does not pin would therefore compile the old browser and judge it
against the new suite — green, meaningless and silent. `--check-upstream`
refuses that, and the workflow passes it.

So an upgrade to a new Firefox is a branch that **edits `upstream.sh`**, which is
what an upgrade is anyway. Resolution then reads it by default, the build
produces it, and the suite is chosen for it — the three cannot disagree. The
`browser_version` input exists for a caller that wants to state the version
explicitly; it must match.

## The Playwright suite

One suite, fetched fresh per run: upstream playwright-python at the resolved tag.
It runs unmodified — `ci/pw_camoufox_plugin.py` adapts the environment around it
rather than editing it, hooking `BrowserType` at the `_impl` layer so upstream
can refactor its fixtures freely — and `ci/suite.py` overlays `tests/camoufox/`
into it.

`tests/camoufox/` is small on purpose: behaviour upstream has no test for (that
`page.route()` must not change what a request looks like on the wire), or asserts
the opposite of on purpose (that a worker should *not* inherit the context
locale, which stock Firefox gets wrong and Camoufox does not). It is not a fork
of anything, so it cannot go stale; it runs against upstream's own conftest and
server at whatever tag was resolved.

`tests/` used to hold a fork of a ~v1.55-era upstream suite. It was deleted after
measuring it against the same binary:

- **73 of the 74 tests it skipped as "Not supported by Camoufox" pass** in
  upstream's copy. Those skips predated main-world execution and were never
  revisited, so the fork was asserting the browser was worse than it is.
- Of its passing tests, eight had no upstream counterpart. Six of those were
  Camoufox-specific and now live in `tests/camoufox/` as three modules; the
  other two were tests upstream had since renamed.

A re-fetched suite cannot drift, and a deliberate difference from upstream now
has to be written down in `ci/skiplist.yml` with a reason, where it is visible,
instead of being encoded as a silent edit to a vendored file.

## What "the suite" means

`ci/run_playwright.py` names its targets explicitly rather than pointing at
`tests/`, so the one thing left out stays visible:

| | |
|---|---|
| `tests/async/` + `tests/sync/` | one pytest process |
| `tests/common/`, `tests/test_reference_count_async.py` | **their own** process |
| `tests/test_installation.py` | excluded, with a reason |

The isolated pair each call `sync_playwright()`/`async_playwright()` inside the
test body, which cannot start while the session fixtures already hold a loop
(`Cannot run the event loop while another loop is running`). Run with the others
all six fail; run alone all six pass. Skiplisting them for that would have
recorded a browser failure that does not exist.

This used to be `tests/async/` alone — 722 tests, 31% of the suite, excluded with
nothing written down. Not a decision: the vendored fork carried `async/` and no
sync suite, and this runner was pointed at the same shape without checking what
upstream shipped. `unclaimed()` now fails the run if upstream adds a test path
that is neither in `TARGETS` nor in `EXCLUDED` with a reason.

## Which world, and the skip list

The suite runs **isolated first** — the configuration Camoufox actually ships —
and falls back to the main world only for what fails, counting every test that
needed the fallback.

Upstream asserts upstream semantics: tests read globals their own page scripts
defined and pass handles into `evaluate()`, and a test doing that fails under
isolation by design. Running the whole suite main-world-only (the previous
behaviour) made those pass, which is true but uninformative — it measured a mode
nobody ships and produced no number for what isolation costs.

Each group is therefore run up to three times, and normally twice:

| Pass | `CI_WORLD` | What it establishes |
| --- | --- | --- |
| 1 | `isolated` | the browser as users run it |
| 2 | `main` | the failures again with isolation off |
| 3 | `main` | only what failed in *both*, retried once — normally empty |

There is deliberately **no second isolated pass**. One sat between 1 and 2 on
the theory that a flake must not be mistaken for a world difference; measured on
the first real CI run it cost 7m50s per shard and recovered nothing:

```
isolated (full)   335s + 331s   35 and 11 failures
isolated retry    205s + 265s   0 recovered      <- deleted
main world         19s +  12s   46 recovered
```

Two reasons it was never going to earn that. These failures are deterministic —
a test reading a global its page script defined does not intermittently see it —
and failing that way is *slow*, because the read returns undefined and the test
sits on a Playwright timeout rather than throwing. And upstream's suite already
ships `pytest-rerunfailures`: pass 1 reported `105 rerun`, which is each of
those 35 failures having been retried three times before the run even reported
them. A flake does not survive that.

A test that passes in pass 2 is recorded as a **main-world fallback**: it counts
as a pass for the run, and its identity goes into
`metrics.main_world_fallbacks`, with `metrics.main_world_fallback_count` on the
summary table (summed across shards). A test failing in both worlds *and* on
retry is a plain failure. The fallback count is the isolated-world conformance
gap — watch it between runs; a jump means the isolation boundary moved.

Both rerun passes are guarded on the failure set being non-empty, which is
load-bearing rather than tidy: pytest declines to filter when nothing it
collected previously failed, so an unguarded `--last-failed` runs the *whole*
group again — in the other world, silently replacing the result it was meant to
refine.

### Why some isolated failures hang

Not every isolated failure fails. Some wait forever, in both
`tests/async/test_route_web_socket.py` and `tests/sync/test_route_web_socket.py`
— and the two are not equally recoverable, which is the subject of the second
half of this section.

The shape recurs, so it is worth stating generally: **a Playwright feature
implemented by installing something on the page's global lands in the isolated
world instead, so anything the page itself originates never reaches the
automation.** Two instances, both measured directly against a build:

```
page's own script opens a WebSocket    isolated -> handler never fires   main -> intercepted
page script calls window.exposedFn()   isolated -> HANG                  main -> resolves
evaluate() calls window.exposedFn()    isolated -> resolves              main -> resolves
```

`route_web_socket` works by replacing `window.WebSocket` from an init script;
isolated, that replacement lands in the sandbox, so a socket the page opens is
never seen. `expose_function` installs its binding on the sandbox global, so page
script calling `window.fn()` finds nothing — though called from `evaluate()` it
works, which is why that one does not hang here.

They **hang** rather than fail because the waits involved — a Twisted future from
the test server, an asyncio future a binding was meant to resolve — have no
Playwright timeout behind them. Everything else isolation breaks fails at
Playwright's 30s.

Worth being clear that the `route_web_socket` half is **not a test artifact**: a
real site's WebSocket is not intercepted either, and the user gets no error
saying so. It is not fixable at this layer — the feature works by replacing a
page global, which is precisely what an isolated world exists to stop a page
from seeing. Tracked in [#775][ws-issue]; the fix is native interception below
the DOM object, which is also the only version of it that stays undetectable.

[ws-issue]: https://github.com/daijro/camoufox/issues/775

So pass 1 is **cost-bounded**, and only pass 1:

| Bound | Value | Why |
| --- | --- | --- |
| per-test timeout | 90s | the slowest test in the whole main-world baseline was 30.4s; only two exceeded 30s and none exceeded 45s. A Playwright action times out at 30s |
| upstream reruns | off (`CI=""`) | `tests/conftest.py` sets `reruns = 3` whenever `$CI` is set — the only thing it reads `$CI` for. The baseline recorded **2** reruns across all 2295 tests; the isolated pass recorded **138 in one shard**, all re-running deterministic world differences |

Together that turns a hang from up to 4 × 180s into one 90s wait. A flake missed
by not rerunning is not lost — it fails pass 1, passes pass 2, and is counted as
a fallback. Note that `--reruns 0` as an *argument* would not work: upstream's
conftest overwrites `config.option.reruns` in `pytest_configure`, so clearing
the environment variable is the only lever that holds.

#### The ones a timeout cannot bound

That bound is not enough for all of them, and it is worth knowing exactly where
it stops working. Measured on run 34799668707 with the 90s bound already in
place:

| Group | Isolated pass | Outcome |
| --- | --- | --- |
| `tests/async/` | completed in 296s | the bound works |
| `tests/sync/` | `test_should_work_with_ws_close` printed pytest-timeout's `+++ Timeout +++` banner at exactly 90s | **the process then sat for 1h50m**, until the job's `timeout-minutes` killed it |

So the signal fires and the *test* dies; the *process* does not. pytest-timeout's
signal method raises at the next bytecode boundary, and Playwright's sync API is
parked in a greenlet switch that never reaches one cleanly — the raise lands
inside the dispatcher and wedges it. `--timeout-method=thread` fires reliably but
kills the interpreter, taking the other ~1500 tests in the group with it. **There
is no per-test timeout value that bounds this.**

So those modules are **declared, not discovered** — `ISOLATION_HANGS` in
`ci/run_playwright.py`. The isolated pass cannot learn that they hang without
hanging, so it is told: they are `--ignore`d out of pass 1 and run directly in
the main world (pass 1b), where they pass and are counted as fallbacks exactly
as if isolation had failed them honestly. The same tests still run, in the world
that can run them.

**Why not `ci/skiplist.yml`.** That list means "fails in the most permissive
world", and `ci/run_skiplist_audit.py` enforces it by running every entry with
`CI_WORLD=main` and failing the build on any that **pass**. A `route_web_socket`
test passes there — the main world is precisely where the feature works — so an
entry would be rejected by the audit, and would be untrue as written. The two
lists are not interchangeable, and `test_isolation_hangs_are_not_in_the_skiplist`
keeps them apart.

Pass 1b sits **above** the `if not failing: continue` guard, deliberately: a
group whose isolated pass found nothing would otherwise skip it, and coverage
would disappear on exactly the runs that look healthiest.

`tests/patches/isolated-evaluate.py` still owns the direct coverage of isolated
evaluation, and must keep passing regardless. That file is what to check if
isolation itself regresses.

`ci/run_skiplist_audit.py` deliberately runs in the **main world**: a skiplist
entry has to claim a test cannot pass in *either* world, or the suite would have
counted it as a fallback rather than a failure.

Seventeen tests are deselected outright by [`ci/skiplist.yml`](skiplist.yml), which
requires a stated reason per entry — `ci/summarize.py` fails the run on an
unreasoned one.

**A reason is not evidence, so the reasons are checked.** The first version of
this file inherited all nine `tests/async/*.disabled` modules from the vendored
suite and gave each a plausible justification without running any of them: of
the 202 tests it skipped, **193 passed**, and seven of the nine modules failed
nothing at all. A written reason made them look verified, which is worse than
leaving them bare.

`ci/run_skiplist_audit.py` now runs every entry with the skiplist disabled and
**fails the build if a skipped test passes**. It is cheap precisely because a
correct skiplist is short — seventeen tests, a few seconds — and it is what keeps the
list from drifting back into a place failing tests go to disappear.

```bash
python3 -m ci.run_skiplist_audit --binary /path/to/camoufox-bin
```

What remains, 17 tests: two `test_keyboard.py`
tests that assert a shifted character arrives without Shift, which Camoufox
presses as a real keyboard would; six client-certificate tests (async and sync)
that need the **browser** to present a certificate during the TLS handshake —
the two that go through the Node driver's own request context instead pass, and
are not skipped; two upstream expectations that encode a stock-Firefox quirk,
replaced by `tests/camoufox/`; two popup tests that rely on Playwright
shipping Firefox's popup blocker off, which Camoufox keeps on; and five layout
tests that assume headless scrollbars take no width, which Playwright gets by
hiding them and Camoufox does not do.

That client-certificate split is the audit earning its place. The entry was
first written as a whole module, because on a local machine all five fail —
Node/OpenSSL there rejects the fixture server outright. In CI two of them pass,
and the audit failed the build one run after the entry was written. **CI is the
authority for what fails; a local run is a hypothesis.**

## Camoufox's own suite

`native-tests/` covers what the Playwright suite cannot ask about:

- **Leaks.** Launch browsers, kill them, prove nothing survived — file
  descriptors, sockets, child processes, X11 lock files. The real assertion is
  that cost does not *scale* with launch count, because that is the shape a leak
  actually has: a scraper that runs fine for six hours and then dies of EMFILE.
  Scope is honest: this measures resources held by our process and its children,
  not Gecko's internal heap.
- **Contexts versus browsers.** Two contexts in one browser must get different
  fingerprints; two pages in one context must get the same one. Get this wrong
  and per-context injection silently degrades to process-global — which passes
  every single-context test there is. It has happened here before (commit
  `d17c887`, "fix screen size leak in contexts").
- **Crashes.** Kill the browser, the X server, a content process or the driver
  mid-run, then check that teardown does not hang, nothing leaks, and a fresh
  launch still works (`test_crash_recovery.py`).
- **Memory growth.** Drive one mechanism (iframes, canvas readback, WebGL
  contexts, workers, script compilation, font measurement) N and 4N times and
  compare the growth: a bounded cost stays flat, a per-iteration leak scales
  (`test_memory_growth.py`). It takes over half an hour in one process, so CI
  runs it one test per runner (the `growth` job, `--subset growth --shard i/7`)
  on every pull request, in the gate.
- **Settled decisions.** `ci/tribal-rules.yml` lists choices this project already
  made, each with the issue or PR that made it, and
  `native-tests/test_tribal_rules.py` asserts them. A comment explaining a
  decision only works on someone who reads it.

## Sundial

> **On since 2026-09-12.** sundial 0.5.0 is deployed and serving score mode, and
> sundial's master branch now deploys itself on push, so merged does mean
> deployed. It was off for as long as the live build predated score mode: an
> older sundial ignores `?score=1` and posts the entire report — every vector's
> id, name, brief, source and value — to whatever collector asked. Receiving
> that on a public runner and discarding it afterwards is not the guarantee this
> section describes; not receiving it is. `enabled: false` in `ci/sundial.yml`
> is still the kill switch, and the resolve job checks it *before* the
> credential comes into scope, so flipping it back stops the request rather than
> just the reporting.

The stealth check reports **a letter grade and a count**. Nothing else leaves
`ci/run_sundial.py::redact()` — not a vector name, description, measured value,
source, and not a per-category breakdown either: a table reading "Graphics 3/17"
is the most useful single fact an adversary could take from a public CI log.

There are **no per-check rows in the results file at all** — not even opaque
ones. An HMAC does not name a vector, but a map of them still publishes how many
distinct checks fail and lets a reader follow one across releases, which is
per-vector data wearing a hash. The instruction was a score, so it is a score:
regression detection is per-score, via `min_pass_rate` and a maximum allowed
drop. Scope and thresholds live in [`ci/sundial.yml`](sundial.yml); only
categories Camoufox actually claims are gated.

Everything that leaves `redact()` is checked against a **whitelist** at runtime,
not a blacklist — a blacklist only stops the leaks somebody already thought of.
Adding a field without adding it to `_PUBLISHABLE` fails the run:

```json
{ "grade": "A", "checks_total": 412, "checks_passed": 403, "pass_rate": 0.978,
  "out_of_scope_failed": 6, "cross_os_total": 24, "cross_os_passed": 5,
  "os": "linux", "sundial_version": "0.3.1", "schema_version": 1 }
```

**Cross-OS detectors are counted, never scored.** They read the host machine
rather than the disguise: a browser claiming macOS while running on Linux fails
them however good its spoofing is, and Camoufox does not claim byte-identical
cross-OS emulation. Folding them into one average would mark it down for a
promise nobody made, and would hide a real regression behind noise it cannot
control. They are reported separately so a drop there reads as "the host shows
through more than it did", which is a different conversation.

The run asks sundial for `?auto=1&score=1`, so it receives counts and the
vectors never cross the wire at all.

### Finding out which checks failed

Worth being precise about, because the answer is "you can't, from CI", and that
is deliberate rather than an oversight. Score mode's payload is buckets keyed
`"<Category>|<class>"` holding two integers each. **It carries no check names and
no ids**, so a failing check's identity is not something the CI process discards
— it is something sundial never sends. Nothing in the artifact, the log, or the
sealed report can recover it.

Two steps down from there, both local only:

```bash
# which CATEGORY the failures are in -- works with the credential CI already has
python3 -m ci.run_sundial --explain --binary /path/to/camoufox-bin

# which CHECKS -- needs a role sundial serves full reports to
python3 -m ci.run_sundial --explain --allow-full-report --binary /path/to/camoufox-bin
```

`--explain` prints to the terminal and never writes to a result file, and is
**refused outright under `GITHUB_ACTIONS`**: a category-level table is not a
vector, but "Graphics 3/17" is still the most useful single fact an adversary
could take from a public log, which is exactly why `redact()` does not publish
one.

### Order of operations

`?score=1` needs a sundial that has it. An older deployment ignores the unknown
parameter and posts the whole report; the numbers still come out right and
`redact()` still discards everything identifying, but **nothing is classified**,
so every cross-OS tally reads `0` — which looks like "no host-OS failures"
rather than "nobody sorted them". `score_mode: false` in the result says which
it is, and the gate says so in its notes rather than leaving you to notice.

So the dependency runs one way, and setting the GitHub secrets is the *last*
step, not the first:

1. deploy sundial's score mode — done; it ships in 0.5.0, and master now
   deploys on push
2. `gh secret set SUNDIAL_AUTOMATION_KEY -R <repo>` for every repository whose
   CI runs this. Without it the job skips, which is the normal case for a fork
   pull request
3. flip `enabled: true` in `ci/sundial.yml` — done

Two things keep a vector out of a public log, and it is worth separating them,
because only one is enforced by the server:

| | guarantee |
|---|---|
| server-side | The run logs in as `guest`, and sundial's middleware refuses `guest` the private-vector bundle outright — those definitions are never served to the session. |
| client-side | This gate only ever requests `/?auto=1&score=1`, and `redact(require_score_mode=True)` **fails the run** if a full report arrives anyway, rather than folding it down and carrying on. |

The stricter option is sundial's score-only `ci` role, which is refused anything
but `/?auto=1&score=1` server-side and so cannot be handed a report even if the
credential leaks. That role is not in sundial's master branch and is therefore
not deployed; when it lands, mint the credential (`make pages-ci`, then
redeploy) and set `SUNDIAL_USERNAME=ci`. Nothing in this repository changes —
the client-side half already behaves as though the server were enforcing it.

There are deliberately **no per-vector rows**, not even opaque ones. An HMAC
names nothing, but a map of them publishes how many distinct checks fail and
lets a reader follow the same id from release to release.

The cost is real: regression detection drops from per-vector ("the check that
passed last release fails now") to per-score ("we got worse"), covered by
`min_pass_rate` in `ci/sundial.yml` — and, once an auto-update pipeline exists
to compare releases, by a maximum allowed drop in its policy file. To get the per-vector view back for your own debugging,
set `SUNDIAL_REPORT_AGE_RECIPIENT` to an `age` public key — the full report is
then kept encrypted to you and nobody else can open it.

Needs **`SUNDIAL_AUTOMATION_KEY`** (the password). **`SUNDIAL_USERNAME`** is
optional and names the account, which is not a secret — it defaults to `guest`.
Absent the password — a pull request from a fork — the job is skipped and the
summary says so.

### What actually stops a vector reaching the log

Asking for `?score=1` is a promise the caller makes, and a promise is not a
mechanism. Today two things back it:

- **`guest` cannot load the private vectors, and that is checked.** sundial's
  middleware answers `isPrivateVectorAsset` paths with an empty stub for that
  role specifically. `admin` and `private` do get them — and `/automated?key=`
  resolves to `private` when handed the private key, which is indistinguishable
  from the guest one by looking at it. So "we set the right key" stays an
  assumption until something checks: the gate reads sundial's own `/__auth/me`
  and **refuses to open the browser at all** unless the session is a role the
  vectors are withheld from. Not knowing the role counts as not safe.
- **A non-score payload fails the run.** `redact(require_score_mode=True)`
  refuses to process a full report rather than folding it down, so a deployment
  that ignored `score=1` is a red build, not a quiet leak.

What is still missing is a server that refuses the *request*. sundial's
score-only `ci` role does exactly that — a bare `/`, `auto=1` without `score=1`,
`?mode=raw`, `?download=true`, `?key=`, the `/automated` and `/locale` export
routes, and any parameter not on its allow-list each get a 403, and on the pages
it does serve the report is never written to a global, so there is nothing for
`page.evaluate`, devtools or a screenshot to read. That role is not merged into
sundial's master and so is not deployed. When it is, set `SUNDIAL_USERNAME=ci`;
nothing here changes, because this side already behaves as though the server
were enforcing it.

The distinction is worth keeping straight: under `guest`, dropping `score=1` by
accident would put the whole report in the collector and leave `redact()` as the
only thing between it and a public artifact. Under `ci`, the same mistake is a
403 at the first request. `--allow-full-report` exists for a deliberate local
run under an account that is allowed one.

## Blocking a merge

Branch protection on `main` requires exactly one check: **`All tests passed`**,
the `gate` job. Pointing at one job instead of a dozen means the required-check
list does not need editing every time a suite is added, renamed, or resharded.

The gate allows exactly three skips, each for a stated reason:

| Skipped | Because |
| --- | --- |
| `build` | the browser was fetched, not compiled |
| `fetch-browser` | the browser was compiled, not fetched |
| `sundial` | disabled in `ci/sundial.yml`, or a fork pull request with no stealth credentials |

Anything else that is not `success` fails it — **including `skipped`**. A suite
that did not run has not passed, and quietly skipping one is the cheapest route
to a green tick.

`build` is also the one suite dropped from `--require` when the browser was
fetched rather than compiled: that job writes no result, and requiring a name
nothing produces fails a run where everything passed.

One suite may additionally record a **`skip` result** without failing the run,
named explicitly in `--allow-skip`: `sundial`, and only when sundial itself is
unreachable. It is a separate service on a separate host, so an outage there
means this browser was never measured — neither a pass nor a failure is true,
and blocking every merge in the repository on someone else's downtime is the
wrong answer. The summary shows it as skipped with the reason. A rejected
credential, a role that would be served the private vectors, a full report where
a score was requested, or a score under the floor all still fail: those are
answers, and an answer gets judged.

The settings live in [`ci/branch-protection.json`](branch-protection.json) so
they are reviewable rather than lore. To apply them (needs admin):

```bash
gh api -X PUT repos/<owner>/<repo>/branches/main/protection \
  --input ci/branch-protection.json
```

Two choices worth knowing about:

- **`enforce_admins: false`** — you can still merge when CI itself is broken.
  Protection should stop mistakes, not lock you out of your own repository.
- **`strict: false`** — a pull request does not have to be rebased onto the
  latest `main` before merging. With `true`, every push to `main` would
  invalidate every open pull request and force another build, and a build here
  is over an hour cold.

Reviews are deliberately not required: a solo maintainer cannot approve their
own pull request, so requiring one would block every merge.

## Cost control

Each tier gates the next, so a two-second lint failure never reaches the build:

```
0  static    lint, self-tests, settled decisions        seconds
1  unit      pythonlib, typescript                      ~1 min
2  browser   build  (patches/additions/settings/assets/upstream.sh/Makefile/scripts changed)
             fetch  (anything else, when the published release has this tree's browser sources)
3a smoke     patch guards (spoofing, automation, parity),
             skiplist audit, build-tester,
             typescript-browser                         ~15 min
3b full      Playwright x6, leaks, memory growth x7,
             stealth                                    ~40 min
4  gate      the required check
```

**Driver-only pull requests test the published release, when it matches.**
There is nothing new to compile, so `fetch-browser` downloads a published
release and the browser suites run against a build users actually get, in a
minute instead of seventy. That is only right when the release was built from
this tree's browser sources. Once a browser change has merged but not been
built, the guards in the checkout would judge an older browser. So the scope
step asks `ci.release paired` for the release built from exactly this tree's
sources, which is the one this tree's library would be paired with (see
[Releases](#releases)). The job then installs it through the same pin a
released package carries. When no release matches, it builds instead, and the
build restores the base branch's cached browser.

**Changing Juggler's JavaScript does not rebuild the browser.** Measured on a
real build: ccache reported a **98.63%** hit rate, so almost none of those 24
minutes was compiling C++ — it was Rust, linking libxul, and packaging, none of
which a `.js` file affects. And in the *unpackaged* `dist/bin` that CI archives
there is no `omni.ja` at all: Juggler is loose files under `chrome/juggler/`, so
delivering new JavaScript is a file copy.

So the build cache is keyed on a hash of the **compiled** inputs only
(`ci/browser_inputs.py`). If that hash matches, the compiled half is identical
*by construction* — no diff required, and no dependence on what the pull request
base happened to contain — and this branch's resources are laid over the
restored browser. A Juggler JavaScript change costs about a minute instead of
twenty-four.

Two things make that dangerous, and both are closed and mutation-tested:

| Trap | What closes it |
| --- | --- |
| `additions/juggler/` is **not** all JavaScript — it holds the screencast encoder and the debugging pipe (5 `.cpp`, 5 `.h`, 2 `.idl`, 3 `components.conf`, 4 `moz.build`) | Only files `jar.mn` actually lists are resources. Everything else — including any extension nobody has considered yet — is native and forces a build. `jar.mn` itself is native, so removing an entry cannot leave a stale file behind |
| The source→destination mapping is **per-file, not a prefix** | It is read from `jar.mn`. `TargetRegistry.js` → `content/TargetRegistry.js` (a level added), `content/FrameTree.js` → `content/content/FrameTree.js` (preserved), `content/JugglerFrameChild.sys.mjs` → `content/JugglerFrameChild.sys.mjs` (dropped). Two files in one source directory landing at different depths is exactly what a prefix rule gets wrong — and it would run stale Juggler while every suite went green |

**A browser that is already built is not built again.** `browser_changed` is
computed against the pull request's *base*, so it stays true for every push to a
branch that touched `patches/` even once. That is right — the published release
does not contain that branch's browser changes, so it cannot be tested against —
but taken alone it meant recompiling a byte-identical browser on every push, 24
minutes at a time, to fix a typo in `ci/`.

The build job therefore asks a narrower question first: not "does this branch
change the browser" but "has the browser changed since the last one we built".
The answer is a cache keyed on a hash of every input that can alter the binary —
the same path list `browser_changed` uses, plus this workflow, which pins the
toolchain. On a hit, a 634 MB `camoufox-dist.tar.zst` is restored and every
build step is skipped; the run still records a `build` result saying the browser
was restored rather than compiled, because a required suite that reports nothing
fails the gate, and "nothing was compiled" should be a fact in the evidence
rather than a hole in it.

Deliberately **no `restore-keys`** on that cache. Everywhere else a partial
match is fine — a partly warm ccache is still warm — but here it would hand the
test jobs a browser built from different sources, and every suite would report
on it looking perfectly healthy. A self-test asserts the key covers every path
`browser_changed` considers browser-affecting, so the two cannot drift apart.

**The ccache is kept warm from `main`.** Pushes to `main` populate it and a
twice-weekly schedule keeps it from being evicted (GitHub drops a cache after
seven days unused). Pull requests restore it through `restore-keys`, so a build
in a pull request starts warm even though its own key is new.

A prebuilt image in `ghcr.io` with the object cache baked in would be warmer
still and would not need the eviction guard. It also needs registry credentials
and a rebuild pipeline of its own; this is the version that works with no setup.

**Preparing the tree retries the network, and nothing else.** `mach bootstrap`
pulls toolchains from Taskcluster, and a connection reset there used to fail the
whole pull request. `ci.run_prepare` runs `setup-minimal` → `dir` →
`mozbootstrap`, retrying the two that download things and only when the failure
text reads as transient. A failed patch hunk or a compile error still fails on
the first attempt — retrying a broken tree only spends a runner to reach the
same answer, and a retry loop that swallows a real breakage turns a red build
into a slow red build. The release workflow (`release.yml`) prepares its tree the same
way, so a release build gets the same hardening.

> One consequence of `cancel-in-progress`: pushing to a branch cancels its
> running build. That is right while iterating, but a 70-minute build will not
> survive a push made 20 minutes in.

## Releases

One workflow, [`release.yml`](../.github/workflows/release.yml), makes every
release. Every tested merge to `main` is released as a **prerelease**; a
maintainer promotes one to **stable** by pushing a tag. Each
library release is paired with exactly one browser build.

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

**Only a tested commit is released.** On a push to `main`, `release.yml` calls
`tests.yml` on the pushed commit and goes on only if it passes; `tests.yml` has no
push trigger of its own. Every later job checks out that same commit.

**The browser** is built only when the merge changed its sources.
`ci.browser_inputs.source_digest()` hashes everything the browser is built
from, except the release number. Every browser release carries a
`manifest.json` asset with that digest and the commit it was built from; if a
published release already carries this digest, nothing is built. Otherwise
`plan` takes the next unused `beta.N`, never below `upstream.sh`'s `release` and
never reused. Nothing is committed: the tag points at the tested `main` commit,
and `ci.release set-build` writes the number from the tag into the build's
working tree, so rebuilding from the tag reproduces the release. The builds are
attested (`gh attestation verify <file> --repo daijro/camoufox`) and published
as a GitHub prerelease, never a draft.

Releases cut before manifests existed (up to `v156.0.1-beta.32`) are paired
the old way: the tag `upstream.sh` names, published (a prerelease counts, a
draft does not), with no browser source changed since.

**The packages** are built once, in `build-library`, and `publish-pypi` and
`publish-npm` upload exactly those files: one version spelled for each
registry, `0.5.8b2` on PyPI and `0.5.8-beta.2` on npm. `pip install camoufox`
ignores prereleases unless `--pre` is passed, and `npm install
@camoufox/camoufox` takes `latest`, not `next`. A prerelease is of the version
in `pyproject.toml` while that version is unreleased, and of the next patch once
it has shipped. A merge that changes nothing a package ships (`pythonlib/`,
`typescript/` or the browser it pins) publishes no library prerelease; the last
published version is found by its tag, `vX.Y.Z` or `vX.Y.ZbN`.

**The pairing.** `ci.release stamp` writes the browser release built from the
package's own sources into `pythonlib/camoufox/browser-pin.json`, which both
launchers read. By default, `camoufox fetch` installs exactly that build and a
launch uses exactly that build, prerelease or not, and whatever else is
installed or was marked active. A user who explicitly chooses another channel
or build keeps it, with a warning at launch. `camoufox set --release` goes back
to the paired build. On `main` the file is `{}`, so a development checkout
follows its channel as before.

**Promotion** is a `vX.Y.Z` tag, and it is refused unless:

- the tagged commit is on `main`;
- `All tests passed` succeeded on it;
- X.Y.Z is newer than every published release;
- a browser release was built from its sources. Wait for that commit's release
  run to finish first.

Both packages are then built and checked. The paired browser release becomes
the stable, latest release, with no rebuild, so users get the binaries that were
tested; the packages are published at X.Y.Z.

**A failed publish** is retried with *Re-run failed jobs*. Every version and
tag comes from `plan`, so a re-run publishes the same release.

**Credentials.** None are stored. PyPI and npm both use trusted publishing
(OIDC): each accepts uploads only from `release.yml` in this repository.

## Running a piece by hand

```bash
python3 -m ci.run_prepare                                # make setup-minimal, dir, mozbootstrap
python3 -m ci.run_build
python3 -m ci.run_pythonlib                              # no browser needed
python3 -m ci.run_typescript                             # no browser needed
python3 -m ci.run_typescript     --browser path/to/camoufox-bin
python3 -m ci.run_patch_guards   --binary path/to/camoufox-bin
python3 -m ci.run_build_tester   --binary path/to/camoufox-bin
python3 -m ci.run_skiplist_audit --binary path/to/camoufox-bin
python3 -m ci.run_playwright     --binary path/to/camoufox-bin
python3 -m ci.run_playwright     --binary path/to/camoufox-bin --shard 3/6
python3 -m ci.run_native         --subset rules          # no browser needed
python3 -m ci.run_native         --subset browser --binary path/to/camoufox-bin
python3 -m ci.run_native         --subset growth  --binary path/to/camoufox-bin
python3 -m ci.run_native         --subset growth  --binary path/to/camoufox-bin --shard 3/7
python3 -m ci.run_sundial        --binary path/to/camoufox-bin
python3 -m ci.summarize          --results-dir .ci-work/results
python3 -m ci.release            browser-plan            # build a browser, or reuse one
python3 -m ci.release            paired                  # the release built from this tree
python3 -m ci.release            lib-plan --channel prerelease
```

Each suite runner writes one result file to `.ci-work/results/` (`run_prepare`
writes none). `ci/summarize.py` folds the shards, decides, and renders the table. A required suite that produced no result
file is a **failure**, never a skip — otherwise deleting a job would be the
cheapest way to a green tick.

## Self-tests

`ci/tests/` asserts the pipeline reports honestly: redaction leaks nothing,
skips carry reasons, shards partition exactly once, version resolution never
picks a suite newer than the browser. These run in the `static` job on every
pull request.
