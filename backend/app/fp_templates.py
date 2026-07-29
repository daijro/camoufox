"""Fingerprint template helpers (sample / serialize)."""

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
