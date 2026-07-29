"""Fingerprint template helpers (sample / serialize / lock resolve)."""

from __future__ import annotations

import json
from typing import Any, Optional

from .launch import _ensure_camoufox_path


def row_to_template(r: Any) -> dict[str, Any]:
    cfg = r["config_json"]
    has_config = bool(cfg and str(cfg).strip() not in ("", "{}", "null"))
    return {
        "id": r["id"],
        "name": r["name"],
        "kind": r["kind"],
        "os": r["os"] or "windows",
        "alignGeo": bool(r["align_geo"]),
        "webrtc": r["webrtc"] or "follow",
        "usePreset": bool(r["use_preset"]),
        "configJson": cfg,
        "hasConfig": has_config,
        "isDefault": bool(r["is_default"]),
        "createdAt": r["created_at"],
    }


def sample_fingerprint_config(*, os_name: str, use_preset: bool) -> dict[str, Any]:
    """Generate a camoucfg-style dict once for template baking."""
    _ensure_camoufox_path()
    from camoufox.fingerprints import (
        from_browserforge,
        from_preset,
        generate_fingerprint,
        get_random_preset,
    )

    os_key = {"windows": "windows", "macos": "macos", "linux": "linux"}.get(
        (os_name or "windows").lower(), "windows"
    )
    if use_preset:
        preset = get_random_preset(os=os_key)
        if preset:
            return from_preset(preset)
        # fall through to generate if no preset pack
    fp = generate_fingerprint(os=os_key)
    return from_browserforge(fp)


def dumps_config(config: dict[str, Any]) -> str:
    return json.dumps(config, ensure_ascii=False)


def parse_config_json(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data else None


def fingerprint_summary_from_config(config: dict[str, Any], os_name: str = "windows") -> str:
    """Human-readable summary from locked camoucfg."""
    os_label = {"windows": "Win", "macos": "Mac", "linux": "Linux"}.get(
        (os_name or "windows").lower(), "Win"
    )
    ua = str(config.get("navigator.userAgent") or "")
    ff = "?"
    if "Firefox/" in ua:
        try:
            ff = ua.split("Firefox/")[1].split()[0].split(".")[0]
        except Exception:
            ff = "?"
    w = config.get("screen.width") or config.get("window.outerWidth") or "?"
    h = config.get("screen.height") or config.get("window.outerHeight") or "?"
    return f"{os_label} · FF {ff} · {w}×{h}"


def resolve_locked_fingerprint(
    profile: dict[str, Any],
    template_row: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], Optional[dict[str, Any]], bool, bool]:
    """Resolve launch fingerprint kwargs with lock-on-first-use.

    Returns:
      (launch_kwargs, config_to_persist_or_None, used_existing_lock, template_fallback)
    """
    locked = parse_config_json(profile.get("fingerprintConfigJson"))
    strategy = (profile.get("fingerprintStrategy") or "auto").lower()
    os_name = profile.get("os") or "windows"
    block_webrtc = False
    if template_row and (template_row.get("webrtc") or "follow") == "disable":
        block_webrtc = True
    if template_row:
        tos = (template_row.get("os") or "").lower()
        if tos in ("windows", "macos", "linux"):
            os_name = tos

    if locked:
        kw: dict[str, Any] = {"config": locked}
        if block_webrtc:
            kw["block_webrtc"] = True
        return kw, None, True, False

    template_fallback = False
    cfg: Optional[dict[str, Any]] = None

    if strategy == "template" and template_row:
        cfg = parse_config_json(
            template_row.get("configJson") or template_row.get("config_json")
        )
        if not cfg:
            use_preset = bool(
                template_row.get("usePreset") or template_row.get("use_preset")
            )
            cfg = sample_fingerprint_config(os_name=os_name, use_preset=use_preset)
            if not (
                template_row.get("configJson") or template_row.get("config_json")
            ):
                template_fallback = True
    elif strategy == "preset":
        cfg = sample_fingerprint_config(os_name=os_name, use_preset=True)
    elif strategy == "template" and not template_row:
        cfg = sample_fingerprint_config(os_name=os_name, use_preset=True)
        template_fallback = True
    else:
        cfg = sample_fingerprint_config(os_name=os_name, use_preset=False)

    kw = {"config": cfg}
    if block_webrtc:
        kw["block_webrtc"] = True
    return kw, cfg, False, template_fallback
