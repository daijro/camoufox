#!/usr/bin/env python3
"""Work out which browser this run tests, and which Playwright suite tests it.

Called by every entry point, so a pull request and the auto-update harness agree
on what "the tests" means:

  pull request      browser comes from upstream.sh; suite is whichever released
                    playwright-python tag targets that Firefox generation.
  auto-update       the harness passes the Firefox version it is moving to, and
                    the same resolution runs against that instead.

Suite selection is "newest released tag whose pinned Firefox is not ahead of
ours". Playwright trails Firefox by weeks, so requiring an exact match would
mean no suite at all for most of a release cycle; taking a newer suite than the
browser would mean testing against an automation contract that assumes engine
work this build does not have. Newest-not-ahead is the one that is both
available and honest.

Run:
    python3 -m ci.versions --json
    python3 -m ci.versions --browser-version 153.0.4 --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from ._util import (
    REPO_ROOT,
    http_json,
    log,
    major,
    parse_version,
    read_upstream_sh,
    set_output,
)

BROWSERS_JSON = "https://raw.githubusercontent.com/microsoft/playwright/{ref}/packages/playwright-core/browsers.json"
TAGS_API = "https://api.github.com/repos/microsoft/playwright-python/tags?per_page=100"
PYPROJECT = "pythonlib/pyproject.toml"
_CEILING = re.compile(r'^playwright\s*=\s*"<\s*([0-9][0-9.]*)"', re.M)

# Consulted only when the network is unavailable or GitHub is rate-limiting an
# unauthenticated runner. Deliberately short: it is a floor, not a source of
# truth, and a stale entry here is better than a run that cannot start.
FALLBACK_PINS: Tuple[Tuple[str, str], ...] = (
    ("v1.62.0", "153.0"),
    ("v1.61.0", "151.0"),
    ("v1.60.0", "150.0.2"),
    ("v1.59.0", "148.0.2"),
    ("v1.58.0", "146.0.1"),
)


def _gh_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def released_tags(limit: int = 40) -> List[str]:
    """Final playwright-python tags, newest first."""
    tags = http_json(TAGS_API, headers=_gh_headers())
    parsed: List[Tuple[Tuple[int, int, int], str]] = []
    for tag in tags:
        name = tag.get("name", "")
        if not name.startswith("v") or any(m in name for m in ("alpha", "beta", "rc", "next", "-")):
            continue
        try:
            parsed.append((parse_version(name[1:]), name))
        except ValueError:
            continue
    parsed.sort(reverse=True)
    return [name for _, name in parsed[:limit]]


def firefox_pinned_by(tag: str) -> Optional[str]:
    """The Firefox browserVersion a Playwright tag ships against."""
    try:
        data = http_json(BROWSERS_JSON.format(ref=tag))
    except Exception:
        return None
    for browser in data.get("browsers", []):
        if browser.get("name") == "firefox":
            return browser.get("browserVersion")
    return None


def pins(limit: int = 10) -> List[Tuple[str, str]]:
    """[(playwright tag, firefox version)], newest first, with a fallback."""
    try:
        out = []
        for tag in released_tags()[:limit]:
            firefox = firefox_pinned_by(tag)
            if firefox:
                out.append((tag, firefox))
        if out:
            return out
        log("no Playwright pins resolved from the network", level="WARN")
    except Exception as exc:  # noqa: BLE001
        log(f"could not reach the Playwright tag list ({exc}); using the built-in table", level="WARN")
    return list(FALLBACK_PINS)


def client_ceiling() -> Optional[Tuple[int, int, int]]:
    """The Playwright version pythonlib refuses to go to, or None if unpinned.

    `camoufox.server` imports `playwright._impl._driver`, a private API with no
    compatibility guarantee, and every Playwright minor is free to change
    Juggler. pythonlib pins a ceiling for that reason, and a suite run above it
    would be testing the browser against a client its own package will not
    install -- a green run that proves nothing a user can reproduce.
    """
    try:
        text = (REPO_ROOT / PYPROJECT).read_text(encoding="utf-8")
    except OSError:
        return None
    found = _CEILING.search(text)
    if not found:
        return None
    try:
        return parse_version(found.group(1))
    except ValueError:
        return None


def resolve(
    *,
    browser_version: Optional[str] = None,
    playwright_tag: Optional[str] = None,
) -> Dict[str, str]:
    """Everything a run needs to know about versions."""
    upstream = read_upstream_sh()
    browser_version = browser_version or upstream.get("version", "")
    release = upstream.get("release", "")
    if not browser_version:
        raise SystemExit("could not determine a browser version; upstream.sh has no `version`")

    available = pins()

    if playwright_tag:
        pinned = dict(available).get(playwright_tag) or firefox_pinned_by(playwright_tag) or ""
        chosen = (playwright_tag, pinned)
        note = f"pinned explicitly to {playwright_tag}, which targets Firefox {pinned or '?'}"
    else:
        ours = major(browser_version)
        # Newest suite that is not ahead of the browser we are testing.
        eligible = [(t, f) for t, f in available if major(f) <= ours]

        # ... and not above the client ceiling pythonlib pins. Dropping this
        # filter does not fail loudly: the suite installs a client the shipped
        # package forbids, and whatever Juggler changed in between reads as a
        # browser bug.
        ceiling = client_ceiling()
        if ceiling and eligible:
            allowed = [(t, f) for t, f in eligible if parse_version(t.lstrip("v")) < ceiling]
            if allowed and allowed != eligible:
                dropped = sorted({t for t, _ in eligible} - {t for t, _ in allowed})
                log(
                    f"ignoring {', '.join(dropped)}: at or above pythonlib's "
                    f"playwright ceiling ({PYPROJECT})"
                )
                eligible = allowed
            elif not allowed:
                log(
                    f"every suite not ahead of Firefox {ours} is at or above pythonlib's "
                    f"playwright ceiling; testing above it. Bump the ceiling in {PYPROJECT} "
                    "or expect protocol noise.",
                    level="WARN",
                )

        if eligible:
            chosen = max(eligible, key=lambda tf: parse_version(tf[1]))
            note = (
                f"the newest released suite not ahead of Firefox {ours} "
                f"(it targets Firefox {chosen[1]})"
            )
        else:
            # Every known suite is newer than this browser -- an old branch, or
            # a Firefox so new nothing targets it yet. Take the oldest available
            # rather than refusing to test at all, and say so loudly.
            chosen = min(available, key=lambda tf: parse_version(tf[1]))
            note = (
                f"no suite targets Firefox {ours} or older; falling back to the oldest "
                f"available ({chosen[0]}, Firefox {chosen[1]}). Expect conformance noise."
            )
            log(note, level="WARN")

    ours_display = major(browser_version)
    resolved = {
        "browser_version": browser_version,
        "browser_release": release,
        "playwright_tag": chosen[0],
        "playwright_firefox": chosen[1],
        "note": note,
    }
    log(
        f"testing Camoufox {browser_version} ({release or 'no release tag'}), built on "
        f"Firefox {ours_display}, against Playwright {chosen[0]} -- {note}"
    )
    return resolved


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-version", help="override the version from upstream.sh")
    parser.add_argument("--playwright-tag", help="pin the suite instead of resolving one")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    resolved = resolve(
        browser_version=args.browser_version, playwright_tag=args.playwright_tag
    )
    if args.json:
        print(json.dumps(resolved, indent=2, sort_keys=True))
    for key, value in resolved.items():
        set_output(key, value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
