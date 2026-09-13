# The test pipeline

Everything that runs a suite against Camoufox. Driven identically from a pull
request, a push to main, and — through `workflow_call` — any caller that needs
to test a specific browser version, so there is one definition of "the tests
pass", not two.

```
resolve ──┬─ static ────────── tribal rules, skiplist, self-tests   (seconds)
          ├─ pythonlib ─────── the package's own tests               (a minute)
          └─ build ──┬─ playwright × 6 shards        (conformance + our own)
                     ├─ skiplist audit ───── every skip must still fail
                     ├─ native ───────────── leaks, contexts         (ours)
                     ├─ patch guards ─────── one per spoofing patch
                     ├─ build-tester ─────── 8 fingerprint profiles
                     └─ sundial ──────────── stealth grade  (off: see below)
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

## Main-world execution, and the skip list

The suite runs with world isolation **off**. It asserts upstream
semantics — tests read globals their own page scripts defined and pass handles
into `evaluate()` — and about 37 of them fail on "X is not defined" otherwise.
Camoufox's actual isolated-world behaviour is covered by
`tests/patches/isolated-evaluate.py`, which must keep passing *without* that
flag. That file is what to check if isolation regresses, not this suite.

With main world on, 1575 of the 1584 collected tests run. The other 9 are
deselected by [`ci/skiplist.yml`](skiplist.yml), which requires a stated reason
per entry — `ci/summarize.py` fails the run on an unreasoned one.

**A reason is not evidence, so the reasons are checked.** The first version of
this file inherited all nine `tests/async/*.disabled` modules from the vendored
suite and gave each a plausible justification without running any of them: of
the 202 tests it skipped, **193 passed**, and seven of the nine modules failed
nothing at all. A written reason made them look verified, which is worse than
leaving them bare.

`ci/run_skiplist_audit.py` now runs every entry with the skiplist disabled and
**fails the build if a skipped test passes**. It is cheap precisely because a
correct skiplist is short — nine tests, a few seconds — and it is what keeps the
list from drifting back into a place failing tests go to disappear.

```bash
python3 -m ci.run_skiplist_audit --binary /path/to/camoufox-bin
```

What remains after the audit: two `test_click.py` tests where Playwright's
stable-position wait races the humanized travel time, the five client-certificate
tests (not built into the binary), and the two upstream expectations that encode
a stock-Firefox quirk and are replaced by `tests/camoufox/`.

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
1  unit      pythonlib                                  ~1 min
2  browser   build  (patches/additions/settings/assets/upstream.sh/Makefile/scripts changed)
             fetch  (anything else -- driver changes test against the published release)
3a smoke     patch guards, build-tester                 ~15 min
3b full      Playwright x2, leaks, stealth              ~40 min
4  gate      the required check
```

**Driver-only pull requests never build.** There is nothing new to compile, so
`fetch-browser` downloads the published release and the browser suites run
against the build users are actually on — a minute instead of seventy.

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
into a slow red build.

> One consequence of `cancel-in-progress`: pushing to a branch cancels its
> running build. That is right while iterating, but a 70-minute build will not
> survive a push made 20 minutes in.

## Running a piece by hand

```bash
python3 -m ci.run_playwright --binary path/to/camoufox-bin
python3 -m ci.run_playwright --binary path/to/camoufox-bin --shard 3/6
python3 -m ci.run_native     --subset rules            # no browser needed
python3 -m ci.run_native     --subset browser --binary path/to/camoufox-bin
python3 -m ci.run_sundial    --binary path/to/camoufox-bin
python3 -m ci.summarize      --results-dir .ci-work/results
```

Each writes one result file to `.ci-work/results/`. `ci/summarize.py` folds the
shards, decides, and renders the table. A required suite that produced no result
file is a **failure**, never a skip — otherwise deleting a job would be the
cheapest way to a green tick.

## Self-tests

`ci/tests/` asserts the pipeline reports honestly: redaction leaks nothing,
skips carry reasons, shards partition exactly once, version resolution never
picks a suite newer than the browser. These run in the `static` job on every
pull request.
