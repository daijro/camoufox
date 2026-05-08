"""
Verify deterministic fingerprint seed derivation helpers.

This script is intentionally stdlib-only so it can run before the full
Camoufox Python package dependencies are installed.

Run directly:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 tests/patches/fingerprint-seed.py

Or with pytest:
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=pythonlib python3 -m pytest --confcutdir=tests/patches tests/patches/fingerprint-seed.py
"""

from camoufox.fingerprint_seed import derive_seed, derive_uint32_seed, deterministic_rng


def assert_raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    except Exception as exc:
        raise AssertionError(f"expected {exc_type.__name__}, got {type(exc).__name__}") from exc
    raise AssertionError(f"expected {exc_type.__name__}")


def test_golden_vectors():
    assert derive_seed("profile-a", "browserforge") == 8050642059126505217
    assert derive_seed(123, "scope") == 17414721184063999779
    assert derive_seed(b"abc", "scope") == 16480259190397790102
    assert derive_seed("profile-a", "uint32", bits=32) == 2711891498
    assert derive_uint32_seed("profile-a", "canvas") == 1519517379


def test_namespace_and_type_boundaries():
    assert derive_seed("profile-a", "browserforge") != derive_seed("profile-a", "webgl")
    assert derive_seed("123", "scope") != derive_seed(123, "scope")
    assert derive_seed(b"\0str:x", "a") != derive_seed("x", "a\0bytes:")


def test_rng_reproducibility():
    first = deterministic_rng("profile-a", "fonts")
    second = deterministic_rng("profile-a", "fonts")
    assert [first.random() for _ in range(5)] == [second.random() for _ in range(5)]


def test_invalid_inputs():
    assert_raises(ValueError, lambda: derive_seed("profile-a", ""))
    assert_raises(TypeError, lambda: derive_seed("profile-a", None))
    assert_raises(ValueError, lambda: derive_seed("profile-a", "scope", bits=0))
    assert_raises(TypeError, lambda: derive_seed("profile-a", "scope", bits=1.5))
    assert_raises(TypeError, lambda: derive_seed("profile-a", "scope", bits=True))
    assert_raises(TypeError, lambda: derive_seed(True, "scope"))


def main():
    test_golden_vectors()
    test_namespace_and_type_boundaries()
    test_rng_reproducibility()
    test_invalid_inputs()
    print("fingerprint seed helper checks passed")


if __name__ == "__main__":
    main()
