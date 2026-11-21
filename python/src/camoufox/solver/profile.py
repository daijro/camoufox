"""Read the User-Agent a cfsolve fingerprint profile presents.

A cfsolve fingerprint file is a JSON document whose ``transport.headers`` map
carries the HTTP headers the session sends. It does not carry
``navigator.userAgent``; the JS-side value is derived by cfsolve itself, so the
header is the value the site actually receives. Keeping the browser's own UA in
step with it is what matters here.

Verified against ``cfsolve/profiles/safari-26-ios.json``:
``transport.headers["User-Agent"]``. A missing field raises an error naming the
file instead of silently shipping a mismatched browser.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

__all__ = ["profile_user_agent", "default_profile"]


def _read(path):
    with open(os.path.expanduser(os.fspath(path)), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _walk(document, keys):
    """Follow a key path through nested dicts; return the str, or None."""
    node = document
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) and node.strip() else None


@lru_cache(maxsize=32)
def _from_path(path):
    document = _read(path)
    # Ordered by where the value has actually lived upstream, keyed exactly.
    for keys in (
        ("transport", "headers", "User-Agent"),
        ("transport", "headers", "user-agent"),
        ("transport", "headers", "UserAgent"),
    ):
        value = _walk(document, keys)
        if value:
            return value
    top = sorted(document) if isinstance(document, dict) else type(document).__name__
    raise ValueError(
        f"could not read the User-Agent header from cfsolve profile {path}; "
        f"top-level keys are {top}"
    )


def profile_user_agent(path):
    """The HTTP User-Agent a cfsolve fingerprint JSON file presents."""
    resolved = os.path.abspath(os.path.expanduser(os.fspath(path)))
    if not os.path.isfile(resolved):
        raise FileNotFoundError(resolved)
    return _from_path(resolved)


def default_profile(repository_root=None):
    """The Safari profile shipped in a cfsolve checkout beside the project.

    ``repository_root`` is the cfsolve clone. When omitted, it is looked for as
    a ``cfsolve`` directory next to the project root, and a missing profile is
    an error rather than a path that could never exist.
    """
    if repository_root is None:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        repository_root = os.path.join(here, "cfsolve")
    candidate = os.path.join(str(repository_root), "profiles", "safari-26-ios.json")
    if not os.path.isfile(candidate):
        raise FileNotFoundError(f"{candidate} does not exist; clone cfsolve or pass its path")
    return candidate
