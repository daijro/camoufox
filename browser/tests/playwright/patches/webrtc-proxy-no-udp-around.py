"""
Verify that behind a proxy no WebRTC UDP leaves this host except through it.

A proxied identity is a machine sitting at the proxy's exit. Whatever that
machine sends, a site sees from the exit, and the network this host sits on
sees nothing: it is not that machine's network. webrtc-socks5-udp.patch used to
send UDP for the local network (RFC 1918, ULA, link-local) straight from the
host socket, by design, so a STUN server or peer on this LAN heard from the
host's own address around the proxy, and Firefox's mDNS service multicast its
queries for a peer's .local name onto the LAN. Now:

    * behind a SOCKS5 proxy that grants UDP ASSOCIATE, every datagram that
      would leave this host goes through the proxy's relay, the local network
      included;
    * behind a proxy that carries no UDP (HTTP CONNECT, SOCKS5 refusing UDP
      ASSOCIATE, or SOCKS5 dropping the association it just granted), none
      leaves at all and no srflx surfaces: the page reads a machine whose UDP
      is blocked (a made-up srflx claimed a Binding Request the page's STUN
      server knows it never received);
    * a page in its proxy's bypass list is still behind a proxy: neither its UDP
      nor a TURN connection over TCP leaves, though a direct context's do;
    * a system proxy counts, on about:blank too, where no load has shown it;
    * only datagrams that stay on this host go direct: to loopback, or to the
      socket's own address (the other end of a page's loopback connection,
      which still connects, as stock's does);
    * mDNS names gathered behind a proxy stay in the browser: a page's two
      peer connections resolve each other's, and no multicast query or answer
      goes out.

How it is measured: the page's STUN server runs on another host on the
network, a container on the docker bridge (not this host's own address, where
a datagram never leaves the machine; not loopback, which Firefox ignores for
STUN), so a datagram sent around the
proxy reaches it from a host socket, and one relayed by the guard's own SOCKS5
proxy reaches it from the relay's socket, whose ports the guard knows. A
socket joined to the mDNS group (224.0.0.251:5353) sees any query or answer
naming a <uuid>.local host candidate. On a build with the LAN shortcut, STUN
behind every proxy arrives from host sockets and the loopback test multicasts
its queries.

Exit 0 PASS, 1 FAIL.

    python browser/tests/playwright/patches/webrtc-proxy-no-udp-around.py
"""

import asyncio
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

SPOOFED_IP = "203.0.113.9"
PAGE = b"<!doctype html><title>proxied</title><body>"
COOKIE = 0x2112A442
UUID_LOCAL = re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# The page scripts run in the main world: an isolated world cannot read the
# RTCStatsReport getStats() returns.
GATHER = """mw:async (stun) => {
  const pc = new RTCPeerConnection({iceServers: [{urls: stun, username: 'guard', credential: 'guard'}]});
  const cands = [];
  const start = performance.now();
  const ended = new Promise(resolve => {
    setTimeout(() => resolve(null), 30000);
    pc.onicecandidate = e => {
      if (!e.candidate) return resolve(performance.now() - start);
      if (e.candidate.candidate) cands.push(e.candidate.candidate);
    };
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  const elapsed = await ended;
  const stats = [];
  (await pc.getStats()).forEach(s => {
    if (s.type === 'local-candidate' && s.candidateType === 'srflx')
      stats.push({address: s.address, port: s.port, priority: s.priority});
  });
  pc.close();
  return {cands, stats, elapsed};
}"""

LOOPBACK = """mw:async () => {
  const a = new RTCPeerConnection(), b = new RTCPeerConnection();
  a.onicecandidate = e => e.candidate && b.addIceCandidate(e.candidate).catch(() => {});
  b.onicecandidate = e => e.candidate && a.addIceCandidate(e.candidate).catch(() => {});
  const channel = a.createDataChannel('probe');
  const received = new Promise(resolve => {
    b.ondatachannel = e => { e.channel.onmessage = m => resolve(m.data); };
    setTimeout(() => resolve('timeout'), 15000);
  });
  channel.onopen = () => channel.send('ping');
  await a.setLocalDescription(await a.createOffer());
  await b.setRemoteDescription(a.localDescription);
  await b.setLocalDescription(await b.createAnswer());
  await a.setRemoteDescription(b.localDescription);
  const message = await received;
  a.close(); b.close();
  return message;
}"""


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # no packet is sent for a UDP connect
        return s.getsockname()[0]
    finally:
        s.close()


def parse_cand(c: str) -> dict:
    p = c.split()
    return {"proto": p[2].lower(), "priority": int(p[3]), "address": p[4], "port": int(p[5]), "type": p[7]}


class TcpListener:
    """Serves the page on this host's own address and counts every connection."""

    def __init__(self, host: str) -> None:
        self.host = host
        self.connections = 0

    async def start(self) -> "TcpListener":
        self.server = await asyncio.start_server(self.serve, self.host, 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def serve(self, reader, writer) -> None:
        self.connections += 1
        try:
            await serve_http_proxy(reader, writer)
        except ConnectionError:
            writer.close()

    def close(self) -> None:
        self.server.close()


STUN_RESPONDER = r"""
import socket, struct, sys
COOKIE = 0x2112A442
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", 3478))
print("READY", flush=True)
while True:
    data, src = s.recvfrom(2048)
    print("FROM %s %d" % src, flush=True)
    if len(data) < 20 or struct.unpack("!HHI", data[:8])[0::2] != (1, COOKIE):
        continue
    ip = struct.unpack("!I", socket.inet_aton(src[0]))[0]
    attr = struct.pack("!HHBBHI", 0x0020, 8, 0, 1, src[1] ^ (COOKIE >> 16), ip ^ COOKIE)
    s.sendto(struct.pack("!HHI", 0x0101, len(attr), COOKIE) + data[8:20] + attr, src)
"""


class StunServer:
    """Binding responder on another host on the network: a container on the
    docker bridge. Logs the source of every datagram.

    It cannot listen on this host's own LAN address: a datagram to the
    socket's own address never leaves the machine, so the build lets it
    through (two peers on one machine connect that way) and a server there
    hears UDP that no other machine could.
    """

    IMAGE = "python:3.11-alpine"

    def __init__(self) -> None:
        self.name = f"webrtc-guard-stun-{os.getpid()}"
        subprocess.run(["docker", "run", "-d", "--rm", "--name", self.name, "--network", "bridge",
                        "--entrypoint", "python3", self.IMAGE, "-u", "-c", STUN_RESPONDER],
                       check=True, stdout=subprocess.DEVNULL)
        self.logs = None
        try:
            self.host = subprocess.run(
                ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                 self.name], check=True, capture_output=True, text=True).stdout.strip()
            self.logs = subprocess.Popen(["docker", "logs", "-f", self.name],
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if self.logs.stdout.readline().strip() != "READY":
                raise RuntimeError("the STUN container did not start")
        except BaseException:
            self.close()
            raise
        self.port = 3478
        self.sources: list[tuple[str, int]] = []
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self) -> None:
        for line in self.logs.stdout:
            if line.startswith("FROM "):
                _, ip, port = line.split()
                self.sources.append((ip, int(port)))

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        if self.logs:
            self.logs.wait(timeout=10)


class MdnsWatch:
    """Every mDNS datagram this host sends that names a <uuid>.local host.

    Other machines on the LAN multicast their own browsers' names; only a
    datagram from one of this host's addresses can be the browser's.
    """

    def __init__(self, lan: str) -> None:
        self.seen: list[tuple[str, str]] = []
        self.own = {lan, "127.0.0.1"}
        self.error = None
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.sock.bind(("", 5353))
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                 socket.inet_aton("224.0.0.251") + socket.inet_aton(lan))
        except OSError as e:
            self.error = str(e)
            return
        threading.Thread(target=self.loop, daemon=True).start()
        # A watcher that cannot hear this host's own query would pass every check below.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(lan))
            sender.sendto(b"00000000-0000-4000-8000-000000000000.local", ("224.0.0.251", 5353))
        time.sleep(1)
        if not self.seen:
            self.error = "the watcher did not hear its own multicast query"
        self.seen.clear()

    def loop(self) -> None:
        while True:
            try:
                data, src = self.sock.recvfrom(9000)
            except OSError:
                return
            if src[0] not in self.own:
                continue
            for m in UUID_LOCAL.finditer(data):
                self.seen.append((src[0], m.group().decode()))


def parse_datagram(data: bytes):
    """RFC 1928 §7 header -> ((host, port), payload), or None."""
    if len(data) < 10 or data[:3] != b"\0\0\0":
        return None
    if data[3] == 1:
        return (socket.inet_ntoa(data[4:8]), struct.unpack("!H", data[8:10])[0]), data[10:]
    if data[3] == 4:
        return (socket.inet_ntop(socket.AF_INET6, data[4:20]), struct.unpack("!H", data[20:22])[0]), data[22:]
    return None


class Relay:
    """One UDP association: `inner` faces the browser, `outer` the network."""

    def __init__(self, proxy: "Socks5Proxy") -> None:
        self.proxy = proxy
        self.client = None
        self.inner = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.inner.bind(("127.0.0.1", 0))
        self.outer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.outer.bind(("0.0.0.0", 0))
        proxy.outer_ports.add(self.outer.getsockname()[1])
        threading.Thread(target=self.up, daemon=True).start()
        threading.Thread(target=self.down, daemon=True).start()

    def up(self) -> None:
        while True:
            try:
                data, src = self.inner.recvfrom(65535)
            except OSError:
                return
            self.client = src
            parsed = parse_datagram(data)
            if not parsed:
                continue
            dst, payload = parsed
            self.proxy.destinations.append(dst)
            try:
                self.outer.sendto(payload, dst)
            except OSError:
                pass

    def down(self) -> None:
        while True:
            try:
                data, src = self.outer.recvfrom(65535)
            except OSError:
                return
            if self.client and ":" not in src[0]:
                head = b"\0\0\0\x01" + socket.inet_aton(src[0]) + struct.pack("!H", src[1])
                try:
                    self.inner.sendto(head + data, self.client)
                except OSError:
                    return

    def close(self) -> None:
        self.inner.close()
        self.outer.close()


class Socks5Proxy:
    """No-auth SOCKS5 that serves the page on CONNECT :80 and, if `udp`, relays
    UDP ASSOCIATE. `drops` ends each association as soon as it is granted."""

    def __init__(self, udp: bool, drops: bool = False) -> None:
        self.udp = udp
        self.drops = drops
        self.associations = 0
        self.refused = 0
        self.outer_ports: set[int] = set()
        self.destinations: list[tuple] = []
        self.relays: list[Relay] = []

    async def start(self) -> int:
        self.server = await asyncio.start_server(self.serve, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

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
        if version != 5 or 0 not in methods:
            writer.write(b"\x05\xff")
            return
        writer.write(b"\x05\x00")
        _, cmd, _, atyp = await reader.readexactly(4)
        if atyp == 1:
            await reader.readexactly(4)
        elif atyp == 3:
            await reader.readexactly((await reader.readexactly(1))[0])
        else:
            await reader.readexactly(16)
        port = struct.unpack("!H", await reader.readexactly(2))[0]
        if cmd == 1:
            if port != 80:  # refusing 443 lets HTTPS-First fall back at once
                writer.write(b"\x05\x05\x00\x01" + bytes(6))
                return
            writer.write(b"\x05\x00\x00\x01" + bytes(6))
            while (await reader.readline()) not in (b"\r\n", b""):
                pass
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                         b"Content-Length: %d\r\n\r\n%s" % (len(PAGE), PAGE))
            await writer.drain()
            return
        if cmd != 3 or not self.udp:
            self.refused += 1
            writer.write(b"\x05\x07\x00\x01" + bytes(6))
            return
        self.associations += 1
        relay = Relay(self)
        self.relays.append(relay)
        bound = relay.inner.getsockname()
        if self.drops:
            # Closed before the grant: the browser flushes its queued datagrams on
            # the grant, and a relay still open would forward them.
            relay.close()
        writer.write(b"\x05\x00\x00\x01" + socket.inet_aton(bound[0]) + struct.pack("!H", bound[1]))
        await writer.drain()
        if not self.drops:
            await reader.read()  # the association lives as long as its control connection
            relay.close()

    def close(self) -> None:
        for r in self.relays:
            r.close()
        self.server.close()


async def serve_http_proxy(reader, writer) -> None:
    while (await reader.readline()) not in (b"\r\n", b""):
        pass
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                 b"Content-Length: %d\r\n\r\n%s" % (len(PAGE), PAGE))
    await writer.drain()
    writer.close()


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    lan = lan_ip()
    if lan.startswith("127."):
        print("  FAIL this host has no LAN address to put the STUN server on")
        return 1
    if shutil.which("docker") is None:
        print("  FAIL docker is needed to put the STUN server on another host")
        return 1
    stun = StunServer()
    try:
        return await judge(lan, stun)
    finally:
        stun.close()


async def judge(lan: str, stun: "StunServer") -> int:
    from camoufox.async_api import AsyncCamoufox

    mdns = MdnsWatch(lan)
    relaying, refusing, dropping = Socks5Proxy(udp=True), Socks5Proxy(udp=False), Socks5Proxy(udp=True, drops=True)
    bypassed = Socks5Proxy(udp=True)
    ports = {p: await p.start() for p in (relaying, refusing, dropping, bypassed)}
    http = await asyncio.start_server(serve_http_proxy, "127.0.0.1", 0)
    servers = {
        "SOCKS5 with UDP ASSOCIATE": f"socks5://127.0.0.1:{ports[relaying]}",
        "SOCKS5 refusing UDP": f"socks5://127.0.0.1:{ports[refusing]}",
        "SOCKS5 dropping the association": f"socks5://127.0.0.1:{ports[dropping]}",
        "HTTP proxy": f"http://127.0.0.1:{http.sockets[0].getsockname()[1]}",
    }
    stun_url = f"stun:{stun.host}:{stun.port}"
    results = {}
    launch = dict(headless=True, os="linux", geoip=False, i_know_what_im_doing=True, main_world_eval=True,
                  executable_path=str(resolve_binary()))
    origin, turn = await TcpListener(lan).start(), await TcpListener(lan).start()
    origin_url = f"http://{lan}:{origin.port}/"
    turn_url = f"turn:{lan}:{turn.port}?transport=tcp"

    async def around_from(page) -> tuple:
        """What the STUN server heard and the TURN listener accepted from this page."""
        before_stun, before_turn = len(stun.sources), turn.connections
        await page.evaluate(GATHER, stun_url)
        await page.evaluate(GATHER, turn_url)
        await asyncio.sleep(0.5)
        return stun.sources[before_stun:], turn.connections - before_turn

    async with AsyncCamoufox(config={"webrtc:ipv4": SPOOFED_IP, "webrtc:hostipv6": True}, **launch) as browser:
        direct_page = await browser.new_page()
        await direct_page.goto(origin_url)
        direct_stun, direct_turn = await around_from(direct_page)
        bypass_context = await browser.new_context(
            proxy={"server": f"socks5://127.0.0.1:{ports[bypassed]}", "bypass": lan})
        bypass_page = await bypass_context.new_page()
        await bypass_page.goto(origin_url)
        bypass_stun, bypass_turn = await around_from(bypass_page)
        for label, server in servers.items():
            context = await browser.new_context(proxy={"server": server})
            page = await context.new_page()
            await page.goto("http://parity.test/")
            before_stun, before_mdns = len(stun.sources), len(mdns.seen)
            gather = await page.evaluate(GATHER, stun_url)
            await asyncio.sleep(0.5)
            sources = stun.sources[before_stun:]
            loopback = await page.evaluate(LOOPBACK)
            await asyncio.sleep(1.0)
            results[label] = {"gather": gather, "sources": sources, "loopback": loopback,
                              "mdns": mdns.seen[before_mdns:]}
            await context.close()

    # Without a schema, Firefox reads the system proxy from these variables on
    # any desktop; GSettings would otherwise answer first.
    system_proxy = f"http://127.0.0.1:{http.sockets[0].getsockname()[1]}"
    env = {**os.environ, "http_proxy": system_proxy, "https_proxy": system_proxy, "XDG_DATA_DIRS": "/nonexistent"}
    env.pop("GSETTINGS_SCHEMA_DIR", None)
    async with AsyncCamoufox(env=env, **launch) as browser:
        system_page = await browser.new_page()
        before_stun = len(stun.sources)
        await system_page.evaluate(GATHER, stun_url)
        await asyncio.sleep(0.5)
        system_stun = stun.sources[before_stun:]
        await system_page.goto("http://parity.test/")
        system_title = await system_page.title()

    for p in (relaying, refusing, dropping, bypassed, origin, turn):
        p.close()
    http.close()

    checks = [
        ("direct: the STUN server hears the page, so silence below means something", bool(direct_stun), direct_stun),
        ("direct: the TURN listener accepts the page, so silence below means something", direct_turn > 0, direct_turn),
        ("a page in the proxy's bypass list: no UDP leaves", not bypass_stun, bypass_stun),
        ("a page in the proxy's bypass list: no TCP leaves", bypass_turn == 0, bypass_turn),
        ("system proxy: pages load through it", system_title == "proxied", system_title),
        ("system proxy, about:blank: no UDP leaves", not system_stun, system_stun),
    ]
    for label, r in results.items():
        cands = [parse_cand(c) for c in r["gather"]["cands"]]
        srflx = [c for c in cands if c["type"] == "srflx"]
        around = [s for s in r["sources"] if s[1] not in relaying.outer_ports]
        if label == "SOCKS5 with UDP ASSOCIATE":
            checks += [
                (f"{label}: the proxy granted an association", relaying.associations > 0, relaying.associations),
                (f"{label}: the LAN STUN server heard from the relay",
                 len(r["sources"]) > len(around), f"{len(r['sources']) - len(around)} via the relay"),
                (f"{label}: no datagram reached it from a host socket around the proxy",
                 not around, around),
                (f"{label}: the srflx carries the relay's mapped port",
                 len(srflx) == 1 and srflx[0]["port"] in relaying.outer_ports,
                 f"{[(c['address'], c['port']) for c in srflx]} relay ports {sorted(relaying.outer_ports)}"),
            ]
        else:
            checks += [
                (f"{label}: no UDP reached the LAN STUN server", not r["sources"], r["sources"]),
                (f"{label}: gathering ends without it", r["gather"]["elapsed"] is not None, r["gather"]["elapsed"]),
                (f"{label}: no srflx without a STUN answer (UDP blocked)",
                 not srflx and not r["gather"]["stats"],
                 f"{[(c['address'], c['port']) for c in srflx]} stats {r['gather']['stats']}"),
            ]
        checks += [
            (f"{label}: the page's two peer connections connect", r["loopback"] == "ping", r["loopback"]),
        ]
        checks.append((f"{label}: no mDNS query or answer for a host candidate's name leaves",
                       not mdns.error and not r["mdns"], mdns.error or sorted(set(r["mdns"]))[:4]))
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
