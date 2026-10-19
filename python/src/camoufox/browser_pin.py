"""
The browser build this copy of the library was released with.

Every published camoufox package (PyPI and npm) is stamped at release time with
the one browser release built from the same sources: `browser-pin.json` names
it. By default the library fetches and launches exactly that build, so a
library upgrade can never silently run against a browser whose Juggler, prefs
or patches it was not tested with -- and a new browser release can never be
picked up by an older library.

A user who explicitly chooses something else (`camoufox set official/stable`,
`camoufox set 156.0.1-beta.33`, ...) keeps that choice; launching then warns
that the build differs from the one this library was released with.

A development checkout carries an empty pin (`{}`): nothing is pinned and the
channel logic applies unchanged, because there is no release to pair with yet.
The release workflow writes the real file (ci/release.py stamp).
"""

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import orjson

PIN_FILE = Path(__file__).parent / "browser-pin.json"


@dataclass(frozen=True)
class BrowserPin:
    tag: str
    repo: str
    repo_name: str
    version: str
    build: str

    @property
    def spec(self) -> str:
        """`<firefox version>-<build>`, the form `camoufox set` and the cache use."""
        return f"{self.version}-{self.build}"


def load_pin(path: Optional[Path] = None) -> Optional[BrowserPin]:
    """The stamped pin, or None for an unpinned (development) copy."""
    try:
        data: Dict[str, Any] = orjson.loads((path or PIN_FILE).read_bytes())
    except (FileNotFoundError, orjson.JSONDecodeError):
        return None
    if not data or not data.get("tag"):
        return None
    return BrowserPin(
        tag=data["tag"],
        repo=data["repo"],
        repo_name=data["repo_name"].lower(),
        version=data["version"],
        build=data["build"],
    )


def is_explicit_choice(config: Dict[str, Any]) -> bool:
    """Whether the user chose a channel or a build themselves."""
    return bool(config.get("channel") or config.get("pinned"))


def effective_pin(config: Optional[Dict[str, Any]] = None) -> Optional[BrowserPin]:
    """The package pin, unless the user explicitly chose otherwise."""
    pin = load_pin()
    if pin is None:
        return None
    if config is None:
        from .multiversion import load_config

        config = load_config()
    return None if is_explicit_choice(config) else pin


def matches(pin: BrowserPin, repo_name: str, version: str, build: str) -> bool:
    return (repo_name.lower(), version, build) == (pin.repo_name, pin.version, pin.build)


_warned = False


def warn_if_unpaired(repo_name: str, version: str, build: str) -> None:
    """Warn once when an explicitly chosen build is not the one this library pairs with."""
    global _warned
    pin = load_pin()
    if _warned or pin is None or matches(pin, repo_name, version, build):
        return
    _warned = True
    warnings.warn(
        f"Launching {repo_name.lower()} {version}-{build}, which you selected explicitly. "
        f"This camoufox release was built and tested with {pin.repo_name} {pin.spec} "
        f"({pin.tag}); other builds may not be compatible. "
        "Run `camoufox set --release` to go back to the paired build.",
        RuntimeWarning,
        stacklevel=3,
    )
