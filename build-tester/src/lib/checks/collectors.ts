"use client";

import type { FingerprintData, WebRTCResult } from "../types";

function simpleHash(data: Float32Array | Uint8Array): string {
  let hash = 0;
  for (let i = 0; i < data.length; i++) {
    const val = data[i];
    hash = ((hash << 5) - hash + (val * 1000000) | 0) | 0;
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function canvasHash(operations: (ctx: CanvasRenderingContext2D) => void): string {
  const canvas = document.createElement("canvas");
  canvas.width = 200;
  canvas.height = 50;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "no-context";
  operations(ctx);
  return canvas.toDataURL().substring(0, 100);
}

export async function collectFingerprints(): Promise<FingerprintData> {
  // Navigator
  const nav = {
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    oscpu: (navigator as any).oscpu || "",
    hardwareConcurrency: navigator.hardwareConcurrency || 0,
    maxTouchPoints: navigator.maxTouchPoints || 0,
    vendor: navigator.vendor || "",
    buildID: (navigator as any).buildID || "",
    doNotTrack: navigator.doNotTrack || "",
  };

  // Screen
  const scr = {
    width: screen.width,
    height: screen.height,
    colorDepth: screen.colorDepth,
    devicePixelRatio: window.devicePixelRatio || 1,
    availWidth: screen.availWidth,
    availHeight: screen.availHeight,
    pixelDepth: screen.pixelDepth,
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    outerWidth: window.outerWidth,
    outerHeight: window.outerHeight,
  };

  // Timezone
  const tz = {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    offset: new Date().getTimezoneOffset(),
    localTime: new Date().toLocaleTimeString(),
  };

  // WebGL
  let webgl: FingerprintData["webgl"] = null;
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
    if (gl && gl instanceof WebGLRenderingContext) {
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      webgl = {
        vendor: gl.getParameter(gl.VENDOR) || "",
        renderer: gl.getParameter(gl.RENDERER) || "",
        unmaskedVendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) || "" : "",
        unmaskedRenderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "" : "",
        maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE) || 0,
      };
    }
  } catch {}

  // Canvas
  const canvasData = (() => {
    try {
      const c = document.createElement("canvas");
      c.width = 200;
      c.height = 50;
      const ctx = c.getContext("2d");
      if (!ctx) return { hash: "no-context", dataUrlPrefix: "" };
      ctx.textBaseline = "top";
      ctx.font = "14px Arial";
      ctx.fillStyle = "#f60";
      ctx.fillRect(125, 1, 62, 20);
      ctx.fillStyle = "#069";
      ctx.fillText("Cwm fjordbank", 2, 15);
      ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
      ctx.fillText("Cwm fjordbank", 4, 17);
      const url = c.toDataURL();
      return { hash: url.substring(0, 100), dataUrlPrefix: url.substring(0, 30) };
    } catch {
      return { hash: "error", dataUrlPrefix: "" };
    }
  })();

  // Audio
  const audioData = await (async () => {
    try {
      const offCtx = new OfflineAudioContext(1, 44100, 44100);
      const osc = offCtx.createOscillator();
      const comp = offCtx.createDynamicsCompressor();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(10000, offCtx.currentTime);
      comp.threshold.setValueAtTime(-50, offCtx.currentTime);
      comp.knee.setValueAtTime(40, offCtx.currentTime);
      comp.ratio.setValueAtTime(12, offCtx.currentTime);
      comp.attack.setValueAtTime(0, offCtx.currentTime);
      comp.release.setValueAtTime(0.25, offCtx.currentTime);
      osc.connect(comp);
      comp.connect(offCtx.destination);
      osc.start(0);
      const rendered = await offCtx.startRendering();
      const channelData = rendered.getChannelData(0);
      const hash = simpleHash(channelData);

      // copyFromChannel
      const copyBuf = new Float32Array(channelData.length);
      rendered.copyFromChannel(copyBuf, 0);
      const copyHash = simpleHash(copyBuf);

      // Analyser methods (use realtime context briefly)
      let analyserFloat = "n/a";
      let analyserByte = "n/a";
      let analyserTimeDomainFloat = "n/a";
      let analyserTimeDomainByte = "n/a";
      try {
        const rtCtx = new AudioContext();
        const analyser = rtCtx.createAnalyser();
        analyser.fftSize = 256;
        const osc2 = rtCtx.createOscillator();
        osc2.connect(analyser);
        osc2.start(0);
        await new Promise((r) => setTimeout(r, 100));
        const floatFreq = new Float32Array(analyser.frequencyBinCount);
        analyser.getFloatFrequencyData(floatFreq);
        analyserFloat = simpleHash(floatFreq);
        const byteFreq = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(byteFreq);
        analyserByte = simpleHash(byteFreq);
        const floatTime = new Float32Array(analyser.frequencyBinCount);
        analyser.getFloatTimeDomainData(floatTime);
        analyserTimeDomainFloat = simpleHash(floatTime);
        const byteTime = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteTimeDomainData(byteTime);
        analyserTimeDomainByte = simpleHash(byteTime);
        osc2.stop();
        await rtCtx.close();
      } catch {}

      return {
        hash,
        sampleRate: offCtx.sampleRate,
        methods: {
          getChannelData: hash,
          copyFromChannel: copyHash,
          analyserFloat,
          analyserByte,
          analyserTimeDomainFloat,
          analyserTimeDomainByte,
        },
      };
    } catch {
      return {
        hash: "error",
        sampleRate: 0,
        methods: {
          getChannelData: "error",
          copyFromChannel: "error",
          analyserFloat: "error",
          analyserByte: "error",
          analyserTimeDomainFloat: "error",
          analyserTimeDomainByte: "error",
        },
      };
    }
  })();

  // Font metrics — use "Arial" (concrete font name) instead of "monospace" (generic family).
  // The fontPlatformConsistency check in extended.ts calls isFontAvailable() 11 times with
  // different font families + monospace fallback, which pollutes fontconfig's generic family
  // resolution cache. On macOS Global (CAMOU_CONFIG), this causes "monospace" to resolve to
  // a different actual font between the two collectFingerprints() calls (42.6px delta observed).
  // Arial is a concrete font always available in all Camoufox font lists, immune to this.
  await document.fonts.ready;
  const fontData = (() => {
    try {
      const c = document.createElement("canvas");
      const ctx = c.getContext("2d");
      if (!ctx) return { measureWidth: 0, hash: "no-context" };
      ctx.font = "72px Arial";
      const w = ctx.measureText("mmmmmmmmmmlli").width;
      return { measureWidth: w, hash: w.toFixed(4) };
    } catch {
      return { measureWidth: 0, hash: "error" };
    }
  })();

  // Client rects
  const clientRectsData = (() => {
    try {
      const el = document.createElement("div");
      el.style.cssText = "position:absolute;left:-9999px;font-size:16px;font-family:Arial;";
      el.textContent = "The quick brown fox jumps over the lazy dog";
      document.body.appendChild(el);
      const range = document.createRange();
      range.selectNode(el);
      const rects = range.getClientRects();
      document.body.removeChild(el);
      let hash = "";
      for (let i = 0; i < rects.length; i++) {
        hash += rects[i].width.toFixed(4) + rects[i].height.toFixed(4);
      }
      return { hash };
    } catch {
      return { hash: "error" };
    }
  })();

  // Emoji canvas
  const emojiData = (() => {
    try {
      const c = document.createElement("canvas");
      c.width = 200;
      c.height = 50;
      const ctx = c.getContext("2d");
      if (!ctx) return { hash: "no-context" };
      ctx.font = "32px serif";
      ctx.fillText("\uD83D\uDE00\uD83D\uDC4D\uD83C\uDFE0\u2764\uFE0F", 0, 40);
      return { hash: c.toDataURL().substring(50, 120) };
    } catch {
      return { hash: "error" };
    }
  })();

  // Font availability
  const fontAvailData = (() => {
    try {
      const testFonts = [
        "Arial", "Helvetica", "Times New Roman", "Courier New", "Georgia",
        "Verdana", "Trebuchet MS", "Lucida Console", "Tahoma", "Impact",
        "Comic Sans MS", "Palatino Linotype", "Garamond", "Bookman Old Style",
        "Menlo", "Monaco", "Consolas", "Segoe UI", "Roboto", "Ubuntu",
        "SF Pro", "Helvetica Neue", "PingFang SC", "Arimo", "Cousine", "Tinos",
        "DejaVu Sans", "Liberation Sans", "Noto Sans",
      ];
      const c = document.createElement("canvas");
      const ctx = c.getContext("2d");
      if (!ctx) return { detected: [], count: 0, hash: "no-context" };
      const baseline = "mmmmmmmmmmlli";
      ctx.font = "72px monospace";
      const baseWidth = ctx.measureText(baseline).width;
      const detected: string[] = [];
      for (const font of testFonts) {
        ctx.font = `72px "${font}", monospace`;
        const w = ctx.measureText(baseline).width;
        if (Math.abs(w - baseWidth) > 0.1) {
          detected.push(font);
        }
      }
      return {
        detected,
        count: detected.length,
        hash: detected.join(",").substring(0, 100),
      };
    } catch {
      return { detected: [], count: 0, hash: "error" };
    }
  })();

  // Speech voices
  const speechVoicesData = await (async () => {
    try {
      let voices = speechSynthesis.getVoices();
      if (voices.length === 0) {
        await new Promise<void>((resolve) => {
          speechSynthesis.onvoiceschanged = () => resolve();
          setTimeout(resolve, 2000);
        });
        voices = speechSynthesis.getVoices();
      }
      const names = voices.map((v) => v.name).sort();
      return { names, count: names.length, hash: names.join(",") };
    } catch {
      return { names: [] as string[], count: 0, hash: "error" };
    }
  })();

  return {
    navigator: nav,
    screen: scr,
    timezone: tz,
    webgl,
    canvas: canvasData,
    audio: audioData,
    fonts: fontData,
    clientRects: clientRectsData,
    emojiCanvas: emojiData,
    fontAvailability: fontAvailData,
    speechVoices: speechVoicesData,
  };
}

export async function checkWebRTC(): Promise<WebRTCResult> {
  const result: WebRTCResult = {
    passed: true,
    iceIPs: [],
    sdpSanitized: true,
    getStatsClean: true,
    candidateCount: 0,
    detail: "",
  };

  try {
    if (typeof RTCPeerConnection === "undefined") {
      return { ...result, detail: "RTCPeerConnection not available" };
    }

    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });

    const ips = new Set<string>();

    const candidatePromise = new Promise<void>((resolve) => {
      const timeout = setTimeout(resolve, 5000);
      pc.onicecandidate = (e) => {
        if (!e.candidate) {
          clearTimeout(timeout);
          resolve();
          return;
        }
        result.candidateCount++;
        const candidateStr = e.candidate.candidate;
        // Extract IP from candidate string
        const ipMatch = candidateStr.match(
          /(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){7}/
        );
        if (ipMatch) ips.add(ipMatch[0]);
        // Check address property
        if (e.candidate.address) ips.add(e.candidate.address);
      };
    });

    pc.createDataChannel("test");
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // Check SDP for IP leaks
    const sdp = pc.localDescription?.sdp || "";
    const privateIPRegex =
      /(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})/;
    if (privateIPRegex.test(sdp)) {
      result.sdpSanitized = false;
    }

    await candidatePromise;

    // Check getStats for IP leaks
    try {
      const stats = await pc.getStats();
      stats.forEach((report) => {
        if (
          report.type === "local-candidate" ||
          report.type === "remote-candidate"
        ) {
          if (report.address) ips.add(report.address);
          if (report.ip) ips.add(report.ip);
        }
      });
    } catch {
      // getStats may fail, that's fine
    }

    pc.close();

    result.iceIPs = Array.from(ips);

    // Check for private IPs in ICE candidates
    const hasPrivateIP = result.iceIPs.some((ip) =>
      privateIPRegex.test(ip)
    );

    if (hasPrivateIP) {
      result.passed = false;
      result.detail =
        "Private IP leaked in ICE candidates: " + result.iceIPs.join(", ");
    } else if (!result.sdpSanitized) {
      result.passed = false;
      result.detail = "Private IP found in SDP";
    } else if (result.iceIPs.length === 0) {
      result.detail =
        "No ICE candidates collected (may be blocked or STUN unreachable)";
    } else {
      result.detail =
        "WebRTC clean - " +
        result.candidateCount +
        " candidates, no private IP leaks";
    }
  } catch (e: any) {
    result.detail = "WebRTC check failed: " + e.message;
  }

  return result;
}
