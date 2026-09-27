"""Self-tests for the repo-wide CI pipeline.

The pipeline's job is to run the right suite against the right browser and
report honestly. These cover the parts where "honestly" is load-bearing:

  * nothing identifying a sundial vector may survive redaction, and the public
    output is a grade rather than a breakdown of what is weak;
  * a skip must carry a reason, or it is indistinguishable from hiding a test;
  * sharding must be stable, so a flake does not appear to move between runners;
  * version resolution must never pick a suite newer than the browser, nor one
    above the Playwright ceiling pythonlib pins;
  * test identities must survive being run from a different working directory.

Run:  python3 -m pytest ci/tests -q
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
import urllib.error
import urllib.parse

import pytest

from ci import results
from ci._util import CI_DIR as CI_ROOT
from ci._pytest import junit_test_id
from ci._util import bump_release, opaque_id, parse_version, read_upstream_sh, write_upstream_sh
from ci.pw_camoufox_plugin import load_skiplist, parse_shard, shard_of, skip_reason
from ci.run_sundial import _iter_entries, grade, redact
from ci.summarize import merge_shards, validate_skiplist
from ci.versions import resolve


# ---------------------------------------------------------------------------
# sundial redaction -- the one that must never regress
# ---------------------------------------------------------------------------


SECRETS = [
    "canvas.rasterizer.subpixel-drift",
    "A private vector name nobody may publish",
    "checks whether the FMA3 path is present",
    "return Math.fround(x) !== y",
    "3.14159265358979",
]

FULL_REPORT = {
    "schemaVersion": 1,
    "sundialVersion": "0.3.1",
    "identity": {"name": "Firefox", "os": "linux", "engine": "SpiderMonkey", "tz": "UTC"},
    "summary": {"total": 3, "pass": 1, "fail": 2},
    "failures": {
        "Graphics": [{
            "key": SECRETS[0], "id": "gfx-1", "name": SECRETS[1], "brief": SECRETS[2],
            "src": SECRETS[3], "source": SECRETS[3], "value": SECRETS[4],
            "expect": SECRETS[4], "category": "Graphics", "status": "fail",
        }],
        "Identity": [{
            "key": "identity.nav.oscpu", "id": "id-9", "name": SECRETS[1],
            "value": SECRETS[4], "category": "Identity", "status": "fail",
        }],
    },
    "succeeded": {
        "Identity": [{
            "key": "identity.nav.platform", "id": "id-3", "name": SECRETS[1],
            "value": SECRETS[4], "category": "Identity", "status": "pass",
        }],
    },
    "private": {
        "failures": {
            "Locale": [{
                "key": "pv-secret-vector", "id": "pv-1", "name": SECRETS[1],
                "src": SECRETS[3], "category": "Locale", "status": "fail",
            }],
        },
    },
}

GATED = ["Identity", "Security", "JS Engine", "Display", "Locale", "Network"]
UNGATED = ["Graphics", "Audio", "CPU"]


def test_redaction_leaks_nothing_identifying():
    blob = json.dumps(redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False))
    for secret in SECRETS:
        assert secret not in blob, f"redaction leaked: {secret!r}"
    for key in ("canvas.rasterizer.subpixel-drift", "identity.nav.oscpu", "pv-secret-vector"):
        assert key not in blob, f"redaction leaked the vector key {key!r}"


def test_only_whitelisted_keys_are_published():
    """A whitelist, not a blacklist.

    A blacklist only stops the leaks somebody already thought of: add a field to
    redact() and forget to consider it, and a blacklist ships it. This fails.
    """
    from ci.run_sundial import _PUBLISHABLE

    out = redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False)
    assert set(out) <= _PUBLISHABLE, f"published beyond the whitelist: {set(out) - _PUBLISHABLE}"
    assert set(out) == {
        "grade", "checks_total", "checks_passed", "pass_rate",
        "out_of_scope_failed", "unknown_category_checks",
        "cross_os_total", "cross_os_passed",
        "score_mode", "os", "sundial_version", "schema_version",
    }


def test_publishing_an_unlisted_key_is_refused():
    """The whitelist has to actually bite, not just describe intent."""
    from ci.run_sundial import _assert_publishable

    with pytest.raises(RuntimeError, match="whitelist"):
        _assert_publishable({"grade": "A", "by_category": {"Graphics": 3}})


def test_no_per_vector_rows_survive():
    """Not even opaque ones.

    An HMAC names nothing, but a map of them says how many distinct checks fail
    and lets a reader follow the same id across releases. The instruction was a
    score, so there are no rows at all.
    """
    out = redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False)
    assert "tests" not in out and "ungated_tests" not in out
    for value in out.values():
        assert not isinstance(value, dict), f"a mapping survived redaction: {value!r}"
    # And nothing that looks like an opaque id.
    blob = json.dumps(out)
    for key in ("canvas.rasterizer.subpixel-drift", "identity.nav.oscpu", "pv-secret-vector"):
        assert opaque_id(key) not in blob


def test_no_category_names_are_published():
    """A table reading "Graphics 3/17" is the most useful single fact an
    adversary could take from a public CI log."""
    blob = json.dumps(redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False))
    for category in GATED + UNGATED:
        assert category not in blob, f"published output names the category {category!r}"


def test_only_in_scope_checks_are_scored():
    out = redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False)
    # Identity: one pass, one fail. Locale (private): one fail. -> 1/3 in scope.
    assert out["checks_total"] == 3
    assert out["checks_passed"] == 1
    assert out["pass_rate"] == pytest.approx(1 / 3, abs=1e-4)
    # Graphics is out of scope: counted, never scored.
    assert out["out_of_scope_failed"] == 1


@pytest.mark.parametrize(
    "rate,expected",
    [(1.0, "A+"), (0.99, "A+"), (0.975, "A"), (0.95, "B"), (0.91, "C"), (0.85, "D"), (0.5, "F")],
)
def test_grade_boundaries(rate, expected):
    assert grade(rate) == expected


def test_iter_entries_finds_public_and_private():
    keys = {k for k, _, _ in _iter_entries(FULL_REPORT)}
    assert "pv-secret-vector" in keys
    assert "identity.nav.platform" in keys


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "classname,name,expected",
    [
        ("tests.async.test_page", "test_foo", "async/test_page.py::test_foo"),
        ("async.test_page", "test_foo", "async/test_page.py::test_foo"),
        # A test inside a class: the trailing segment is the class, not a
        # module, so it has to stay on the far side of the `.py`.
        (
            "async.test_page_clock.TestWhileRunning",
            "test_should_pause",
            "async/test_page_clock.py::TestWhileRunning::test_should_pause",
        ),
        (
            "tests.async.test_page_clock.TestWhileRunning",
            "test_should_pause",
            "async/test_page_clock.py::TestWhileRunning::test_should_pause",
        ),
        # Nested classes keep their order.
        (
            "async.test_x.TestOuter.TestInner",
            "test_y",
            "async/test_x.py::TestOuter::TestInner::test_y",
        ),
        # Nothing that looks like a test module: fall back to the old shape
        # rather than inventing one.
        ("some.module", "test_z", "some/module.py::test_z"),
    ],
)
def test_junit_ids_are_stable_across_rootdirs(classname, name, expected):
    """How many leading segments junit reports depends on where pytest ran."""
    assert junit_test_id(classname, name) == expected


def test_a_class_based_id_is_a_node_id_pytest_would_accept():
    """The id is fed back to pytest and matched against ci/skiplist.yml.

    Both uses need a real node id: `path/to/file.py::Class::test`. The bug this
    guards against turned the class into a directory
    (`test_page_clock/TestWhileRunning.py::test_should_pause`), which named no
    file on disk, so `--last-failed` could not re-run it and no skiplist entry
    could match it.
    """
    tid = junit_test_id("async.test_page_clock.TestWhileRunning", "test_should_pause")
    path, _, rest = tid.partition("::")
    assert path.endswith(".py")
    assert "TestWhileRunning" not in path, "the class must not become part of the path"
    assert rest == "TestWhileRunning::test_should_pause"


@pytest.mark.parametrize(
    "given,expected",
    [("beta.31", "beta.32"), ("beta.9", "beta.10"), ("alpha", "alpha.1")],
)
def test_release_bump(given, expected):
    assert bump_release(given) == expected


def test_version_parsing():
    assert parse_version("153.0.4") == (153, 0, 4)
    assert parse_version("155.0") == (155, 0, 0)


def test_upstream_sh_roundtrip_preserves_comments(tmp_path):
    path = tmp_path / "upstream.sh"
    path.write_text("# a comment\nversion=152.0.4\nrelease=beta.31\nextra=1\n")
    write_upstream_sh({"version": "153.0.4", "release": "beta.32"}, path)
    text = path.read_text()
    assert "# a comment" in text
    assert "extra=1" in text
    assert read_upstream_sh(path)["version"] == "153.0.4"


def test_gate_result_keeps_the_best_outcome_across_retries():
    result = results.GateResult(gate="x")
    result.record("t", "fail")
    result.record("t", "pass")
    result.record("t", "fail")
    assert result.tests["t"] == "pass"




# ---------------------------------------------------------------------------
# skiplist
# ---------------------------------------------------------------------------


SKIPS = [
    {"module": "tests/async/test_click.py", "reason": "humanized input"},
    {"test": "tests/async/test_page.py::test_one", "reason": "specific"},
    {"pattern": "[chromium]", "reason": "not a Chromium fork"},
]


@pytest.mark.parametrize(
    "nodeid,expected",
    [
        ("tests/async/test_click.py::test_anything", "humanized input"),
        ("tests/async/test_clicker.py::test_anything", None),   # prefix must not over-match
        ("tests/async/test_page.py::test_one", "specific"),
        ("tests/async/test_page.py::test_two", None),
        ("tests/async/test_x.py::test_y[chromium]", "not a Chromium fork"),
        ("tests/async/test_x.py::test_y[firefox]", None),
        # Every test in the suite is parameterised by browser, so this is the
        # only spelling a `test:` entry ever actually meets.
        ("tests/async/test_page.py::test_one[firefox]", "specific"),
        ("tests/async/test_page.py::test_two[firefox]", None),
        # Stripping the parameters must not widen the match to a longer name.
        ("tests/async/test_page.py::test_one_more[firefox]", None),
    ],
)
def test_skip_matching(nodeid, expected):
    assert skip_reason(nodeid, SKIPS) == expected


def test_every_shipped_test_entry_matches_a_parameterised_node_id():
    """A `test:` entry that only matches the unparameterised id is a no-op.

    The suite runs `--browser firefox`, so pytest's ids all end in `[firefox]`.
    An entry compared for exact equality against that never fires: the test goes
    on running and failing while the skiplist reads as though it were handled.
    This asserts the shipped entries match the id shape they will really see.
    """
    entries = load_skiplist()
    targets = [str(e["test"]) for e in entries if "test" in e]
    assert targets, "no `test:` entries -- drop this test if that is intentional"
    for target in targets:
        assert skip_reason(f"{target}[firefox]", entries), (
            f"{target} does not match its own parameterised node id"
        )


def test_the_shipped_skiplist_is_valid():
    """Every entry names something and says why."""
    assert validate_skiplist() == []
    entries = load_skiplist()
    assert entries, "the shipped skiplist is empty"
    for entry in entries:
        assert str(entry.get("reason", "")).strip()


def test_an_unreasoned_skip_is_rejected(tmp_path):
    path = tmp_path / "skiplist.yml"
    path.write_text("schema: 1\nskip:\n  - module: tests/async/test_x.py\n")
    problems = validate_skiplist(path)
    assert problems and "no reason" in problems[0]


def test_a_replaced_by_that_names_nothing_is_rejected(tmp_path):
    """Two entries skip an upstream test because a Camoufox test took the job on.

    That claim is only true while the named file exists. Rename or delete it and
    the skip silently becomes "nothing checks this any more" -- which is exactly
    the state the skiplist's stated-reason rule exists to prevent, arrived at
    from the other direction.
    """
    path = tmp_path / "skiplist.yml"
    path.write_text(
        "schema: 1\n"
        "skip:\n"
        "  - test: tests/async/test_x.py::test_y\n"
        "    replaced-by: tests/camoufox/test_nope.py\n"
        "    reason: superseded\n"
    )
    problems = validate_skiplist(path)
    assert problems and "does not exist" in problems[0]


def test_every_replaced_by_in_the_shipped_skiplist_resolves():
    """The shipped file, not a fixture -- this is the one that has to hold."""
    assert not validate_skiplist()


def test_load_skiplist_refuses_an_unreasoned_entry(tmp_path, monkeypatch):
    """The plugin must refuse too -- validating only in the summary would let a
    skip take effect for the whole run before anyone objected."""
    path = tmp_path / "skiplist.yml"
    path.write_text("schema: 1\nskip:\n  - module: tests/async/test_x.py\n")
    monkeypatch.setenv("CI_SKIPLIST", str(path))
    with pytest.raises(RuntimeError, match="no reason"):
        load_skiplist()


# ---------------------------------------------------------------------------
# sharding
# ---------------------------------------------------------------------------


def test_shards_partition_the_suite_exactly_once():
    nodeids = [f"tests/async/test_{i // 20}.py::test_{i}" for i in range(600)]
    seen = {}
    for shard in range(1, 7):
        for nodeid in nodeids:
            if shard_of(nodeid, 6) == shard:
                assert nodeid not in seen, f"{nodeid} landed in two shards"
                seen[nodeid] = shard
    assert len(seen) == len(nodeids), "some tests landed in no shard"


def test_shards_are_roughly_even():
    nodeids = [f"tests/async/test_{i // 20}.py::test_{i}" for i in range(1500)]
    counts = [sum(1 for n in nodeids if shard_of(n, 6) == s) for s in range(1, 7)]
    assert min(counts) > len(nodeids) / 6 * 0.8, counts


def test_shard_membership_is_stable_when_a_test_is_inserted():
    """Hashed, not positional: adding a test in the middle of a file must not
    reshuffle every later test, or a flake looks like it moved runners."""
    before = {n: shard_of(n, 6) for n in ("a::t1", "a::t2", "a::t3")}
    after = {n: shard_of(n, 6) for n in ("a::t1", "a::t_new", "a::t2", "a::t3")}
    for nodeid, shard in before.items():
        assert after[nodeid] == shard


@pytest.mark.parametrize("raw,expected", [("3/6", (3, 6)), ("1/1", (1, 1)), (None, None), ("", None)])
def test_parse_shard(raw, expected):
    assert parse_shard(raw) == expected


@pytest.mark.parametrize("raw", ["0/6", "7/6", "abc", "3/0"])
def test_parse_shard_rejects_nonsense(raw):
    with pytest.raises(RuntimeError):
        parse_shard(raw)


# ---------------------------------------------------------------------------
# version resolution
# ---------------------------------------------------------------------------


PINS = [("v1.62.0", "153.0"), ("v1.61.0", "151.0"), ("v1.60.0", "150.0.2"), ("v1.58.0", "146.0.1")]


@pytest.fixture
def offline_pins(monkeypatch):
    monkeypatch.setattr("ci.versions.pins", lambda limit=10: list(PINS))


def test_never_picks_a_suite_newer_than_the_browser(offline_pins, monkeypatch):
    """A newer suite assumes engine work this build does not have, so every
    failure it reports would be ambiguous."""
    monkeypatch.setattr("ci.versions.read_upstream_sh", lambda: {"version": "152.0.4", "release": "beta.31"})
    out = resolve()
    assert out["playwright_tag"] == "v1.61.0"
    assert parse_version(out["playwright_firefox"]) <= parse_version("152.0.4")


def test_the_harness_can_pass_a_version_in(offline_pins, monkeypatch):
    monkeypatch.setattr("ci.versions.read_upstream_sh", lambda: {"version": "152.0.4", "release": "beta.31"})
    assert resolve(browser_version="153.0.4")["playwright_tag"] == "v1.62.0"
    assert resolve(browser_version="146.0.1")["playwright_tag"] == "v1.58.0"


def test_an_explicit_tag_wins(offline_pins, monkeypatch):
    monkeypatch.setattr("ci.versions.read_upstream_sh", lambda: {"version": "146.0.1", "release": "beta.1"})
    out = resolve(playwright_tag="v1.62.0")
    assert out["playwright_tag"] == "v1.62.0"


def test_a_browser_older_than_every_suite_still_resolves(offline_pins, monkeypatch):
    """An old branch should still get tested, loudly, rather than not at all."""
    monkeypatch.setattr("ci.versions.read_upstream_sh", lambda: {"version": "120.0", "release": "old"})
    out = resolve()
    assert out["playwright_tag"] == "v1.58.0"
    assert "oldest available" in out["note"]


# ---------------------------------------------------------------------------
# shard merging
# ---------------------------------------------------------------------------


def test_shards_merge_into_one_record():
    records = {
        "playwright_upstream-1of3": {
            "gate": "playwright_upstream-1of3", "status": "pass",
            "tests": {"a::t1": "pass"}, "metrics": {"shard": "1/3"}, "notes": ["ok"],
        },
        "playwright_upstream-2of3": {
            "gate": "playwright_upstream-2of3", "status": "fail",
            "tests": {"a::t2": "fail"}, "metrics": {"shard": "2/3"}, "notes": ["one failed"],
        },
        "playwright_upstream-3of3": {
            "gate": "playwright_upstream-3of3", "status": "pass",
            "tests": {"a::t3": "pass"}, "metrics": {"shard": "3/3"}, "notes": ["ok"],
        },
        "build": {"gate": "build", "status": "pass", "tests": {}, "metrics": {}, "notes": []},
    }
    merged = merge_shards(records)
    assert set(merged) == {"playwright_upstream", "build"}
    combined = merged["playwright_upstream"]
    assert combined["tests"] == {"a::t1": "pass", "a::t2": "fail", "a::t3": "pass"}
    assert combined["status"] == "fail", "one failing shard must fail the suite"
    assert combined["metrics"]["shards"] == 3
    assert combined["metrics"]["tally"]["total"] == 3
    assert "shard" not in combined["metrics"]


def test_an_errored_shard_beats_a_failed_one():
    records = {
        "s-1of2": {"gate": "s-1of2", "status": "fail", "tests": {"a::1": "fail"}, "metrics": {}, "notes": []},
        "s-2of2": {"gate": "s-2of2", "status": "error", "tests": {}, "metrics": {}, "notes": []},
    }
    assert merge_shards(records)["s"]["status"] == "error"


def test_every_native_test_file_is_actually_run():
    """A suite that exists but is not in the runner's list is invisible.

    test_crash_recovery.py was written, passing, and unwired for a while -- the
    kind of gap that looks like coverage on the filesystem and is nothing in CI.
    """
    from pathlib import Path

    from ci._util import REPO_ROOT
    from ci.run_native import FILES

    on_disk = {p.name for p in (REPO_ROOT / "native-tests").glob("test_*.py")}
    # Every group, not a hardcoded pair -- otherwise adding a subset silently
    # narrows the check, which is the same class of hole it exists to catch.
    wired = {f for group in FILES.values() for f in group}
    missing = on_disk - wired
    assert not missing, f"native-tests files that no subset runs: {sorted(missing)}"
    assert not wired - on_disk, f"runner lists files that do not exist: {sorted(wired - on_disk)}"


# ---------------------------------------------------------------------------
# sundial's score-only payload, with cross-OS split out
# ---------------------------------------------------------------------------


SCORE_PAYLOAD = {
    "schemaVersion": 1,
    "mode": "score",
    "sundialVersion": "0.3.1",
    "identity": {"name": "Firefox", "os": "linux"},
    "buckets": {
        # in scope, browser's own behaviour
        "Identity|core": {"scored": 40, "passed": 39, "failed": 1},
        "Network|core": {"scored": 12, "passed": 12, "failed": 0},
        # in scope by category, but reads the host machine
        "Locale|crossOs": {"scored": 18, "passed": 4, "failed": 14},
        # out of scope entirely
        "Graphics|core": {"scored": 9, "passed": 6, "failed": 3},
        "Graphics|crossOs": {"scored": 6, "passed": 1, "failed": 5},
    },
}


def test_cross_os_failures_never_count_against_the_score():
    """A browser claiming macOS on Linux fails the host-OS detectors regardless.

    Those read the machine underneath, not the disguise, and Camoufox does not
    claim byte-identical cross-OS emulation -- so counting them would mark it
    down for a promise nobody made.
    """
    out = redact(SCORE_PAYLOAD, GATED, UNGATED, os_name="linux")
    # Identity + Network core only: 52 scored, 51 passed.
    assert out["checks_total"] == 52
    assert out["checks_passed"] == 51
    assert out["pass_rate"] == pytest.approx(51 / 52, abs=1e-4)
    # The 14 Locale cross-OS failures did not drag it down...
    assert out["grade"] == "A"
    # ...but they are still reported, from both categories.
    assert out["cross_os_total"] == 24
    assert out["cross_os_passed"] == 5


def test_out_of_scope_failures_are_counted_but_not_scored():
    out = redact(SCORE_PAYLOAD, GATED, UNGATED, os_name="linux")
    # Graphics is not a gated category: its 3 core failures are counted only.
    assert out["out_of_scope_failed"] == 3


def test_the_score_payload_publishes_no_categories_or_classes():
    """Checked against keys and values, not the raw JSON text.

    A substring scan flagged "score_mode" for containing "core", which is the
    kind of false positive that gets an assertion loosened until it stops
    catching anything.
    """
    out = redact(SCORE_PAYLOAD, GATED, UNGATED, os_name="linux")
    forbidden = {"Identity", "Network", "Locale", "Graphics", "crossOs", "core", "buckets"}

    assert not (set(out) & forbidden), f"a published key names a category or class: {set(out) & forbidden}"
    leaked = [v for v in out.values() if isinstance(v, str) and v in forbidden]
    assert not leaked, f"a published value names a category or class: {leaked}"
    # And no nested structure that could carry one.
    assert all(not isinstance(v, (dict, list)) for v in out.values())


def test_a_full_report_still_folds_to_the_same_shape():
    """Older sundial, or a deliberate local run, must not break the gate."""
    from ci.run_sundial import _PUBLISHABLE

    out = redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False)
    assert set(out) <= _PUBLISHABLE
    assert out["checks_total"] == 3 and out["checks_passed"] == 1
    # A full report carries no class tags, so nothing is attributed to cross-OS.
    assert out["cross_os_total"] == 0


def test_a_deployment_without_score_mode_is_flagged_not_silent():
    """An old sundial ignores ?score=1 and posts the whole report.

    The numbers still come out right, but nothing is classified, so every
    cross-OS tally reads zero -- which looks like "no host-OS failures" rather
    than "nobody sorted them". score_mode says which of those it is.
    """
    assert redact(SCORE_PAYLOAD, GATED, UNGATED, os_name="linux")["score_mode"] is True
    legacy = redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False)
    assert legacy["score_mode"] is False
    assert legacy["cross_os_total"] == 0


# ---------------------------------------------------------------------------
# cross-profile uniqueness, judged by what each slot promises
# ---------------------------------------------------------------------------


def _cross(**kw):
    base = {"total": 3, "uniqueAudio": 3, "uniqueCanvas": 3, "uniqueFonts": 3,
            "uniqueTimezones": 3, "uniqueScreens": 3, "uniqueVoices": 3,
            "uniqueWebGL": 3, "uniquePlatforms": 1}
    base.update(kw)
    return {"crossProfile": {"macPerContext": base}}


def test_a_shared_per_context_value_is_a_leak():
    """audio and timezone are derived per context.

    Two contexts sharing one is the failure this whole suite exists to catch.
    """
    from ci.run_build_tester import uniqueness

    for slot in ("uniqueAudio", "uniqueTimezones"):
        out = uniqueness(_cross(**{slot: 1}))
        assert out["leaks"] == [f"macPerContext.{slot} (1/3 distinct)"], slot
        assert not out["noise"]


def test_a_shared_canvas_is_noise_not_a_leak():
    """The canvas is rendered, not noised (#528), so contexts with the same
    fonts and GPU draw the same image, as two real machines would."""
    from ci.run_build_tester import uniqueness

    out = uniqueness(_cross(uniqueCanvas=2))
    assert out["noise"] == ["macPerContext.uniqueCanvas (2/3 distinct)"]
    assert not out["leaks"]


def test_a_shared_preset_value_is_noise_not_a_leak():
    """fonts, screens, voices and WebGL come from a pool of real devices.

    Three draws from a dozen collide regularly. Reported, never fatal.
    """
    from ci.run_build_tester import uniqueness

    for slot in ("uniqueFonts", "uniqueScreens", "uniqueVoices", "uniqueWebGL"):
        out = uniqueness(_cross(**{slot: 2}))
        assert out["noise"] == [f"macPerContext.{slot} (2/3 distinct)"], slot
        assert not out["leaks"]


def test_identical_platforms_are_correct_not_a_collision():
    """Every macOS context reports MacIntel. That is what macOS reports.

    The flat count that preceded this read three contexts agreeing as three
    collisions and failed a run that scored 1054/1054.
    """
    from ci.run_build_tester import uniqueness

    out = uniqueness(_cross(uniquePlatforms=1))
    assert not out["leaks"] and not out["not_constant"] and not out["noise"]


def test_a_platform_that_varies_within_one_os_is_the_bug():
    from ci.run_build_tester import uniqueness

    out = uniqueness(_cross(uniquePlatforms=3))
    assert out["not_constant"] == ["macPerContext.uniquePlatforms (3/3 distinct)"]


def test_zero_distinct_is_absence_not_collision():
    """Nothing collected -- no speech voices headless, say.

    Counting it as a collision reports a leak where there is no data at all.
    """
    from ci.run_build_tester import uniqueness

    out = uniqueness(_cross(uniqueVoices=0))
    assert out["absent"] == ["macPerContext.uniqueVoices (0/3 distinct)"]
    assert not out["leaks"] and not out["noise"]


def test_version_resolution_honours_pythonlibs_playwright_ceiling():
    """The resolver must not pick a client pythonlib refuses to install.

    `camoufox.server` imports `playwright._impl._driver`, a private API, so
    pythonlib pins a ceiling. Without this filter a Firefox bump silently moves
    the suite above that ceiling, and whatever Juggler changed in between is
    reported as a browser failure in a suite nobody shipping the package could
    reproduce.

    Pinned inputs, so this tests the rule and not today's release list.
    """
    from ci import versions

    available = [("v1.64.0", "158.0"), ("v1.63.0", "156.0"), ("v1.62.0", "153.0")]
    real_pins, real_ceiling = versions.pins, versions.client_ceiling
    try:
        versions.pins = lambda limit=10: list(available)
        versions.client_ceiling = lambda: (1, 63, 0)
        resolved = versions.resolve(browser_version="158.0.1")
    finally:
        versions.pins, versions.client_ceiling = real_pins, real_ceiling

    assert resolved["playwright_tag"] == "v1.62.0", (
        "resolved to a Playwright at or above pythonlib's ceiling; the suite would "
        "install a client the shipped package forbids"
    )


def test_pythonlib_still_pins_a_playwright_ceiling():
    """The filter above is only as real as the pin it reads.

    If the ceiling is dropped from pyproject.toml, `client_ceiling()` returns
    None and the filter quietly stops applying -- so assert the pin exists here
    rather than discovering it from a protocol failure later.
    """
    from ci.versions import client_ceiling

    assert client_ceiling() is not None, (
        "pythonlib/pyproject.toml no longer pins a playwright ceiling, so "
        "ci.versions has nothing to clamp the suite to"
    )


# ---------------------------------------------------------------------------
# score mode is a requirement, not a preference
# ---------------------------------------------------------------------------


def test_a_full_report_is_refused_by_default():
    """The gate only ever asks for `?auto=1&score=1`.

    So a full report arriving here means the deployment did not honour it. That
    is the one case where the vectors really are in this process, and folding
    them down anyway would mean they passed through and nobody noticed -- the
    failure has to be loud.
    """
    with pytest.raises(RuntimeError, match="full report, not a score"):
        redact(FULL_REPORT, GATED, UNGATED, os_name="linux")


def test_a_full_report_still_folds_when_explicitly_allowed():
    """The escape hatch is for a local run under an account allowed a report."""
    out = redact(FULL_REPORT, GATED, UNGATED, os_name="linux", require_score_mode=False)
    assert out["score_mode"] is False
    assert out["checks_total"] > 0


def test_the_score_payload_is_accepted_without_the_flag():
    assert redact(SCORE_PAYLOAD, GATED, UNGATED, os_name="linux")["score_mode"] is True


def test_consumers_only_read_published_metric_keys():
    """Every `metrics[...]` read in the pipeline must name a key redact() emits.

    This is the check that was missing when `redact()` renamed `gated_passed` to
    `checks_passed`: the redaction tests all passed, because they only ever
    exercised redact() itself, while its two consumers went on reading the old
    names -- one raising KeyError on every successful run, the other silently
    rendering "0/0 in-scope checks passed". Asserting the contract from the
    consumer side is what catches that, so it is done by reading the source
    rather than by calling one code path.
    """
    import ast

    from ci.run_sundial import _PUBLISHABLE

    # In run_sundial.py every `metrics` is sundial's. summarize.py also folds
    # shard metrics for the other gates under that name, so there the sundial
    # reads carry a distinct one.
    holders = {"run_sundial.py": {"metrics"}, "summarize.py": {"sundial_metrics"}}

    offenders = []
    for module, names in holders.items():
        path = CI_ROOT / module
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            key = name = None
            # metrics["x"] -- reads only; `metrics["shards"] = n` is a write.
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
                and node.value.id in names
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                name, key = node.value.id, node.slice.value
            # metrics.get("x", ...)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in names
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                name, key = node.func.value.id, node.args[0].value

            if key is not None and key not in _PUBLISHABLE:
                offenders.append(f"{module}: {name}[{key!r}]")


    assert not offenders, (
        "these read a metrics key redact() does not publish, so they will raise "
        f"KeyError or render a zero: {offenders}"
    )


# ---------------------------------------------------------------------------
# the stealth-gate kill switch
# ---------------------------------------------------------------------------


def test_the_gate_is_off_unless_the_config_says_otherwise():
    """Absent the key, off.

    The check talks to a private suite and puts the answer in a public log, so
    the safe default is not to run. A config predating the flag must not start
    running by inheriting a permissive default.
    """
    from ci.run_sundial import is_enabled

    assert is_enabled({}) is False
    assert is_enabled({"url": "https://example.invalid"}) is False
    assert is_enabled({"enabled": False}) is False
    assert is_enabled({"enabled": True}) is True


def test_sundial_yml_declares_enabled_explicitly():
    """Whether CI may contact sundial is too important to be implicit.

    Asserting the key is present (rather than that it is false) keeps this test
    valid either way, while still forcing the decision to be written down.
    """
    import yaml

    cfg = yaml.safe_load((CI_ROOT / "sundial.yml").read_text(encoding="utf-8")) or {}
    assert "enabled" in cfg, "ci/sundial.yml must state `enabled:` one way or the other"
    assert isinstance(cfg["enabled"], bool), "`enabled:` must be a bool, not a string"


def test_a_disabled_gate_makes_no_request():
    """Disabled means no credential is read and no connection is opened.

    Asserted by making every route out fatal: authenticate(), both of the login
    functions it can reach, and scan() all raise if called, and the credential is
    put in the environment so that a gate which ignored the flag would sail past
    the missing-credential check and hit them.
    """
    import ci.run_sundial as rs

    calls = []

    def explode(*args, **kwargs):
        calls.append(args)
        raise AssertionError("a disabled stealth gate contacted sundial")

    names = ("authenticate", "login", "login_with_key", "scan")
    monkey = {name: getattr(rs, name) for name in names}
    monkey["_config"] = rs._config
    for name in names:
        setattr(rs, name, explode)
    rs._config = lambda: {"enabled": False, "url": "https://sundial.invalid"}
    old_key = os.environ.get("SUNDIAL_AUTOMATION_KEY")
    os.environ["SUNDIAL_AUTOMATION_KEY"] = "would-be-used-if-the-flag-were-ignored"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            code = rs.gate(["--binary", "/nonexistent", "--evidence-dir", tmp])
            produced = pathlib.Path(tmp) / "sundial.json"
            written = json.loads(produced.read_text()) if produced.exists() else None
    finally:
        for name in names:
            setattr(rs, name, monkey[name])
        rs._config = monkey["_config"]
        if old_key is None:
            os.environ.pop("SUNDIAL_AUTOMATION_KEY", None)
        else:
            os.environ["SUNDIAL_AUTOMATION_KEY"] = old_key

    assert calls == [], "the gate reached the network while disabled"
    assert code == 0, "a disabled gate is a skip, not a failure"
    # No result file, matching CI, where the job is never scheduled. A skip
    # record here would fail a summary that CI would have passed.
    assert written is None, "a disabled gate must not write a result file"


# ---------------------------------------------------------------------------
# the workflow's plumbing -- result files have to survive the round trip
# ---------------------------------------------------------------------------

WORKFLOW = CI_ROOT.parent / ".github" / "workflows" / "tests.yml"


def _upload_blocks():
    """(name, path-lines, block-text) for every upload-artifact step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    blocks = []
    for match in re.finditer(r"- uses: actions/upload-artifact@v4\n", text):
        block = text[match.start() : match.start() + 900]
        # Stop at the next step at the same indentation.
        end = re.search(r"\n( *)- (uses|name):", block[40:])
        if end:
            block = block[: 40 + end.start()]
        name = re.search(r"name: (\S.*)", block)
        paths = re.findall(r"^\s+(\.ci-work\S*|summary\.\w+)\s*$", block, re.M)
        inline = re.search(r"path: (\.ci-work\S*)", block)
        if inline:
            paths.append(inline.group(1))
        blocks.append((name.group(1) if name else "?", paths, block))
    return blocks


def test_results_artifacts_keep_their_json_at_the_top_level():
    """A `results-*` artifact must hold its JSON at the artifact root.

    The summary downloads every one of them with `merge-multiple: true` into a
    single directory, and results.load_all() globs exactly one level. Give
    upload-artifact a second path and its common root moves up, so the files
    arrive nested under `results/` and are silently invisible -- the summary
    then reports a suite that passed as "produced no result file". That is what
    happened to build_tester.
    """
    offenders = [
        (name, paths)
        for name, paths, _ in _upload_blocks()
        if name.startswith("results-") and paths != [".ci-work/results/"]
    ]
    assert not offenders, (
        "a results-* artifact must upload exactly `.ci-work/results/` and nothing "
        f"else; put diagnostics in their own artifact: {offenders}"
    )


def test_every_ci_work_upload_includes_hidden_files():
    """`.ci-work` is a dotfile, and upload-artifact v4 drops those by default.

    Without this the upload silently finds nothing -- which is how a failing
    suite came back as "missing" rather than as the failure it was.
    """
    offenders = [
        name
        for name, paths, block in _upload_blocks()
        if any(p.startswith(".ci-work") for p in paths)
        and "include-hidden-files: true" not in block
    ]
    assert not offenders, f"these upload .ci-work without include-hidden-files: {offenders}"


def test_required_suites_are_names_a_runner_actually_writes():
    """Requiring a name nothing produces fails every run, forever.

    `static` is a job, not a suite; requiring it meant summarize reported
    "produced no result file" on runs where everything passed.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    required: set[str] = set()
    for line in re.findall(r'required="([^"]*)"', text):
        required.update(part for part in line.split() if not part.startswith("$"))

    producible = {
        "build", "build_tester", "patch_guards", "pythonlib", "sundial",
        "native", "native_rules", "native_browser", "native_growth",
        "playwright", "skiplist_audit", "typescript", "typescript_browser",
    }
    unknown = required - producible
    assert not unknown, (
        f"required but no runner writes a result by that name: {sorted(unknown)}. "
        "summarize.py will report it missing on every run."
    )


# ---------------------------------------------------------------------------
# build-tester: a spoofed software renderer is not a headless tell
# ---------------------------------------------------------------------------


def _bt_profile(webgl_renderer: str, *, noswift_passed: bool) -> dict:
    return {
        "profiles": [
            {
                "profile": {
                    "os": "linux",
                    "mode": "per-context",
                    "index": 0,
                    "webglRenderer": webgl_renderer,
                },
                "results": {
                    "extended": {
                        "headlessDetection": {
                            "noSwiftShader": {
                                "passed": noswift_passed,
                                "detail": "SOFTWARE RENDERER: llvmpipe (headless indicator)",
                            },
                            "noWebdriver": {"passed": True, "detail": "false"},
                        }
                    }
                },
            }
        ]
    }


def test_a_profile_that_asked_for_llvmpipe_is_not_graded_headless():
    """camoufox's own preset pool ships "llvmpipe, or similar".

    When `generate_context_fingerprint()` draws that preset, the browser is meant
    to report llvmpipe -- doing so is the WebGL spoof working. Grading it as a
    headless indicator made this gate fail at random, on the runs where that
    preset happened to be drawn.
    """
    from ci.run_build_tester import category_failures, flatten

    full = _bt_profile("llvmpipe, or similar", noswift_passed=False)
    tid = "linux-per-context-0/extended/headlessDetection/noSwiftShader"
    assert flatten(full)[tid] == "pass"
    assert category_failures(full, ["headlessDetection"]) == {}


def test_an_unasked_for_software_renderer_still_fails():
    """The case the check exists for: the spoof fell through to the host GPU."""
    from ci.run_build_tester import category_failures, flatten

    full = _bt_profile("AMD Radeon R9 200 Series", noswift_passed=False)
    tid = "linux-per-context-0/extended/headlessDetection/noSwiftShader"
    assert flatten(full)[tid] == "fail"
    assert category_failures(full, ["headlessDetection"]) == {"headlessDetection": 1}


def test_the_exemption_is_confined_to_that_one_check():
    """A different headlessDetection check must not inherit the exemption."""
    from ci.run_build_tester import flatten

    full = _bt_profile("llvmpipe, or similar", noswift_passed=False)
    checks = full["profiles"][0]["results"]["extended"]["headlessDetection"]
    checks["noWebdriver"] = {"passed": False, "detail": "navigator.webdriver = true"}
    tests = flatten(full)
    assert tests["linux-per-context-0/extended/headlessDetection/noWebdriver"] == "fail"


# ---------------------------------------------------------------------------
# preparing the source tree: retry the network, never the real failures
# ---------------------------------------------------------------------------


# The exact text that failed run 34673115086, trimmed to the lines that matter.
_TASKCLUSTER_RESET = """\
  File "/home/runner/work/camoufox/camoufox/camoufox-152.0.4-beta.31/python/mach/mach/main.py", line 416, in _run
    return Registrar._run_command_handler(
requests.exceptions.ConnectionError: ('Connection aborted.', \
ConnectionResetError(104, 'Connection reset by peer'))
make: *** [Makefile:95: mozbootstrap] Error 1
"""

_REAL_BUILD_FAILURE = """\
patching file browser/base/content/browser.js
Hunk #1 FAILED at 812.
1 out of 1 hunk FAILED -- saving rejects to browser/base/content/browser.js.rej
make: *** [Makefile:88: dir] Error 1
"""


def test_a_taskcluster_connection_reset_is_transient():
    from ci.run_prepare import is_transient

    assert is_transient(_TASKCLUSTER_RESET)


def test_a_failed_patch_hunk_is_not_transient():
    """The retry must not paper over the failure mode this pipeline exists to catch."""
    from ci.run_prepare import is_transient

    assert not is_transient(_REAL_BUILD_FAILURE)


class _FakeRun:
    """Stands in for run_prepare._run_capturing, replaying scripted outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        return self.outcomes.pop(0)


def _run_step(monkeypatch, outcomes, *, target="mozbootstrap", retry=True, attempts=3):
    import ci.run_prepare as rp

    fake = _FakeRun(outcomes)
    monkeypatch.setattr(rp, "_run_capturing", fake)
    monkeypatch.setattr(rp.time, "sleep", lambda _s: None)
    code = rp.run_step(target, retry=retry, attempts=attempts, backoff=0, timeout=60)
    return code, fake


def test_a_transient_failure_is_retried_and_can_succeed(monkeypatch):
    code, fake = _run_step(monkeypatch, [(2, _TASKCLUSTER_RESET), (0, "ok")])
    assert code == 0
    assert len(fake.calls) == 2


def test_a_real_failure_is_not_retried(monkeypatch):
    """Retrying a broken tree only spends a runner to reach the same answer."""
    code, fake = _run_step(monkeypatch, [(2, _REAL_BUILD_FAILURE)])
    assert code == 2
    assert len(fake.calls) == 1


def test_retries_are_bounded(monkeypatch):
    code, fake = _run_step(
        monkeypatch, [(2, _TASKCLUSTER_RESET)] * 3, attempts=3
    )
    assert code == 2
    assert len(fake.calls) == 3


def test_applying_patches_is_never_retried(monkeypatch):
    """`make dir` touches no network once the tarball is there, so a failure is real."""
    import ci.run_prepare as rp

    assert dict(rp._STEPS)["dir"] is False
    code, fake = _run_step(
        monkeypatch, [(2, _TASKCLUSTER_RESET)], target="dir", retry=False
    )
    assert code == 2
    assert len(fake.calls) == 1


def test_the_workflow_prepares_through_the_retrying_entry_point():
    """A step that shells straight to `make mozbootstrap` gets no retry."""
    from ci._util import REPO_ROOT

    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "python3 -m ci.run_prepare" in workflow
    prepare = workflow.split("Prepare the source tree", 1)[1].split("- name:", 1)[0]
    # Comments in that step quote the make targets while explaining them, so
    # judge the commands only.
    commands = "\n".join(
        line for line in prepare.splitlines() if not line.strip().startswith("#")
    )
    for target in ("make setup-minimal", "make dir", "make mozbootstrap"):
        assert target not in commands, (
            f"{target} is invoked directly; it would not be retried"
        )


def test_zero_attempts_still_runs_the_step_once(monkeypatch):
    """`--attempts 0` must not report success by never running anything."""
    code, fake = _run_step(monkeypatch, [(0, "ok")], attempts=0)
    assert len(fake.calls) == 1
    assert code == 0


# ---------------------------------------------------------------------------
# a category nobody has ruled on is a blind spot, not an "out of scope"
# ---------------------------------------------------------------------------


def _score_payload(*buckets) -> dict:
    """A minimal sundial score payload: (category, class, scored, passed)."""
    return {
        "schemaVersion": 1,
        "mode": "score",
        "sundialVersion": "0.5.0",
        "buckets": {
            f"{cat}|{cls}": {"scored": n, "passed": p, "failed": n - p}
            for cat, cls, n, p in buckets
        },
    }


def test_sundial_yml_names_every_section_sundial_has():
    """ci/sundial.yml must partition sundial's taxonomy, not sample it.

    sundial's SECTIONS are the `category` every scored entry carries. If the two
    lists here do not cover all of them, whatever is missing is silently
    unscored -- the gate would report a pass rate over a slice of the suite and
    read exactly like a clean run.
    """
    import yaml

    cfg = yaml.safe_load((CI_ROOT / "sundial.yml").read_text(encoding="utf-8"))
    named = {c.lower() for c in cfg["gated_categories"]} | {
        c.lower() for c in cfg["ungated_categories"]
    }
    # sundial 0.5.0, src/lib/engine.js SECTIONS[].label.
    sundial_sections = {
        "identity", "security", "js engine", "graphics",
        "display", "locale", "audio", "cpu", "network",
    }
    assert sundial_sections <= named, (
        f"not scored by either list: {sorted(sundial_sections - named)}"
    )
    assert not (named - sundial_sections), (
        f"named here but not a sundial section: {sorted(named - sundial_sections)}"
    )


def test_a_category_in_neither_list_is_counted_as_unknown():
    out = redact(
        _score_payload(
            ("Identity", "core", 10, 10),
            ("Graphics", "core", 5, 3),      # deliberately ungated
            ("Battery", "core", 4, 1),       # a section nobody has ruled on
        ),
        GATED, UNGATED, os_name="linux",
    )
    assert out["checks_total"] == 10
    assert out["unknown_category_checks"] == 4
    # Still only a count -- the category name never reaches the metrics.
    assert "Battery" not in json.dumps(out)


def test_a_known_ungated_category_is_not_unknown():
    out = redact(
        _score_payload(("Identity", "core", 10, 10), ("Graphics", "core", 5, 3)),
        GATED, UNGATED, os_name="linux",
    )
    assert out["unknown_category_checks"] == 0
    assert out["out_of_scope_failed"] == 2


def test_run_capturing_keeps_stdout_and_stderr():
    """The classifier reads this output, so losing stderr loses the diagnosis."""
    from ci.run_prepare import _run_capturing

    code, out = _run_capturing(
        ["bash", "-c", "echo on-stdout; echo on-stderr >&2; exit 3"], timeout=30
    )
    assert code == 3
    assert "on-stdout" in out and "on-stderr" in out


def test_a_step_that_wedges_without_printing_is_killed():
    """The timeout has to cover a silent hang, which is what a stalled download is.

    Draining the pipe on the calling thread would block in readline until EOF
    and only then reach proc.wait(timeout=...) -- so a process producing no
    output would never be timed out at all.
    """
    import time

    from ci.run_prepare import _run_capturing

    started = time.monotonic()
    code, out = _run_capturing(["bash", "-c", "sleep 60"], timeout=2)
    elapsed = time.monotonic() - started
    assert code == 124, "a timed-out step must not report success"
    assert "TIMEOUT" in out
    assert elapsed < 15, f"the timeout did not fire promptly ({elapsed:.1f}s)"


# ---------------------------------------------------------------------------
# the credential must not ride out on an error message
# ---------------------------------------------------------------------------


def test_scrub_removes_the_secret_in_both_encodings():
    """An exception from urllib can carry the URL that raised it.

    For the token route that URL *is* the credential, percent-encoded. Whatever
    reaches result.note() is published to the results artifact and the pull
    request comment, so it goes through scrub() first.
    """
    from ci.run_sundial import scrub

    secret = "yPsM+key/with=specials"
    quoted = urllib.parse.quote(secret, safe="")
    text = f"HTTPError at https://sundial.daijro.dev/automated?key={quoted} and raw {secret}"
    out = scrub(text, secret)
    assert secret not in out
    assert quoted not in out
    assert out.count("<redacted>") == 2


def test_scrub_is_a_no_op_without_a_secret():
    from ci.run_sundial import scrub

    assert scrub("nothing to hide", "") == "nothing to hide"


def test_a_failed_login_never_publishes_the_credential():
    """End to end: a bad credential fails the gate without leaking itself."""
    import ci.run_sundial as rs

    secret = "super-secret-automation-key"

    def boom(base_url, key, **kwargs):
        raise urllib.error.HTTPError(
            f"{base_url}/automated?key={urllib.parse.quote(secret, safe='')}",
            401, "Unauthorized", {}, None,
        )

    monkey = {"login_with_key": rs.login_with_key, "login": rs.login}
    rs.login_with_key = boom
    rs.login = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"rejected {secret}"))
    try:
        with pytest.raises(RuntimeError) as exc_info:
            rs.authenticate("https://sundial.invalid", "guest", secret)
    finally:
        rs.login_with_key, rs.login = monkey["login_with_key"], monkey["login"]

    message = str(exc_info.value)
    assert secret not in message, "the credential reached the published error text"
    assert "<redacted>" in message
    # Still says enough to act on.
    assert "automation key" in message and "form login" in message


# ---------------------------------------------------------------------------
# CI must not scan under a role that is handed the vectors
# ---------------------------------------------------------------------------


def _with_role(monkeypatch, role):
    import ci.run_sundial as rs

    monkeypatch.setattr(rs, "session_role", lambda *a, **k: role)
    return rs


@pytest.mark.parametrize("role", ["guest", "ci"])
def test_a_role_without_the_vectors_is_accepted(monkeypatch, role):
    rs = _with_role(monkeypatch, role)
    assert rs.assert_role_cannot_read_vectors("https://sundial.invalid", "cookie") == role


@pytest.mark.parametrize("role", ["private", "admin"])
def test_a_role_that_can_read_the_vectors_is_refused(monkeypatch, role):
    """`/automated?key=` resolves to `private` when handed the private key.

    The two keys look identical, so "we set the guest one" is an assumption
    until something checks. Loading the vectors onto a public runner is the
    exact outcome this gate exists to prevent, so the check has to come before
    the browser opens sundial -- not after, and not in redaction, which only
    governs what gets published.
    """
    rs = _with_role(monkeypatch, role)
    with pytest.raises(RuntimeError, match=f"{role}.*role"):
        rs.assert_role_cannot_read_vectors("https://sundial.invalid", "cookie")


def test_an_unreadable_role_fails_closed(monkeypatch):
    """Not knowing the role is not the same as the role being safe."""
    rs = _with_role(monkeypatch, None)
    with pytest.raises(RuntimeError, match="did not say what role"):
        rs.assert_role_cannot_read_vectors("https://sundial.invalid", "cookie")


def test_the_role_is_publishable_but_the_whitelist_still_bites():
    from ci.run_sundial import _PUBLISHABLE, _assert_publishable

    assert "sundial_role" in _PUBLISHABLE
    _assert_publishable({"sundial_role": "guest"})
    with pytest.raises(RuntimeError):
        _assert_publishable({"sundial_role": "guest", "vector_name": "pv-secret"})


def test_the_evidence_records_which_role_the_run_used(monkeypatch, tmp_path):
    """`sundial_role` has to survive into the saved result, not just be checked.

    redact()'s output replaces result.metrics wholesale, so a role recorded
    before the scan was silently dropped on the way out -- the check still ran
    and still failed closed, but the artifact did not say which role it had
    confirmed, leaving "the vectors were never served to this session"
    unverifiable after the fact.
    """
    import ci.run_sundial as rs

    score = {
        "schemaVersion": 1,
        "mode": "score",
        "sundialVersion": "v0.5.0",
        "buckets": {"Identity|core": {"scored": 10, "passed": 10, "failed": 0}},
    }

    monkeypatch.setattr(rs, "_config", lambda: {
        "enabled": True,
        "url": "https://sundial.invalid",
        "gated_categories": ["Identity"],
        "ungated_categories": ["Graphics"],
        "min_pass_rate": 0.9,
    })
    monkeypatch.setattr(rs, "authenticate", lambda *a, **k: "cookie")
    monkeypatch.setattr(rs, "assert_role_cannot_read_vectors", lambda *a, **k: "guest")
    async def _scan(**_kwargs):
        return score

    monkeypatch.setattr(rs, "scan", _scan)
    monkeypatch.setattr(rs, "seal", lambda *a, **k: None)
    monkeypatch.setenv("SUNDIAL_AUTOMATION_KEY", "a-key")

    code = rs.gate(["--binary", str(tmp_path / "fake-bin"), "--evidence-dir", str(tmp_path)])
    saved = json.loads((tmp_path / "sundial.json").read_text())

    assert code == 0, saved.get("notes")
    assert saved["metrics"]["sundial_role"] == "guest"
    # And it is still only ever counts beside it.
    assert "vector" not in json.dumps(saved).lower()


# ---------------------------------------------------------------------------
# the overlay: our tests must not silently replace upstream's
# ---------------------------------------------------------------------------


def _fake_checkout(tmp_path, upstream_modules=("test_page.py",)):
    async_dir = tmp_path / "checkout" / "tests" / "async"
    async_dir.mkdir(parents=True)
    for name in upstream_modules:
        (async_dir / name).write_text("# upstream\n", encoding="utf-8")
    return tmp_path / "checkout"


def test_the_overlay_refuses_to_shadow_an_upstream_module(tmp_path, monkeypatch):
    """Copying over an upstream file would drop every test in it, silently.

    The suite would simply be smaller, with nothing in the log to say a module
    had been replaced -- so this has to be refused rather than resolved.
    """
    from ci import suite

    checkout = _fake_checkout(tmp_path, upstream_modules=("test_page.py",))
    ours = tmp_path / "camoufox"
    ours.mkdir()
    (ours / "test_page.py").write_text("# ours\n", encoding="utf-8")
    monkeypatch.setattr(suite, "CAMOUFOX_TESTS", ours)

    with pytest.raises(SystemExit):
        suite.overlay(checkout)

    assert (checkout / "tests" / "async" / "test_page.py").read_text() == "# upstream\n"


def test_the_overlay_is_idempotent_and_clears_stale_files(tmp_path, monkeypatch):
    """A reused checkout must not trip the collision check on our own files.

    `fetch()` reuses a checkout when one is already there, so the second run
    finds the first run's copies already in place. It must overwrite those --
    and drop a module we have since renamed, which would otherwise linger and
    keep passing against code that no longer claims it.
    """
    from ci import suite

    checkout = _fake_checkout(tmp_path)
    ours = tmp_path / "camoufox"
    ours.mkdir()
    (ours / "test_ours.py").write_text("# v1\n", encoding="utf-8")
    monkeypatch.setattr(suite, "CAMOUFOX_TESTS", ours)

    assert suite.overlay(checkout) == ["test_ours.py"]

    # Second run: same file, edited, plus one renamed away.
    (ours / "test_ours.py").write_text("# v2\n", encoding="utf-8")
    assert suite.overlay(checkout) == ["test_ours.py"]
    assert (checkout / "tests" / "async" / "test_ours.py").read_text() == "# v2\n"

    (ours / "test_ours.py").rename(ours / "test_renamed.py")
    assert suite.overlay(checkout) == ["test_renamed.py"]
    assert not (checkout / "tests" / "async" / "test_ours.py").exists()
    assert (checkout / "tests" / "async" / "test_renamed.py").exists()
    # Upstream's own module is untouched throughout.
    assert (checkout / "tests" / "async" / "test_page.py").read_text() == "# upstream\n"


def test_every_camoufox_test_module_is_named_unlike_upstreams():
    """Names are the only thing standing between an overlay and a shadowed module.

    Checked here as well as at overlay time so a badly named file fails in the
    static job in seconds, rather than forty minutes in when the browser is up.
    """
    from ci.suite import CAMOUFOX_TESTS

    ours = sorted(p.name for p in CAMOUFOX_TESTS.glob("test_*.py"))
    assert ours, "tests/camoufox/ has no test modules; the overlay guards nothing"
    # Upstream names every module after the API it covers; ours are named after
    # the Camoufox behaviour, so a collision means someone copied a file in.
    generic = {"test_page.py", "test_network.py", "test_worker.py", "test_browsercontext.py"}
    assert not (set(ours) & generic), (
        f"{sorted(set(ours) & generic)} shares a name with an upstream module"
    )


# ---------------------------------------------------------------------------
# --explain: a local diagnostic that must stay local
# ---------------------------------------------------------------------------


def _explain_payload():
    return {
        "schemaVersion": 1,
        "mode": "score",
        "sundialVersion": "v0.5.0",
        "buckets": {
            "Identity|core": {"scored": 10, "passed": 8},
            "Graphics|core": {"scored": 4, "passed": 3},
            "Identity|crossOs": {"scored": 5, "passed": 4},
        },
    }


def _stub_sundial(monkeypatch, rs, payload):
    monkeypatch.setattr(rs, "_config", lambda: {
        "enabled": True,
        "url": "https://sundial.invalid",
        "gated_categories": ["Identity"],
        "ungated_categories": ["Graphics"],
        "min_pass_rate": 0.5,
    })
    monkeypatch.setattr(rs, "authenticate", lambda *a, **k: "cookie")
    monkeypatch.setattr(rs, "assert_role_cannot_read_vectors", lambda *a, **k: "guest")

    async def _scan(**_kwargs):
        return payload

    monkeypatch.setattr(rs, "scan", _scan)
    monkeypatch.setattr(rs, "seal", lambda *a, **k: None)
    monkeypatch.setenv("SUNDIAL_AUTOMATION_KEY", "a-key")


def test_explain_is_refused_in_ci(monkeypatch, tmp_path):
    """A per-category weakness map must not be written to a public workflow log.

    The counts are not vectors, but they do say where this browser is weak, and
    the repository is public. Refused before anything is sent, so the flag cannot
    be switched on in CI and discovered afterwards.
    """
    import ci.run_sundial as rs

    _stub_sundial(monkeypatch, rs, _explain_payload())
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    with pytest.raises(SystemExit, match="public"):
        rs.gate(["--explain", "--binary", str(tmp_path / "bin"), "--evidence-dir", str(tmp_path)])

    assert not (tmp_path / "sundial.json").exists(), "refused before anything ran"


def test_explain_prints_but_never_records(monkeypatch, tmp_path, capsys):
    """The breakdown goes to the terminal; the artifact keeps only the whitelist.

    This is the boundary the whole module is built around, so assert it on the
    one path that deliberately produces more detail than it publishes.
    """
    import ci.run_sundial as rs

    _stub_sundial(monkeypatch, rs, _explain_payload())
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    code = rs.gate(["--explain", "--binary", str(tmp_path / "bin"), "--evidence-dir", str(tmp_path)])
    printed = capsys.readouterr().out
    saved = json.loads((tmp_path / "sundial.json").read_text())

    assert code == 0, saved.get("notes")
    assert "per-category breakdown" in printed and "Identity" in printed
    # Nothing about categories reached the artifact.
    assert "Identity" not in json.dumps(saved)
    assert "breakdown" not in json.dumps(saved)
    assert set(saved["metrics"]) <= set(rs._PUBLISHABLE)


def test_explain_says_the_names_are_not_available(monkeypatch):
    """The output must not imply it is showing individual checks.

    Score mode carries no check names at all, so a reader who takes this for the
    full answer would conclude the failing checks are unknowable rather than
    that they need a different credential.
    """
    from ci.run_sundial import explain_buckets

    lines = "\n".join(explain_buckets(_explain_payload(), ["Identity"], ["Graphics"]))
    assert "--allow-full-report" in lines
    assert "no check names" in lines


def test_explain_flags_a_category_nobody_has_classified():
    """Same rule as the gate: a new sundial section must not default to ignored."""
    from ci.run_sundial import explain_buckets

    payload = {"mode": "score", "buckets": {"Quantum|core": {"scored": 3, "passed": 1}}}
    lines = "\n".join(explain_buckets(payload, ["Identity"], ["Graphics"]))
    assert "UNKNOWN CATEGORY" in lines


# ---------------------------------------------------------------------------
# the skiplist audit: a reason is an assertion, and assertions get checked
# ---------------------------------------------------------------------------


def test_the_audit_can_name_a_target_for_every_entry_it_claims_to_check():
    """`pattern` entries name no file, so they cannot be audited by selection.

    They must be reported as unaudited rather than counted as checked -- an
    entry that looks verified and is not is the exact bug this gate exists for.
    """
    from ci.run_skiplist_audit import targets

    selectable, unresolved = targets([
        {"module": "tests/async/test_x.py", "reason": "r"},
        {"test": "tests/async/test_y.py::test_z", "reason": "r"},
        {"pattern": "[chromium]", "reason": "r"},
    ])
    assert selectable == ["tests/async/test_x.py", "tests/async/test_y.py::test_z"]
    assert unresolved == ["[chromium]"]


def test_every_shipped_skiplist_entry_is_auditable():
    """Nothing currently in the file escapes the audit.

    If a pattern entry is ever added this fails, which is the prompt to decide
    how it gets verified rather than letting it ride unchecked.
    """
    import sys

    from ci._util import REPO_ROOT
    from ci.run_skiplist_audit import targets

    sys.path.insert(0, str(REPO_ROOT / "ci"))
    from pw_camoufox_plugin import load_skiplist

    selectable, unresolved = targets(load_skiplist(REPO_ROOT / "ci" / "skiplist.yml"))
    assert selectable, "the skiplist audit would check nothing"
    assert not unresolved, (
        f"these skiplist entries cannot be audited: {unresolved}. Either express them "
        "as a module/test, or decide how their truth gets checked."
    )


# ---------------------------------------------------------------------------
# which of upstream's tests we run, and which we admit we do not
# ---------------------------------------------------------------------------


def test_the_sync_suite_is_in_the_target_set():
    """It was not, for no reason anyone had written down.

    `tests/async/` alone left out 722 of upstream's 2306 tests -- inherited from
    the vendored fork, which carried no sync suite -- with nothing recorded to
    say so. Pinned here so dropping it again has to be deliberate.
    """
    from ci.run_playwright import TARGETS

    assert "tests/sync/" in TARGETS
    assert "tests/async/" in TARGETS


def test_async_and_sync_are_in_separate_groups():
    """They cannot share a pytest process, and the damage does not look like it.

    Upstream's sync suite is greenlet-based and its async suite runs under
    pytest-asyncio; together, whichever runs second breaks the other's loop and
    the failures land in async FIXTURE SETUP. That reads as "the fetch tests are
    flaky", and the retry pass hides it: 50 tests passed only on retry before
    these were split. A group boundary is the fix; a skiplist entry would have
    recorded a browser failure that does not exist.
    """
    from ci.run_playwright import GROUPS

    home = {}
    for index, group in enumerate(GROUPS):
        for target in group.targets:
            home[target] = index
    assert home["tests/async/"] != home["tests/sync/"], (
        "async and sync share a pytest process; that produces fixture errors in async"
    )


def test_every_target_belongs_to_exactly_one_group():
    """A target in two groups runs twice and double-counts."""
    from ci.run_playwright import GROUPS, TARGETS

    flat = [t for g in GROUPS for t in g.targets]
    assert len(flat) == len(set(flat)), f"a target appears in more than one group: {flat}"
    assert tuple(flat) == TARGETS


def test_the_small_group_is_not_sharded():
    """Sharding six tests hands some shard an empty selection; pytest exits 5."""
    from ci.run_playwright import GROUPS

    small = [g for g in GROUPS if "tests/common/" in g.targets]
    assert small and not small[0].sharded


def test_every_exclusion_carries_a_reason():
    """Same bar as the skiplist: not running something requires saying why."""
    from ci.run_playwright import EXCLUDED

    assert EXCLUDED, "nothing is excluded, so either the set is stale or the guard is"
    for path, reason in EXCLUDED.items():
        assert len(reason.split()) >= 5, f"{path} is excluded without a real reason"


def test_a_new_upstream_subtree_is_reported_not_ignored(tmp_path):
    """Upstream adding a test directory must fail the run, not vanish from it.

    The silent version of this is the bug: the suite gets narrower, every number
    still looks healthy, and nothing says coverage moved.
    """
    from ci.run_playwright import unclaimed

    tests = tmp_path / "tests"
    (tests / "async").mkdir(parents=True)
    (tests / "async" / "test_a.py").write_text("")
    (tests / "assets").mkdir()
    (tests / "assets" / "page.html").write_text("")       # fixtures, not tests
    (tests / "golden-firefox").mkdir()
    (tests / "test_installation.py").write_text("")        # excluded with a reason

    assert unclaimed(tmp_path) == []

    (tests / "integration").mkdir()
    (tests / "integration" / "test_new.py").write_text("")
    (tests / "test_brand_new.py").write_text("")
    assert unclaimed(tmp_path) == ["tests/integration/", "tests/test_brand_new.py"]


# ---------------------------------------------------------------------------
# the version under test has to be the version that gets built
# ---------------------------------------------------------------------------


def test_a_requested_version_the_branch_does_not_pin_is_refused(monkeypatch):
    """Only suite selection follows --browser-version; the build reads upstream.sh.

    So asking for a version the branch does not pin builds the OLD browser and
    judges it against the NEW suite. Green, meaningless, and silent -- which is
    the worst combination available.
    """
    from ci import versions

    monkeypatch.setattr(versions, "read_upstream_sh", lambda: {"version": "152.0.4"})

    problem = versions.upstream_mismatch("155.0")
    assert problem and "152.0.4" in problem and "155.0" in problem

    # The legitimate flows: no input at all, or an input that agrees.
    assert versions.upstream_mismatch(None) is None
    assert versions.upstream_mismatch("152.0.4") is None
    assert versions.upstream_mismatch("  152.0.4  ") is None


def test_the_workflow_actually_runs_that_check():
    """A guard nothing invokes is decoration."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--check-upstream" in text, (
        "ci.versions is invoked without --check-upstream, so a browser_version "
        "that disagrees with upstream.sh would silently test the wrong browser"
    )


def test_a_fetched_build_from_another_firefox_generation_is_refused():
    """The driver-only path downloads; the suite comes from upstream.sh.

    Those agree until an upgrade window, when upstream.sh names a Firefox nobody
    has published yet. Then a driver PR fetches the old browser and is judged by
    the new suite -- green, and about nothing.
    """
    from ci.versions import fetched_mismatch

    # Beta drift inside a generation is expected and fine.
    assert fetched_mismatch("official/prerelease/152.0.4-beta.30 (5720d45b)", "152.0.4") is None
    assert fetched_mismatch("152.0.4-beta.31", "152.0.4") is None
    # A generation apart is the bug.
    problem = fetched_mismatch("official/prerelease/149.0-beta.1 (x)", "152.0.4")
    assert problem and "149" in problem and "152" in problem
    # Unreadable input fails closed rather than passing by accident.
    assert fetched_mismatch("", "152.0.4")
    assert fetched_mismatch("no digits here", "152.0.4")


def test_the_workflow_checks_the_fetched_build():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--check-fetched" in text, (
        "the fetch path installs a browser without checking it is the generation "
        "the Playwright suite was chosen for"
    )


# ---------------------------------------------------------------------------
# what the summary is told to require
# ---------------------------------------------------------------------------


def _required_suites(browser_changed: str, has_sundial: str) -> set:
    """Run the workflow's own `required=` assembly and report what it produced.

    Extracted and executed rather than pattern-matched, because the bug this
    guards was a comparison that read as deliberate (`!= "skip"`) against a
    value that is only ever `true` or `false`. Only running it says what it
    does.
    """
    import subprocess

    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index('required="pythonlib')
    end = text.index("python3 -m ci.summarize", start)
    block = text[start:end]
    block = block.replace("${{ needs.resolve.outputs.browser_changed }}", browser_changed)
    block = block.replace("${{ needs.resolve.outputs.has_sundial }}", has_sundial)
    proc = subprocess.run(
        ["bash", "-c", block + '\necho "$required"'],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return set(proc.stdout.split())


def test_build_is_required_only_when_the_browser_was_built():
    """A driver-only pull request skips `build`, so requiring it fails the gate.

    `build` writes a result file only from the build job, which is skipped
    whenever the browser was fetched instead. summarize treats a required suite
    with no result as a failure -- correctly -- so requiring it unconditionally
    blocked every pull request that did not touch browser sources: docs,
    pythonlib, ci/ and tests/ alike. That is most of them, and it is precisely
    the cheap path this pipeline advertises.
    """
    assert "build" in _required_suites("true", "false")
    assert "build" not in _required_suites("false", "false")


def test_the_browser_suites_are_required_either_way():
    """Fetching instead of building narrows what was compiled, not what is tested."""
    for changed in ("true", "false"):
        required = _required_suites(changed, "false")
        assert {
            "pythonlib", "native_rules", "patch_guards", "skiplist_audit",
            "build_tester", "playwright", "native_browser",
        } <= required, changed


def test_sundial_is_required_only_when_there_is_a_credential():
    assert "sundial" in _required_suites("true", "true")
    assert "sundial" not in _required_suites("true", "false")


# ---------------------------------------------------------------------------
# sundial being down is not a verdict about the browser
# ---------------------------------------------------------------------------


def _write_result(directory, gate, status, **extra):
    payload = {"gate": gate, "status": status, "tests": {}, "metrics": {}, "notes": []}
    payload.update(extra)
    (directory / f"{gate}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_a_skipped_suite_fails_the_run_unless_it_is_explicitly_allowed(tmp_path):
    """`--allow-skip` is the whole permission, and it is per suite.

    Without it a SKIP must stay a failure: a suite that did not run has not
    passed, and "record a skip" would otherwise be the cheapest way to make any
    gate disappear.
    """
    from ci.summarize import main as summarize

    _write_result(tmp_path, "sundial", results.SKIP, notes=["sundial is unreachable"])
    _write_result(tmp_path, "playwright", results.SKIP, notes=["did not feel like it"])

    # Not allowed: both are failures.
    assert summarize(["--results-dir", str(tmp_path), "--require", "sundial", "playwright"]) == 1

    # Allowing one does not allow the other.
    code = summarize([
        "--results-dir", str(tmp_path), "--require", "sundial", "playwright",
        "--allow-skip", "sundial",
    ])
    assert code == 1, "a skip for a suite outside --allow-skip must still fail"

    (tmp_path / "playwright.json").unlink()
    code = summarize([
        "--results-dir", str(tmp_path), "--require", "sundial", "--allow-skip", "sundial",
    ])
    assert code == 0


def test_an_allowed_skip_is_still_shown_as_a_skip(tmp_path):
    """Tolerated is not the same as invisible: it keeps its icon and its reason."""
    from ci.summarize import render

    merged = {"sundial": {
        "gate": "sundial", "status": results.SKIP, "tests": {}, "metrics": {},
        "notes": ["stealth check skipped -- sundial could not be reached"],
    }}
    markdown = render(merged, ["sundial"], [], {})
    assert "⏭️" in markdown
    assert "could not be reached" in markdown
    assert "✅ Tests passed" in markdown  # tolerated: the run still passes
    # And it must not render as a measurement that came back empty.
    assert "grade **?**" not in markdown


def test_the_workflow_allows_a_skip_only_for_sundial():
    """A skip is tolerated because sundial is someone else's uptime. Nothing else
    in this pipeline has that excuse -- every other suite runs on the runner."""
    text = WORKFLOW.read_text(encoding="utf-8")
    allowed = re.findall(r"--allow-skip ([^\\\n]*)", text)
    assert allowed, "the summary step no longer passes --allow-skip"
    for line in allowed:
        assert line.split() == ["sundial"], line


def test_only_a_transport_failure_counts_as_sundial_being_down():
    """An HTTP reply is an answer, and answers get judged.

    401 means the credential is wrong and 403 means the edge refused us -- both
    are this repository's problem to fix, and skipping past them would turn a
    misconfigured stealth gate into a permanently green one.
    """
    from ci.run_sundial import _unavailable_reason

    def http(code):
        return urllib.error.HTTPError("https://sundial.invalid", code, "", {}, None)

    assert _unavailable_reason(http(500))
    assert _unavailable_reason(http(503))
    assert _unavailable_reason(http(429))
    assert _unavailable_reason(urllib.error.URLError("Name or service not known"))
    assert _unavailable_reason(TimeoutError("timed out"))
    assert _unavailable_reason(ConnectionResetError("reset"))

    assert _unavailable_reason(http(401)) is None
    assert _unavailable_reason(http(403)) is None
    assert _unavailable_reason(http(404)) is None
    assert _unavailable_reason(RuntimeError("sundial rejected the credentials")) is None


def test_an_unreachable_sundial_is_a_skip_and_a_bad_credential_is_not(monkeypatch, tmp_path):
    """The gate's two exits, and the line between them.

    Down: the browser was never measured, so neither pass nor fail is true, and
    an outage on another host must not block every merge here. Rejected: sundial
    answered, and the answer was about this repository's configuration.
    """
    import ci.run_sundial as rs

    monkeypatch.setattr(rs, "_config", lambda: {
        "enabled": True, "url": "https://sundial.invalid",
        "gated_categories": ["Identity"], "ungated_categories": [], "min_pass_rate": 0.9,
    })
    monkeypatch.setenv("SUNDIAL_AUTOMATION_KEY", "a-key")
    binary = tmp_path / "fake-bin"
    binary.write_text("")

    def down(*_a, **_k):
        raise rs.SundialUnavailable("sundial could not be reached (Connection refused)")

    monkeypatch.setattr(rs, "authenticate", down)
    assert rs.gate(["--binary", str(binary), "--evidence-dir", str(tmp_path)]) == 0
    saved = json.loads((tmp_path / "sundial.json").read_text())
    assert saved["status"] == results.SKIP
    assert "could not be reached" in " ".join(saved["notes"])

    def rejected(*_a, **_k):
        raise RuntimeError("sundial rejected the credentials.")

    monkeypatch.setattr(rs, "authenticate", rejected)
    assert rs.gate(["--binary", str(binary), "--evidence-dir", str(tmp_path)]) == 1
    saved = json.loads((tmp_path / "sundial.json").read_text())
    assert saved["status"] == results.ERROR


def test_a_skip_note_cannot_carry_the_credential(monkeypatch, tmp_path):
    """The token route puts the secret in the URL, and a URLError carries it."""
    import ci.run_sundial as rs

    secret = "super-secret-automation-key"
    monkeypatch.setattr(rs, "_config", lambda: {
        "enabled": True, "url": "https://sundial.invalid",
        "gated_categories": ["Identity"], "ungated_categories": [], "min_pass_rate": 0.9,
    })
    monkeypatch.setenv("SUNDIAL_AUTOMATION_KEY", secret)
    binary = tmp_path / "fake-bin"
    binary.write_text("")

    def down(*_a, **_k):
        raise rs.SundialUnavailable(
            f"sundial could not be reached: https://sundial.invalid/automated?key={secret}"
        )

    monkeypatch.setattr(rs, "authenticate", down)
    rs.gate(["--binary", str(binary), "--evidence-dir", str(tmp_path)])
    assert secret not in (tmp_path / "sundial.json").read_text()


def test_one_route_answering_means_sundial_is_up(monkeypatch):
    """Both routes are tried, and the key one 401s whenever the secret is a
    password. That is an answer, so the failure that follows is a real one."""
    import ci.run_sundial as rs

    def key_route(*_a, **_k):
        raise RuntimeError("the automation key route returned 401 and no session cookie")

    def form_route(*_a, **_k):
        raise RuntimeError("sundial rejected the credentials.")

    monkeypatch.setattr(rs, "login_with_key", key_route)
    monkeypatch.setattr(rs, "login", form_route)
    with pytest.raises(RuntimeError) as caught:
        rs.authenticate("https://sundial.invalid", "guest", "secret")
    assert not isinstance(caught.value, rs.SundialUnavailable)

    def unreachable(*_a, **_k):
        raise rs.SundialUnavailable("sundial could not be reached (Connection refused)")

    monkeypatch.setattr(rs, "login_with_key", unreachable)
    monkeypatch.setattr(rs, "login", unreachable)
    with pytest.raises(rs.SundialUnavailable):
        rs.authenticate("https://sundial.invalid", "guest", "secret")


# ---------------------------------------------------------------------------
# isolated world first, main world as a counted fallback
# ---------------------------------------------------------------------------


def test_the_isolated_world_is_what_runs_unless_asked_otherwise(monkeypatch):
    """The default has to be the configuration users ship.

    The suite used to force main-world execution for every run, which made the
    upstream tests pass and measured a mode nobody ships. Anyone running the
    plugin by hand now gets the real thing.
    """
    from ci.pw_camoufox_plugin import ISOLATED_WORLD, MAIN_WORLD, selected_world

    monkeypatch.delenv("CI_WORLD", raising=False)
    assert selected_world() == ISOLATED_WORLD
    monkeypatch.setenv("CI_WORLD", "")
    assert selected_world() == ISOLATED_WORLD
    monkeypatch.setenv("CI_WORLD", "isolated")
    assert selected_world() == ISOLATED_WORLD
    monkeypatch.setenv("CI_WORLD", "MAIN")
    assert selected_world() == MAIN_WORLD


def test_an_isolated_run_clears_a_stale_main_world_flag(monkeypatch):
    """Clearing matters as much as setting.

    The two passes are separate processes that inherit the same job
    environment. A leftover `disableWorldIsolation: true` would make the
    "isolated" pass quietly measure the main world -- and since that pass is
    what produces the fallback count, the number would silently become zero
    while reading as a clean result.
    """
    from ci.pw_camoufox_plugin import ISOLATED_WORLD, MAIN_WORLD, _apply_world

    monkeypatch.setenv("CAMOU_CONFIG", json.dumps({
        "disableWorldIsolation": True, "webgl:renderer": "keep me",
    }))
    _apply_world(ISOLATED_WORLD)
    config = json.loads(os.environ["CAMOU_CONFIG"])
    assert "disableWorldIsolation" not in config
    assert config["webgl:renderer"] == "keep me", "unrelated config must survive"

    _apply_world(MAIN_WORLD)
    assert json.loads(os.environ["CAMOU_CONFIG"])["disableWorldIsolation"] is True


def test_only_the_first_pass_runs_isolated():
    """Exactly one isolated pytest run per group, and it is the measurement.

    A second isolated pass is what the first real CI run showed to be pure
    waste: 7m50s a shard, nothing recovered, because these failures are
    deterministic and slow (a Playwright timeout each) and upstream's own
    pytest-rerunfailures had already retried every one of them three times.
    Guarded here because "retry it in the same world first, just to be safe"
    reads as obviously correct and costs eight minutes a shard.
    """
    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    assert source.count('"CI_WORLD": ISOLATED_WORLD') == 1, (
        "a second isolated pass re-runs deterministic world differences at a "
        "timeout each and recovers nothing"
    )
    # The declared-hang pass (1b), the fallback (2), and the retry for what
    # failed in both worlds (3). Isolation is the half that must stay at one;
    # a main-world run is cheap and adjudicates, an isolated one measures.
    assert source.count('"CI_WORLD": MAIN_WORLD') == 3


def test_only_the_isolated_pass_is_cost_bounded():
    """The tighter timeout and the rerun suppression belong to pass 1 only.

    Pass 1 asks one question -- does this pass as Camoufox ships? -- and a test
    that hangs has already answered it. Passes 2 and 3 are the ones that decide
    what the answer means, so they keep upstream's conditions: the full timeout,
    and upstream's own reruns.
    """
    from ci.run_playwright import ISOLATED_TIMEOUT, _NO_UPSTREAM_RERUNS

    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    assert source.count("per_test_timeout=ISOLATED_TIMEOUT") == 1
    assert source.count("**_NO_UPSTREAM_RERUNS") == 1
    # Both on the isolated pass, not on a main-world one.
    isolated = source.index('"CI_WORLD": ISOLATED_WORLD')
    first_main = source.index('"CI_WORLD": MAIN_WORLD', source.index("# --- 2."))
    for marker in ("per_test_timeout=ISOLATED_TIMEOUT", "**_NO_UPSTREAM_RERUNS"):
        at = source.index(marker)
        assert abs(at - isolated) < abs(at - first_main), marker

    # 30.4s was the slowest test in the whole main-world baseline, and a
    # Playwright action times out at 30s. Below ~60 this starts failing honest
    # tests; at 180 a hang costs three minutes.
    assert 60 <= ISOLATED_TIMEOUT <= 120
    assert _NO_UPSTREAM_RERUNS == {"CI": ""}


def test_suppressing_reruns_survives_upstreams_conftest():
    """`--reruns 0` on the command line would not work.

    upstream's tests/conftest.py sets `config.option.reruns = 3` in
    pytest_configure whenever $CI is set, which overwrites anything passed as an
    argument. Clearing the variable is the only lever that holds, and $CI is the
    only thing that conftest reads it for -- so this must stay an env change,
    not an argument.
    """
    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    assert "--reruns" not in source, (
        "upstream's conftest overwrites config.option.reruns whenever $CI is "
        "set, so a --reruns argument is silently ignored"
    )


def test_no_rerun_pass_can_start_from_an_empty_failure_set():
    """`--last-failed` with nothing previously failed runs EVERYTHING.

    pytest declines to filter when nothing it collected previously failed, so
    an unguarded rerun pass would re-run the whole group -- in the other world,
    silently replacing the result it was meant to refine. Every `--last-failed`
    invocation must therefore sit behind a check that the set is non-empty.
    """
    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    body = source[source.index("# --- 1. isolated world"):source.index('result.metrics["groups"]')]
    guards = [n for n, line in enumerate(body.splitlines()) if line.strip() == "if not failing:"]
    reruns = [n for n, line in enumerate(body.splitlines()) if '"--last-failed"' in line]
    assert len(reruns) == 2, reruns
    for r in reruns:
        assert any(g < r for g in guards), (
            f"the --last-failed at line {r} of the group body is not guarded by a "
            "non-empty failure set"
        )


def test_every_group_gets_its_own_pytest_cache():
    """`--last-failed` reads pytest's cache, and the cache is per directory.

    All three groups run in one checkout, and pytest only drops a `lastfailed`
    entry when that test is collected again and passes -- so with a shared
    cache the async group's rerun selected from a set the sync group had also
    written into. Depending on which groups had failed that meant re-running
    the entire group or selecting nothing at all.
    """
    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    assert 'cache_dir = WORK_DIR / f"pytest-cache{suffix}" / str(index)' in source
    assert 'common = [*base_args, "-o", f"cache_dir={cache_dir}"]' in source
    # Every rerun goes through `common`, which is what carries the redirected
    # cache. A `--last-failed` that did not would silently read the shared one.
    reruns = re.findall(r"args=\[([^\]]*--last-failed[^\]]*)\]", source)
    assert len(reruns) == 2, f"expected the retry and the fallback, got {reruns}"
    for args in reruns:
        assert args.strip().startswith("*common"), args


def test_the_skiplist_audit_runs_in_the_most_permissive_world():
    """An entry has to mean "cannot pass in either world".

    The suite counts a test needing the main world as a fallback, not a
    failure. Auditing under isolation would let an entry justify itself with a
    failure the suite would never have counted -- which is the same class of
    untrue-but-plausible reason the audit exists to catch.
    """
    source = (CI_ROOT / "run_skiplist_audit.py").read_text(encoding="utf-8")
    assert '"CI_WORLD": MAIN_WORLD' in source


def test_fallback_counts_are_summed_across_shards_not_sampled():
    """Six shards each report their own share; the first shard's is not the total."""
    merged = merge_shards({
        "playwright-1of3": {
            "gate": "playwright-1of3", "status": "pass",
            "tests": {"a.py::t1": "pass"},
            "metrics": {
                "main_world_fallback_count": 2,
                "main_world_fallbacks": ["a.py::t1", "a.py::t2"],
                "isolated_world_failures": 3,
                "playwright_tag": "v1.61.0",
            },
        },
        "playwright-2of3": {
            "gate": "playwright-2of3", "status": "pass",
            "tests": {"b.py::t3": "pass"},
            "metrics": {
                "main_world_fallback_count": 4,
                "main_world_fallbacks": ["b.py::t3"],
                "isolated_world_failures": 4,
                "playwright_tag": "v1.61.0",
            },
        },
        "playwright-3of3": {
            "gate": "playwright-3of3", "status": "pass",
            "tests": {"c.py::t4": "pass"},
            "metrics": {
                "main_world_fallback_count": 0,
                "main_world_fallbacks": [],
                "isolated_world_failures": 0,
                "playwright_tag": "v1.61.0",
            },
        },
    })
    metrics = merged["playwright"]["metrics"]
    assert metrics["main_world_fallback_count"] == 6
    assert metrics["isolated_world_failures"] == 7
    assert metrics["main_world_fallbacks"] == ["a.py::t1", "a.py::t2", "b.py::t3"]
    # A property of the run as a whole is still taken once, not summed.
    assert metrics["playwright_tag"] == "v1.61.0"


def test_the_summary_publishes_the_fallback_count():
    """It is invisible in the pass/fail totals by construction -- these tests
    pass -- so if it is not on the table it is not anywhere a reviewer looks."""
    from ci.summarize import render

    merged = {"playwright": {
        "gate": "playwright", "status": "pass", "tests": {}, "notes": [],
        "metrics": {
            "tally": {"pass": 2229, "fail": 0, "total": 2295},
            "main_world_fallback_count": 37,
        },
    }}
    markdown = render(merged, ["playwright"], [], {})
    assert "37 via main-world fallback" in markdown


def test_a_zero_fallback_count_is_still_printed():
    """Zero is the interesting value: it is the one that means the gap closed,
    and an absent line reads the same as a line nobody added."""
    from ci.summarize import render

    merged = {"playwright": {
        "gate": "playwright", "status": "pass", "tests": {}, "notes": [],
        "metrics": {"tally": {"pass": 10, "fail": 0, "total": 10}, "main_world_fallback_count": 0},
    }}
    assert "0 via main-world fallback" in render(merged, ["playwright"], [], {})


# ---------------------------------------------------------------------------
# reusing a browser that is already built
# ---------------------------------------------------------------------------


def _build_job():
    import yaml

    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["build"]


def test_the_native_inputs_cover_everything_that_can_change_the_binary():
    """The cache key and the "did the browser change?" test must agree.

    `resolve` decides whether to build at all by grepping the diff for paths
    that can alter the binary. The build job then reuses a cached browser keyed
    on a hash of the native inputs. If the first list ever grows and the second
    does not, a change to the new path would neither force a build nor
    invalidate the cache -- and every suite would report on a browser that
    predates it, looking perfectly healthy while doing so.
    """
    from ci.browser_inputs import BROWSER_DIRS, BROWSER_FILES

    text = WORKFLOW.read_text(encoding="utf-8")
    scope = re.search(r"sources='\^\(([^)]*)\)'", text)
    assert scope, "the browser_changed grep is gone or was reshaped"
    considered = {
        part.replace("\\", "").rstrip("/") for part in scope.group(1).split("|") if part
    }
    hashed = set(BROWSER_DIRS) | set(BROWSER_FILES)
    missing = considered - hashed
    assert not missing, (
        f"{sorted(missing)} can change the binary but does not feed the native hash, "
        "so a change there would be served a stale browser"
    )


def test_nothing_the_build_runs_is_excluded_from_the_native_hash():
    """The exclusion list must not contain a script a build can reach.

    NON_NATIVE_SCRIPTS exists so a tool that rewrites pythonlib's data files
    does not invalidate a 665 MB cached browser and buy an hour of compiling
    (measured: editing scripts/clean-fingerprint-data.py did exactly that).
    Excluding a script the build DOES run is the dangerous direction -- the
    cache would then serve a browser built from different sources, and every
    suite downstream would pass against it. So each entry is checked against
    the files a build enters through, rather than trusted.
    """
    from ci.browser_inputs import BUILD_ENTRY_POINTS, NON_NATIVE_SCRIPTS, REPO_ROOT

    reachable = ""
    for entry in BUILD_ENTRY_POINTS:
        path = REPO_ROOT / entry
        assert path.is_file(), f"{entry} is gone; the check below proves nothing"
        reachable += path.read_text(encoding="utf-8", errors="ignore")

    for script in sorted(NON_NATIVE_SCRIPTS):
        name = pathlib.Path(script).name
        assert name not in reachable, (
            f"{script} is referenced from a build entry point but is excluded "
            "from the native hash -- a change to it would be served a stale browser"
        )


def test_excluded_scripts_exist():
    """A stale exclusion silently stops excluding anything; say so instead."""
    from ci.browser_inputs import NON_NATIVE_SCRIPTS, REPO_ROOT

    for script in sorted(NON_NATIVE_SCRIPTS):
        assert (REPO_ROOT / script).is_file(), f"{script} no longer exists"


def test_jar_mn_is_read_not_guessed():
    """Two files in one source directory land at different depths.

    This is the trap the whole overlay turns on. A prefix rule would write
    JugglerFrameChild.sys.mjs one level too deep, leave the old copy in place,
    and run stale Juggler while every suite went green.
    """
    from ci.browser_inputs import jar_entries

    entries = jar_entries()
    assert entries["additions/juggler/TargetRegistry.js"] == "chrome/juggler/content/TargetRegistry.js"
    assert entries["additions/juggler/content/FrameTree.js"] == "chrome/juggler/content/content/FrameTree.js"
    assert entries["additions/juggler/content/JugglerFrameChild.sys.mjs"] == "chrome/juggler/content/JugglerFrameChild.sys.mjs"


def _fake_repo(tmp_path):
    """A miniature additions/juggler with one resource and one native file."""
    jug = tmp_path / "additions" / "juggler"
    (jug / "content").mkdir(parents=True)
    (jug / "screencast").mkdir()
    (jug / "Helper.js").write_text("resource\n")
    (jug / "content" / "FrameTree.js").write_text("resource\n")
    (jug / "screencast" / "Encoder.cpp").write_text("native\n")
    (jug / "jar.mn").write_text(
        "juggler.jar:\n% content juggler %content/\n"
        "  content/Helper.js (Helper.js)\n"
        "  content/content/FrameTree.js (content/FrameTree.js)\n"
    )
    (tmp_path / "upstream.sh").write_text("version=1\n")
    return tmp_path


def test_a_javascript_change_does_not_move_the_native_hash(tmp_path):
    """The whole point: editing packaged JavaScript must not force a rebuild."""
    from ci.browser_inputs import native_digest

    root = _fake_repo(tmp_path)
    before = native_digest(root)
    (root / "additions" / "juggler" / "content" / "FrameTree.js").write_text("changed\n")
    assert native_digest(root) == before


def test_a_cpp_change_does_move_the_native_hash(tmp_path):
    """...and the converse, which is the half that must never be wrong.

    additions/juggler/ holds the screencast encoder and the debugging pipe as
    well as the JavaScript. Treating the directory as "all resources" would ship
    a browser without a C++ change in it.
    """
    from ci.browser_inputs import native_digest

    root = _fake_repo(tmp_path)
    before = native_digest(root)
    (root / "additions" / "juggler" / "screencast" / "Encoder.cpp").write_text("changed\n")
    assert native_digest(root) != before


def test_an_unrecognised_file_counts_as_native(tmp_path):
    """Fail closed. A file type nobody has thought about forces a build."""
    from ci.browser_inputs import native_digest

    root = _fake_repo(tmp_path)
    before = native_digest(root)
    (root / "additions" / "juggler" / "something.rs").write_text("who knows\n")
    assert native_digest(root) != before


def test_jar_mn_itself_is_native(tmp_path):
    """It decides the mapping and what is packaged at all.

    If changing it only re-overlaid, a resource removed from jar.mn would keep
    its stale copy in the dist forever.
    """
    from ci.browser_inputs import native_digest

    root = _fake_repo(tmp_path)
    before = native_digest(root)
    (root / "additions" / "juggler" / "jar.mn").write_text(
        "juggler.jar:\n% content juggler %content/\n  content/Helper.js (Helper.js)\n"
    )
    assert native_digest(root) != before


def test_the_overlay_writes_where_jar_mn_says(tmp_path):
    from ci.browser_inputs import overlay

    root = _fake_repo(tmp_path)
    dist = tmp_path / "bin"
    (root / "additions" / "juggler" / "content" / "FrameTree.js").write_text("new js\n")
    written = overlay(dist, root)
    assert sorted(written) == [
        "chrome/juggler/content/Helper.js",
        "chrome/juggler/content/content/FrameTree.js",
    ]
    assert (dist / "chrome/juggler/content/content/FrameTree.js").read_text() == "new js\n"


def test_the_overlay_runs_only_on_a_hit_and_before_the_upload():
    """On a fresh build the dist already holds the right resources; overlaying
    there would cost a 634 MB unpack and repack to copy files onto themselves."""
    steps = _build_job()["steps"]
    names = [s.get("name") or s.get("uses") or "run" for s in steps]
    overlay = next(i for i, n in enumerate(names) if "resources over the restored" in n)
    upload = next(i for i, n in enumerate(names) if n == "actions/upload-artifact@v4")
    assert steps[overlay]["if"].strip() == "steps.prebuilt.outputs.cache-hit == 'true'"
    assert overlay < upload, "the artifact would be uploaded before the resources were laid over it"


def test_a_restored_browser_still_reports_a_build_result():
    """Otherwise the gate fails on a cache hit.

    `build` is required whenever the browser was built rather than fetched, and
    requiring a suite that produced no result is -- correctly -- a failure. A
    cache hit skips the job that writes it, so the hit path has to write one
    itself. Same trap as requiring `build` on a driver-only run, reached from
    the other side.
    """
    steps = _build_job()["steps"]
    hit = [s for s in steps if s.get("if", "").strip() == "steps.prebuilt.outputs.cache-hit == 'true'"]
    assert hit, "nothing runs on a cache hit, so no build result is produced"
    assert any("GateResult(gate='build')" in str(s.get("run", "")) for s in hit)


def test_every_expensive_build_step_is_skipped_on_a_hit():
    """A hit that still spends twenty minutes clearing disk has saved nothing."""
    steps = _build_job()["steps"]
    guard = "steps.prebuilt.outputs.cache-hit != 'true'"
    expensive = ("Maximize build space", "Remove unwanted tools", "Install build dependencies",
                 "Create swap", "Prepare the source tree", "Build",
                 "Package the binary for the test jobs", "Restore ccache")
    for name in expensive:
        step = next((s for s in steps if s.get("name") == name), None)
        assert step is not None, f"{name} is gone -- update this list"
        assert step.get("if", "").strip() == guard, f"{name} runs even when the browser was restored"


def test_the_prebuilt_cache_has_no_restore_keys():
    """A prefix match would serve a browser built from different sources.

    Everywhere else in this workflow `restore-keys` is right -- a partially warm
    ccache is still warm. Here it would hand the test jobs the wrong binary
    while every suite reported on it as though it were the one under review.
    """
    step = next(s for s in _build_job()["steps"] if s.get("id") == "prebuilt")
    assert "restore-keys" not in step["with"]
    assert step["with"]["path"] == "camoufox-dist.tar.zst"


# ---------------------------------------------------------------------------
# declared isolation hangs
# ---------------------------------------------------------------------------


def test_isolation_hangs_are_deselected_from_the_isolated_pass():
    """The whole point of declaring them: they must not reach pass 1.

    A hang there is bounded by nothing. pytest-timeout's signal fires and the
    sync API's greenlet never unwinds, so the process wedges with the timeout
    banner already printed -- which is what burned four shards for two hours
    each on run 34799668707.
    """
    from ci.run_playwright import ISOLATION_HANGS

    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    assert ISOLATION_HANGS
    # Built from the declared list rather than spelled out, so adding an entry
    # cannot leave the isolated pass still collecting it.
    assert 'args=[*common, *[f"--ignore={m}" for m in hangs], *group.targets]' in source
    assert "hangs = [m for m in ISOLATION_HANGS" in source


def test_isolation_hangs_still_run_somewhere():
    """Deselecting is not skipping. They run in the main world, and must.

    The run has to sit above the `failing` guard: a group whose isolated pass
    found nothing hits `continue`, and anything below it would quietly stop
    being covered on exactly the runs that look healthiest.
    """
    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    declared = source.index("# --- 1b.")
    guard = source.index("if not failing:")
    second = source.index("# --- 2.")
    assert declared < guard < second
    # And an empty result is a failure, not an empty pass.
    assert "hang that stops running is how coverage disappears" in source


def test_declared_hangs_run_unsharded_on_one_shard():
    """Sharding a six-test module hands most shards nothing.

    pytest exits 5 on an empty selection and writes no junit, which the guard
    above cannot tell from "did not run" -- so it failed every shard that owned
    none of the module ("collected 6 items / 6 deselected / 0 selected"), which
    was three of six on the first run that got this far. Run once, whole, the
    way tests/common/ is.

    CI_SHARD is cleared rather than dropped because ci/_util.run() layers env
    over os.environ, so an omitted key still inherits whatever is there.
    """
    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    assert "if hangs and first_shard:" in source
    assert '"CI_SHARD": ""' in source
    # Cleared for the declared-hang pass only; the real passes stay sharded.
    assert source.count('"CI_SHARD": ""') == 1


def test_empty_shard_selection_is_not_a_shard_number():
    """parse_shard must read cleared-to-empty as 'no shard', not raise.

    That is what makes clearing CI_SHARD a working way to unshard one run; if
    it raised, the declared-hang pass would die on an unparseable shard instead.
    """
    assert parse_shard("") is None
    assert parse_shard(None) is None
    assert parse_shard("3/6") == (3, 6)


def test_every_isolation_hang_is_inside_a_group_target():
    """A declared module outside every target would be deselected from nothing
    and then run in a main-world pass that no group reaches -- covered on
    paper, run never."""
    from ci.run_playwright import GROUPS, ISOLATION_HANGS

    targets = [t for g in GROUPS for t in g.targets]
    for module in ISOLATION_HANGS:
        assert any(module.startswith(t) for t in targets), module


def test_isolation_hangs_are_not_in_the_skiplist():
    """These two lists mean different things and the audit enforces the split.

    ci/skiplist.yml means "fails in the most permissive world", and
    run_skiplist_audit.py checks it by running every entry with CI_WORLD=main
    and failing the build on any that PASS. A route_web_socket test passes
    there -- main world is precisely where the feature works -- so an entry
    would be rejected by the audit and would be untrue as written.
    """
    from ci.run_playwright import ISOLATION_HANGS

    entries = load_skiplist(CI_ROOT / "skiplist.yml")
    listed = {str(e.get("module") or e.get("test") or "").lstrip("./") for e in entries}
    for module in ISOLATION_HANGS:
        assert module not in listed, (
            f"{module} is declared as an isolation hang AND skiplisted; the audit "
            "runs skiplist entries in the main world, where it passes."
        )


def test_group_timeout_is_shorter_than_the_job_timeout():
    """The backstop can only fire if it is reached first.

    This is the bug that made a hang cost two hours rather than twenty minutes:
    the per-invocation subprocess bound defaulted to 10800s against a job capped
    at 120 minutes, so GitHub hard-killed the runner before it ever ran out --
    taking the junit and diagnostics uploads with it.
    """
    import yaml

    from ci.run_playwright import main as _main  # noqa: F401

    source = (CI_ROOT / "run_playwright.py").read_text(encoding="utf-8")
    default = int(re.search(r'"--group-timeout", type=int, default=(\d+)', source).group(1))

    job = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["playwright"]
    job_seconds = int(job["timeout-minutes"]) * 60
    assert default < job_seconds, (default, job_seconds)
    # And with enough room left over to still upload what it collected.
    assert default <= job_seconds // 2
    # Four times the slowest healthy invocation measured (296s); below that it
    # starts cutting slow-but-working groups short.
    assert default >= 900


# ---------------------------------------------------------------------------
# build-tester agrees with the identities pythonlib can present
# ---------------------------------------------------------------------------


def test_build_tester_accepts_every_core_count_pythonlib_presents():
    """A real identity must not fail build-tester's plausibility check.

    build-tester's plausibleHWC list lacked 18 and 22 -- both real (Intel Meteor
    Lake laptops) and both in the recorded presets -- so a run that drew one of
    the two Linux presets reporting 22 failed. About one run in eleven, on any
    pull request. The list follows the data, not the other way round.
    """
    repo = pathlib.Path(__file__).resolve().parents[2]
    source = (repo / "build-tester/src/lib/checks/extended.ts").read_text(encoding="utf-8")
    block = source[source.index("plausibleHWC"):]
    listed = re.search(r"const common = \[([^\]]*)\]", block)
    assert listed, "plausibleHWC's list of common core counts was not found"
    accepted = {int(n) for n in re.findall(r"\d+", listed.group(1))}

    presented = set()
    lib = repo / "pythonlib/camoufox"
    for name in ("fingerprint-presets.json", "fingerprint-presets-v150.json"):
        data = json.loads((lib / name).read_text(encoding="utf-8"))
        for rows in data.get("presets", {}).values():
            for row in rows:
                hwc = row.get("navigator", {}).get("hardwareConcurrency")
                if isinstance(hwc, int):
                    presented.add(hwc)
    table = re.search(
        r"^PLAUSIBLE_CORE_COUNTS = \(([^)]*)\)",
        (lib / "fingerprints.py").read_text(encoding="utf-8"),
        re.M,
    )
    assert table, "PLAUSIBLE_CORE_COUNTS was not found in fingerprints.py"
    presented |= {int(n) for n in re.findall(r"\d+", table.group(1))}

    missing = sorted(presented - accepted)
    assert not missing, (
        f"build-tester's plausibleHWC rejects core counts pythonlib presents: {missing}. "
        "Add them to the list in build-tester/src/lib/checks/extended.ts."
    )


# ---------------------------------------------------------------------------
# build-or-fetch: the published release is used only when it matches the tree
# ---------------------------------------------------------------------------


def _scope(repo: pathlib.Path, base: str) -> tuple[str, str]:
    """Run the workflow's own "Does this change the browser?" step in `repo`."""
    import subprocess

    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("        run: |\n          if [ \"${{ github.event_name }}\" != \"pull_request\" ]")
    end = text.index("      - name: May the stealth check run?", start)
    lines = text[start:end].splitlines()[1:]
    block = "\n".join(line[10:] if line.startswith(" " * 10) else line.strip() for line in lines)
    block = block.replace("${{ github.event_name }}", "pull_request")
    block = block.replace("${{ github.event.pull_request.base.sha }}", base)
    out = repo / "out.txt"
    proc = subprocess.run(
        ["bash", "-e", "-c", block], cwd=repo, capture_output=True, text=True,
        env={**os.environ, "GITHUB_OUTPUT": str(out)},
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text().strip(), proc.stdout


def _git(repo: pathlib.Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-c", "user.email=ci@test", "-c", "user.name=ci", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def release_repo(tmp_path):
    """A repo whose v1.0-beta.1 tag is the published release, and a main after it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "upstream.sh").write_text("version=1.0\nrelease=beta.1\n")
    (repo / "patches").mkdir()
    (repo / "patches" / "a.patch").write_text("a\n")
    (repo / "typescript").mkdir()
    (repo / "typescript" / "x.ts").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "release")
    _git(repo, "tag", "v1.0-beta.1")
    return repo


def test_driver_pr_on_the_released_sources_tests_the_release(release_repo):
    base = _git(release_repo, "rev-parse", "HEAD")
    (release_repo / "typescript" / "x.ts").write_text("y\n")
    _git(release_repo, "commit", "-qam", "driver change")
    assert _scope(release_repo, base)[0] == "browser_changed=false"


def test_driver_pr_on_unreleased_browser_sources_builds(release_repo):
    """#785: main had merged browser patches (#779) that no release carried yet,
    so a TS-only pull request fetched beta.31 and ran #779's patch guards on it."""
    (release_repo / "patches" / "a.patch").write_text("merged but unreleased\n")
    _git(release_repo, "commit", "-qam", "browser change merged to main")
    base = _git(release_repo, "rev-parse", "HEAD")
    (release_repo / "typescript" / "x.ts").write_text("y\n")
    _git(release_repo, "commit", "-qam", "driver change")
    result, log = _scope(release_repo, base)
    assert result == "browser_changed=true"
    assert "patches/a.patch" in log


def test_browser_pr_builds(release_repo):
    base = _git(release_repo, "rev-parse", "HEAD")
    (release_repo / "patches" / "a.patch").write_text("b\n")
    _git(release_repo, "commit", "-qam", "browser change")
    assert _scope(release_repo, base)[0] == "browser_changed=true"


def test_unpublished_release_tag_builds(release_repo):
    _git(release_repo, "tag", "-d", "v1.0-beta.1")
    base = _git(release_repo, "rev-parse", "HEAD")
    (release_repo / "typescript" / "x.ts").write_text("y\n")
    _git(release_repo, "commit", "-qam", "driver change")
    assert _scope(release_repo, base)[0] == "browser_changed=true"
