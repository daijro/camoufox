r"""
Verify network:ipv4Only makes the browser behave as on an IPv4-only network.

When the host's IPv6 address geolocates elsewhere than the identity, the
launcher sets network:ipv4Only. network.dns.disableIPv6, used before, only
stopped AAAA lookups: a URL with an IPv6 literal still connected, and WebRTC
still gathered IPv6 candidates, so a page could read the host's IPv6 address,
and could tell the browser apart from one on a real IPv4-only network, where
neither works.

The guard runs in its own network namespace (unshare -rnm), on a dummy
interface with 10.77.0.1 and fd77::1 and default routes for both families, and
its own /etc/hosts naming v6only.test (fd77::1) and dual.test (both). It brings
its own resolver too: one on loopback with nothing listening, so a name the
hosts file lacks fails at once, as on a network whose DNS answers. The host's
resolver may be unreachable from the namespace, and every lookup then waits
out its timeouts; the guard runs as on such a host to prove it never does. A
dual-stack HTTP server answers with the family each request arrived on. With
the key off, every IPv6 path must work, or the check would be vacuous. With it
on, the IPv6 literal and v6only.test must fail at once, as an unreachable
network does, dual.test must arrive over IPv4, and WebRTC must offer no IPv6
host candidate.

    python browser/tests/playwright/patches/ipv4-only-network.py
"""

import asyncio
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

INSIDE = "CAMOUFOX_IPV4_ONLY_GUARD_NETNS"
V4, V6 = "10.77.0.1", "fd77::1"
FILES = {
    "hosts": f"127.0.0.1 localhost\n::1 localhost\n{V4} dual.test\n{V6} dual.test\n{V6} v6only.test\n",
    "nsswitch.conf": "hosts: files dns\n",
    "resolv.conf": "nameserver 127.0.0.1\n",
    # 192.0.2.0/24 is TEST-NET-1: the dummy interface swallows what is sent there.
    "unreachable-resolv.conf": "nameserver 192.0.2.53\n",
}
# A host whose /etc/resolv.conf names a resolver the namespace cannot reach, as
# some GitHub runners' does: there v6only.test waited out two lookups' timeouts
# (#931).
UNREACHABLE_RESOLVER = """set -e
mount --bind "$NET_FILES/unreachable-resolv.conf" /etc/resolv.conf
exec "$@"
"""
SETUP = f"""set -e
ip link set lo up
ip link add d0 type dummy
ip link set d0 up
ip addr add {V4}/24 dev d0
ip addr add {V6}/64 dev d0 nodad
ip route add default dev d0
ip -6 route add default dev d0
for file in hosts nsswitch.conf resolv.conf; do
  mount --bind "$NET_FILES/$file" /etc/$file
done
exec "$@"
"""

PROBE = """async ([port]) => {
  const get = async url => {
    const start = performance.now();
    try {
      const body = await (await fetch(url, {cache: 'no-store'})).json();
      return {family: body.family, ms: performance.now() - start};
    } catch (e) {
      return {error: String(e), ms: performance.now() - start};
    }
  };
  const pc = new RTCPeerConnection();
  const hosts = [];
  const done = new Promise(resolve => {
    setTimeout(resolve, 10000);
    pc.onicecandidate = e => {
      if (!e.candidate) return resolve();
      const m = e.candidate.candidate.match(/ \\d+ (\\S+) \\d+ typ host/);
      if (m) hosts.push(m[1]);
    };
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  await done;
  pc.close();
  return {
    literal: await get(`http://[fd77::1]:${port}/`),
    v6only: await get(`http://v6only.test:${port}/`),
    dual: await get(`http://dual.test:${port}/`),
    hosts,
  };
}"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        family = "v4" if self.client_address[0].startswith("::ffff:") else "v6"
        body = json.dumps({"family": family}).encode() if self.path == "/" else b"<!DOCTYPE html>"
        self.send_response(200)
        self.send_header("Content-Type", "application/json" if self.path == "/" else "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DualStackServer(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


async def probe(port: int, ipv4_only: bool) -> dict:
    from camoufox.async_api import AsyncCamoufox

    config = {"network:ipv4Only": True} if ipv4_only else {}
    async with AsyncCamoufox(headless=True, config=config, i_know_what_im_doing=True,
                             firefox_user_prefs={"media.peerconnection.ice.obfuscate_host_addresses": False},
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.goto(f"http://{V4}:{port}/page")
        return await page.evaluate(PROBE, [port])


def check(port: int) -> int:
    off, on = (asyncio.run(probe(port, ipv4_only)) for ipv4_only in (False, True))
    print(f"  key off: {off}\n  key on:  {on}")
    failures = []
    if not (off["literal"].get("family") == "v6" and off["v6only"].get("family") == "v6"
            and any(":" in h for h in off["hosts"])):
        failures.append("IPv6 does not work here with the key off, so the check would be vacuous")
    for name in ("literal", "v6only"):
        if "error" not in on[name]:
            failures.append(f"{name} reached the server over IPv6 with network:ipv4Only")
        elif on[name]["ms"] > 1000:
            failures.append(f"{name} took {on[name]['ms']:.0f} ms to fail; an unreachable network fails at once")
    if on["dual"].get("family") != "v4":
        failures.append(f"dual.test should arrive over IPv4, got {on['dual']}")
    if any(":" in h for h in on["hosts"]):
        failures.append(f"WebRTC offered an IPv6 host candidate: {on['hosts']}")
    if not on["hosts"]:
        failures.append("WebRTC offered no host candidate at all")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("PASS: with network:ipv4Only the browser behaves as on an IPv4-only network.")
    return 0


def main() -> int:
    if os.environ.get(INSIDE):
        server = DualStackServer(("::", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return check(server.server_address[1])
        finally:
            server.shutdown()

    if not shutil.which("unshare") or not shutil.which("ip"):
        print("FAIL: this guard needs unshare and ip (util-linux, iproute2)")
        return 1
    if subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode:
        print("FAIL: unprivileged user namespaces are denied here. On Ubuntu, run "
              "`sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`.")
        return 1
    with tempfile.TemporaryDirectory() as files:
        for name, text in FILES.items():
            Path(files, name).write_text(text)
        env = {**os.environ, INSIDE: "1", "NET_FILES": files}
        cmd = ["unshare", "-rm", "sh", "-c", UNREACHABLE_RESOLVER, "sh",
               "unshare", "-rnm", "sh", "-c", SETUP, "sh", sys.executable, *sys.argv]
        return subprocess.run(cmd, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
