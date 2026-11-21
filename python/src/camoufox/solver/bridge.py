"""Thin subprocess bridge to a `challenge` (cfsolve) binary.

The CLI surface mirrored here is the one cfsolve's own `src/bin/challenge/cli.rs`
documents:

    challenge --page <page-url> <output-directory> --solve --fingerprint <fp.json>
    challenge --page <page-url> <output-directory> --solve --fingerprint <fp.json> \
              --sitekey <k> [--action <a>] [--cdata <c>] [--blank-page] \
              [--proxy <url>]

On success a solve prints either the widget token on stdout, or (once a challenge
page cleared) the single line `cf_clearance=<value>`. The output directory must be
new or empty, so each solve gets its own temporary directory.

`--blank-page` requires both `--solve` and `--sitekey`: a solve renders the
widget it names, and there is no container to match on a blank page.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

__all__ = ["CFSolveBridge", "CFSolveError", "SolveResult", "proxy_to_url"]


class CFSolveError(RuntimeError):
    """The challenge binary was missing, failed, or printed nothing usable."""


@dataclass
class SolveResult:
    # "clearance" when stdout carried `cf_clearance=<value>`, otherwise "token"
    # for a widget token. `raw` keeps the successful stdout line for diagnostics.
    kind: str
    value: str
    raw: str = ""
    stderr: str = ""


def proxy_to_url(proxy):
    """Normalise a proxy into the URL form the binary's `--proxy` accepts.

    Accepts a URL string, or a Playwright-style dict
    ``{"server": ..., "username": ..., "password": ...}``. Credentials go into
    the URL, which is the only form the CLI documents:
    ``socks5h://user:password@host:port``.
    """
    if not proxy:
        return None
    if isinstance(proxy, str):
        return proxy

    server = str(proxy.get("server", ""))
    if not server:
        raise CFSolveError("proxy dict has no 'server'")
    if "://" not in server:
        server = "http://" + server

    username = proxy.get("username")
    if username is None:
        return server

    parts = urlsplit(server)
    auth = quote(str(username), safe="")
    password = proxy.get("password")
    if password is not None:
        auth += ":" + quote(str(password), safe="")

    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{auth}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class CFSolveBridge:
    """Runs one solve per call. Safe to reuse; each call gets a fresh directory."""

    def __init__(self, binary, profile, proxy=None, timeout=180, verbose=False):
        self.binary = str(Path(binary).expanduser().resolve())
        self.profile = str(Path(profile).expanduser().resolve())
        self.proxy = proxy_to_url(proxy)
        self.timeout = int(timeout)
        self.verbose = bool(verbose)

        if not Path(self.binary).is_file():
            raise CFSolveError(f"cfsolve binary not found: {self.binary}")
        if not Path(self.profile).is_file():
            raise CFSolveError(f"cfsolve profile not found: {self.profile}")

    def build_command(self, url, directory, sitekey=None, action=None, cdata=None, blank_page=False):
        cmd = [
            self.binary,
            "--page", url, str(directory),
            "--solve",
            "--fingerprint", self.profile,
        ]
        if sitekey:
            cmd += ["--sitekey", sitekey]
        # --action and --cdata only mean something next to --sitekey.
        if sitekey and action:
            cmd += ["--action", action]
        if sitekey and cdata:
            cmd += ["--cdata", cdata]
        if blank_page:
            # cli.rs: "--blank-page requires --solve and --sitekey: a solve
            # renders the widget it names".
            if not sitekey:
                raise CFSolveError("blank_page=True requires a sitekey")
            cmd += ["--blank-page"]
        if self.proxy:
            cmd += ["--proxy", self.proxy]
        return cmd

    def solve(self, url, sitekey=None, action=None, cdata=None, blank_page=False):
        workdir = tempfile.mkdtemp(prefix="cfsolve-")
        try:
            cmd = self.build_command(url, workdir, sitekey, action, cdata, blank_page)
            if self.verbose:
                print("[cfsolve]", shlex.join(cmd))
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                raise CFSolveError(f"cfsolve timed out after {self.timeout}s") from exc

            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip()
                raise CFSolveError(detail[-4000:] or f"cfsolve exited {proc.returncode}")

            lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
            for line in reversed(lines):
                if line.startswith("cf_clearance="):
                    return SolveResult(
                        "clearance", line.split("=", 1)[1].strip(), line, proc.stderr or ""
                    )
            if not lines:
                raise CFSolveError("cfsolve produced no stdout")
            return SolveResult("token", lines[-1], lines[-1], proc.stderr or "")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
