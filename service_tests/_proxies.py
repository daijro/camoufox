import asyncio
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def load_proxies(path: Path) -> list:
    """
    Load proxies from a file. Each line must be: user:pass@domain:port
    Returns a list of Playwright-format proxy dicts.
    """
    if not path.exists():
        print(f"ERROR: Proxies file not found: {path}", file=sys.stderr)
        print("  Create a proxies.txt file with one proxy per line: user:pass@domain:port", file=sys.stderr)
        sys.exit(1)

    proxies = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            creds, hostport = line.rsplit("@", 1)
            user, password = creds.split(":", 1)
            domain, port = hostport.rsplit(":", 1)
        except ValueError:
            print(f"ERROR: proxies.txt line {lineno}: expected user:pass@domain:port, got: {line!r}", file=sys.stderr)
            sys.exit(1)
        proxies.append({"server": f"http://{domain}:{port}", "username": user, "password": password})

    if not proxies:
        print("ERROR: proxies.txt contains no valid proxy entries.", file=sys.stderr)
        sys.exit(1)

    return proxies


async def resolve_proxy_geo(proxy: dict) -> dict:
    """Queries ip-api.com through the proxy for IP, city, country, and timezone."""
    p = urlparse(proxy.get("server", ""))
    user = proxy.get("username", "")
    pwd = proxy.get("password", "")
    proxy_url = f"{p.scheme}://{user}:{pwd}@{p.netloc}" if user and pwd else proxy.get("server", "")

    def _fetch() -> dict:
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        try:
            with opener.open("http://ip-api.com/json?fields=query,city,country,timezone", timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}

    return await asyncio.get_event_loop().run_in_executor(None, _fetch)
