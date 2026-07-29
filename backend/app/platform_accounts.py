"""Platform accounts: encrypt secrets, TOTP, presets, stage console-home addon."""

from __future__ import annotations

import json
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]  # backend/
DATA_DIR = Path(
    __import__("os").environ.get("CAMOUFOX_CONSOLE_DATA", ROOT / "data")
)
SECRETS_KEY_PATH = DATA_DIR / ".secrets_key"
EXTENSION_SRC = ROOT / "extensions" / "console-home"

PLATFORM_PRESETS: list[dict[str, str]] = [
    {"label": "Gmail", "url": "https://mail.google.com/"},
    {"label": "Gemini", "url": "https://gemini.google.com/"},
    {"label": "PayPal", "url": "https://www.paypal.com/"},
    {"label": "Stripe", "url": "https://stripe.com/"},
    {"label": "Amazon", "url": "https://www.amazon.com/"},
    {"label": "Facebook", "url": "https://www.facebook.com/"},
    {"label": "Yandex", "url": "https://yandex.com/"},
    {"label": "Mail.com", "url": "https://www.mail.com/"},
    {"label": "PingPong", "url": "https://www.pingpongx.com/"},
    {"label": "Payssion", "url": "https://www.payssion.com/"},
]

# profile_id -> {token, expires_at}
_home_sessions: dict[str, dict[str, Any]] = {}


def _fernet() -> Fernet:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRETS_KEY_PATH.exists():
        key = SECRETS_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        SECRETS_KEY_PATH.write_bytes(key)
    return Fernet(key)


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    if plain is None or plain == "":
        return None
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def totp_now(secret: Optional[str]) -> tuple[Optional[str], int]:
    """Return (code, seconds_remaining)."""
    if not secret or not str(secret).strip():
        return None, 0
    try:
        import pyotp

        cleaned = "".join(str(secret).split()).replace(" ", "")
        totp = pyotp.TOTP(cleaned)
        code = totp.now()
        remaining = int(totp.interval - (time.time() % totp.interval))
        return code, remaining
    except Exception:
        return None, 0


def is_gemini_eligible(platform_url: Optional[str]) -> bool:
    if not platform_url:
        return False
    try:
        from urllib.parse import urlparse

        host = (urlparse(platform_url).hostname or "").lower()
    except Exception:
        host = ""
    return host == "gemini.google.com" or host.endswith(".gemini.google.com") or (
        "gemini.google.com" in str(platform_url).lower()
    )


def row_to_account(r: Any, *, reveal: bool = False) -> dict[str, Any]:
    pwd_enc = r["password_enc"]
    totp_enc = r["totp_secret_enc"]
    has_password = bool(pwd_enc)
    has_totp = bool(totp_enc)
    keys = set(r.keys()) if hasattr(r, "keys") else set()
    auto_login = True
    if "auto_login" in keys:
        auto_login = bool(r["auto_login"]) if r["auto_login"] is not None else True
    url = r["platform_url"] or ""
    out: dict[str, Any] = {
        "id": r["id"],
        "profileId": r["profile_id"],
        "platformUrl": url,
        "platformLabel": r["platform_label"] or "",
        "username": r["username"] or "",
        "hasPassword": has_password,
        "hasTotp": has_totp,
        "isActive": bool(r["is_active"]),
        "autoLogin": auto_login,
        "autoLoginEligible": is_gemini_eligible(url),
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }
    if reveal:
        out["password"] = decrypt_secret(pwd_enc) or ""
        out["totpSecret"] = decrypt_secret(totp_enc) or ""
        code, rem = totp_now(out["totpSecret"])
        out["totpCode"] = code
        out["totpRemaining"] = rem
    else:
        out["password"] = None
        out["totpSecret"] = None
        out["totpCode"] = None
        out["totpRemaining"] = 0
    return out


def issue_home_session(profile_id: str, ttl_sec: int = 3600 * 12) -> str:
    token = secrets.token_urlsafe(24)
    _home_sessions[profile_id] = {
        "token": token,
        "expires_at": time.time() + ttl_sec,
    }
    return token


def verify_home_session(profile_id: str, token: Optional[str]) -> bool:
    if not token:
        return False
    sess = _home_sessions.get(profile_id)
    if not sess:
        return False
    if time.time() > float(sess["expires_at"]):
        _home_sessions.pop(profile_id, None)
        return False
    return secrets.compare_digest(str(sess["token"]), str(token))


def clear_home_session(profile_id: str) -> None:
    _home_sessions.pop(profile_id, None)


def stage_console_home_addon(
    profile_path: str | Path,
    *,
    profile_id: str,
    api_base: str,
    session_token: str,
) -> Optional[Path]:
    """Copy extension into profile dir and bake bootstrap.js. Returns addon path or None."""
    src = EXTENSION_SRC
    if not (src / "manifest.json").is_file():
        return None
    dest = Path(profile_path) / ".console-home-addon"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)
    bootstrap = {
        "profileId": profile_id,
        "apiBase": api_base.rstrip("/"),
        "sessionToken": session_token,
    }
    (dest / "bootstrap.js").write_text(
        "window.CAMOUFOX_CONSOLE_BOOTSTRAP = "
        + json.dumps(bootstrap, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )
    return dest
