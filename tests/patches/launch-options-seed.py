"""
Verify launch_options forwards fingerprint_seed into launch-level fingerprint values.

Run directly:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 tests/patches/launch-options-seed.py

Or with pytest:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 -m pytest --confcutdir=tests/patches tests/patches/launch-options-seed.py
"""

import json
from concurrent.futures import ThreadPoolExecutor

from camoufox import utils
from camoufox.fingerprints import from_browserforge, generate_fingerprint


NOISE_SEED_KEYS = (
    "fonts:spacing_seed",
    "audio:seed",
    "canvas:seed",
)


def _config_from_env(env):
    chunks = []
    index = 1
    while f"CAMOU_CONFIG_{index}" in env:
        chunks.append(env[f"CAMOU_CONFIG_{index}"])
        index += 1
    return json.loads("".join(chunks))


def _launch_config(**kwargs):
    original_validate_config = utils.validate_config
    original_get_screen_cons = utils.get_screen_cons
    original_add_default_addons = utils.add_default_addons
    original_confirm_paths = utils.confirm_paths

    utils.validate_config = lambda config, path=None: None
    utils.get_screen_cons = lambda headless=None: None
    utils.add_default_addons = lambda addons, exclude_addons: None
    utils.confirm_paths = lambda addons: None
    try:
        options = utils.launch_options(
            env={},
            headless=True,
            executable_path="/tmp/camoufox",
            ff_version=146,
            i_know_what_im_doing=True,
            **kwargs,
        )
    finally:
        utils.validate_config = original_validate_config
        utils.get_screen_cons = original_get_screen_cons
        utils.add_default_addons = original_add_default_addons
        utils.confirm_paths = original_confirm_paths

    assert "fingerprint_seed" not in options
    return _config_from_env(options["env"])


def test_same_seed_reuses_synthetic_launch_config():
    first = _launch_config(fingerprint_seed="profile-a")
    second = _launch_config(fingerprint_seed="profile-a")
    assert first == second


def test_same_seed_reuses_preset_launch_config():
    first = _launch_config(fingerprint_seed="profile-a", fingerprint_preset=True)
    second = _launch_config(fingerprint_seed="profile-a", fingerprint_preset=True)
    assert first == second


def test_different_seed_changes_noise_seeds():
    first = _launch_config(fingerprint_seed="profile-a")
    second = _launch_config(fingerprint_seed="profile-b")
    assert first["fonts:spacing_seed"] != second["fonts:spacing_seed"]
    assert first["audio:seed"] != second["audio:seed"]
    assert first["canvas:seed"] != second["canvas:seed"]


def test_unseeded_launch_still_sets_nonzero_noise_seeds():
    first = _launch_config()
    second = _launch_config()
    for config in (first, second):
        for key in NOISE_SEED_KEYS:
            assert 1 <= config[key] <= 4_294_967_295
    assert tuple(first[key] for key in NOISE_SEED_KEYS) != tuple(
        second[key] for key in NOISE_SEED_KEYS
    )


def test_seeded_browserforge_is_stable_with_concurrent_unseeded_calls():
    expected = from_browserforge(
        generate_fingerprint(os="macos", fingerprint_seed="profile-a"),
        fingerprint_seed="profile-a",
    )

    def seeded_config():
        fingerprint = generate_fingerprint(os="macos", fingerprint_seed="profile-a")
        return from_browserforge(fingerprint, fingerprint_seed="profile-a")

    def unseeded_config():
        fingerprint = generate_fingerprint(os="macos")
        return from_browserforge(fingerprint)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for _ in range(20):
            futures.append(executor.submit(seeded_config))
            futures.append(executor.submit(unseeded_config))

    results = [future.result() for future in futures]
    seeded_results = [result for index, result in enumerate(results) if index % 2 == 0]
    unseeded_results = [result for index, result in enumerate(results) if index % 2 == 1]
    assert seeded_results
    assert unseeded_results
    assert all(result == expected for result in seeded_results)


def main():
    test_same_seed_reuses_synthetic_launch_config()
    test_same_seed_reuses_preset_launch_config()
    test_different_seed_changes_noise_seeds()
    test_unseeded_launch_still_sets_nonzero_noise_seeds()
    test_seeded_browserforge_is_stable_with_concurrent_unseeded_calls()
    print("launch options seed checks passed")


if __name__ == "__main__":
    main()
