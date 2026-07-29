"""Camoufox real / mock browser launch helpers."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional


def _ensure_camoufox_path() -> None:
    try:
        import camoufox  # noqa: F401
    except ImportError:
        repo_lib = Path(__file__).resolve().parents[2] / "pythonlib"
        if str(repo_lib) not in sys.path:
            sys.path.insert(0, str(repo_lib))


def parse_cookies(cookies_json: str) -> list[dict[str, Any]]:
    raw = (cookies_json or "[]").strip() or "[]"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Cookie JSON 无效: {e}") from e
    if not isinstance(parsed, list):
        raise ValueError("Cookie 须为 JSON 数组")
    return parsed


def build_proxy_dict(px_row: Any) -> Optional[dict[str, str]]:
    if not px_row:
        return None
    server = f"{px_row['protocol']}://{px_row['host']}:{px_row['port']}"
    proxy: dict[str, str] = {"server": server}
    if px_row["username"]:
        proxy["username"] = px_row["username"]
        proxy["password"] = px_row["password"] or ""
    return proxy


def fingerprint_kwargs(strategy: str) -> dict[str, Any]:
    s = (strategy or "auto").lower()
    if s == "preset":
        return {"fingerprint_preset": True}
    if s == "template":
        # Fixed-template seed not yet persisted; use preset sampling as stand-in.
        return {"fingerprint_preset": True}
    return {}


def extract_pid(context: Any) -> Optional[int]:
    """Best-effort PID from Playwright Browser handle (often missing for persistent)."""
    try:
        browser_obj = getattr(context, "browser", None)
        if browser_obj is None:
            return None
        impl = getattr(browser_obj, "_impl_obj", None)
        proc = None
        if impl is not None:
            proc = getattr(impl, "_process", None)
        if proc is None:
            proc = getattr(browser_obj, "process", None)
        if proc is not None:
            return getattr(proc, "pid", None)
    except Exception:
        return None
    return None


def list_browser_pids() -> set[int]:
    """PIDs of camoufox/firefox processes (Windows tasklist + POSIX fallback)."""
    names = ("camoufox.exe", "camoufox", "firefox.exe", "firefox")
    found: set[int] = set()
    if sys.platform == "win32":
        import subprocess

        for name in ("camoufox.exe", "firefox.exe"):
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                    text=True,
                    errors="ignore",
                    timeout=5,
                )
            except Exception:
                continue
            for line in out.splitlines():
                line = line.strip()
                if not line or line.upper().startswith("INFO:"):
                    continue
                # "camoufox.exe","1234","Console","1","12,345 K"
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 2:
                    try:
                        found.add(int(parts[1]))
                    except ValueError:
                        pass
        return found

    try:
        import subprocess

        out = subprocess.check_output(["ps", "-A", "-o", "pid=,comm="], text=True, errors="ignore")
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            comm = parts[1].strip().lower()
            if any(n in comm for n in names):
                try:
                    found.add(int(parts[0]))
                except ValueError:
                    pass
    except Exception:
        pass
    return found


def pid_from_diff(before: set[int]) -> Optional[int]:
    """Pick a newly appeared browser PID after launch (prefer largest PID as newest)."""
    new = list_browser_pids() - before
    if not new:
        return None
    return max(new)


async def real_launch(
    profile: dict[str, Any],
    *,
    proxy_row: Any = None,
) -> dict[str, Any]:
    """Launch Camoufox persistent context; returns pid/ws and keeps handles for caller."""
    from playwright.async_api import async_playwright

    _ensure_camoufox_path()
    from camoufox.async_api import AsyncNewBrowser
    from camoufox.utils import launch_options

    cookies = parse_cookies(profile.get("cookiesJson") or "[]")
    user_data = profile["profilePath"]
    Path(user_data).mkdir(parents=True, exist_ok=True)

    proxy = build_proxy_dict(proxy_row)
    os_map = {"windows": "windows", "macos": "macos", "linux": "linux"}
    fp_kw = fingerprint_kwargs(profile.get("fingerprintStrategy") or "auto")
    if (profile.get("fingerprintStrategy") or "").lower() == "template":
        # Logged by caller via return flag
        pass

    want_geoip = bool(profile.get("alignGeoWithProxy")) and proxy is not None
    geoip_fallback = False

    def _opts(use_geoip: bool) -> dict[str, Any]:
        o = launch_options(
            os=os_map.get(profile.get("os") or "windows", "windows"),
            headless=bool(profile.get("headless")),
            geoip=use_geoip,
            proxy=proxy,
            humanize=True,
            **fp_kw,
        )
        o["user_data_dir"] = user_data
        return o

    before_pids = list_browser_pids()
    pw = await async_playwright().start()
    try:
        try:
            context = await AsyncNewBrowser(
                pw, persistent_context=True, from_options=_opts(want_geoip)
            )
        except Exception as e:
            # Proxy geoip probe (ipecho etc.) often times out; still launch without geo.
            msg = str(e).lower()
            if want_geoip and ("ip address" in msg or "geoip" in msg or "ipecho" in msg):
                geoip_fallback = True
                context = await AsyncNewBrowser(
                    pw, persistent_context=True, from_options=_opts(False)
                )
            else:
                await pw.stop()
                raise
    except Exception:
        await pw.stop()
        raise

    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception as e:
            await context.close()
            await pw.stop()
            raise ValueError(f"注入 Cookie 失败: {e}") from e

    start_url = (profile.get("startUrl") or "").strip()
    if start_url:
        page = await context.new_page()
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            # Non-fatal: browser is up even if navigation fails
            pass

    pid = extract_pid(context) or pid_from_diff(before_pids)
    return {
        "pid": pid,
        "wsEndpoint": None,
        "playwright": pw,
        "browser": context,
        "templateFallback": (profile.get("fingerprintStrategy") or "").lower() == "template",
        "geoipFallback": geoip_fallback,
    }


async def mock_launch(profile: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.4)
    pid = 10000 + (abs(hash(profile["id"])) % 50000)
    ws = (
        f"ws://127.0.0.1:{9222 + (abs(hash(profile['id'])) % 20)}"
        f"/devtools/browser/{profile['id'][-6:]}"
    )
    return {
        "pid": pid,
        "wsEndpoint": ws,
        "playwright": None,
        "browser": None,
        "mock": True,
    }


async def close_handle(handle: Optional[dict[str, Any]]) -> None:
    if not handle:
        return
    browser = handle.get("browser")
    pw = handle.get("playwright")
    try:
        if browser is not None:
            await browser.close()
    except Exception:
        pass
    try:
        if pw is not None:
            await pw.stop()
    except Exception:
        pass


def check_proxy_exit(
    protocol: str,
    host: str,
    port: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> dict[str, Any]:
    """Probe public IP through proxy; returns status/latency/exitIp."""
    t0 = time.perf_counter()
    server = f"{protocol}://{host}:{port}"
    proxy_str = server
    if username:
        # user:pass@host:port form for requests
        auth = username
        if password:
            auth = f"{username}:{password}"
        proxy_str = f"{protocol}://{auth}@{host}:{port}"

    try:
        _ensure_camoufox_path()
        from camoufox.ip import public_ip

        ip = public_ip(proxy_str)
        latency = int((time.perf_counter() - t0) * 1000)
        return {
            "status": "ok",
            "exitIp": ip,
            "country": None,
            "latencyMs": latency,
        }
    except Exception as e:
        # Fallback: try urllib without camoufox
        try:
            import urllib.request

            proxy_handler = urllib.request.ProxyHandler(
                {"http": proxy_str, "https": proxy_str}
            )
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open("https://api.ipify.org", timeout=8) as resp:
                ip = resp.read().decode().strip()
            latency = int((time.perf_counter() - t0) * 1000)
            return {
                "status": "ok",
                "exitIp": ip,
                "country": None,
                "latencyMs": latency,
            }
        except Exception:
            return {
                "status": "fail",
                "exitIp": None,
                "country": None,
                "latencyMs": None,
                "error": str(e),
            }
