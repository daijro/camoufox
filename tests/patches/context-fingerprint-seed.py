"""
Verify seeded context fingerprint generation for Camoufox-owned values.

Run directly:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 tests/patches/context-fingerprint-seed.py

Or with pytest:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 -m pytest --confcutdir=tests/patches tests/patches/context-fingerprint-seed.py
"""

from camoufox.fingerprints import generate_context_fingerprint


PRESET = {
    "navigator": {
        "userAgent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:146.0) "
            "Gecko/20100101 Firefox/146.0"
        ),
        "platform": "MacIntel",
        "hardwareConcurrency": 8,
        "oscpu": "Intel Mac OS X 10.15",
        "maxTouchPoints": 0,
    },
    "screen": {
        "width": 1440,
        "height": 900,
        "colorDepth": 24,
        "availWidth": 1440,
        "availHeight": 875,
    },
    "webgl": {
        "unmaskedVendor": "Apple Inc.",
        "unmaskedRenderer": "Apple GPU",
    },
    "timezone": "America/New_York",
    "fonts": ["Arial", "Helvetica", "Times New Roman"],
    "speechVoices": ["Samantha", "Alex"],
}

SEEDED_CONFIG_KEYS = (
    "fonts:spacing_seed",
    "audio:seed",
    "canvas:seed",
    "fonts",
    "voices",
)
SYNTHETIC_SEEDED_CONFIG_KEYS = SEEDED_CONFIG_KEYS + (
    "webGl:vendor",
    "webGl:renderer",
)
NOISE_SEED_KEYS = (
    "fonts:spacing_seed",
    "audio:seed",
    "canvas:seed",
)


def _seeded_values(seed):
    result = generate_context_fingerprint(preset=PRESET, fingerprint_seed=seed)
    return {
        "config": {key: result["config"].get(key) for key in SEEDED_CONFIG_KEYS},
        "init_script": result["init_script"],
        "context_options": result["context_options"],
    }


def test_same_seed_reuses_camoufox_values():
    first = _seeded_values("profile-a")
    second = _seeded_values("profile-a")
    assert first == second


def test_same_seed_reuses_synthetic_camoufox_values():
    first = generate_context_fingerprint(os="macos", fingerprint_seed="profile-a")["config"]
    second = generate_context_fingerprint(os="macos", fingerprint_seed="profile-a")["config"]
    for key in SYNTHETIC_SEEDED_CONFIG_KEYS:
        assert first.get(key) == second.get(key)


def test_same_seed_reuses_default_synthetic_camoufox_values():
    first = generate_context_fingerprint(fingerprint_seed="profile-a")["config"]
    second = generate_context_fingerprint(fingerprint_seed="profile-a")["config"]
    for key in SYNTHETIC_SEEDED_CONFIG_KEYS:
        assert first.get(key) == second.get(key)


def test_different_seed_changes_noise_seeds():
    first = _seeded_values("profile-a")["config"]
    second = _seeded_values("profile-b")["config"]
    assert first["fonts:spacing_seed"] != second["fonts:spacing_seed"]
    assert first["audio:seed"] != second["audio:seed"]
    assert first["canvas:seed"] != second["canvas:seed"]


def test_unseeded_context_still_sets_nonzero_noise_seeds():
    first = generate_context_fingerprint(preset=PRESET)["config"]
    second = generate_context_fingerprint(preset=PRESET)["config"]
    for config in (first, second):
        for key in NOISE_SEED_KEYS:
            assert 1 <= config[key] <= 4_294_967_295
    assert tuple(first[key] for key in NOISE_SEED_KEYS) != tuple(
        second[key] for key in NOISE_SEED_KEYS
    )


def main():
    test_same_seed_reuses_camoufox_values()
    test_same_seed_reuses_synthetic_camoufox_values()
    test_same_seed_reuses_default_synthetic_camoufox_values()
    test_different_seed_changes_noise_seeds()
    test_unseeded_context_still_sets_nonzero_noise_seeds()
    print("context fingerprint seed checks passed")


if __name__ == "__main__":
    main()
