"""
Verify each context's WebRTC IP is the one its ICE candidates carry.

NewContext(webrtc_ip=...) hands the IP to the browser through setWebRTCIPv4,
which stores it for that context. PeerConnectionImpl only ever read the
launch-level `webrtc:ipv4`/`webrtc:ipv6` keys, so a per-context IP was stored
and never used: a context created behind its own proxy reported no public
address, or the launch-level one.

The probe gathers against a STUN server on this host that answers with a public
address, so a real srflx candidate forms with no network, and the browser must
replace that address with the context's. Against a server that never answers, no
srflx may appear: one says the server saw a request, and that server knows better.

What PASS means:
    * two contexts in one browser each see their own IP in a srflx candidate;
    * the launch-level `webrtc:ipv4` still reaches a plain new_page();
    * every candidate arrives before end-of-candidates;
    * a STUN server that never answers gets no srflx.

    python browser/tests/playwright/patches/webrtc-context-ip.py
"""

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import AnsweringStun, own_address, resolve_binary  # noqa: E402

LAUNCH_IP = "203.0.113.9"
CONTEXT_IPS = ("203.0.113.7", "203.0.113.8")

PROBE = """async (stun) => {
  const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  const srflx = [];
  let ended = false;
  const done = new Promise(resolve => {
    setTimeout(resolve, 30000);
    pc.onicecandidate = e => {
      if (!e.candidate) {
        ended = true;
        // Long past any STUN round trip, so a straggler would show up here.
        return setTimeout(resolve, 1000);
      }
      if (ended) srflx.push('after end-of-candidates: ' + e.candidate.candidate);
      const m = e.candidate.candidate.match(/ (\\S+) \\d+ typ srflx/);
      if (m && !ended) srflx.push(m[1]);
    };
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  await done;
  pc.close();
  return srflx;
}"""


async def srflx_ips(page, stun: str) -> list:
    await page.goto("about:blank")
    return await page.evaluate(PROBE, stun)


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox, AsyncNewContext

    answering = AnsweringStun()
    stun = answering.url
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind((own_address(), 0))

    checks = []
    async with AsyncCamoufox(headless=True, os="linux", config={"webrtc:ipv4": LAUNCH_IP},
                             i_know_what_im_doing=True,
                             executable_path=str(resolve_binary())) as browser:
        page = await browser.new_page()
        checks.append(("launch-level", [LAUNCH_IP], await srflx_ips(page, stun)))
        checks.append(("a STUN server that never answers", [],
                       await srflx_ips(page, "stun:{}:{}".format(*silent.getsockname()))))
        for ip in CONTEXT_IPS:
            context = await AsyncNewContext(browser, os="linux", webrtc_ip=ip)
            checks.append((f"context {ip}", [ip], await srflx_ips(await context.new_page(), stun)))
    answering.close()
    silent.close()

    passed = True
    for label, expected, got in checks:
        if got == expected:
            print(f"  PASS {label}: srflx {got}")
        else:
            passed = False
            print(f"  FAIL {label}: srflx {got}, expected {expected!r}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
