"""
Verify a SOCKS5 proxy that requires a username and password works.

SOCKS5 proxies can authenticate every connection with
RFC 1929 username/password, and often put the session's options in the
username (`user+denver+os-linux`). Playwright's client refuses
`proxy={"server": "socks5://...", "username": ...}` outright ("Browser does not
support socks5 proxy authentication"), and Juggler's proxy filter built its
proxy info without credentials, so Firefox offered the proxy no
username/password method at all.

The launchers now take the credentials out of what Playwright sees and hand
them to Juggler, which sends them with the context's SOCKS5 proxy. This guard
runs its own SOCKS5 proxy that requires RFC 1929 authentication and serves a
page on CONNECT.

What PASS means:
    * a launch-level SOCKS5 proxy with the right credentials loads a page, and
      the proxy saw those credentials;
    * per-context SOCKS5 proxies load a page with the right credentials, each
      context's own, and a context with the wrong password loads nothing;
    * a launch with the wrong password loads nothing;
    * the password is on no Camoufox process's command line and in no file of
      the profile.

    python browser/tests/playwright/patches/socks5-proxy-auth.py
"""

import asyncio
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

URL = "http://auth.test/"
PASSWORD = "pw-" + secrets.token_hex(8)
USERS = ("user+denver+os-linux", "user+austin+os-linux", "user+boston+os-linux")


class AuthSocks5Proxy:
    """A SOCKS5 proxy that only accepts RFC 1929 username/password, and for
    CONNECT to port 80 serves a page naming the user it authenticated."""

    def __init__(self) -> None:
        self.accepted = []  # usernames that authenticated
        self.rejected = []  # usernames whose password was wrong
        self.unauthenticated = 0  # greetings that offered no username/password
        self.server = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self.serve, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    def close(self) -> None:
        self.server.close()

    async def serve(self, reader, writer) -> None:
        try:
            await self.handle(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def handle(self, reader, writer) -> None:
        version, count = await reader.readexactly(2)
        methods = await reader.readexactly(count)
        if version != 5 or 2 not in methods:
            self.unauthenticated += 1
            writer.write(b"\x05\xff")
            return
        writer.write(b"\x05\x02")
        _, ulen = await reader.readexactly(2)
        user = (await reader.readexactly(ulen)).decode()
        (plen,) = await reader.readexactly(1)
        password = (await reader.readexactly(plen)).decode()
        if user not in USERS or password != PASSWORD:
            self.rejected.append(user)
            writer.write(b"\x01\x01")
            return
        self.accepted.append(user)
        writer.write(b"\x01\x00")
        _, cmd, _, atyp = await reader.readexactly(4)
        if atyp == 1:
            await reader.readexactly(4)
        elif atyp == 3:
            (n,) = await reader.readexactly(1)
            await reader.readexactly(n)
        else:
            await reader.readexactly(16)
        port = int.from_bytes(await reader.readexactly(2), "big")
        # Only plain HTTP: refusing 443 lets HTTPS-First fall back at once.
        if cmd != 1 or port != 80:
            writer.write(b"\x05\x05\x00\x01" + bytes(6))
            return
        writer.write(b"\x05\x00\x00\x01" + bytes(6))
        while (await reader.readline()) not in (b"\r\n", b""):
            pass
        page = f"<!doctype html><title>{user}</title>".encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                     b"Content-Length: %d\r\n\r\n%s" % (len(page), page))
        await writer.drain()


async def load(context) -> str:
    """The title of the page the context loads through its proxy, or the error."""
    page = await context.new_page()
    try:
        await page.goto(URL, timeout=15000)
        return await page.title()
    except Exception as e:  # noqa: BLE001 - any failure to load is the answer
        return "error: " + str(e).splitlines()[0][:120]
    finally:
        await page.close()


def camoufox_processes(binary: Path):
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if cmdline and cmdline[0] and Path(cmdline[0].decode(errors="replace")).name == binary.name:
            yield cmdline


def leaks(binary: Path) -> list:
    """Where the password shows up: command lines, then profile files."""
    found, profiles = [], set()
    for cmdline in camoufox_processes(binary):
        if any(PASSWORD.encode() in arg for arg in cmdline):
            found.append("command line")
        for flag, value in zip(cmdline, cmdline[1:]):
            if flag == b"-profile":
                profiles.add(Path(value.decode()))
    for profile in profiles:
        for path in profile.rglob("*"):
            try:
                if path.is_file() and PASSWORD.encode() in path.read_bytes():
                    found.append(str(path.relative_to(profile)))
            except OSError:
                pass
    return found + ([] if profiles else ["no profile found to search"])


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    binary = resolve_binary()
    proxy = AuthSocks5Proxy()
    port = await proxy.start()
    server = f"socks5://127.0.0.1:{port}"
    options = dict(headless=True, os="linux", geoip=False, i_know_what_im_doing=True,
                   executable_path=str(binary))

    async def launch(password: str, contexts=()):
        launch_proxy = {"server": server, "username": USERS[0], "password": password}
        try:
            async with AsyncCamoufox(proxy=launch_proxy, **options) as browser:
                results = {"launch": await load(await browser.new_context())}
                for name, user, pw in contexts:
                    context = await browser.new_context(
                        proxy={"server": server, "username": user, "password": pw})
                    results[name] = await load(context)
                results["leaks"] = leaks(binary)
                return results
        except Exception as e:  # noqa: BLE001 - the launch itself refusing is a failure
            return {"launch": "error: " + str(e).splitlines()[0][:160]}

    good = await launch(PASSWORD, [("austin", USERS[1], PASSWORD),
                                   ("boston", USERS[2], PASSWORD),
                                   ("wrong", USERS[1], "nope")])
    accepted_good = list(proxy.accepted)
    bad = await launch("nope")
    proxy.close()

    checks = [
        ("launch-level SOCKS5 proxy with the right credentials loads the page",
         good.get("launch") == USERS[0], good.get("launch")),
        ("per-context SOCKS5 proxies load the page, each with its own credentials",
         good.get("austin") == USERS[1] and good.get("boston") == USERS[2],
         f"austin={good.get('austin')} boston={good.get('boston')}"),
        ("a context with the wrong password loads nothing",
         str(good.get("wrong", "")).startswith("error:") and USERS[1] in proxy.rejected,
         good.get("wrong")),
        ("the proxy saw every request authenticated",
         set(accepted_good) >= set(USERS) and proxy.unauthenticated == 0,
         f"accepted {sorted(set(accepted_good))}, {proxy.unauthenticated} without credentials"),
        ("a launch with the wrong password loads nothing",
         str(bad.get("launch", "")).startswith("error:"), bad.get("launch")),
        ("the password is on no command line and in no profile file",
         good.get("leaks") == [], good.get("leaks")),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
