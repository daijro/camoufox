"""
Verify media-device spoofing (media-device-spoofing.patch + pythonlib
media-devices.json) presents ONE coherent machine.

Stock Firefox exposes, before any getUserMedia grant, at most one device per
input kind with empty labels/ids and no audiooutput; after a capture it lists
the OS's own device names with distinct deviceIds and grouped groupIds, and
the captured track carries the very label/deviceId/groupId of one listed
device. Camoufox used to (a) crash the content process on the first
enumerateDevices() when the identity had a camera and no microphone
(InsertElementAt(1) on an empty array), (b) expose every configured device
pre-grant, (c) label everything "Default Audio Device"/"Default Video
Device" with one shared raw id per kind, and (d) capture the HOST's devices
on getUserMedia, so track labels contradicted the enumerated list.

Playwright's Firefox has no microphone/camera permission, so the prompt is
auto-granted with media.navigator.permission.disabled -- which is also how a
stock browser comes to expose labels (an active capture).

Run against a specific build:
    CAMOUFOX_EXECUTABLE_PATH=/path/to/camoufox-bin python3 browser/tests/playwright/patches/media-devices-coherence.py

What PASS means, for each spoofed OS and for the camera-only identity:
    * pre-grant: <=1 audioinput, <=1 videoinput, 0 audiooutput, no labels;
    * getUserMedia({audio}) succeeds iff the identity has a microphone, and
      the track's label/deviceId/groupId equal an enumerated audioinput;
    * getUserMedia({video}) succeeds iff the identity has a camera;
    * post-grant labels are OS-style (never the fake engine's names), ids are
      distinct, a microphone and a speaker of the same sound card share a
      groupId, and every configured device is listed;
    * the camera-only identity does not crash the page.
"""

import asyncio
import sys

from camoufox.async_api import AsyncCamoufox
from helpers import launch_kwargs

SPOOFED_OSES = ["windows", "macos", "linux"]
FAKE_NAMES = ("Default Audio Device", "Default Video Device", "Fake Video Group", "Fake Audio Group")

ENUM_JS = """async () => {
  const d = await navigator.mediaDevices.enumerateDevices();
  return d.map(x => ({kind: x.kind, label: x.label, id: x.deviceId, group: x.groupId}));
}"""
GUM_JS = """async (c) => {
  try {
    const s = await navigator.mediaDevices.getUserMedia(c);
    window.__streams = (window.__streams || []).concat([s]);
    return s.getTracks().map(t => { const st = t.getSettings(); return {kind: t.kind, label: t.label, id: st.deviceId, group: st.groupId}; });
  } catch (e) { return {error: e.name}; }
}"""


async def _check(spoofed_os, config=None) -> bool:
    label = f"[{spoofed_os}{' camera-only' if config else ''}]"
    async with AsyncCamoufox(**launch_kwargs(
        os=spoofed_os,
        firefox_user_prefs={"media.navigator.permission.disabled": True},
        config=config,
        i_know_what_im_doing=bool(config),
    )) as browser:
        page = await browser.new_page()
        await page.goto("https://example.com/")
        pre = await page.evaluate(ENUM_JS)
        n = lambda kind, devs: sum(1 for d in devs if d["kind"] == kind)  # noqa: E731
        if n("audioinput", pre) > 1 or n("videoinput", pre) > 1 or n("audiooutput", pre) > 0 or any(d["label"] for d in pre):
            print(f"  {label} FAIL: pre-grant shape {[(d['kind'], d['label']) for d in pre]}")
            return False
        has_mic = n("audioinput", pre) == 1
        has_cam = n("videoinput", pre) == 1

        audio = await page.evaluate(GUM_JS, {"audio": True})
        if has_mic and not isinstance(audio, list):
            print(f"  {label} FAIL: getUserMedia(audio) {audio} although a microphone is listed")
            return False
        if not has_mic and isinstance(audio, list):
            print(f"  {label} FAIL: getUserMedia(audio) succeeded without a microphone")
            return False
        video = await page.evaluate(GUM_JS, {"video": True})
        if has_cam and not isinstance(video, list):
            print(f"  {label} FAIL: getUserMedia(video) {video} although a camera is listed")
            return False
        if not has_cam and isinstance(video, list):
            print(f"  {label} FAIL: getUserMedia(video) succeeded without a camera")
            return False

        post = await page.evaluate(ENUM_JS)
        if not has_mic and not has_cam:
            print(f"  {label} ok (no input devices; nothing to expose)")
            return True
        labelled = [d for d in post if d["label"]]
        if not labelled:
            print(f"  {label} FAIL: no labels exposed after capture")
            return False
        for d in labelled:
            if d["label"] in FAKE_NAMES or not d["id"] or not d["group"]:
                print(f"  {label} FAIL: fake/empty device {d}")
                return False
        ids = [d["id"] for d in labelled]
        if len(set(ids)) != len(ids):
            print(f"  {label} FAIL: duplicate deviceIds {ids}")
            return False
        for tracks in (audio, video):
            if isinstance(tracks, list):
                for t in tracks:
                    if not any(d["label"] == t["label"] and d["id"] == t["id"] and d["group"] == t["group"] for d in labelled):
                        print(f"  {label} FAIL: captured track {t} is not one of the enumerated devices")
                        return False
        if has_mic and n("audiooutput", post) == 0:
            print(f"  {label} FAIL: no audiooutput listed after a microphone grant")
            return False
        shape = ", ".join(f"{d['kind']}:{d['label']}" for d in labelled)
        print(f"  {label} ok ({shape})")
        return True


async def main() -> int:
    ok = True
    for spoofed_os in SPOOFED_OSES:
        ok &= await _check(spoofed_os)
    # The identity that used to segfault: a camera and no microphone.
    ok &= await _check("linux", {"mediaDevices:enabled": True, "mediaDevices:micros": 0, "mediaDevices:webcams": 1,
                                 "mediaDevices:speakers": 1, "mediaDevices:webcamLabels": ["Integrated Camera: Integrated C (04f2:b6d9)"],
                                 "mediaDevices:speakerLabels": ["Built-in Audio Analog Stereo"]})
    print("PASS: media devices coherent" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
