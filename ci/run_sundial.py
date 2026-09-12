#!/usr/bin/env python3
"""Stealth gate: drive the private sundial suite and bring back numbers only.

Sundial is a private detection suite. Its value is that the vectors it probes
are not public, so **nothing identifying a vector may ever leave this module**:
not a name, not a description, not a measured value, not the test's source. This
repository is public, and an evidence file or a pull-request comment is
permanent. Everything downstream of `_redact()` is counts and opaque ids.

The opaque id is `HMAC(salt, vector_key)`. That is enough to notice "the vector
that passed last release is failing now", which is the only thing the gate
needs, and it is not enough to learn what the vector was.

Scope: only categories Camoufox actually claims to implement are gated
(`policy.yml: gates.sundial.gated_categories`). Cross-OS rendering parity, for
one, is measured and reported but never fails a build -- Camoufox does not claim
byte-identical emulation of another platform's rasterizer.

How it runs:
  1. Form-login to sundial, keep the `sundial_session` cookie.
  2. Start a loopback collector.
  3. Launch the built binary, seed the cookie, open `?auto=1&post=<collector>`.
     Sundial runs its scan on load and POSTs `window.fullReport` back.
  4. Redact, score, write evidence.

Run:
    python3 -m ci.run_sundial --binary /path/to/camoufox-bin
    python3 -m ci.run_sundial waive --key '<vector key>' --reason '...'
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import results as evidence
from ._util import CI_DIR, RESULTS_DIR, WORK_DIR, log, opaque_id, run

CONFIG_PATH = CI_DIR / "sundial.yml"
COOKIE_NAME = "sundial_session"
# The account CI logs in as. `guest` is the least-privileged role the deployment
# actually has (sundial 0.5.0): its middleware refuses `guest` the private-vector
# bundle outright, so the definitions this repository must never see are not
# served to this session at all.
#
# Two guarantees keep a vector out of a public log, and it is worth being precise
# about which is which, because only one of them is enforced by the server:
#
#   server-side  `guest` cannot load vectors-private.js (_middleware.js checks
#                the role against isPrivateVectorAsset).
#   client-side  this gate only ever requests `/?auto=1&score=1`, and redact()
#                refuses to process anything that is not a score payload, so a
#                deployment that ignored `score=1` fails the run instead of
#                folding a report down and carrying on.
#
# The stricter option is sundial's score-only `ci` role, which is refused
# anything but `/?auto=1&score=1` server-side and so cannot retrieve a report
# even if this credential leaks. That role is not in sundial's master branch and
# is therefore not deployed; when it lands, set SUNDIAL_USERNAME=ci and the
# server-side half of the guarantee gets stronger with no change here.
DEFAULT_USERNAME = "guest"
DEFAULT_URL = "https://sundial.daijro.dev"

# Report fields that may describe a private vector. Dropped without exception.
_FORBIDDEN_FIELDS = (
    "name", "brief", "src", "source", "value", "expect", "requires",
    "key", "id", "cat", "elapsedMs", "entropy",
)

# The complete set of keys allowed to leave this module. A whitelist, checked at
# runtime, because a blacklist only stops the leaks somebody already thought of:
# add a field to redact() and forget to think about it, and a blacklist ships it.
# This fails the run instead.
#
# There are deliberately no per-vector rows here, not even opaque ones. An HMAC
# does not name a vector, but a map of them is still per-vector data: it says how
# many distinct checks fail and lets a reader follow the same id across releases.
# The instruction is a score, so this is a score.
_PUBLISHABLE = frozenset({
    "grade",              # a letter
    "checks_total",       # how many in-scope checks were scored
    "checks_passed",
    "pass_rate",
    "out_of_scope_failed",  # a single count, no attribution
    "unknown_category_checks",  # ditto -- how many, never which
    "cross_os_total",     # host-OS detectors: measured, never gated
    "cross_os_passed",
    "score_mode",         # did sundial answer in score mode? a protocol fact
    "os",                 # which profile it was measured under; we chose it
    "sundial_version",
    "schema_version",
    "policy_violations",  # our own strings, not sundial's
})


def _assert_publishable(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Refuse to hand back anything not on the whitelist."""
    extra = set(metrics) - _PUBLISHABLE
    if extra:
        raise RuntimeError(
            f"the stealth gate tried to publish {sorted(extra)}, which is not on the "
            "whitelist in ci/run_sundial.py. Sundial's vectors are private and this "
            "repository is public; add the key to _PUBLISHABLE only after deciding it "
            "is a score and not a metric."
        )
    return metrics


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


# Cloudflare sits in front of sundial and refuses a document request carrying a
# non-browser User-Agent -- Python's urllib default and anything else that does
# not look like a browser gets a 403 before the request reaches sundial at all.
# So present as one. This has to be on *every* request, not just the first: a
# client that authenticates with browser headers and then fetches with urllib's
# defaults logs in successfully and gets a confusing 403 on the very next hop.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Upgrade-Insecure-Requests": "1",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Both auth routes answer 303 + Set-Cookie; following it hides the cookie."""

    def redirect_request(self, *_args, **_kwargs):  # noqa: D102
        return None


def _session_cookie(headers) -> Optional[str]:  # noqa: ANN001
    for raw in headers.get_all("Set-Cookie") or []:
        if raw.startswith(COOKIE_NAME + "="):
            value = raw.split(";", 1)[0][len(COOKIE_NAME) + 1 :]
            if value:
                return value
    return None


def login_with_key(base_url: str, key: str, *, timeout: int = 30) -> str:
    """Token login: `GET /automated?key=` mints the session cookie.

    This is the route the credential in CI is actually for -- sundial's
    `make pages-automation-keys` mints report-URL keys, and a key presented here
    resolves to the `guest` role. Tried before the form because it needs no
    username, so there is no second secret to keep in step with whatever
    `GUEST_USER` was set to.
    """
    url = base_url.rstrip("/") + "/automated?key=" + urllib.parse.quote(key, safe="")
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        resp = opener.open(req, timeout=timeout)
        status, headers = resp.status, resp.headers
    except urllib.error.HTTPError as exc:
        status, headers = exc.code, exc.headers
    cookie = _session_cookie(headers)
    if cookie:
        log("sundial auth OK (automation key)")
        return cookie
    raise RuntimeError(f"the automation key route returned {status} and no session cookie")


def login(base_url: str, username: str, password: str, *, timeout: int = 30) -> str:
    """Form-login and return the session cookie value.

    The endpoint answers 303 + Set-Cookie on success and 401 + the login page on
    failure, so a redirect handler would hide the result; handle it manually.
    """
    body = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/__auth/login",
        data=body,
        method="POST",
        headers={
            **_BROWSER_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        resp = opener.open(req, timeout=timeout)
        status, headers = resp.status, resp.headers
    except urllib.error.HTTPError as exc:
        status, headers = exc.code, exc.headers
        if status == 401:
            raise RuntimeError(
                "sundial rejected the credentials. Check SUNDIAL_USERNAME and "
                "SUNDIAL_AUTOMATION_KEY."
            ) from None
        if status == 429:
            raise RuntimeError("sundial rate-limited the login; try again in a few minutes.") from None
        if status != 303:
            raise RuntimeError(f"sundial login returned {status}") from None

    cookie = _session_cookie(headers)
    if cookie:
        log("sundial login OK (form)")
        return cookie
    raise RuntimeError("sundial login succeeded but returned no session cookie")


def scrub(text: str, secret: str) -> str:
    """Remove a secret from text that is about to be published.

    Whatever goes into result.note() reaches the results artifact and the pull
    request comment, and an exception raised deep inside urllib can carry the
    URL that produced it -- which, for the token route, is the credential. So
    nothing built from an exception is published until it has been through here.
    Both the raw secret and its percent-encoded form, because the URL holds the
    latter.
    """
    if not secret:
        return text
    for form in (secret, urllib.parse.quote(secret, safe="")):
        if form:
            text = text.replace(form, "<redacted>")
    return text


def authenticate(base_url: str, username: str, secret: str, *, timeout: int = 30) -> str:
    """Get a session cookie, whichever shape the stored credential is.

    SUNDIAL_AUTOMATION_KEY has been both things over this repository's life: an
    automation key for `/automated?key=`, and a password for the login form. The
    two are indistinguishable by looking at them, and which one a given
    repository holds is not something this code can know -- so try the key route
    first (it needs no username) and fall back to the form. The only cost when
    the secret is a password is one extra request that 401s.
    """
    errors = []
    try:
        return login_with_key(base_url, secret, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 -- reported below if the form fails too
        detail = scrub(str(exc), secret)
        errors.append(f"automation key: {detail}")
        log(f"automation-key login did not take ({detail}); trying the form", level="WARN")
    try:
        return login(base_url, username, secret, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"form login as {username!r}: {scrub(str(exc), secret)}")
    raise RuntimeError(
        scrub(
            "could not authenticate to sundial. Both routes were tried:\n  "
            + "\n  ".join(errors),
            secret,
        )
        + "\nSUNDIAL_AUTOMATION_KEY must be either an automation key from "
        "`make pages-automation-keys` or the password for the account named by "
        "SUNDIAL_USERNAME (default 'guest')."
    )


# ---------------------------------------------------------------------------
# collector
# ---------------------------------------------------------------------------


class _Collector:
    """Loopback endpoint that receives the one POST sundial makes."""

    def __init__(self) -> None:
        self.payload: Optional[dict] = None
        self._event = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8", "replace")
                try:
                    outer.payload = json.loads(raw)
                except json.JSONDecodeError:
                    outer.payload = {"_parse_error": raw[:500]}
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                outer._event.set()

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def log_message(self, *_args) -> None:  # keep the run log readable
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "_Collector":
        self._thread.start()
        log(f"collector listening on 127.0.0.1:{self.port}")
        return self

    def __exit__(self, *_exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    def wait(self, timeout: float) -> Optional[dict]:
        self._event.wait(timeout)
        return self.payload


# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------


def _iter_entries(report: dict) -> List[Tuple[str, str, str]]:
    """(vector_key, category, status) for every vector, public and private."""
    out: List[Tuple[str, str, str]] = []
    buckets = ("failures", "succeeded", "pending", "skipped")
    for scope in (report, report.get("private") or {}):
        if not isinstance(scope, dict):
            continue
        for bucket in buckets:
            grouped = scope.get(bucket)
            if not isinstance(grouped, dict):
                continue
            for category, entries in grouped.items():
                for entry in entries or []:
                    if not isinstance(entry, dict):
                        continue
                    key = entry.get("key") or entry.get("id") or ""
                    if not key:
                        continue
                    out.append((str(key), str(category or "Uncategorised"), str(entry.get("status", "pending"))))
    return out


_STATUS_MAP = {
    "pass": evidence.PASS,
    "fail": evidence.FAIL,
    "error": evidence.ERROR,
    "skipped": evidence.SKIP,
    "pending": evidence.SKIP,
}


def grade(pass_rate: float) -> str:
    """A single letter, which is the only stealth number that goes public."""
    for floor, letter in ((0.99, "A+"), (0.97, "A"), (0.94, "B"), (0.90, "C"), (0.80, "D")):
        if pass_rate >= floor:
            return letter
    return "F"


def _from_buckets(payload: dict, gated: List[str], ungated: List[str]) -> Dict[str, int]:
    """Fold sundial's score payload into the three numbers we publish.

    Buckets arrive keyed "<Category>|<class>". Category decides scope -- whether
    Camoufox claims that area at all -- and class decides whether a failure is
    the browser's fault or the machine's.

    A category in neither list is counted separately. sundial's taxonomy is nine
    top-level sections and ci/sundial.yml names all nine, so a tenth means
    sundial grew one and nobody decided whether Camoufox claims it. Folding that
    into "out of scope" would answer the question by default, in the direction
    that never fails a build -- a stealth blind spot that looks like a pass.
    """
    gated_set = {c.lower() for c in gated}
    known = gated_set | {c.lower() for c in ungated}
    scored = passed = 0
    out_of_scope_failed = 0
    unknown_scored = 0
    cross_total = cross_passed = 0

    for key, bucket in (payload.get("buckets") or {}).items():
        category, _, cls = str(key).partition("|")
        n_scored = int(bucket.get("scored", 0))
        n_passed = int(bucket.get("passed", 0))

        if cls == "crossOs":
            # Host-OS detectors read the machine underneath, not the disguise.
            # Camoufox does not claim byte-identical cross-OS emulation, so
            # these are reported and never gated -- counting them against the
            # score would be marking it down for a promise nobody made.
            cross_total += n_scored
            cross_passed += n_passed
            continue

        if category.lower() in gated_set:
            scored += n_scored
            passed += n_passed
        else:
            out_of_scope_failed += n_scored - n_passed
            if category.lower() not in known:
                unknown_scored += n_scored

    return {
        "scored": scored,
        "passed": passed,
        "out_of_scope_failed": out_of_scope_failed,
        "unknown_category_checks": unknown_scored,
        "cross_os_total": cross_total,
        "cross_os_passed": cross_passed,
    }


def redact(
    payload: dict,
    gated: List[str],
    ungated: List[str],
    *,
    os_name: str = "",
    require_score_mode: bool = True,
) -> Dict[str, Any]:
    """Turn sundial's response into a score, and nothing else.

    Two shapes arrive here. `mode: "score"` is the one to want: sundial has
    already aggregated, so no vector identity ever crossed the wire. A full
    report is **refused** unless `require_score_mode=False`, because the `ci`
    role this gate authenticates as cannot be served one -- so a report arriving
    means the run is misconfigured, and folding it down would hide that while
    the vectors sat in this process. The flag is for a deliberate local run
    under an account sundial does allow a report.

    Either way what leaves is a grade, how many in-scope checks were scored and
    passed, a count of out-of-scope failures, and the cross-OS tally kept
    separate. No names, no values, no categories, and no per-vector rows -- not
    even opaque ones, because a map of HMACs still publishes how many distinct
    checks fail and lets a reader follow one across releases.

    Regression detection is therefore per-score, not per-vector: policy.yml
    carries a floor and a maximum allowed drop. For the per-vector view set
    SUNDIAL_REPORT_AGE_RECIPIENT and read the sealed report locally.
    """
    score_mode = payload.get("mode") == "score"
    if not score_mode and require_score_mode:
        # This gate asks for `/?auto=1&score=1` and nothing else, so a full
        # report cannot legitimately arrive here. If one does, the deployment
        # ignored `score=1` -- it predates score mode, or the request did not
        # reach the code that honours it. Either way the vectors are now in this
        # process, and the honest thing is to fail loudly rather than quietly
        # fold them down and carry on as though the guarantee had held.
        raise RuntimeError(
            "sundial answered with a full report, not a score. This gate only ever "
            "requests `?auto=1&score=1`, so the deployment did not honour it: check that "
            "sundial is at 0.5.0 or later (score mode landed in f136985). Refusing to "
            "process the payload. Pass --allow-full-report for a deliberate local run "
            "under an account that is allowed one."
        )
    if score_mode:
        counts = _from_buckets(payload, gated, ungated)
    else:
        # Legacy path: fold a full report down to the same numbers.
        gated_set = {c.lower() for c in gated}
        known = gated_set | {c.lower() for c in ungated}
        scored = passed = out_of_scope_failed = unknown_scored = 0
        for _key, category, status in _iter_entries(payload):
            outcome = _STATUS_MAP.get(status, evidence.SKIP)
            if outcome not in (evidence.PASS, evidence.FAIL, evidence.ERROR):
                continue
            if category.lower() in gated_set:
                scored += 1
                passed += outcome == evidence.PASS
            else:
                if outcome != evidence.PASS:
                    out_of_scope_failed += 1
                if category.lower() not in known:
                    unknown_scored += 1
        counts = {
            "scored": scored, "passed": passed,
            "out_of_scope_failed": out_of_scope_failed,
            "unknown_category_checks": unknown_scored,
            "cross_os_total": 0, "cross_os_passed": 0,
        }

    rate = round(counts["passed"] / counts["scored"], 4) if counts["scored"] else 0.0
    return _assert_publishable({
        "score_mode": score_mode,
        "grade": grade(rate),
        "checks_total": counts["scored"],
        "checks_passed": counts["passed"],
        "pass_rate": rate,
        "out_of_scope_failed": counts["out_of_scope_failed"],
        "unknown_category_checks": counts["unknown_category_checks"],
        "cross_os_total": counts["cross_os_total"],
        "cross_os_passed": counts["cross_os_passed"],
        "os": os_name,
        "sundial_version": payload.get("sundialVersion"),
        "schema_version": payload.get("schemaVersion"),
    })


# ---------------------------------------------------------------------------
# the scan
# ---------------------------------------------------------------------------


async def scan(
    *,
    binary: Path,
    base_url: str,
    cookie: str,
    os_name: str,
    headless: bool,
    timeout: float,
) -> dict:
    """Open sundial in the built browser and collect the report it posts back."""
    from camoufox.async_api import AsyncCamoufox

    host = urllib.parse.urlparse(base_url).hostname or "sundial.daijro.dev"

    with _Collector() as collector:
        # score=1 makes sundial post counts rather than the report itself, so
        # the vectors never cross the wire. Without it the full report arrives
        # here and the only thing keeping it private is redact() being called --
        # this makes the leak structurally impossible instead of policy-based.
        target = (
            f"{base_url.rstrip('/')}/?auto=1&score=1&post="
            + urllib.parse.quote(f"http://127.0.0.1:{collector.port}/collect", safe="")
        )
        async with AsyncCamoufox(
            executable_path=str(binary),
            headless=headless,
            os=os_name,
            i_know_what_im_doing=True,
        ) as browser:
            context = await browser.new_context()
            await context.add_cookies(
                [{
                    "name": COOKIE_NAME,
                    "value": cookie,
                    "domain": host,
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Strict",
                }]
            )
            page = await context.new_page()
            log(f"opening sundial (auto scan) as {os_name}")
            await page.goto(target, wait_until="load", timeout=120_000)

            payload = await asyncio.get_running_loop().run_in_executor(
                None, collector.wait, timeout
            )
            await context.close()

    if payload is None:
        raise TimeoutError(
            f"sundial did not post a report within {timeout:.0f}s. The usual cause is an "
            "expired session cookie (the page silently renders the login form instead of "
            "the suite), or the browser failing to reach the loopback collector."
        )
    if "_parse_error" in payload:
        raise RuntimeError("sundial posted something that was not JSON")
    return payload


def seal(report: dict, out: Path) -> Optional[Path]:
    """Optionally keep an encrypted copy of the *full* report for debugging.

    Only written when SUNDIAL_REPORT_AGE_RECIPIENT names an age public key, and
    only readable by whoever holds the matching private key. Without it the full
    report is discarded, because there is nowhere safe to put it: workflow
    artifacts on a public repository are world-readable.
    """
    recipient = os.environ.get("SUNDIAL_REPORT_AGE_RECIPIENT", "").strip()
    if not recipient:
        log("no SUNDIAL_REPORT_AGE_RECIPIENT set -- discarding the full report unencrypted-on-disk")
        return None
    if not run(["which", "age"]).ok:
        log("age is not installed; cannot seal the full report", level="WARN")
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    plain = out.with_suffix(".tmp.json")
    plain.write_text(json.dumps(report), encoding="utf-8")
    try:
        res = run(["age", "-r", recipient, "-o", str(out), str(plain)])
    finally:
        plain.unlink(missing_ok=True)
    if not res.ok:
        log(f"sealing failed: {res.combined()[-400:]}", level="WARN")
        return None
    log(f"sealed full report -> {out} (only the age key holder can read it)")
    return out


# ---------------------------------------------------------------------------


def _config() -> dict:
    """Scope and thresholds, from ci/sundial.yml."""
    import yaml

    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def is_enabled(cfg: Optional[dict] = None) -> bool:
    """Whether CI may run the stealth check at all (ci/sundial.yml: enabled).

    Defaults to False when the key is absent: a check that talks to a private
    suite and posts the answer into a public log should be opt-in, so a config
    that predates the flag does not silently start running.
    """
    return bool((cfg if cfg is not None else _config()).get("enabled", False))


def status(argv: Optional[List[str]] = None) -> int:
    """Print the flag for the workflow, which decides whether to schedule the job."""
    parser = argparse.ArgumentParser(description="report whether the stealth gate is enabled")
    parser.parse_args(argv)
    print("true" if is_enabled() else "false")
    return 0


def gate(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, help="camoufox-bin under test")
    parser.add_argument("--os", dest="os_name", default="linux", choices=["linux", "macos", "windows"])
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--evidence-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--allow-full-report",
        action="store_true",
        help=(
            "accept a full report instead of the score. For a deliberate local run under an "
            "account sundial allows one; never in CI, where the account cannot obtain one."
        ),
    )
    args = parser.parse_args(argv)

    cfg = _config()
    base_url = os.environ.get("SUNDIAL_URL") or cfg.get("url") or DEFAULT_URL
    result = evidence.GateResult(gate="sundial")

    # Checked before the credential is read, and before anything is sent, so a
    # disabled gate cannot reach the deployment even by accident. The workflow
    # also declines to schedule the job; this is the second lock on the same
    # door, for a hand-run or a caller that ignores the first.
    if not is_enabled(cfg):
        # Deliberately writes NO result file, so a hand-run leaves the results
        # directory exactly as a CI run does -- there, the job is not scheduled
        # at all. summarize.py treats every non-pass result as a problem (a suite
        # that did not run has not passed), so emitting a skip here would fail a
        # summary that CI would have passed. And if some caller does require
        # `sundial`, the missing file is the loud failure it should be.
        log(
            "stealth gate disabled in ci/sundial.yml (`enabled: false`) -- not contacting "
            "sundial, and writing no result. See the comment there for what has to be true "
            "before turning it back on."
        )
        return 0

    # The username is not a secret -- it names an account. Only the password
    # needs protecting, so this defaults rather than demanding a second secret.
    username = (os.environ.get("SUNDIAL_USERNAME") or DEFAULT_USERNAME).strip()
    password = os.environ.get("SUNDIAL_AUTOMATION_KEY", "").strip()
    if not username or not password:
        result.note(
            "SUNDIAL_AUTOMATION_KEY is not set. The stealth gate is required by policy, so a "
            "missing credential fails the run rather than skipping it. (SUNDIAL_USERNAME is "
            f"optional and defaults to {DEFAULT_USERNAME!r}.)"
        )
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    from ._pytest import require_binary

    try:
        binary = args.binary or require_binary()
        cookie = authenticate(base_url, username, password)
        report = asyncio.run(
            scan(
                binary=binary,
                base_url=base_url,
                cookie=cookie,
                os_name=args.os_name,
                headless=not args.headful,
                timeout=args.timeout,
            )
        )
    except Exception as exc:  # noqa: BLE001 -- any failure here is a gate failure
        # Scrubbed: this note goes to the results artifact and the pull request
        # comment, and an exception from deep inside urllib can carry the URL
        # that raised it -- which for the token route contains the credential.
        result.note(scrub(f"{type(exc).__name__}: {exc}", password))
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1

    sealed = seal(report, WORK_DIR / "sundial-full-report.age")
    # The plaintext report is dropped here and never referenced again.
    try:
        metrics = redact(
            report,
            cfg.get("gated_categories") or [],
            cfg.get("ungated_categories") or [],
            os_name=args.os_name,
            require_score_mode=not args.allow_full_report,
        )
    except RuntimeError as exc:
        del report
        result.note(str(exc))
        result.finish(evidence.ERROR).save(args.evidence_dir)
        return 1
    del report

    # Deliberately no per-test map. See redact(): a set of opaque ids is still
    # per-vector data, and verify.py judges this gate on the score instead.
    result.metrics = metrics
    if sealed:
        result.artifacts.append(sealed.name)

    metrics = result.metrics
    # This string reaches the job summary and the pull request. Grade and counts
    # only -- no category, no vector, no value. The keys are the ones on
    # _PUBLISHABLE; read them through it so that renaming one breaks here rather
    # than silently rendering a zero.
    result.note(
        f"grade {metrics['grade']} -- {metrics['checks_passed']}/{metrics['checks_total']} "
        f"in-scope checks passed ({metrics['pass_rate'] * 100:.1f}%). "
        f"{metrics['out_of_scope_failed']} out-of-scope check(s) failed; those are measured "
        "but not gated, because Camoufox does not claim them."
    )

    floor = float(cfg.get("min_pass_rate", 0) or 0)
    status = evidence.PASS
    # Absolute rules, independent of the baseline: a run that scores badly fails
    # even if the previous release scored just as badly.
    violations: List[str] = []
    if metrics["checks_total"] == 0:
        result.note("no gated vectors were scored -- treating as a failure, not a pass")
        violations.append(
            "no gated vectors were scored; the scan produced a report with nothing in scope"
        )
        status = evidence.FAIL
    elif metrics.get("unknown_category_checks"):
        n = metrics["unknown_category_checks"]
        result.note(
            f"{n} scored check(s) are in a category ci/sundial.yml does not name, so "
            "nobody has decided whether Camoufox claims them"
        )
        violations.append(
            f"{n} scored check(s) fell outside both category lists in ci/sundial.yml. "
            "sundial has grown a section; add it to gated_categories or "
            "ungated_categories. Failing rather than ignoring it, because ignoring it "
            "is a stealth blind spot that reads as a pass."
        )
        status = evidence.FAIL
    elif metrics["pass_rate"] < floor:
        result.note(f"pass rate {metrics['pass_rate']:.3f} is below the policy floor {floor}")
        violations.append(
            f"stealth pass rate {metrics['pass_rate']:.3f} is below the policy floor {floor}"
        )
        status = evidence.FAIL
    result.metrics["policy_violations"] = violations
    _assert_publishable(result.metrics)

    result.finish(status).save(args.evidence_dir)
    # Per-test regressions are verify.py's job; this only reports the floor.
    return 0 if status == evidence.PASS else 1


def waive(argv: Optional[List[str]] = None) -> int:
    """Print a policy.yml waiver stanza for a vector, without naming it there."""
    parser = argparse.ArgumentParser(description="compute a waiver entry for a sundial vector")
    parser.add_argument("--key", required=True, help="the vector key, as it appears in the report")
    parser.add_argument("--reason", required=True, help="why Camoufox does not claim this")
    parser.add_argument("--days", type=int, default=90, help="waiver lifetime (default 90)")
    args = parser.parse_args(argv)

    print("\nAdd under gates.sundial.waivers in the auto-update pipeline's policy file:\n")
    print(f"  - id: {opaque_id(args.key)}")
    print(f"    reason: {args.reason}")
    print(f"    expires: {date.today() + timedelta(days=args.days)}")
    print("\n(The key itself is deliberately not written to the file.)\n")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "waive":
        return waive(argv[1:])
    if argv and argv[0] == "status":
        return status(argv[1:])
    return gate(argv)


if __name__ == "__main__":
    sys.exit(main())
