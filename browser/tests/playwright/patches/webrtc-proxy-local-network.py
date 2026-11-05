"""
Verify WebRTC behind a proxy keeps stock's local behaviour without leaking.

proxy_only_if_behind_proxy made Firefox refuse UDP outright for a page loaded
through a proxy: no host candidate, and no connection even between two peers on
this machine, where stock Firefox connects. webrtc-proxy-local-network.patch
keeps the UDP host sockets; webrtc-socks5-udp.patch lets them send off this
host only through the proxy's UDP relay, so nothing goes around the proxy, and
a page's two peer connections still connect over this host's own address.

The page is served by a one-file HTTP proxy, so the browser loads it through a
proxy. The STUN server is a TEST-NET address that never answers: a browser that
asked it would wait out the STUN timeout before end-of-candidates.

What PASS means:
    * two peer connections in the page connect and pass a message;
    * the page sees mDNS host candidates;
    * against the TEST-NET STUN server, gathering ends within a few seconds and
      the only srflx is the one carrying the identity's `webrtc:ipv4`, in the
      page and in about:blank, srcdoc and blob: frames it creates.

    python browser/tests/playwright/patches/webrtc-proxy-local-network.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

SPOOFED_IP = "203.0.113.9"
INTERNET_STUN = "stun:198.51.100.1:3478"

PAGE = b"<!doctype html><title>proxied</title><body>"
FRAMES = ("top", "about:blank", "srcdoc", "blob")

LOOPBACK = """async () => {
  const a = new RTCPeerConnection(), b = new RTCPeerConnection();
  const hosts = [];
  a.onicecandidate = e => {
    if (!e.candidate) return;
    if (/ typ host/.test(e.candidate.candidate)) hosts.push(e.candidate.candidate);
    b.addIceCandidate(e.candidate);
  };
  b.onicecandidate = e => e.candidate && a.addIceCandidate(e.candidate);
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
  return {message, hosts};
}"""

# `where` is "top", or the kind of same-origin frame whose RTCPeerConnection
# gathers: those documents have no channel of their own, and Firefox decides
# whether a page is behind a proxy from the document's channel.
GATHER = """async ([stun, where]) => {
  let win = window;
  if (where !== 'top') {
    const frame = document.createElement('iframe');
    if (where === 'srcdoc') frame.srcdoc = '<p>frame</p>';
    if (where === 'blob') frame.src = URL.createObjectURL(new Blob(['<p>frame</p>'], {type: 'text/html'}));
    const loaded = new Promise(resolve => frame.onload = resolve);
    document.body.append(frame);
    if (where !== 'about:blank') await loaded;
    win = frame.contentWindow;
  }
  const pc = new win.RTCPeerConnection({iceServers: [{urls: stun}]});
  const srflx = [];
  const start = performance.now();
  const ended = new Promise(resolve => {
    setTimeout(() => resolve(null), 30000);
    pc.onicecandidate = e => {
      if (!e.candidate) return resolve(performance.now() - start);
      const m = e.candidate.candidate.match(/ (\\S+) \\d+ typ srflx/);
      if (m) srflx.push(m[1]);
    };
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  const elapsed = await ended;
  pc.close();
  return {srflx, elapsed};
}"""


async def serve_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    # Every request is answered by the proxy itself: the page needs no origin.
    while (await reader.readline()) not in (b"\r\n", b""):
        pass
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                 b"Content-Length: %d\r\n\r\n%s" % (len(PAGE), PAGE))
    await writer.drain()
    writer.close()


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    proxy = await asyncio.start_server(serve_proxy, "127.0.0.1", 0)
    port = proxy.sockets[0].getsockname()[1]

    async with AsyncCamoufox(headless=True, os="linux", config={"webrtc:ipv4": SPOOFED_IP},
                             proxy={"server": f"http://127.0.0.1:{port}"}, geoip=False,
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        await page.goto("http://parity.test/")
        loopback = await page.evaluate(LOOPBACK)
        gathers = {where: await page.evaluate(GATHER, [INTERNET_STUN, where]) for where in FRAMES}
    proxy.close()

    checks = [
        ("peers on this machine connect", loopback["message"] == "ping", loopback["message"]),
        ("mDNS host candidates surface",
         bool(loopback["hosts"]) and all(".local " in c for c in loopback["hosts"]), loopback["hosts"]),
    ]
    for where, gather in gathers.items():
        checks += [
            (f"{where}: a STUN server on the internet is not asked",
             gather["elapsed"] is not None and gather["elapsed"] < 5000, gather["elapsed"]),
            (f"{where}: the only srflx carries the identity's address",
             gather["srflx"] == [SPOOFED_IP], gather["srflx"]),
        ]
    passed = True
    for label, ok, got in checks:
        print(f"  {'PASS' if ok else 'FAIL'} {label}: {got}")
        passed &= ok
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
