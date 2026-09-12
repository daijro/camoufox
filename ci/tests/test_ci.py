"""Self-tests for the repo-wide CI pipeline.

The pipeline's job is to run the right suite against the right browser and
report honestly. These cover the parts where "honestly" is load-bearing:

  * nothing identifying a sundial vector may survive redaction, and the public
    output is a grade rather than a breakdown of what is weak;
  * a skip must carry a reason, or it is indistinguishable from hiding a test;
  * sharding must be stable, so a flake does not appear to move between runners;
  * version resolution must never pick a suite newer than the browser;
  * test identities must match across the vendored and upstream suite layouts.

Run:  python3 -m pytest ci/tests -q
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile

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
def test_junit_ids_match_across_vendored_and_upstream_layouts(classname, name, expected):
    """The two suites report different dotted paths for the same test file."""
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
    path.write_text("# a comment\nversion=152.0.4\nrelease=beta.31\nclosedsrc_rev=1.0.0\n")
    write_upstream_sh({"version": "153.0.4", "release": "beta.32"}, path)
    text = path.read_text()
    assert "# a comment" in text
    assert "closedsrc_rev=1.0.0" in text
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
    """audio, canvas and timezone are derived per context.

    Two contexts sharing one is the failure this whole suite exists to catch.
    """
    from ci.run_build_tester import uniqueness

    for slot in ("uniqueAudio", "uniqueTimezones"):
        out = uniqueness(_cross(**{slot: 1}))
        assert out["leaks"] == [f"macPerContext.{slot} (1/3 distinct)"], slot
        assert not out["noise"]


def test_canvas_collisions_are_tracked_but_do_not_gate():
    """Canvas belongs in must-vary and does not hold there yet.

    Measured 16 distinct canvas fingerprints in 24 samples where audio gave
    24/24 -- so two contexts collide about a third of the time. Gating would
    fail one run in three for a real, unfixed reason; silence would lose the
    finding. It gets its own bucket and is reported every run.
    """
    from ci.run_build_tester import uniqueness

    out = uniqueness(_cross(uniqueCanvas=2))
    assert out["low_entropy"] == ["macPerContext.uniqueCanvas (2/3 distinct)"]
    assert not out["leaks"] and not out["noise"]


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


def test_the_vendored_suite_honours_pythonlibs_playwright_ceiling():
    """Two files decide which Playwright the regression suite runs against.

    pythonlib/pyproject.toml caps it deliberately -- every Playwright minor is
    free to change Juggler, and 1.61 added params the protocol schema had to
    learn. tests/local-requirements.txt installs the client the suite actually
    uses. Unpinned there, the cap means nothing: the suite quietly installs a
    client the browser cannot speak to, and it reads as a browser failure.
    """
    import re

    from ci._util import REPO_ROOT

    pyproject = (REPO_ROOT / "pythonlib" / "pyproject.toml").read_text(encoding="utf-8")
    cap = re.search(r'^playwright\s*=\s*"([^"]+)"', pyproject, re.M)
    assert cap, "pythonlib/pyproject.toml no longer pins playwright"

    reqs = (REPO_ROOT / "tests" / "local-requirements.txt").read_text(encoding="utf-8")
    line = next(
        (l.strip() for l in reqs.splitlines()
         if l.strip().lower().startswith("playwright") and not l.strip().startswith("#")),
        None,
    )
    assert line, "tests/local-requirements.txt no longer lists playwright"
    assert line != "playwright", (
        "tests/local-requirements.txt installs an unpinned playwright, so "
        f"pythonlib's {cap.group(1)!r} ceiling does not apply to the suite that "
        "actually exercises the browser."
    )
    assert cap.group(1).replace(" ", "") in line.replace(" ", ""), (
        f"the suite pins {line!r} but pythonlib caps at {cap.group(1)!r}; they have drifted"
    )


# ---------------------------------------------------------------------------
# the score-only `ci` role
# ---------------------------------------------------------------------------


def test_a_full_report_is_refused_by_default():
    """The gate runs as a role sundial refuses to serve a report to.

    So a full report arriving here means the run is pointed at the wrong
    account, or at a deployment that predates the role. Folding it down anyway
    would mean the vectors passed through this process and nobody noticed --
    the failure has to be loud.
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
        "playwright_upstream", "playwright_vendored",
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
