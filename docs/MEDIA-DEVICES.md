# Media devices

How Camoufox presents `navigator.mediaDevices` (`media-device-spoofing.patch`,
`python/src/camoufox/media-devices.json`, `draw_media_devices()`).

## What a page can see

Stock Firefox exposes, **before** any `getUserMedia` grant, at most one device
per input kind with empty `label`/`deviceId`/`groupId` and no `audiooutput`.
**After** a grant (or while capturing) it lists every device with the OS's own
names, per-origin hashed ids, and shared `groupId`s for devices of the same
hardware. The captured track's `label` and `getSettings().deviceId/groupId`
are those of one listed device.

Camoufox reproduces exactly that for a spoofed machine:

- The fake media engine (`MediaEngineFake::EnumerateDevices`) emits the
  identity's microphones, cameras and speakers, with labels, raw ids and
  groups from the config, and `MediaManager` uses it for mics/cams and for the
  outputs whenever `mediaDevices:enabled` is set. `MediaDevices.cpp` is stock,
  so the pre-/post-grant rules, feature policy, permission prompts, the
  capture indicator and the camera/microphone `groupId` correlation all run
  unchanged.
- `getUserMedia()` therefore succeeds iff the identity has the requested
  device kind (a claimed camera captures the fake engine's test pattern; a
  camera-less identity gets `NotFoundError`, like a real machine without one).
- The patch treats the identity's devices (`LocalMediaDevice::IsIdentityDevice()`)
  as real hardware, so they get the permission prompt, count as capturing
  and expose their labels after a grant. `media.navigator.permission.fake`
  stays off, as in stock Firefox, because a page can detect it.

## Config keys

| key | meaning |
| --- | --- |
| `mediaDevices:enabled` | use the identity's devices instead of the host's |
| `mediaDevices:micros` / `webcams` / `speakers` | counts |
| `mediaDevices:microphoneLabels` / `webcamLabels` / `speakerLabels` | labels, aligned with the counts |
| `mediaDevices:microphoneGroups` / `webcamGroups` / `speakerGroups` | raw group ids (same string = same `groupId`) |

The Python package draws all of them from `media-devices.json`, seeded by the
identity, unless the caller set any `mediaDevices:` key. Label styles follow
the OS: Windows WASAPI friendly names (`Microphone Array (Realtek(R) Audio)`),
macOS CoreAudio names (`MacBook Pro Microphone`, `FaceTime HD Camera`), Linux
PulseAudio/PipeWire descriptions plus v4l2 card names with the USB id, and a
`Monitor of …` source per output as PulseAudio exposes.

## Guard

`browser/tests/playwright/patches/media-devices-coherence.py` checks the
pre-grant shape, that capture succeeds exactly for listed kinds, that captured
tracks match listed devices, that labels are never the fake engine's, and that a
camera-only identity does not crash the content process (it did, before
build12).
