"""Smoke test: the bridge drives the real built binary and parses its answer.

Read-only and network-touching, but only as far as Cloudflare's public demo
widget. Run with `python3 scripts/solver_smoke.py [url]`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python" / "src"))

from camoufox.solver import CFSolveBridge, default_profile, profile_user_agent  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BINARY = REPO.parent / "cfsolve" / "target" / "release" / "challenge"


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://nowsecure.nl"
    profile = default_profile(REPO.parent / "cfsolve")
    print(f"binary    : {BINARY} ({'ok' if BINARY.is_file() else 'MISSING'})")
    print(f"profile   : {profile}")
    print(f"user-agent: {profile_user_agent(profile)}")
    print(f"target    : {url}\n")

    bridge = CFSolveBridge(BINARY, profile, timeout=120)
    result = bridge.solve(url)
    print(f"kind      : {result.kind}")
    print(f"value     : {result.value[:64]}... ({len(result.value)} chars)")
    assert result.value, "the binary returned an empty answer"
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
