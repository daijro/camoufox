# Contributing to Camoufox

Thanks for your interest in contributing.

| Contribution | How |
|---|---|
| Bug report | Open an issue with steps to reproduce, expected behaviour and actual behaviour. |
| Detection report | Use the "Camoufox detected" issue template. |
| Feature request | Open an issue describing the use case. |
| Code or docs | Fork, branch, and open a pull request tied to an issue. |

Comment on an issue before you start work on it.

## Setup

The browser builds on Linux; the steps are in the
[README](README.md#building-the-browser). Install [ccache](https://ccache.dev/)
(`sudo apt install ccache` or `sudo dnf install ccache`). The build config
enables it, so a rebuild after a small change takes about 5 minutes instead of
40.

### What goes where

| Change | Repository |
|---|---|
| The launchers, Python and TypeScript: launch options, fingerprint generation and its data files, geoip, `camoufox fetch` and the rest of the CLI, the MCP server | [CamouBrowser/camoucore](https://github.com/CamouBrowser/camoucore), where they ship in the one `camoucore` package as `camoucore.camoufox` (npm: `camoucore/camoufox`). Code, tests and issues go there ([Python](https://github.com/CamouBrowser/camoucore/blob/main/python/camoucore/docs/camoufox.md#development), [TypeScript](https://github.com/CamouBrowser/camoucore/blob/main/typescript/camoucore/docs/camoufox.md#development)). |
| The browser: patches, settings, fonts, the build, its tests and CI | Here. |
| The `camoufox` release wrapper (`pyproject.toml`, `camoufox/`, `camoufox_pin/`, `npm/`): camoucore's launcher under the `camoufox` name, an exact `camoucore` pin and the browser pin | Here, but it holds no launcher code: only alias stubs and version pins. |

A change that needs both ships the browser first, then the launcher
([`ci/README.md`](ci/README.md#the-driver)). The static CI job fails a pull
request here that adds launcher code (`python/`, `typescript/`, a
`camoufox/` module that is more than an alias stub, or Python or TypeScript
outside `browser/`, `ci/` and `.github/`); open it against camoucore
instead.

## Pull request rules

The engineering rules in [`AGENTS.md`](AGENTS.md) apply to every change,
whether a person or an agent wrote it: less code, no band-aids, no flakes, and
docs that ship with the code.

1. Each pull request is associated with a GitHub issue.
2. Follow the pull request template.
3. Keep commits focused: one logical change per commit.
4. Describe what you changed and why.
5. The test pipeline must pass.

## Testing

**CI runs everything on every pull request.**
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) builds the browser
from your branch when you touch browser sources (and tests the published
release when you do not), then runs every suite. Branch protection requires one
check, **`All tests passed`**. CI leaves a summary comment on the pull request,
so there is nothing to attach by hand.

The stealth check needs a credential, and GitHub gives secrets only to pull
requests whose branch is in this repository. If you have write access, push your
branch here rather than to a fork; on a fork pull request that check is skipped
and the summary says so.

While you work, run the suite that covers your change:

| You changed | Run | Docs |
|---|---|---|
| Which suite for which change | the table in `AGENTS.md` | [`AGENTS.md`](AGENTS.md#testing) |
| Any CI job, locally | `python3 -m ci.<runner>` | [`ci/README.md`](ci/README.md#running-a-piece-by-hand) |
| Browser patches, C++, Juggler | build-tester: the raw binary, no launcher | [`browser/tests/build-tester/README.md`](browser/tests/build-tester/README.md) |
| Proxy handling | service tests: the installed driver with real proxies | [`browser/tests/service/README.md`](browser/tests/service/README.md) |

build-tester and the service tests check different layers, and passing one
does not stand in for the other. How they differ:
[build-tester README](browser/tests/build-tester/README.md#how-it-differs-from-the-service-tests).

## Reporting issues

Search existing issues first. A launcher problem (options, identities, install,
`camoufox fetch`) belongs in [camoucore's issues](https://github.com/CamouBrowser/camoucore/issues);
a browser one (a patch, a detection, a crash) here. Include:

- Camoufox package and browser version (`camoufox version`)
- OS, and your Python or Node.js version
- A minimal reproducible example
