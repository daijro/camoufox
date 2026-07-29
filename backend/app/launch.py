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


# Console launches use light chrome. Binary camoufox.cfg defaults to dark via
# extensions.activeThemeID + ui.systemUsesDarkTheme=1 (the latter alone keeps
# chrome/about:blank dark even when compact-light is selected).
LIGHT_THEME_PREFS: dict[str, Any] = {
    "extensions.activeThemeID": "firefox-compact-light@mozilla.org",
    "ui.systemUsesDarkTheme": 0,
    "userChrome.theme.fully_dark": False,
    # 0=follow browser, 1=light, 2=dark
    "layout.css.prefers-color-scheme.content-override": 1,
}

SESSION_RESTORE_PREFS: dict[str, Any] = {
    "browser.startup.page": 3,  # resume previous session
    "browser.sessionstore.resume_from_crash": True,
    "browser.sessionstore.resume_session_once": False,
    "browser.sessionstore.max_tabs_undo": 10,
    "browser.sessionstore.max_windows_undo": 2,
    "browser.sessionstore.restore_on_demand": False,
    "browser.sessionstore.restore_tabs_lazily": False,
    "browser.sessionstore.resuming_after_os_restart": True,
}

SESSION_NO_RESTORE_PREFS: dict[str, Any] = {
    "browser.startup.page": 1,  # home
    "browser.sessionstore.resume_from_crash": False,
    "browser.sessionstore.max_tabs_undo": 0,
    "browser.sessionstore.max_windows_undo": 0,
}


def _pref_js_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(int(v) if isinstance(v, float) and v == int(v) else v)
    # string
    escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def ensure_profile_prefs(
    user_data_dir: str | Path,
    *,
    restore_session: bool = True,
) -> dict[str, Any]:
    """Write user.js (light theme + session policy) and return prefs for Playwright."""
    path = Path(user_data_dir)
    path.mkdir(parents=True, exist_ok=True)
    prefs = dict(LIGHT_THEME_PREFS)
    if restore_session:
        prefs.update(SESSION_RESTORE_PREFS)
    else:
        prefs.update(SESSION_NO_RESTORE_PREFS)
    lines = [
        "// Camoufox console: chrome theme + session restore policy",
    ]
    for k, v in prefs.items():
        lines.append(f'user_pref("{k}", {_pref_js_value(v)});')
    lines.append("")
    (path / "user.js").write_text("\n".join(lines), encoding="utf-8")
    return prefs


def ensure_light_theme_profile(user_data_dir: str | Path) -> None:
    """Backward-compatible alias."""
    ensure_profile_prefs(user_data_dir, restore_session=True)


def profile_has_cookie_db(user_data_dir: str | Path) -> bool:
    """True if Firefox cookies.sqlite already exists with meaningful size."""
    db = Path(user_data_dir) / "cookies.sqlite"
    try:
        return db.is_file() and db.stat().st_size > 4096
    except OSError:
        return False


def fingerprint_kwargs(
    strategy: str,
    template_row: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], bool]:
    """Legacy helper — prefer resolve_locked_fingerprint via fp_templates."""
    s = (strategy or "auto").lower()
    if s == "preset":
        return {"fingerprint_preset": True}, False
    if s == "template":
        if template_row:
            raw = template_row.get("configJson") or template_row.get("config_json")
            if isinstance(raw, str) and raw.strip():
                try:
                    cfg = json.loads(raw)
                    if isinstance(cfg, dict) and cfg:
                        kw: dict[str, Any] = {"config": cfg}
                        if (template_row.get("webrtc") or "follow") == "disable":
                            kw["block_webrtc"] = True
                        return kw, False
                except json.JSONDecodeError:
                    pass
            if template_row.get("usePreset") or template_row.get("use_preset"):
                return {"fingerprint_preset": True}, False
            return {}, False
        return {"fingerprint_preset": True}, True
    return {}, False


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
    template_row: Optional[dict[str, Any]] = None,
    console_home_addon: Optional[str | Path] = None,
    open_console_home: bool = False,
) -> dict[str, Any]:
    """Launch Camoufox persistent context; returns pid/ws and keeps handles for caller."""
    from playwright.async_api import async_playwright

    _ensure_camoufox_path()
    from camoufox.async_api import AsyncNewBrowser
    from camoufox.utils import launch_options

    from .fp_templates import resolve_locked_fingerprint

    user_data = profile["profilePath"]
    Path(user_data).mkdir(parents=True, exist_ok=True)
    restore_session = profile.get("restoreSession", True)
    if restore_session is None:
        restore_session = True
    firefox_prefs = ensure_profile_prefs(
        user_data, restore_session=bool(restore_session)
    )

    should_inject_cookies = not profile_has_cookie_db(user_data)
    cookies: list[dict[str, Any]] = []
    if should_inject_cookies:
        cookies = parse_cookies(profile.get("cookiesJson") or "[]")

    proxy = build_proxy_dict(proxy_row)
    os_map = {"windows": "windows", "macos": "macos", "linux": "linux"}
    launch_os = profile.get("os") or "windows"
    if template_row:
        tos = (template_row.get("os") or "").lower()
        if tos in os_map:
            launch_os = tos
        if "alignGeo" in template_row or "align_geo" in template_row:
            align = template_row.get("alignGeo")
            if align is None:
                align = bool(template_row.get("align_geo"))
            profile = {**profile, "alignGeoWithProxy": bool(align)}

    fp_kw, config_to_persist, used_lock, template_fallback = resolve_locked_fingerprint(
        profile, template_row
    )

    want_geoip = bool(profile.get("alignGeoWithProxy")) and proxy is not None
    geoip_fallback = False
    addon_paths: list[str] = []
    if console_home_addon:
        addon_paths.append(str(console_home_addon))

    def _opts(use_geoip: bool) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "os": os_map.get(launch_os, "windows"),
            "headless": bool(profile.get("headless")),
            "geoip": use_geoip,
            "proxy": proxy,
            "humanize": True,
            "firefox_user_prefs": dict(firefox_prefs),
            **fp_kw,
        }
        if addon_paths:
            kw["addons"] = list(addon_paths)
        o = launch_options(**kw)
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

    cookies_injected = False
    if cookies:
        try:
            await context.add_cookies(cookies)
            cookies_injected = True
        except Exception as e:
            await context.close()
            await pw.stop()
            raise ValueError(f"注入 Cookie 失败: {e}") from e

    # With session restore, do not force-navigate; only goto startUrl when restore off
    # and Console Home is not managing first paint.
    start_url = (profile.get("startUrl") or "").strip()
    if start_url and not restore_session and not open_console_home:
        page = await context.new_page()
        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            pass

    pid = extract_pid(context) or pid_from_diff(before_pids)
    return {
        "pid": pid,
        "wsEndpoint": None,
        "playwright": pw,
        "browser": context,
        "templateFallback": template_fallback,
        "geoipFallback": geoip_fallback,
        "consoleHome": bool(console_home_addon),
        "configToPersist": config_to_persist,
        "usedFingerprintLock": used_lock,
        "cookiesInjected": cookies_injected,
        "cookiesSkipped": not should_inject_cookies,
    }


async def mock_launch(profile: dict[str, Any]) -> dict[str, Any]:
    await asyncio.sleep(0.4)
    from .fp_templates import resolve_locked_fingerprint

    _kw, config_to_persist, used_lock, template_fallback = resolve_locked_fingerprint(
        profile, None
    )
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
        "configToPersist": config_to_persist,
        "usedFingerprintLock": used_lock,
        "templateFallback": template_fallback,
        "cookiesInjected": False,
        "cookiesSkipped": True,
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
