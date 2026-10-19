"""The font draw has to produce machines that could exist.

verify-fonts.py already checks that a draw only names families fonts.json can
report. That is a membership check, and membership is not the property that
matters: a draw that returned the same list every time, or that put Office on a
third of Windows machines instead of 60%, passes it. Those are the failures this
file is for.

Three properties, each of which a plausible refactor could silently break:

  * COMPLETE BASE   -- a real machine runs one OS version and has that version's
                       whole default font set. `_ESSENTIAL_FONTS_*` is only the
                       INTERSECTION of the versions, so asserting it is not the
                       same as asserting a base.
                       Caveat, measured by mutation-testing this file: the
                       essential floor is large (125 win / 369 mac / 274 lin)
                       and refills most of a subsetted base, so
                       test_every_draw_contains_one_complete_base alone does NOT
                       catch a base that is silently truncated -- what catches
                       that is test_base_weights_match_the_manifest, because
                       truncation removes the exclusive families a version is
                       identified by. Keep both.
  * REAL RATES      -- each unit appears at the probability the manifest gives
                       it, measured against real machines. The draw used to take
                       a flat 30-78% sample over units, which put the
                       Pan-European pack (really 2.8%) on more than half of
                       identities.
  * VARIATION       -- the population of draws is diverse. Font lists are a
                       high-entropy surface; a draw that collapses toward one
                       list makes every Camoufox install look like the same
                       machine.

Rates are sampled, so every threshold here is a binomial tolerance around the
manifest value rather than an equality, and the sample is drawn once per OS and
shared (module-scoped fixture) to keep the suite fast.
"""

import json
import math
import os
from collections import Counter

import pytest

from camoufox import fingerprints
from camoufox.fingerprints import OS_KEYS
from camoufox.fingerprints import _generate_random_font_subset as draw

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src', 'camoufox')
N = 1500


def _load(name):
    with open(os.path.join(DATA, name), 'rb') as fh:
        return json.loads(fh.read())


BASES = _load('font-bases.json')
GROUPS = _load('font-groups.json')
REPORTABLE = _load('fonts.json')


def tolerance(p, n=N, sigmas=5.0, floor=0.03):
    """Binomial slack, wide enough that a correct draw is not flaky."""
    return max(floor, sigmas * math.sqrt(max(p * (1.0 - p), 1e-6) / n))


@pytest.fixture(scope='module')
def samples():
    """{os_name: [set(fonts), ...]} -- one shared sample per OS."""
    return {name: [set(draw(name, seed=i)) for i in range(N)] for name in OS_KEYS}


# ---------------------------------------------------------------------------
# a complete OS-version base, never a partial one
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_every_draw_contains_one_complete_base(os_name, samples):
    """A machine has its OS version's whole default set, not a subset of it."""
    bases = BASES[OS_KEYS[os_name]]
    assert bases, f'{os_name}: no generated bases -- run browser/scripts/gen-font-groups.py'
    base_sets = {b['id']: set(b['fonts']) for b in bases}
    for i, fonts in enumerate(samples[os_name]):
        if not any(fs <= fonts for fs in base_sets.values()):
            short = {bid: sorted(fs - fonts)[:5] for bid, fs in base_sets.items()}
            pytest.fail(
                f'{os_name} draw #{i} contains no base in full; missing per base: {short}'
            )


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_base_weights_match_the_manifest(os_name, samples):
    """Each OS version turns up at its real-world share."""
    bases = BASES[OS_KEYS[os_name]]
    # Identify a base by the families that ONLY it has. A base with none (a
    # strict subset of another, e.g. Windows 10 under Windows 11) is not
    # separable and is not asserted here.
    counts = Counter()
    exclusive = {}
    for b in bases:
        others = set().union(*[set(o['fonts']) for o in bases if o['id'] != b['id']])
        exclusive[b['id']] = set(b['fonts']) - others
    for fonts in samples[os_name]:
        for bid, ex in exclusive.items():
            if ex and ex <= fonts:
                counts[bid] += 1
    for b in bases:
        ex = exclusive[b['id']]
        if not ex:
            continue
        seen, want = counts[b['id']] / N, b['weight']
        assert abs(seen - want) <= tolerance(want), (
            f'{os_name} base {b["id"]}: drawn {seen:.3f}, manifest weight {want}'
        )


# ---------------------------------------------------------------------------
# addition units appear at their measured real-world probability
# ---------------------------------------------------------------------------

def _unit_exclusive(os_key, unit):
    """Fonts that identify this unit: in no base and in no other unit."""
    units = GROUPS[os_key]
    other_units = set().union(
        *[set(u['fonts']) for u in units if u['id'] != unit['id']]
    ) if len(units) > 1 else set()
    in_base = set().union(*[set(b['fonts']) for b in BASES[os_key]]) if BASES[os_key] else set()
    return set(unit['fonts']) - in_base - other_units


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_unit_probabilities_match_the_manifest(os_name, samples):
    """Office on ~60% of Windows boxes, the Pan-European pack on ~2.8%."""
    os_key = OS_KEYS[os_name]
    checked = 0
    for unit in GROUPS[os_key]:
        if unit.get('requiresLocale'):
            continue  # gated separately, below
        ex = _unit_exclusive(os_key, unit)
        if not ex:
            continue  # wholly shared with a base/another unit: not separable
        hits = sum(1 for fonts in samples[os_name] if ex & fonts)
        seen, want = hits / N, unit['prob']
        checked += 1
        assert abs(seen - want) <= tolerance(want), (
            f'{os_name} unit {unit["id"]}: drawn {seen:.3f}, manifest prob {want}'
        )
    assert checked, f'{os_name}: no separable units to check'


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_bundle_units_are_all_or_nothing(os_name, samples):
    """Office installs as one download; a draw must never show half of it.

    A partial group is an artefact no real machine produces (sundial
    "co-shipped families not split").
    """
    os_key = OS_KEYS[os_name]
    for unit in GROUPS[os_key]:
        if unit['kind'] != 'bundle':
            continue
        ex = _unit_exclusive(os_key, unit)
        if len(ex) < 2:
            continue
        for i, fonts in enumerate(samples[os_name]):
            present = ex & fonts
            if present and present != ex:
                pytest.fail(
                    f'{os_name} draw #{i}: bundle unit {unit["id"]} is partial -- '
                    f'{len(present)} of {len(ex)} exclusive families, '
                    f'missing e.g. {sorted(ex - present)[:4]}'
                )


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_alacarte_units_are_piecemeal_not_all_or_nothing(os_name, samples):
    """Developer/web fonts are installed a few at a time, not as a block.

    This is the property that separates an alacarte unit from a bundle one; if
    the draw ever treats them alike, identities lose most of their font entropy.
    """
    os_key = OS_KEYS[os_name]
    checked = 0
    for unit in GROUPS[os_key]:
        if unit['kind'] != 'alacarte':
            continue
        ex = _unit_exclusive(os_key, unit)
        if len(ex) < 4:
            continue
        counts = {len(ex & fonts) for fonts in samples[os_name]}
        partial = {c for c in counts if 0 < c < len(ex)}
        checked += 1
        assert partial, (
            f'{os_name} unit {unit["id"]}: never appears partially '
            f'(counts seen: {sorted(counts)[:6]}) -- it is behaving like a bundle'
        )
        expected = sum(s['n'] * s['w'] for s in unit['sizes']) / sum(s['w'] for s in unit['sizes'])
        drawn = [len(ex & fonts) for fonts in samples[os_name] if ex & fonts]
        mean = sum(drawn) / len(drawn)
        # `sizes` is renormalised against the reportable subset, so allow slack.
        assert mean <= max(expected * 2.5, expected + 2), (
            f'{os_name} unit {unit["id"]}: mean install size {mean:.2f}, '
            f'manifest sizes expect about {expected:.2f}'
        )
    assert checked, f'{os_name}: no alacarte units to check'


def test_locale_gated_units_need_their_locale(monkeypatch):
    """A zh-TW-only pack must not land on an en-US identity.

    No shipped unit is locale-gated today, so the gate is exercised on one
    that is certain to be drawn whenever its locale matches.
    """
    unit = {'id': 'zh-tw-pack', 'kind': 'bundle', 'prob': 1.0,
            'fonts': ['Locale Gated Family'], 'requiresLocale': 'zh-TW'}
    monkeypatch.setattr(fingerprints, '_FONT_GROUPS_CACHE', {'win': [unit]})
    assert 'Locale Gated Family' not in draw('windows', seed=0, locale='en-US')
    assert 'Locale Gated Family' in draw('windows', seed=0, locale='zh-TW')


# ---------------------------------------------------------------------------
# variation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_draws_are_varied(os_name, samples):
    """Font lists are a high-entropy surface; they must not collapse."""
    lists = [tuple(sorted(f)) for f in samples[os_name]]
    distinct = len(set(lists))
    assert distinct >= 50, (
        f'{os_name}: only {distinct} distinct font lists in {N} draws'
    )
    commonest = Counter(lists).most_common(1)[0][1] / N
    assert commonest <= 0.5, (
        f'{os_name}: one identical font list covers {commonest:.1%} of draws'
    )


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_list_length_varies(os_name, samples):
    """Two machines of the same OS should not report the same number of fonts."""
    lengths = {len(f) for f in samples[os_name]}
    assert len(lengths) >= 5, (
        f'{os_name}: font-list length takes only {len(lengths)} values {sorted(lengths)[:6]}'
    )


# ---------------------------------------------------------------------------
# invariants the above must not be bought at the expense of
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_draw_only_reports_renderable_families(os_name, samples):
    """Reporting a font the browser cannot draw is a reverse leak."""
    pool = set(REPORTABLE[OS_KEYS[os_name]])
    for i, fonts in enumerate(samples[os_name]):
        extra = fonts - pool
        assert not extra, f'{os_name} draw #{i} names families outside fonts.json: {sorted(extra)[:5]}'


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_draw_is_deterministic_per_identity(os_name):
    """One identity must present one font list across launches.

    A page that keeps cookies and sees the font list change has caught the
    browser out (daijro/camoufox#442, #765).
    """
    for seed in (1, 7, 99):
        assert draw(os_name, seed=seed) == draw(os_name, seed=seed)


@pytest.mark.parametrize('os_name', sorted(OS_KEYS))
def test_no_duplicate_families_in_a_draw(os_name, samples):
    for i in range(min(N, 200)):
        lst = draw(os_name, seed=i)
        assert len(lst) == len(set(lst)), f'{os_name} draw #{i} repeats a family'
