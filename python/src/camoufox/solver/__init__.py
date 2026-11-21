"""Opt-in Cloudflare/Turnstile solving for Camoufox, powered by cfsolve.

The binary is external: :mod:`camoufox.solver.bridge` runs it, :mod:`.detect`
decides whether a page is asking for an answer, and :mod:`.autosolve` wires the
two into a browser or context.
"""

from camoufox.solver.autosolve import AutoSolveError, install, solve_page
from camoufox.solver.bridge import CFSolveBridge, CFSolveError, SolveResult
from camoufox.solver.detect import (
    extract_sitekey,
    extract_sitekey_async,
    is_cloudflare_challenge,
    is_cloudflare_challenge_async,
)
from camoufox.solver.profile import default_profile, profile_user_agent

__all__ = [
    "AutoSolveError",
    "CFSolveBridge",
    "CFSolveError",
    "SolveResult",
    "default_profile",
    "extract_sitekey",
    "extract_sitekey_async",
    "install",
    "is_cloudflare_challenge",
    "is_cloudflare_challenge_async",
    "profile_user_agent",
    "solve_page",
]
