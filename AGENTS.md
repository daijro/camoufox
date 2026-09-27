# AGENTS.md

Instructions for any coding agent working in this repository: Claude Code,
Codex, Cursor, Copilot, Gemini or anything else. `CLAUDE.md` only imports this
file, so there is one set of rules. Edit them here.

---

## Before you touch anything

1. **This repository is public.** The professionalism rules below govern every
   line, commit message, PR title and comment you write.
2. **Read [`ci/tribal-rules.yml`](ci/tribal-rules.yml).** It lists the decisions
   this repo has already made, each with its evidence. Many are checked by
   `native-tests/test_tribal_rules.py`. Do not reopen one without new evidence.
   When a new decision is argued and settled, add it there with its citation.
3. **Branch off `main`. Never commit or push to `main`.** Every change is a pull
   request tied to a GitHub issue ([`CONTRIBUTING.md`](CONTRIBUTING.md)).

## Before you write a function

Search for an existing implementation first: `pythonlib/camoufox/`, `ci/`,
`scripts/` and `additions/`. If something close
exists, extend it rather than forking it. Duplicated logic is a serious defect
here, because the copies drift and a fingerprint built from two drifting copies
is detectable.

## Professionalism

A public repository is a finished product. People judge the project by what
is in it, and they will not ask what a file was for.

- **No garbage.** No scratch files, diagnostic scripts, saved test output,
  logs, debug logging, commented-out code, dead code, placeholder text, stub
  docs, or `TODO`s left as notes to self.
- **Nothing private reaches this repo.** That includes proprietary results,
  private repo names, and per-vector stealth detail. `ci/run_sundial.py` reports
  a grade and a count; the vectors never leave that module.
- Write commits and PR titles for a stranger reading them in a year.
- **Documentation is never stale.** Update the README, `docs/` and the package
  READMEs in the same pull request as the code that changed them, never
  "later". Every snippet must run as written.

## Code

- **Less code.** More code is a cost, not an achievement. Make minimal, general
  changes, and delete dead code when you find it.
- **No band-aids.** Fix the main flow. A hard-coded value or a special case at
  the call site is a bug relocated, not fixed.
- **Fallbacks are a last resort.** They turn a loud failure into a silent wrong
  answer, and in an anti-detect browser a silent wrong answer is a fingerprint.
  Fail loudly instead.
- **Check real data before inventing a value.** Every spoofed value must be
  something a real device reports. Take it from the recorded distributions
  (fpgen, `pythonlib/camoufox/*.json`), not from memory.
- **Read the provider's docs** before writing against a third-party API or a
  Firefox internal. Never infer an endpoint, pref or field from memory.
- **Comments say why, in a sentence or two.** Simple code needs none. A longer
  explanation is a decision: put it in `ci/tribal-rules.yml` or `docs/`.

## Tests

- **Run the failing test, not the whole suite.** CI runs the full pipeline on
  every pull request.
- **Write test output to a log file and grep the file.** Piping a run straight
  into `grep` throws away output you will need. Delete the log afterwards.
- **Every bug gets a regression test, in this order:** reproduce it with a test
  and confirm the test fails, fix the bug, confirm the test passes, then land
  both.
- **No flakes.** An intermittent failure means something is non-deterministic.
  Fix that behaviour. Never retry, loosen a threshold or skip the test to get
  green.
- **A missing prerequisite fails in CI; it never passes as a skip.** A skip
  reads as green, so a job that forgot to install something passes having
  tested nothing.
- **When local and CI disagree, name the mechanism and fix it in the repo.**
  Typical causes are git-ignored inputs, skipped prerequisites and cold-cache
  races. A fresh clone is a sanity check, not a fix.
- **Never write a test just to pass, or code just to pass a test.**

## Security

- **Never commit a credential.** That covers code, config, fixtures, logs and
  commit messages. CI secrets live in GitHub Actions secrets.
- **Least privilege** for workflows and tokens. Grant `permissions:` per job,
  and only what that job needs.
- **Adding a dependency is a decision.** Say why in the pull request, and commit
  the lockfile.

## Working with the maintainers

- Say when a direction is wrong, before starting, and give the reason.
- Review your own diff the way a strict senior reviewer would. You are biased
  toward what you just wrote.
- Explain plainly and briefly.

## Parallel work

- **Separate pull requests:** one agent per task, each in its own git worktree,
  running at the same time.
- **One pull request with independent slow parts:** use subagents in worktrees.
  Merge each part into your branch as it finishes, then delete the worktrees.
- **Shared files or an ordering requirement:** use one agent.

---

# Repository

## What this is

Camoufox is an anti-detect Firefox for web scraping and automation. This repo
is **not the Firefox source**. It is a build system that fetches upstream
Firefox, applies `patches/` and copies in `additions/`, and produces the
browser. Fingerprint spoofing happens in C++ and in Juggler, not in injected
JavaScript, so a page cannot see it.

`upstream.sh` pins `version` and `release`. The `Makefile` sources and exports
it, so every script sees them. The Firefox tree lives in
`camoufox-<version>-<release>/`. It is generated: persist a change there as a
patch, never as an edit to that tree.

| Path | What it is |
|---|---|
| `patches/` | Diffs applied to Firefox (44 top level, plus `playwright/`, `librewolf/`, `ghostery/`). Browser behaviour changes here. |
| `additions/camoucfg/` | The C++ config layer. `MaskConfig.hpp` reads `CAMOU_CONFIG`, which the patches consult. |
| `additions/juggler/` | Camoufox's Juggler, Playwright's Firefox protocol. The page agent runs in an isolated world. `input/` holds the Cursory cursor trajectories. |
| `settings/` | `camoufox.cfg` (prefs), `properties.json` (every config key and its type), `chrome.css`, policies. |
| `scripts/` | `patch.py` applies patches and writes the mozconfig; `copy-additions.sh`, `package.py`, `install-deps.sh`, font tooling. |
| `pythonlib/` | The `camoufox` PyPI package, the reference launcher. It draws identities with [fpgen](https://github.com/scrapfly/fingerprint-generator), checks them with `coherence.py`, and launches the binary. |
| `ci/` | The test pipeline (below). `ci/tribal-rules.yml` holds the settled decisions. |
| `build-tester/`, `tests/`, `native-tests/`, `service-tester/` | Test suites (below). |
| `bundle/` | Font bundle manifests. The fonts themselves are a release asset: `make fonts-extract`. |

## Building

The build runs on **Linux**. Windows and macOS binaries are cross-compiled from
it. `mach` needs Python 3.11 or newer.

```bash
bash scripts/install-deps.sh   # host build dependencies
make dir                       # fetch Firefox, copy additions, apply every patch
make bootstrap                 # one time: system packages + mach bootstrap
make build                     # ./mach build
make run                       # run the build (wipes ~/.camoufox)
make package-linux arch=x86_64 # or package-macos / package-windows
python3 multibuild.py --target linux windows macos --arch x86_64 arm64
```

Install `ccache`. A cold build takes about 40 minutes, and an incremental one
about 5.

## Changing a patch

Never hand-edit a `.patch` file. Edit the tree, then write the diff:

```bash
make dir && make first-checkpoint          # a new patch: checkpoint, edit, then
make diff > patches/my-change.patch        # (git add -N new files first)

make dir && make workspace ./patches/x.patch   # an existing patch: edit, then
make diff > patches/x.patch
```

`make patch` and `make unpatch` apply or reverse one patch. `make revert` resets
the tree to unpatched Firefox. Keep the `Makefile` diff minimal: host
dependencies belong in `scripts/install-deps.sh`.

## Testing

`ci/` is the whole pipeline. It runs the same way locally and on a pull request
([`ci/README.md`](ci/README.md)). Branch protection requires one check, **`All
tests passed`**. Run the suite that covers your change while you work:

| You changed | Run |
|---|---|
| Patches, C++, Juggler | `python3 -m ci.run_build_tester --binary <camoufox-bin>` (the anti-detect suite) and `python3 -m ci.run_patch_guards --binary <camoufox-bin>` (one guard per shipped behaviour, in three groups: `--group spoofing|automation|parity`) |
| Automation behaviour | `make tests`, the upstream Playwright suite with `ci/skiplist.yml` applied |
| `pythonlib/` | `python3 -m ci.run_pythonlib` |
| `ci/` itself | `python3 -m pytest ci/tests -q` |

- **`tests/` is not a fork of Playwright's tests.** It holds only `patches/`
  and `camoufox/`. A deliberate difference from upstream goes in
  `ci/skiplist.yml`, with its reason.
- **Tests against an unpackaged build** need `make stage-fonts` first. Without
  it the browser has no content fonts.
- **The stealth grade** (`ci/run_sundial.py`) reports a letter and a count, never
  the individual vectors.
