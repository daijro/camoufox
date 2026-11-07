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
    * a top-level blob: page the proxied page opened with noopener, which no
      document loaded over HTTP leads back to, gathers through the relay too;
    * so do about:blank and data: pages, whose documents loaded nothing through
      the proxy, and pages behind a launch-level proxy;
    * a relay works behind RFC 1929 credentials, and whichever way the grant
      names it: an IPv6 address, a host name or the unspecified address (these
      two mean the address the control connection reached);
    * a TURN server over TCP is asked through the proxy, SOCKS5 or HTTP, and an
      HTTP proxy that hangs up right after CONNECT does not take the browser
      down (stock reports the close before the connect, then calls through the
      callbacks the close cleared);
    * a proxy that drops the control connection once the relay is in use leaves
      gathering as UDP-blocked as a proxy that never had a relay;
    * behind an HTTP proxy, and behind a SOCKS5 proxy that refuses UDP
      ASSOCIATE, nothing reaches the server, no srflx surfaces, and gathering
      takes as long as it does for a machine whose STUN server never answers:
      the page reads a machine whose UDP is blocked;
    * with capture permission, which is what opens a real host candidate on
      stock, a proxied page finds this machine's address in no candidate, SDP
      or stat, while a direct page on the same browser does find it;
    * a datagram too large for the ICE stack's 9216-byte read buffer is dropped,
      and gathering goes on (one once overran that buffer by up to 252 bytes);
    * two pages in two contexts, each behind its own SOCKS5 proxy and given
      only each other's srflx, open a data channel through both relays.

    python browser/tests/playwright/patches/webrtc-socks5-udp.py
"""

import asyncio
import socket
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import own_address, resolve_binary, stun_binding_response  # noqa: E402

SPOOFED_IP = "203.0.113.9"
STUN_ADDR = ("198.51.100.1", 3478)
STUN_NAME = "stun.relay.test"
# With its 10-byte relay header, this fills the relay read of 262 + 9216 bytes.
OVERSIZED = 9468
NAMES = {STUN_NAME: STUN_ADDR[0]}
PAGE = b"<!doctype html><title>proxied</title><body>"
TURN_TCP = f"turn:{STUN_ADDR[0]}:{STUN_ADDR[1]}?transport=tcp"
CREDENTIALS = ("guard-user", "guard-password")
# Both gatherings run the same STUN retransmit timers, which measured within
# 20 ms of each other at 11.1 s; the margin is for a loaded CI runner.
TIMER_TOLERANCE_MS = 1000

# The page scripts run in the main world: an isolated world cannot read the
# RTCStatsReport getStats() returns.
GATHER = """mw:async (stun) => {
  const pc = new RTCPeerConnection({iceServers: [{urls: stun, username: 'guard', credential: 'guard'}]});
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

# Everything a page can read about its own candidates while it is capturing.
CAPTURING = """mw:async (stun) => {
  const stream = await navigator.mediaDevices.getUserMedia({audio: true});
  const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  stream.getTracks().forEach(track => pc.addTrack(track, stream));
  const cands = [];
  const ended = new Promise(resolve => {
    setTimeout(resolve, 30000);
    pc.onicecandidate = e => e.candidate ? cands.push(e.candidate.candidate) : resolve();
  });
  await pc.setLocalDescription(await pc.createOffer());
  await ended;
  const stats = [];
  (await pc.getStats()).forEach(s => stats.push(s));
  const seen = JSON.stringify([cands, pc.localDescription.sdp, stats]);
  pc.close();
  stream.getTracks().forEach(track => track.stop());
  return seen;
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

# A button the guard clicks, since the popup blocker stops an untrusted open.
OPEN_BLOB = """mw:() => {
  const button = document.body.appendChild(document.createElement('button'));
  button.id = 'open-blob';
  button.textContent = 'open';
  button.onclick = () => window.open(URL.createObjectURL(
    new Blob(['<!doctype html><title>blob</title>'], {type: 'text/html'})),
    '_blank', 'noopener');
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
        self.oversized = False  # send a datagram past the read buffer before each answer
        net.hosts[STUN_ADDR] = self.on_datagram

    def on_datagram(self, data: bytes, src: tuple) -> None:
        response = stun_binding_response(data, *src)
        if response is None:
            return
        self.requests.append(src)
        self.mapped.append(f"{src[0]}:{src[1]}")
        if self.oversized:
            self.net.send(b"\xff" * OVERSIZED, STUN_ADDR, src)
        self.net.send(response, STUN_ADDR, src)


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
        self.control = None
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
        if self.proxy.hang_up:
            self.proxy.hung_up += 1
            self.control.close()
            self.close()
            return
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
    """A SOCKS5 proxy that serves the page on CONNECT and, unless `udp` is
    False, relays UDP ASSOCIATE onto `net` from `public_ip`. `auth` requires
    those RFC 1929 credentials. `bound` is how the grant names the relay:
    "address", "ipv6", "name" or "unspecified". `hang_up` drops the control
    connection at the first datagram the relay hears."""

    def __init__(self, net: Internet, public_ip: str, udp: bool = True,
                 auth: tuple = None, bound: str = "address", hang_up: bool = False) -> None:
        self.net, self.public_ip, self.udp, self.auth, self.bound = net, public_ip, udp, auth, bound
        self.hang_up = hang_up
        self.hung_up = 0
        self.authenticated = 0
        self.connects = []  # (host, port) of every CONNECT
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
        method = 2 if self.auth else 0
        if version != 5 or method not in methods:
            writer.write(b"\x05\xff")
            return
        writer.write(bytes((5, method)))
        if self.auth:
            await reader.readexactly(1)
            user = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
            password = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
            if (user, password) != self.auth:
                writer.write(b"\x01\x01")
                return
            self.authenticated += 1
            writer.write(b"\x01\x00")
        _, cmd, _, atyp = await reader.readexactly(4)
        host, port = await read_addr(reader, atyp)
        if cmd == 1:
            self.connects.append((host, port))
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
        # The browser reaches an IPv6 relay from ::1, not from the control connection's address.
        local = "::1" if self.bound == "ipv6" else "127.0.0.1"
        client_ip = local if self.bound == "ipv6" else writer.get_extra_info("peername")[0]
        loop = asyncio.get_running_loop()
        _, relay = await loop.create_datagram_endpoint(
            lambda: Relay(self, client_ip, public), local_addr=(local, 0))
        relay.control = writer
        self.relays.append(relay)
        port = relay.transport.get_extra_info("sockname")[1]
        name = b"relay.proxy.test"
        if self.bound == "ipv6":
            bound = b"\x04" + socket.inet_pton(socket.AF_INET6, local)
        elif self.bound == "name":
            bound = b"\x03" + bytes((len(name),)) + name
        elif self.bound == "unspecified":
            bound = b"\x01" + bytes(4)
        else:
            bound = b"\x01" + socket.inet_aton(local)
        writer.write(b"\x05\x00\x00" + bound + struct.pack("!H", port))
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


async def serve_http_proxy(requests: list, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    requests.append((await reader.readline()).decode().strip())
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
    authed = Socks5Proxy(net, "198.51.100.50", auth=CREDENTIALS)
    grants = {bound: Socks5Proxy(net, ip, bound=bound) for bound, ip in (
        ("ipv6", "198.51.100.60"), ("name", "198.51.100.70"), ("unspecified", "198.51.100.80"))}
    launched = Socks5Proxy(net, "198.51.100.90")
    capturing = Socks5Proxy(net, "198.51.100.100")
    hanging_up = Socks5Proxy(net, "198.51.100.110", hang_up=True)
    proxies = {p: await p.start() for p in (relaying, refusing, peer_a, peer_b, authed, launched, capturing, hanging_up,
                                            *grants.values())}
    http_requests = []
    http = await asyncio.start_server(lambda r, w: serve_http_proxy(http_requests, r, w), "127.0.0.1", 0)
    http_port = http.sockets[0].getsockname()[1]
    stun_url = f"stun:{STUN_ADDR[0]}:{STUN_ADDR[1]}"

    async def page_behind(browser, server: str, **credentials):
        context = await browser.new_context(proxy={"server": server, **credentials})
        page = await context.new_page()
        await page.goto("http://parity.test/")
        return page

    async def blob_page_of(page):
        await page.evaluate(OPEN_BLOB)
        async with page.context.expect_page() as opened:
            await page.click("#open-blob")
        blob = await opened.value
        await blob.wait_for_load_state()
        return blob

    def socks(proxy: Socks5Proxy) -> str:
        return f"socks5://127.0.0.1:{proxies[proxy]}"

    async def gather_through(page) -> tuple:
        """The gathering, with the Binding requests it sent and the addresses they mapped."""
        before = len(stun.requests)
        gather = await page.evaluate(GATHER, stun_url)
        return gather, stun.requests[before:], stun.mapped[before:]

    def relayed(label: str, proxy: Socks5Proxy, result: tuple) -> list:
        gather, requests, mapped = result
        return [
            (f"{label}: Binding requests came only from the proxy's relay",
             bool(requests) and set(requests) <= proxy.publics(), f"{len(requests)} from {sorted(set(requests))}"),
            (f"{label}: the one srflx is the address the server mapped",
             len(gather["srflx"]) == 1 and gather["srflx"][0] in mapped, f"{gather['srflx']} mapped {sorted(set(mapped))}"),
        ]

    launch = dict(headless=True, os="linux", geoip=False, i_know_what_im_doing=True, main_world_eval=True,
                  executable_path=str(resolve_binary()))
    async with AsyncCamoufox(config={"webrtc:ipv4": SPOOFED_IP}, **launch) as browser:
        unanswered = await (await browser.new_page()).evaluate(GATHER, stun_url)
        page = await page_behind(browser, socks(relaying))
        by_ip = await page.evaluate(GATHER, stun_url)
        ip_requests, ip_mapped = list(stun.requests), list(stun.mapped)
        by_name = await page.evaluate(GATHER, f"stun:{STUN_NAME}:{STUN_ADDR[1]}")
        name_requests, name_mapped = stun.requests[len(ip_requests):], stun.mapped[len(ip_mapped):]
        blob_page = await blob_page_of(page)
        blob_url = blob_page.url
        before = len(stun.requests)
        via_blob = await blob_page.evaluate(GATHER, stun_url)
        blob_requests, blob_mapped = stun.requests[before:], stun.mapped[before:]

        stun.oversized = True
        via_oversized = await page.evaluate(GATHER, stun_url)
        stun.oversized = False

        http_page = await page_behind(browser, f"http://127.0.0.1:{http_port}")
        via_http = await http_page.evaluate(GATHER, f"stun:{STUN_NAME}:{STUN_ADDR[1]}")
        refused_page = await page_behind(browser, socks(refusing))
        via_refused = await refused_page.evaluate(GATHER, stun_url)

        blank = await page.context.new_page()
        via_blank = await gather_through(blank)
        await blank.goto("data:text/html,<!doctype html><title>data</title>")
        via_data = await gather_through(blank)
        via_auth = await gather_through(await page_behind(
            browser, socks(authed), username=CREDENTIALS[0], password=CREDENTIALS[1]))
        via_grant = {bound: await gather_through(await page_behind(browser, socks(proxy)))
                     for bound, proxy in grants.items()}
        via_hang_up = await gather_through(await page_behind(browser, socks(hanging_up)))
        await page.evaluate(GATHER, TURN_TCP)
        await http_page.evaluate(GATHER, TURN_TCP)

        a, b = await page_behind(browser, socks(peer_a)), await page_behind(browser, socks(peer_b))
        offer = await a.evaluate(OFFER, stun_url)
        answer = await b.evaluate(ANSWER, [stun_url, srflx_only(offer)])
        opened = await a.evaluate(FINISH, srflx_only(answer))
        messages = (await a.evaluate("mw:received"), await b.evaluate("mw:received")) if opened else (None, None)

    async with AsyncCamoufox(proxy={"server": socks(launched)}, **launch) as browser:
        launch_context = await browser.new_context()
        launch_blank = await launch_context.new_page()
        via_launch_blank = await gather_through(launch_blank)
        await launch_blank.goto("http://parity.test/")
        via_launch_page = await gather_through(launch_blank)

    # No webrtc:ipv4 here, which would hide the address behind its own replacement.
    machine = own_address()
    capture_prefs = {"media.navigator.streams.fake": True, "media.navigator.permission.disabled": True,
                     "media.devices.insecure.enabled": True, "media.getusermedia.insecure.enabled": True}
    async with AsyncCamoufox(firefox_user_prefs=capture_prefs, **launch) as browser:
        direct_page = await browser.new_page()
        await direct_page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=PAGE))
        await direct_page.goto("http://parity.test/")
        seen_direct = await direct_page.evaluate(CAPTURING, stun_url)
        seen_behind = {}
        for label, server in (("SOCKS5", socks(capturing)), ("SOCKS5 refusing UDP", socks(refusing)),
                              ("HTTP proxy", f"http://127.0.0.1:{http_port}")):
            seen_behind[label] = await (await page_behind(browser, server)).evaluate(CAPTURING, stun_url)
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
        ("SOCKS5, a top-level blob: page opened with noopener: Binding requests came only "
         "from the context's relay",
         blob_url.startswith("blob:") and bool(blob_requests)
         and {f"{h}:{p}" for h, p in blob_requests} <= relay_publics,
         f"{blob_url}: {len(blob_requests)} requests from {sorted({f'{h}:{p}' for h, p in blob_requests})}"),
        ("SOCKS5, the blob: page: the one srflx is the address the server mapped",
         len(via_blob["srflx"]) == 1 and via_blob["srflx"][0] in blob_mapped,
         f"{via_blob['srflx']} mapped {sorted(set(blob_mapped))}"),
        ("SOCKS5: an oversized datagram is dropped and the real answer still counts",
         len(via_oversized["srflx"]) == 1, via_oversized["srflx"]),
        ("SOCKS5: the relay heard only from the control connection's address",
         relaying.strangers == 0, f"{relaying.strangers} strangers"),
        *relayed("SOCKS5, about:blank", relaying, via_blank),
        *relayed("SOCKS5, a data: page", relaying, via_data),
        *relayed("SOCKS5 requiring credentials", authed, via_auth),
        ("SOCKS5 requiring credentials: the association authenticated",
         authed.authenticated >= 2 and authed.associations >= 1,
         f"{authed.authenticated} logins, {authed.associations} associations"),
        *[check for bound, result in via_grant.items()
          for check in relayed(f"SOCKS5 granting a relay by {bound}", grants[bound], result)],
        *relayed("launch proxy, about:blank", launched, via_launch_blank),
        *relayed("launch proxy, a loaded page", launched, via_launch_page),
        ("SOCKS5: a TURN server over TCP is asked through the proxy",
         STUN_ADDR in relaying.connects, relaying.connects),
        ("HTTP proxy: a TURN server over TCP is asked through CONNECT",
         any(r.startswith(f"CONNECT {STUN_ADDR[0]}:{STUN_ADDR[1]} ") for r in http_requests), http_requests),
        ("SOCKS5 refusing UDP: the browser asked for a relay and was refused",
         refusing.refused >= 1, f"{refusing.refused} refused associations"),
    ]
    for label, gather in (("HTTP proxy", via_http), ("SOCKS5 refusing UDP", via_refused)):
        checks += [
            (f"{label}: gathering takes as long as an unanswered STUN server's",
             gather["elapsed"] is not None and unanswered["elapsed"] is not None
             and abs(gather["elapsed"] - unanswered["elapsed"]) < TIMER_TOLERANCE_MS,
             f"{gather['elapsed']} against {unanswered['elapsed']}"),
            (f"{label}: no srflx without a STUN answer (UDP blocked)",
             gather["srflx"] == [] and gather["stats"] == [], gather["srflx"]),
        ]
    checks += [
        ("SOCKS5 losing its control connection: the relay was in use when it went",
         hanging_up.hung_up >= 1, f"{hanging_up.hung_up} hang-ups"),
        ("SOCKS5 losing its control connection: no srflx",
         via_hang_up[0]["srflx"] == [] and via_hang_up[0]["stats"] == [], via_hang_up[0]["srflx"]),
        ("SOCKS5 losing its control connection: gathering takes as long as an unanswered STUN server's",
         via_hang_up[0]["elapsed"] is not None and unanswered["elapsed"] is not None
         and abs(via_hang_up[0]["elapsed"] - unanswered["elapsed"]) < TIMER_TOLERANCE_MS,
         f"{via_hang_up[0]['elapsed']} against {unanswered['elapsed']}"),
        ("two contexts, each behind its own SOCKS5 proxy: the data channel opens",
         opened and messages == ("pong", "ping"), f"opened={opened} messages={messages}"),
        ("two contexts: their datagrams crossed between the two relays",
         a_to_b > 0 and b_to_a > 0, f"{a_to_b} A->B, {b_to_a} B->A"),
        ("capturing, direct: this machine's address reaches the page, so its absence below means something",
         machine in seen_direct, machine),
        *[(f"capturing, {label}: this machine's address reaches the page nowhere",
           machine not in seen, f"{len(seen)} bytes of candidates, SDP and stats")
          for label, seen in seen_behind.items()],
    ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
