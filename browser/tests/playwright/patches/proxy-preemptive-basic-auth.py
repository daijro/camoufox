"""
Verify `proxy:preemptiveBasicAuth` sends Basic credentials with the first
request through an authenticated HTTP proxy.

Juggler hands a proxy its credentials only after the proxy answers 407, and
setting a context proxy empties Firefox's auth cache, so a new context's first
connection to the proxy cost a round trip (#1144). With the option, Juggler puts
Proxy-Authorization on the channel. Firefox copies it into the CONNECT and drops
it from the request sent inside the tunnel.

This guard runs an HTTP proxy that wants Basic for two hosts and Digest for a
third, an HTTPS site behind it, a plain site it is bypassed for, and a second
authenticated proxy: the browser's own proxy for another bypassed host, and a
third context's proxy.

What PASS means:
    * with the option, two contexts load https:// and http:// pages, each with
      its own credentials, also through route.continue() and
      route.continue(headers=...), and the proxy never answers them with 407,
      although one context sets a stale Proxy-Authorization in its extra headers;
    * a Digest challenge still authenticates when the route overrides the
      headers, and the next request sends the cached Digest answer unchallenged,
      also over a stale Proxy-Authorization in the extra headers;
    * no site receives Proxy-Authorization, and the other proxy never receives
      the context proxy's credentials, after route.continue(url=...) moves a
      request off the context proxy; once the other proxy's own credentials are
      cached, such a request is let through with them, unchallenged;
    * request.headers() never shows Proxy-Authorization;
    * a context with the wrong password loads nothing (the preemptive Basic and
      Firefox's one retry are both refused);
    * without the option the proxy still answers 407 first.

    python browser/tests/playwright/patches/proxy-preemptive-basic-auth.py
"""

import asyncio
import base64
import hashlib
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

PASSWORD = "pw-" + secrets.token_hex(8)
USER = "usér+denver"  # non-ASCII: the header must be UTF-8, as Firefox's own Basic is
USER2 = "user+austin"  # a second context on the same proxy address
USER3 = "user+boston"  # the other proxy's
SECURE, PLAIN, DIGEST, OTHER = "secure.test", "plain.test", "digest.test", "other.test"
REALM, NONCE = "guard", secrets.token_hex(16)
BASIC_OK = {"Basic " + base64.b64encode(f"{user}:{PASSWORD}".encode()).decode() for user in (USER, USER2)}
BASIC_OTHER = "Basic " + base64.b64encode(f"{USER3}:{PASSWORD}".encode()).decode()


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def digest_ok(header: str, method: str, target: str, seen: set) -> bool:
    """Whether a Digest answer (qop=auth, MD5) proves USER2's password for this
    request, and is not one already used."""
    if not header.startswith("Digest "):
        return False
    fields = {k: v1 or v2 for k, v1, v2 in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header)}
    uri, use = fields.get("uri", ""), (fields.get("nc"), fields.get("cnonce"))
    if uri not in (target, "/" + target.split("/", 3)[-1]) or use in seen:
        return False
    seen.add(use)
    ha1 = md5(f"{USER2}:{REALM}:{PASSWORD}")
    ha2 = md5(f"{method}:{uri}")
    expected = md5(f"{ha1}:{NONCE}:{use[0]}:{use[1]}:auth:{ha2}")
    return fields.get("username") == USER2 and fields.get("response") == expected


async def read_head(reader):
    """The request line and the headers (lower-case names) of one HTTP request."""
    line = (await reader.readline()).decode("latin-1").strip()
    headers = {}
    while (raw := await reader.readline()) not in (b"\r\n", b""):
        name, _, value = raw.decode("latin-1").partition(":")
        headers[name.strip().lower()] = value.strip()
    return line, headers


def respond(writer, status: str, title: str = "", extra: bytes = b"") -> None:
    body = f"<!doctype html><title>{title}</title>".encode() if title else b""
    writer.write(b"HTTP/1.1 %s\r\n%sContent-Type: text/html\r\nConnection: close\r\n"
                 b"Content-Length: %d\r\n\r\n%s" % (status.encode(), extra, len(body), body))


class Site:
    """Serves one page per connection and counts the requests that carried
    Proxy-Authorization."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.requests = 0
        self.leaked = 0

    async def serve(self, reader, writer) -> None:
        try:
            line, headers = await read_head(reader)
            if line:
                self.requests += 1
                self.leaked += "proxy-authorization" in headers
                respond(writer, "200 OK", self.title)
                await writer.drain()
        except (ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()


class AuthHttpProxy:
    """Wants Basic for SECURE and PLAIN, Digest for DIGEST; tunnels CONNECT to
    SECURE and serves PLAIN and DIGEST itself."""

    def __init__(self, secure_port: int) -> None:
        self.secure_port = secure_port
        self.challenged = []  # (host, "missing" or "wrong")
        self.accepted = []  # (host, user) of every authenticated request
        self.digest_uses = set()  # (nc, cnonce) of every Digest answer accepted
        self.guarded = []  # host + path of requests that arrived with the route's x-guard header

    async def serve(self, reader, writer) -> None:
        try:
            await self.handle(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def handle(self, reader, writer) -> None:
        line, headers = await read_head(reader)
        method, _, target = line.partition(" ")
        target = target.split(" ")[0]
        if method == "CONNECT":
            host = target.split(":")[0]
        elif target.startswith("http://"):
            host = target.split("/")[2].split(":")[0]
        else:
            return  # an empty or unexpected request line: nothing to answer
        # Anything else, and HTTPS-First trying plain.test or digest.test over TLS: refuse at once,
        # so the browser falls back without a challenge.
        if host not in (SECURE, PLAIN, DIGEST) or method == "CONNECT" and host != SECURE:
            respond(writer, "502 Bad Gateway")
            return
        auth = headers.get("proxy-authorization", "")
        if not (digest_ok(auth, method, target, self.digest_uses) if host == DIGEST else auth in BASIC_OK):
            self.challenged.append((host, "wrong" if auth else "missing"))
            scheme = (f'Digest realm="{REALM}", nonce="{NONCE}", qop="auth", algorithm=MD5'
                      if host == DIGEST else f'Basic realm="{REALM}"')
            respond(writer, "407 Proxy Authentication Required", extra=f"Proxy-Authenticate: {scheme}\r\n".encode())
            return
        user = USER2 if host == DIGEST else base64.b64decode(auth[6:]).decode().split(":")[0]
        self.accepted.append((host, user))
        if method != "CONNECT":
            if "x-guard" in headers:
                self.guarded.append(target.split("//", 1)[1])
            respond(writer, "200 OK", host.split(".")[0])
            await writer.drain()
            return
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", self.secure_port)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")

        async def pipe(src, dst):
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except ConnectionError:
                pass
            finally:
                dst.close()

        await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


class OtherProxy:
    """Serves OTHER to USER3's Basic credentials. It answers the first request
    that has them with 407 anyway, so that Firefox caches them for this address."""

    def __init__(self) -> None:
        self.requests = 0
        self.foreign = 0  # requests that carried the first proxy's credentials
        self.challenged = []
        self.forced = False

    async def serve(self, reader, writer) -> None:
        try:
            line, headers = await read_head(reader)
            auth = headers.get("proxy-authorization", "")
            if f"//{OTHER}" not in line:
                respond(writer, "502 Bad Gateway")
            elif auth != BASIC_OTHER or not self.forced:
                self.requests += 1
                self.foreign += auth in BASIC_OK
                self.forced |= auth == BASIC_OTHER
                self.challenged.append("forced" if auth == BASIC_OTHER else "wrong" if auth else "missing")
                respond(writer, "407 Proxy Authentication Required",
                        extra=b'Proxy-Authenticate: Basic realm="other"\r\n')
            else:
                self.requests += 1
                respond(writer, "200 OK", "other")
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()


async def goto(context, url: str) -> str:
    """The title of the page the context loads, or the error."""
    tab = await context.new_page()
    try:
        await tab.goto(url, timeout=15000)
        return await tab.title()
    except Exception as e:  # noqa: BLE001 - any failure to load is the answer
        return "error: " + str(e).splitlines()[0][:120]
    finally:
        await tab.close()


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    binary = resolve_binary()
    with tempfile.TemporaryDirectory() as tmp:
        key, cert = Path(tmp) / "key.pem", Path(tmp) / "cert.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
                        "-out", str(cert), "-days", "1", "-subj", f"/CN={SECURE}"],
                       check=True, capture_output=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)

    secure, direct, other = Site("secure"), Site("direct"), OtherProxy()
    secure_server = await asyncio.start_server(secure.serve, "127.0.0.1", 0, ssl=tls)
    direct_server = await asyncio.start_server(direct.serve, "127.0.0.1", 0)
    other_server = await asyncio.start_server(other.serve, "127.0.0.1", 0)
    direct_port = direct_server.sockets[0].getsockname()[1]
    proxy = AuthHttpProxy(secure_server.sockets[0].getsockname()[1])
    proxy_server = await asyncio.start_server(proxy.serve, "127.0.0.1", 0)
    server = f"http://127.0.0.1:{proxy_server.sockets[0].getsockname()[1]}"
    options = dict(headless=True, os="linux", geoip=False, i_know_what_im_doing=True,
                   executable_path=str(binary))
    # The browser's own proxy, which a host bypassed by the context proxy goes through.
    other_port = other_server.sockets[0].getsockname()[1]
    other_proxy = {"server": f"http://127.0.0.1:{other_port}", "username": USER3, "password": PASSWORD}
    system_proxy = {"network.proxy.type": 1, "network.proxy.http": "127.0.0.1", "network.proxy.http_port": other_port,
                    "network.proxy.ssl": "127.0.0.1", "network.proxy.ssl_port": other_port}

    def context_options(user: str, password: str) -> dict:
        return dict(ignore_https_errors=True,
                    proxy={"server": server, "username": user, "password": password,
                           "bypass": f"127.0.0.1,{OTHER}"})

    def add_guard(route):
        return route.continue_(headers={**route.request.headers, "x-guard": "1"})

    results, shown = {}, []
    stale = {"Proxy-Authorization": "Basic " + base64.b64encode(b"stale:stale").decode()}
    async with AsyncCamoufox(config={"proxy:preemptiveBasicAuth": True}, firefox_user_prefs=system_proxy,
                             **options) as browser:
        first = await browser.new_context(**context_options(USER, PASSWORD))
        second = await browser.new_context(**context_options(USER2, PASSWORD))
        # Created up front: setting a context proxy empties Firefox's auth cache, the other proxy's too.
        third = await browser.new_context(proxy=other_proxy)
        for context in (first, second):
            context.on("request", lambda request: shown.append(request.headers))
        # A client's value is never sent: Juggler's Basic replaces it, and DIRECT drops it.
        await first.set_extra_http_headers(stale)
        await first.route(f"http://{PLAIN}/routed", lambda route: route.continue_())
        await first.route(f"http://{PLAIN}/headers", add_guard)
        await first.route(f"http://{PLAIN}/away",
                          lambda route: route.continue_(url=f"http://127.0.0.1:{direct_port}/away"))
        await first.route(f"http://{PLAIN}/elsewhere", lambda route: route.continue_(url=f"http://{OTHER}/elsewhere"))
        await second.route(f"http://{DIGEST}/headers", add_guard)
        await second.route(f"http://{PLAIN}/elsewhere", lambda route: route.continue_(url=f"http://{OTHER}/elsewhere"))
        for name, url in (("https", f"https://{SECURE}/"), ("https again", f"https://{SECURE}/again"),
                          ("http", f"http://{PLAIN}/"), ("routed", f"http://{PLAIN}/routed"),
                          ("headers", f"http://{PLAIN}/headers"), ("away", f"http://{PLAIN}/away"),
                          ("elsewhere", f"http://{PLAIN}/elsewhere")):
            results[name] = await goto(first, url)
        first_users = {user for _, user in proxy.accepted}
        mark = len(proxy.accepted)
        results["second"] = await goto(second, f"https://{SECURE}/")
        second_users = {user for _, user in proxy.accepted[mark:]}
        basic_challenges = list(proxy.challenged)
        # Two contexts with different credentials on one proxy address make Juggler empty the auth
        # cache before every request. With one left, the Digest answer stays cached, as it would
        # for every context from then on, so the Digest checks come last.
        await first.close()
        results["warm"] = await goto(third, f"http://{OTHER}/warm")
        mark = len(other.challenged)
        results["elsewhere again"] = await goto(second, f"http://{PLAIN}/elsewhere")
        other_warm_challenges = other.challenged[mark:]
        mark = len(proxy.challenged)
        results["digest"] = await goto(second, f"http://{DIGEST}/headers")
        digest_challenges = proxy.challenged[mark:]
        mark = len(proxy.challenged)
        results["digest again"] = await goto(second, f"http://{DIGEST}/again")
        await second.set_extra_http_headers(stale)
        results["digest extra"] = await goto(second, f"http://{DIGEST}/extra")
        warm_challenges = proxy.challenged[mark:]
        mark = len(proxy.challenged)
        wrong = await browser.new_context(**context_options(USER, "nope"))
        # No routes here: its requests are never intercepted, so the event reads the channel's header.
        wrong.on("request", lambda request: shown.append(request.headers))
        results["wrong"] = await goto(wrong, f"https://{SECURE}/")
        wrong_challenges = proxy.challenged[mark:]

    proxy.challenged.clear()
    async with AsyncCamoufox(**options) as browser:
        results["off"] = await goto(await browser.new_context(**context_options(USER, PASSWORD)),
                                    f"https://{SECURE}/")
    off_challenges = list(proxy.challenged)
    for s in (proxy_server, secure_server, direct_server, other_server):
        s.close()

    expected = {"https": "secure", "https again": "secure", "http": "plain", "routed": "plain",
                "headers": "plain", "away": "direct", "second": "secure", "warm": "other", "elsewhere again": "other",
                "digest": "digest", "digest again": "digest", "digest extra": "digest"}
    loaded = {name: results[name] for name in expected}
    checks = [
        ("with the option, every page loads", loaded == expected, loaded),
        ("with the option, the Basic proxy never answers 407", basic_challenges == [], basic_challenges),
        ("each context sends its own credentials", first_users == {USER} and second_users == {USER2},
         f"first {sorted(first_users)}, second {sorted(second_users)}"),
        ("the route's header overrides ran",
         {f"{PLAIN}/headers", f"{DIGEST}/headers"} <= set(proxy.guarded), proxy.guarded),
        ("a Digest challenge authenticates through the header override",
         results["digest"] == "digest" and digest_challenges[:1] == [(DIGEST, "wrong")], digest_challenges),
        ("the cached Digest answer goes out unchallenged, also over a stale extra header",
         warm_challenges == [], warm_challenges),
        ("no site receives Proxy-Authorization",
         secure.requests > 0 and direct.requests > 0 and secure.leaked == 0 and direct.leaked == 0,
         f"secure {secure.leaked}/{secure.requests}, direct {direct.leaked}/{direct.requests}"),
        ("the other proxy never receives the context proxy's credentials",
         other.requests > 0 and other.foreign == 0, f"{other.foreign}/{other.requests}"),
        ("the other proxy's own cached credentials are kept",
         results["elsewhere again"] == "other" and other_warm_challenges == [], other_warm_challenges),
        ("request.headers() never shows Proxy-Authorization",
         shown != [] and not any("proxy-authorization" in headers for headers in shown),
         f"{sum('proxy-authorization' in headers for headers in shown)} of {len(shown)}"),
        ("a context with the wrong password loads nothing",
         results["wrong"].startswith("error:") and (SECURE, "wrong") in wrong_challenges,
         f"{results['wrong']}, {wrong_challenges}"),
        ("without the option the proxy answers 407 first",
         results["off"] == "secure" and (SECURE, "missing") in off_challenges,
         f"{results['off']}, {off_challenges}"),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
