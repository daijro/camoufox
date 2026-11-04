"""
Verify WebRTC's UDP goes through a SOCKS5 proxy's UDP ASSOCIATE relay.

A real machine at the proxy's exit address sends its STUN Binding requests from
there, so a page running its own STUN server sees the request arrive and gets
back the srflx it mapped. Behind a proxy, Camoufox used to send no internet UDP
at all and fabricate the srflx from the identity's `webrtc:ipv4`: the page's
server never heard from it. webrtc-socks5-udp.patch sends every datagram that
would leave this host through a UDP ASSOCIATE relay (RFC 1928 §7) on the
context's own SOCKS5 proxy, and names STUN servers to it by host name, so the
name is resolved by the proxy. (webrtc-proxy-no-udp-around.py covers the local
network: no exception there either.)

The guard runs its own SOCKS5 proxies and the internet behind them. Each relay
appears on that internet under a TEST-NET address of its own, and the page's
STUN server lives there at 198.51.100.1, also named stun.relay.test. Nothing on
this machine answers at a TEST-NET address, so a request that went around a
proxy reaches no server at all: every request the server sees came through a
relay. Each context has its own proxy; the page is served by the proxy itself.

What PASS means:
    * behind a SOCKS5 proxy, the STUN server gets Binding requests, every one
      from that context's relay, and the page's one srflx is the address the
      server mapped, in the candidate, the SDP and getStats(), not the
      identity's `webrtc:ipv4`;
    * a STUN server named by host name is asked through the relay by that name;
    * behind an HTTP proxy, and behind a SOCKS5 proxy that refuses UDP
      ASSOCIATE, nothing reaches the server, gathering ends within a few
      seconds and the only srflx carries `webrtc:ipv4`, as before;
    * two pages in two contexts, each behind its own SOCKS5 proxy and given
      only each other's srflx, open a data channel through both relays.

    python browser/tests/playwright/patches/webrtc-socks5-udp.py
"""

import asyncio
import ipaddress
import socket
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

SPOOFED_IP = "203.0.113.9"
STUN_ADDR = ("198.51.100.1", 3478)
STUN_NAME = "stun.relay.test"
NAMES = {STUN_NAME: STUN_ADDR[0]}
PAGE = b"<!doctype html><title>proxied</title><body>"
COOKIE = 0x2112A442

# The page scripts run in the main world: an isolated world cannot read the
# RTCStatsReport getStats() returns.
GATHER = """mw:async (stun) => {
  const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  const srflx = [];
  const start = performance.now();
  const ended = new Promise(resolve => {
    setTimeout(() => resolve(null), 30000);
    pc.onicecandidate = e => {
      if (!e.candidate) return resolve(performance.now() - start);
      const m = e.candidate.candidate.match(/ (\\S+) (\\d+) typ srflx/);
      if (m) srflx.push(m[1] + ':' + m[2]);
    };
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  const elapsed = await ended;
  const sdp = [...pc.localDescription.sdp.matchAll(/ (\\S+) (\\d+) typ srflx/g)]
    .map(m => m[1] + ':' + m[2]);
  const stats = [];
  (await pc.getStats()).forEach(s => {
    if (s.type === 'local-candidate' && s.candidateType === 'srflx')
      stats.push(s.address + ':' + s.port);
  });
  pc.close();
  return {srflx, sdp, stats, elapsed};
}"""

# Each side keeps only its srflx candidates in what it hands the other, so the
# pages can reach each other only through the relays.
OFFER = """mw:async (stun) => {
  window.pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  window.channel = pc.createDataChannel('probe');
  // The answerer's reply comes back on this channel: ondatachannel fires only
  // for channels the other side opens.
  window.received = new Promise(resolve => {
    setTimeout(() => resolve('timeout'), 20000);
    channel.onmessage = m => resolve(m.data);
  });
  const gathered = new Promise(resolve => pc.onicegatheringstatechange =
    () => pc.iceGatheringState === 'complete' && resolve());
  window.opened = new Promise(resolve => channel.onopen = resolve);
  await pc.setLocalDescription(await pc.createOffer());
  await gathered;
  return pc.localDescription.sdp;
}"""

ANSWER = """mw:async ([stun, offer]) => {
  window.pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  window.received = new Promise(resolve => {
    setTimeout(() => resolve('timeout'), 20000);
    pc.ondatachannel = e => {
      e.channel.onmessage = m => resolve(m.data);
      e.channel.onopen = () => e.channel.send('pong');
    };
  });
  const gathered = new Promise(resolve => pc.onicegatheringstatechange =
    () => pc.iceGatheringState === 'complete' && resolve());
  await pc.setRemoteDescription({type: 'offer', sdp: offer});
  await pc.setLocalDescription(await pc.createAnswer());
  await gathered;
  return pc.localDescription.sdp;
}"""

FINISH = """mw:async (answer) => {
  await pc.setRemoteDescription({type: 'answer', sdp: answer});
  const ok = await Promise.race([opened.then(() => true),
                                 new Promise(r => setTimeout(() => r(false), 20000))]);
  if (ok) channel.send('ping');
  return ok;
}"""


def srflx_only(sdp: str) -> str:
    return "".join(line for line in sdp.splitlines(keepends=True)
                   if not line.startswith("a=candidate:") or " typ srflx" in line)


class Internet:
    """The network behind the proxies: datagrams between registered addresses."""

    def __init__(self) -> None:
        self.hosts = {}
        self.delivered = []  # (src, dst)

    def send(self, payload: bytes, src: tuple, dst: tuple) -> None:
        handler = self.hosts.get(dst)
        if handler:
            self.delivered.append((src, dst))
            handler(payload, src)


class StunServer:
    """Answers Binding requests with the source it saw as XOR-MAPPED-ADDRESS."""

    def __init__(self, net: Internet) -> None:
        self.net = net
        self.requests = []  # source of every Binding request
        self.mapped = []  # every XOR-MAPPED-ADDRESS returned, "ip:port"
        net.hosts[STUN_ADDR] = self.on_datagram

    def on_datagram(self, data: bytes, src: tuple) -> None:
        if len(data) < 20:
            return
        kind, _, cookie = struct.unpack("!HHI", data[:8])
        if kind != 0x0001 or cookie != COOKIE:
            return
        self.requests.append(src)
        ip = int(ipaddress.IPv4Address(src[0]))
        attr = struct.pack("!HHBBHI", 0x0020, 8, 0, 1, src[1] ^ (COOKIE >> 16), ip ^ COOKIE)
        self.mapped.append(f"{src[0]}:{src[1]}")
        self.net.send(struct.pack("!HHI", 0x0101, len(attr), COOKIE) + data[8:20] + attr,
                      STUN_ADDR, src)


async def read_addr(reader: asyncio.StreamReader, atyp: int) -> tuple:
    if atyp == 1:
        return socket.inet_ntoa(await reader.readexactly(4)), struct.unpack("!H", await reader.readexactly(2))[0]
    if atyp == 3:
        name = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
        return name, struct.unpack("!H", await reader.readexactly(2))[0]
    return socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16)), struct.unpack("!H", await reader.readexactly(2))[0]


def parse_datagram(data: bytes):
    """RFC 1928 §7 header -> (atyp, (host, port), payload), or None."""
    if len(data) < 10 or data[:3] != b"\0\0\0":
        return None
    atyp = data[3]
    if atyp == 1:
        return atyp, (socket.inet_ntoa(data[4:8]), struct.unpack("!H", data[8:10])[0]), data[10:]
    if atyp == 3:
        n = data[4]
        return atyp, (data[5:5 + n].decode(), struct.unpack("!H", data[5 + n:7 + n])[0]), data[7 + n:]
    return None


class Relay(asyncio.DatagramProtocol):
    """One association: its socket here, and its address on the internet."""

    def __init__(self, proxy: "Socks5Proxy", control_ip: str, public: tuple) -> None:
        self.proxy, self.control_ip, self.public = proxy, control_ip, public
        self.client = None
        self.transport = None
        proxy.net.hosts[public] = self.to_client

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        if addr[0] != self.control_ip or (self.client and addr != self.client):
            self.proxy.strangers += 1
            return
        self.client = addr
        parsed = parse_datagram(data)
        if not parsed:
            return
        atyp, (host, port), payload = parsed
        self.proxy.destinations.append((atyp, host, port))
        if atyp == 3:
            host = NAMES.get(host)
            if not host:
                return
        self.proxy.net.send(payload, self.public, (host, port))

    def to_client(self, payload: bytes, src: tuple) -> None:
        if self.client and self.transport:
            header = b"\0\0\0\x01" + socket.inet_aton(src[0]) + struct.pack("!H", src[1])
            self.transport.sendto(header + payload, self.client)

    def close(self) -> None:
        self.proxy.net.hosts.pop(self.public, None)
        if self.transport:
            self.transport.close()


class Socks5Proxy:
    """A no-auth SOCKS5 proxy that serves the page on CONNECT and, unless
    `udp` is False, relays UDP ASSOCIATE onto `net` from `public_ip`."""

    def __init__(self, net: Internet, public_ip: str, udp: bool = True) -> None:
        self.net, self.public_ip, self.udp = net, public_ip, udp
        self.associations = 0
        self.refused = 0
        self.strangers = 0
        self.destinations = []  # (atyp, host, port) of every relayed datagram
        self.relays = []
        self.server = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self.serve, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
        _, port = await read_addr(reader, atyp)
        if cmd == 1:
            # Only plain HTTP: refusing 443 lets HTTPS-First fall back at once.
            if port != 80:
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
        public = (self.public_ip, 40000 + self.associations)
        control_ip = writer.get_extra_info("peername")[0]
        loop = asyncio.get_running_loop()
        _, relay = await loop.create_datagram_endpoint(
            lambda: Relay(self, control_ip, public), local_addr=("127.0.0.1", 0))
        self.relays.append(relay)
        bound = relay.transport.get_extra_info("sockname")
        writer.write(b"\x05\x00\x00\x01" + socket.inet_aton(bound[0]) + struct.pack("!H", bound[1]))
        await writer.drain()
        # The association lives as long as its control connection.
        await reader.read()
        relay.close()

    def publics(self) -> set:
        return {r.public for r in self.relays}

    def close(self) -> None:
        for relay in self.relays:
            relay.close()
        self.server.close()


async def serve_http_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while (await reader.readline()) not in (b"\r\n", b""):
        pass
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                 b"Content-Length: %d\r\n\r\n%s" % (len(PAGE), PAGE))
    await writer.drain()
    writer.close()


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    net = Internet()
    stun = StunServer(net)
    relaying = Socks5Proxy(net, "198.51.100.10")
    refusing = Socks5Proxy(net, "198.51.100.20", udp=False)
    peer_a = Socks5Proxy(net, "198.51.100.30")
    peer_b = Socks5Proxy(net, "198.51.100.40")
    proxies = {p: await p.start() for p in (relaying, refusing, peer_a, peer_b)}
    http = await asyncio.start_server(serve_http_proxy, "127.0.0.1", 0)
    http_port = http.sockets[0].getsockname()[1]

    async def page_behind(browser, server: str):
        context = await browser.new_context(proxy={"server": server})
        page = await context.new_page()
        await page.goto("http://parity.test/")
        return page

    def socks(proxy: Socks5Proxy) -> str:
        return f"socks5://127.0.0.1:{proxies[proxy]}"

    async with AsyncCamoufox(headless=True, os="linux", config={"webrtc:ipv4": SPOOFED_IP},
                             geoip=False, i_know_what_im_doing=True, main_world_eval=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await page_behind(browser, socks(relaying))
        by_ip = await page.evaluate(GATHER, f"stun:{STUN_ADDR[0]}:{STUN_ADDR[1]}")
        ip_requests, ip_mapped = list(stun.requests), list(stun.mapped)
        by_name = await page.evaluate(GATHER, f"stun:{STUN_NAME}:{STUN_ADDR[1]}")
        name_requests, name_mapped = stun.requests[len(ip_requests):], stun.mapped[len(ip_mapped):]

        before = len(stun.requests)
        http_page = await page_behind(browser, f"http://127.0.0.1:{http_port}")
        via_http = await http_page.evaluate(GATHER, f"stun:{STUN_NAME}:{STUN_ADDR[1]}")
        refused_page = await page_behind(browser, socks(refusing))
        via_refused = await refused_page.evaluate(GATHER, f"stun:{STUN_ADDR[0]}:{STUN_ADDR[1]}")
        unrelayed_requests = len(stun.requests) - before

        stun_url = f"stun:{STUN_ADDR[0]}:{STUN_ADDR[1]}"
        a, b = await page_behind(browser, socks(peer_a)), await page_behind(browser, socks(peer_b))
        offer = await a.evaluate(OFFER, stun_url)
        answer = await b.evaluate(ANSWER, [stun_url, srflx_only(offer)])
        opened = await a.evaluate(FINISH, srflx_only(answer))
        messages = (await a.evaluate("mw:received"), await b.evaluate("mw:received")) if opened else (None, None)
    for proxy in proxies:
        proxy.close()
    http.close()

    relay_publics = {f"{h}:{p}" for h, p in relaying.publics()}
    a_to_b = sum(1 for s, d in net.delivered if s in peer_a.publics() and d in peer_b.publics())
    b_to_a = sum(1 for s, d in net.delivered if s in peer_b.publics() and d in peer_a.publics())
    checks = [
        ("SOCKS5: the STUN server got Binding requests, all from the context's relay",
         bool(ip_requests) and {f"{h}:{p}" for h, p in ip_requests} <= relay_publics,
         f"{len(ip_requests)} requests from {sorted({f'{h}:{p}' for h, p in ip_requests})}"),
        ("SOCKS5: the one srflx is the address the server mapped",
         len(by_ip["srflx"]) == 1 and by_ip["srflx"][0] in ip_mapped, f"{by_ip['srflx']} mapped {sorted(set(ip_mapped))}"),
        ("SOCKS5: the SDP and getStats() carry the same srflx",
         by_ip["sdp"] == by_ip["srflx"] and by_ip["stats"] == by_ip["srflx"],
         f"sdp {by_ip['sdp']} stats {by_ip['stats']}"),
        ("SOCKS5: a STUN server named by host name is asked by that name, through the relay",
         bool(name_requests) and (3, STUN_NAME, STUN_ADDR[1]) in relaying.destinations
         and len(by_name["srflx"]) == 1 and by_name["srflx"][0] in name_mapped,
         f"{len(name_requests)} requests, srflx {by_name['srflx']} mapped {sorted(set(name_mapped))}"),
        ("SOCKS5: the relay heard only from the control connection's address",
         relaying.strangers == 0, f"{relaying.strangers} strangers"),
        ("HTTP proxy and SOCKS5 refusing UDP: nothing reaches the STUN server",
         unrelayed_requests == 0 and refusing.refused >= 1,
         f"{unrelayed_requests} requests, {refusing.refused} refused associations"),
    ]
    for label, gather in (("HTTP proxy", via_http), ("SOCKS5 refusing UDP", via_refused)):
        checks += [
            (f"{label}: gathering ends without the STUN server",
             gather["elapsed"] is not None and gather["elapsed"] < 5000, gather["elapsed"]),
            (f"{label}: the only srflx carries the identity's address",
             [c.split(":")[0] for c in gather["srflx"]] == [SPOOFED_IP], gather["srflx"]),
        ]
    checks += [
        ("two contexts, each behind its own SOCKS5 proxy: the data channel opens",
         opened and messages == ("pong", "ping"), f"opened={opened} messages={messages}"),
        ("two contexts: their datagrams crossed between the two relays",
         a_to_b > 0 and b_to_a > 0, f"{a_to_b} A->B, {b_to_a} B->A"),
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
