"""Camoufox Console Local API — FastAPI + SQLite orchestration layer."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .launch import check_proxy_exit, close_handle, mock_launch, real_launch

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]  # backend/
DATA_DIR = Path(os.environ.get("CAMOUFOX_CONSOLE_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "console.db"
PROFILE_ROOT = Path(
    os.environ.get("CAMOUFOX_PROFILE_ROOT", DATA_DIR / "profiles")
)
PROFILE_ROOT.mkdir(parents=True, exist_ok=True)

API_TOKEN = os.environ.get("CAMOUFOX_API_TOKEN", "cf_dev_token_mock_8f3a")
REAL_LAUNCH = os.environ.get("CAMOUFOX_REAL_LAUNCH", "0") in ("1", "true", "True")
CAMOUFOX_VERSION = os.environ.get("CAMOUFOX_VERSION", "152.0.4-beta.28")

app = FastAPI(title="Camoufox Console API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory runtime registry: profile_id -> handle
_runtime: dict[str, dict[str, Any]] = {}
_runtime_lock = threading.Lock()
_starting: set[str] = set()


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              parent_id TEXT
            );
            CREATE TABLE IF NOT EXISTS tags (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              color TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proxies (
              id TEXT PRIMARY KEY,
              alias TEXT NOT NULL,
              protocol TEXT NOT NULL,
              host TEXT NOT NULL,
              port INTEGER NOT NULL,
              username TEXT,
              password TEXT,
              exit_ip TEXT,
              country TEXT,
              latency_ms INTEGER,
              last_checked_at TEXT,
              status TEXT NOT NULL DEFAULT 'unknown'
            );
            CREATE TABLE IF NOT EXISTS profiles (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              platform TEXT,
              note TEXT,
              group_id TEXT,
              tags_json TEXT,
              proxy_id TEXT,
              proxy_label TEXT,
              fingerprint TEXT,
              fingerprint_strategy TEXT,
              os TEXT,
              align_geo INTEGER,
              cookies_json TEXT,
              start_url TEXT,
              headless INTEGER,
              status TEXT,
              last_started_at TEXT,
              deleted_at TEXT,
              pid INTEGER,
              ws_endpoint TEXT,
              profile_path TEXT,
              disk_mb REAL,
              logs_json TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        # Seed if empty
        n = conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
        if n == 0:
            seed(conn)


def seed(conn: sqlite3.Connection) -> None:
    groups = [
        ("grp_main", "主力账号", None),
        ("grp_test", "测试", None),
        ("grp_auto", "自动化", None),
    ]
    conn.executemany(
        "INSERT INTO groups (id, name, parent_id) VALUES (?,?,?)", groups
    )
    tags = [
        ("tag_main", "主力账号", "#0d9488"),
        ("tag_test", "测试实例", "#64748b"),
        ("tag_auto", "自动化", "#4f46e5"),
    ]
    conn.executemany(
        "INSERT INTO tags (id, name, color) VALUES (?,?,?)", tags
    )
    proxies = [
        (
            "px_1",
            "US-SOCKS-01",
            "socks5",
            "192.168.1.20",
            1080,
            None,
            None,
            "104.28.***.**",
            "US",
            86,
            now_stamp(),
            "ok",
        ),
        (
            "px_2",
            "EU-HTTP-03",
            "http",
            "103.45.22.11",
            8080,
            None,
            None,
            "185.12.***.**",
            "DE",
            142,
            now_stamp(),
            "ok",
        ),
    ]
    conn.executemany(
        """INSERT INTO proxies
        (id,alias,protocol,host,port,username,password,exit_ip,country,latency_ms,last_checked_at,status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        proxies,
    )
    pid = "prof_seed01"
    path = str(PROFILE_ROOT / pid)
    conn.execute(
        """INSERT INTO profiles
        (id,name,platform,note,group_id,tags_json,proxy_id,proxy_label,fingerprint,
         fingerprint_strategy,os,align_geo,cookies_json,start_url,headless,status,
         last_started_at,deleted_at,pid,ws_endpoint,profile_path,disk_mb,logs_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pid,
            "示例环境_US",
            "Amazon",
            "",
            "grp_main",
            json.dumps(["主力账号"], ensure_ascii=False),
            "px_1",
            "socks5://192.168.1.***:1080",
            "Win · FF 152 · 1920×1080",
            "auto",
            "windows",
            1,
            "[]",
            "https://www.amazon.com",
            0,
            "idle",
            None,
            None,
            None,
            None,
            path,
            12,
            json.dumps(
                [{"at": now_stamp(), "level": "info", "message": "种子环境已创建"}],
                ensure_ascii=False,
            ),
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("camoufox_version", CAMOUFOX_VERSION),
    )


def row_to_profile(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "platform": r["platform"] or "",
        "note": r["note"] or "",
        "groupId": r["group_id"],
        "tags": json.loads(r["tags_json"] or "[]"),
        "proxyId": r["proxy_id"],
        "proxyLabel": r["proxy_label"],
        "fingerprint": r["fingerprint"] or "",
        "fingerprintStrategy": r["fingerprint_strategy"] or "auto",
        "os": r["os"] or "windows",
        "alignGeoWithProxy": bool(r["align_geo"]),
        "cookiesJson": r["cookies_json"] or "[]",
        "startUrl": r["start_url"] or "",
        "headless": bool(r["headless"]),
        "status": r["status"],
        "lastStartedAt": r["last_started_at"],
        "deletedAt": r["deleted_at"],
        "pid": r["pid"],
        "wsEndpoint": r["ws_endpoint"],
        "profilePath": r["profile_path"],
        "diskMb": r["disk_mb"] or 0,
        "logs": json.loads(r["logs_json"] or "[]"),
    }


def row_to_proxy(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "alias": r["alias"],
        "protocol": r["protocol"],
        "host": r["host"],
        "port": r["port"],
        "username": r["username"],
        "password": r["password"],
        "exitIp": r["exit_ip"],
        "country": r["country"],
        "latencyMs": r["latency_ms"],
        "lastCheckedAt": r["last_checked_at"],
        "status": r["status"],
    }


def require_token(authorization: Optional[str]) -> None:
    if not authorization:
        return  # allow open local mode for MVP
    token = authorization.removeprefix("Bearer ").strip()
    if token and token != API_TOKEN:
        raise HTTPException(401, "Invalid token")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProfileCreate(BaseModel):
    name: str
    platform: str = ""
    note: str = ""
    groupId: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    proxyId: Optional[str] = None
    proxyLabel: Optional[str] = None
    fingerprintStrategy: str = "auto"
    os: str = "windows"
    alignGeoWithProxy: bool = True
    cookiesJson: str = "[]"
    startUrl: str = ""
    fingerprint: Optional[str] = None
    headless: bool = False


class ProfilePatch(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    note: Optional[str] = None
    groupId: Optional[str] = None
    tags: Optional[list[str]] = None
    proxyId: Optional[str] = None
    proxyLabel: Optional[str] = None
    cookiesJson: Optional[str] = None
    startUrl: Optional[str] = None
    headless: Optional[bool] = None
    status: Optional[str] = None
    diskMb: Optional[float] = None


class ProxyCreate(BaseModel):
    alias: str
    protocol: str = "socks5"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None


class GroupCreate(BaseModel):
    name: str
    parentId: Optional[str] = None


class TagCreate(BaseModel):
    name: str
    color: str = "#0d9488"


# ---------------------------------------------------------------------------
# Runtime / Camoufox launch
# ---------------------------------------------------------------------------


def append_log(conn: sqlite3.Connection, profile_id: str, message: str, level: str = "info") -> None:
    row = conn.execute(
        "SELECT logs_json FROM profiles WHERE id=?", (profile_id,)
    ).fetchone()
    logs = json.loads(row["logs_json"] or "[]")
    logs.append({"at": now_stamp(), "level": level, "message": message})
    conn.execute(
        "UPDATE profiles SET logs_json=? WHERE id=?",
        (json.dumps(logs, ensure_ascii=False), profile_id),
    )


def update_status(
    profile_id: str,
    status: str,
    *,
    pid: Optional[int] = None,
    ws: Optional[str] = None,
    started: bool = False,
) -> None:
    with db() as conn:
        fields = ["status=?"]
        vals: list[Any] = [status]
        if pid is not None or status in ("idle", "error"):
            fields.append("pid=?")
            vals.append(pid)
        if ws is not None or status in ("idle", "error"):
            fields.append("ws_endpoint=?")
            vals.append(ws)
        if started:
            fields.append("last_started_at=?")
            vals.append(now_stamp())
        vals.append(profile_id)
        conn.execute(
            f"UPDATE profiles SET {', '.join(fields)} WHERE id=?", vals
        )
        append_log(conn, profile_id, f"状态 → {status}")


async def _cleanup_dead_handle(profile_id: str) -> None:
    with _runtime_lock:
        handle = _runtime.get(profile_id)
    if not handle or handle.get("mock"):
        return
    browser = handle.get("browser")
    dead = False
    try:
        if browser is None:
            dead = True
        else:
            # Playwright BrowserContext has no reliable is_connected; best-effort pages check
            pages = getattr(browser, "pages", None)
            if pages is not None and len(pages) == 0 and handle.get("started_at", 0) < time.time() - 5:
                # Still may be alive; skip aggressive kill
                pass
    except Exception:
        dead = True
    if dead:
        with _runtime_lock:
            _runtime.pop(profile_id, None)
        await close_handle(handle)
        update_status(profile_id, "error", pid=None, ws=None)
        with db() as conn:
            append_log(conn, profile_id, "检测到浏览器句柄失效", level="error")


async def start_profile_async(profile_id: str) -> dict[str, Any]:
    with _runtime_lock:
        if profile_id in _starting:
            raise HTTPException(409, "Profile is already starting")
        if profile_id in _runtime:
            raise HTTPException(409, "Profile is already running")
        _starting.add(profile_id)

    try:
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE id=?", (profile_id,)
            ).fetchone()
            if not row or row["deleted_at"]:
                raise HTTPException(404, "Profile not found")
            if row["status"] in ("starting", "running", "api"):
                raise HTTPException(409, f"Profile is already {row['status']}")
            profile = row_to_profile(row)
            conn.execute(
                "UPDATE profiles SET status=? WHERE id=?", ("starting", profile_id)
            )
            append_log(conn, profile_id, "正在启动…")

        proxy_row = None
        if profile.get("proxyId"):
            with db() as conn:
                proxy_row = conn.execute(
                    "SELECT * FROM proxies WHERE id=?", (profile["proxyId"],)
                ).fetchone()

        try:
            if REAL_LAUNCH:
                result = await real_launch(profile, proxy_row=proxy_row)
            else:
                result = await mock_launch(profile)
        except HTTPException:
            raise
        except ValueError as e:
            update_status(profile_id, "error", pid=None, ws=None)
            with db() as conn:
                append_log(conn, profile_id, str(e), level="error")
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            update_status(profile_id, "error", pid=None, ws=None)
            with db() as conn:
                append_log(conn, profile_id, f"启动失败: {e}", level="error")
            raise HTTPException(500, f"Launch failed: {e}") from e

        with _runtime_lock:
            _runtime[profile_id] = {
                "playwright": result.get("playwright"),
                "browser": result.get("browser"),
                "mock": bool(result.get("mock")),
                "started_at": time.time(),
            }

        update_status(
            profile_id,
            "running",
            pid=result.get("pid"),
            ws=result.get("wsEndpoint"),
            started=True,
        )
        with db() as conn:
            msg = "浏览器启动成功" + (" (Camoufox)" if REAL_LAUNCH else " (mock)")
            if result.get("templateFallback"):
                msg += "；指纹模板策略暂以 preset 采样代替"
            append_log(conn, profile_id, msg)
        return get_profile(profile_id)
    finally:
        with _runtime_lock:
            _starting.discard(profile_id)


async def stop_profile_async(profile_id: str) -> dict[str, Any]:
    with _runtime_lock:
        handle = _runtime.pop(profile_id, None)
        _starting.discard(profile_id)
    await close_handle(handle)
    update_status(profile_id, "idle", pid=None, ws=None)
    with db() as conn:
        append_log(conn, profile_id, "已停止")
    return get_profile(profile_id)


def get_profile(profile_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Profile not found")
    return row_to_profile(row)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    # Clear stale runtime flags after process restart
    with db() as conn:
        conn.execute(
            """UPDATE profiles SET status='idle', pid=NULL, ws_endpoint=NULL
               WHERE status IN ('starting','running','api') AND deleted_at IS NULL"""
        )


@app.get("/api/v1/health")
def health():
    return {
        "ok": True,
        "realLaunch": REAL_LAUNCH,
        "version": CAMOUFOX_VERSION,
        "tokenRequired": False,
    }


@app.get("/api/v1/settings")
def get_settings(authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    data = {r["key"]: r["value"] for r in rows}
    return {
        "apiPort": 50325,
        "apiToken": API_TOKEN,
        "apiRunning": True,
        "camoufoxVersion": data.get("camoufox_version", CAMOUFOX_VERSION),
        "profileRoot": str(PROFILE_ROOT),
        "theme": "light",
        "defaultHeadless": False,
        "realLaunch": REAL_LAUNCH,
    }


@app.get("/api/v1/profiles")
def list_profiles(
    include_deleted: bool = False,
    authorization: Optional[str] = Header(None),
):
    require_token(authorization)
    with db() as conn:
        if include_deleted:
            rows = conn.execute("SELECT * FROM profiles ORDER BY name").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM profiles WHERE deleted_at IS NULL ORDER BY name"
            ).fetchall()
    return [row_to_profile(r) for r in rows]


@app.get("/api/v1/profiles/{profile_id}")
def get_profile_route(profile_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    return get_profile(profile_id)


@app.post("/api/v1/profiles")
def create_profile(body: ProfileCreate, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    pid = uid("prof")
    path = str(PROFILE_ROOT / pid)
    Path(path).mkdir(parents=True, exist_ok=True)
    os_label = {"windows": "Win", "macos": "Mac", "linux": "Linux"}.get(body.os, "Win")
    fp = body.fingerprint or f"{os_label} · FF 152 · 1920×1080"
    with db() as conn:
        conn.execute(
            """INSERT INTO profiles
            (id,name,platform,note,group_id,tags_json,proxy_id,proxy_label,fingerprint,
             fingerprint_strategy,os,align_geo,cookies_json,start_url,headless,status,
             last_started_at,deleted_at,pid,ws_endpoint,profile_path,disk_mb,logs_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pid,
                body.name,
                body.platform,
                body.note,
                body.groupId,
                json.dumps(body.tags, ensure_ascii=False),
                body.proxyId,
                body.proxyLabel,
                fp,
                body.fingerprintStrategy,
                body.os,
                1 if body.alignGeoWithProxy else 0,
                body.cookiesJson,
                body.startUrl,
                1 if body.headless else 0,
                "idle",
                None,
                None,
                None,
                None,
                path,
                12,
                json.dumps(
                    [{"at": now_stamp(), "level": "info", "message": "环境已创建"}],
                    ensure_ascii=False,
                ),
            ),
        )
    return get_profile(pid)


@app.patch("/api/v1/profiles/{profile_id}")
def patch_profile(
    profile_id: str, body: ProfilePatch, authorization: Optional[str] = Header(None)
):
    require_token(authorization)
    mapping = {
        "name": "name",
        "platform": "platform",
        "note": "note",
        "groupId": "group_id",
        "proxyId": "proxy_id",
        "proxyLabel": "proxy_label",
        "cookiesJson": "cookies_json",
        "startUrl": "start_url",
        "status": "status",
        "diskMb": "disk_mb",
    }
    data = body.model_dump(exclude_unset=True)
    if not data:
        return get_profile(profile_id)
    fields = []
    vals: list[Any] = []
    for k, v in data.items():
        if k == "tags":
            fields.append("tags_json=?")
            vals.append(json.dumps(v, ensure_ascii=False))
        elif k == "headless":
            fields.append("headless=?")
            vals.append(1 if v else 0)
        elif k in mapping:
            fields.append(f"{mapping[k]}=?")
            vals.append(v)
    vals.append(profile_id)
    with db() as conn:
        conn.execute(
            f"UPDATE profiles SET {', '.join(fields)} WHERE id=?", vals
        )
    return get_profile(profile_id)


@app.post("/api/v1/profiles/{profile_id}/start")
async def start_profile_route(
    profile_id: str, authorization: Optional[str] = Header(None)
):
    require_token(authorization)
    return await start_profile_async(profile_id)


@app.post("/api/v1/profiles/{profile_id}/stop")
async def stop_profile_route(
    profile_id: str, authorization: Optional[str] = Header(None)
):
    require_token(authorization)
    return await stop_profile_async(profile_id)


@app.post("/api/v1/profiles/{profile_id}/trash")
async def trash_profile(profile_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with _runtime_lock:
        if profile_id in _runtime:
            await stop_profile_async(profile_id)
    with db() as conn:
        conn.execute(
            "UPDATE profiles SET deleted_at=?, status='idle', pid=NULL, ws_endpoint=NULL WHERE id=?",
            (now_stamp(), profile_id),
        )
    return get_profile(profile_id)


@app.post("/api/v1/profiles/{profile_id}/restore")
def restore_profile(profile_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        conn.execute(
            "UPDATE profiles SET deleted_at=NULL WHERE id=?", (profile_id,)
        )
    return get_profile(profile_id)


@app.delete("/api/v1/profiles/{profile_id}")
def delete_profile(profile_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        conn.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    return {"ok": True}


@app.get("/api/v1/runtime")
def list_runtime(authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE deleted_at IS NULL AND status IN ('running','api','starting')"
        ).fetchall()
    return [row_to_profile(r) for r in rows]


@app.get("/api/v1/proxies")
def list_proxies(authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        rows = conn.execute("SELECT * FROM proxies ORDER BY alias").fetchall()
    return [row_to_proxy(r) for r in rows]


@app.post("/api/v1/proxies")
def create_proxy(body: ProxyCreate, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    pid = uid("px")
    with db() as conn:
        conn.execute(
            """INSERT INTO proxies
            (id,alias,protocol,host,port,username,password,status)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                pid,
                body.alias,
                body.protocol,
                body.host,
                body.port,
                body.username,
                body.password,
                "unknown",
            ),
        )
    return get_proxy(pid)


def get_proxy(proxy_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM proxies WHERE id=?", (proxy_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Proxy not found")
    return row_to_proxy(row)


@app.post("/api/v1/proxies/{proxy_id}/check")
def check_proxy(proxy_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM proxies WHERE id=?", (proxy_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Proxy not found")
    result = check_proxy_exit(
        row["protocol"],
        row["host"],
        row["port"],
        row["username"],
        row["password"],
    )
    with db() as conn:
        conn.execute(
            """UPDATE proxies SET status=?, latency_ms=?, exit_ip=?, country=?, last_checked_at=?
               WHERE id=?""",
            (
                result["status"],
                result.get("latencyMs"),
                result.get("exitIp"),
                result.get("country"),
                now_stamp(),
                proxy_id,
            ),
        )
    return get_proxy(proxy_id)


@app.delete("/api/v1/proxies/{proxy_id}")
def delete_proxy(proxy_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        conn.execute("DELETE FROM proxies WHERE id=?", (proxy_id,))
        conn.execute(
            "UPDATE profiles SET proxy_id=NULL, proxy_label=NULL WHERE proxy_id=?",
            (proxy_id,),
        )
    return {"ok": True}


@app.get("/api/v1/groups")
def list_groups(authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        rows = conn.execute("SELECT * FROM groups").fetchall()
    return [
        {"id": r["id"], "name": r["name"], "parentId": r["parent_id"]} for r in rows
    ]


@app.post("/api/v1/groups")
def create_group(body: GroupCreate, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    gid = uid("grp")
    with db() as conn:
        conn.execute(
            "INSERT INTO groups (id, name, parent_id) VALUES (?,?,?)",
            (gid, body.name, body.parentId),
        )
    return {"id": gid, "name": body.name, "parentId": body.parentId}


class GroupPatch(BaseModel):
    name: str


@app.patch("/api/v1/groups/{group_id}")
def patch_group(
    group_id: str, body: GroupPatch, authorization: Optional[str] = Header(None)
):
    require_token(authorization)
    with db() as conn:
        row = conn.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Group not found")
        conn.execute(
            "UPDATE groups SET name=? WHERE id=?", (body.name, group_id)
        )
    return {"id": group_id, "name": body.name, "parentId": row["parent_id"]}


@app.delete("/api/v1/groups/{group_id}")
def delete_group(group_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
        conn.execute(
            "UPDATE profiles SET group_id=NULL WHERE group_id=?", (group_id,)
        )
    return {"ok": True}


@app.get("/api/v1/tags")
def list_tags(authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        rows = conn.execute("SELECT * FROM tags").fetchall()
    return [{"id": r["id"], "name": r["name"], "color": r["color"]} for r in rows]


@app.post("/api/v1/tags")
def create_tag(body: TagCreate, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    tid = uid("tag")
    with db() as conn:
        conn.execute(
            "INSERT INTO tags (id, name, color) VALUES (?,?,?)",
            (tid, body.name, body.color),
        )
    return {"id": tid, "name": body.name, "color": body.color}


@app.delete("/api/v1/tags/{tag_id}")
def delete_tag(tag_id: str, authorization: Optional[str] = Header(None)):
    require_token(authorization)
    with db() as conn:
        tag = conn.execute("SELECT * FROM tags WHERE id=?", (tag_id,)).fetchone()
        if not tag:
            raise HTTPException(404, "Tag not found")
        name = tag["name"]
        conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        rows = conn.execute("SELECT id, tags_json FROM profiles").fetchall()
        for r in rows:
            tags = json.loads(r["tags_json"] or "[]")
            if name in tags:
                tags = [t for t in tags if t != name]
                conn.execute(
                    "UPDATE profiles SET tags_json=? WHERE id=?",
                    (json.dumps(tags, ensure_ascii=False), r["id"]),
                )
    return {"ok": True}


@app.get("/api/v1/browser/versions")
def browser_versions(authorization: Optional[str] = Header(None)):
    require_token(authorization)
    active = CAMOUFOX_VERSION
    return {
        "active": active,
        "installed": [active],
        "remote": [
            {"version": "152.0.4-beta.28", "channel": "beta"},
            {"version": "150.0.2-beta.25", "channel": "beta"},
            {"version": "135.0.1-beta.23", "channel": "beta"},
        ],
        "note": "全局 Active；真实切换可对接 camoufox multiversion / gui",
    }
