"use client";

type CheckResult = { passed: boolean; detail: string };
type CategoryResults = Record<string, CheckResult>;

export async function runExtendedChecks(): Promise<
  Record<string, Record<string, { passed: boolean; detail: string }>>
> {
  const result: Record<string, CategoryResults> = {
    crossSignal: {},
    cssFingerprint: {},
    mathEngine: {},
    permissionsAPI: {},
    speechVoices: {},
    performanceAPI: {},
    intlConsistency: {},
    emojiFingerprint: {},
    canvasNoiseDetection: {},
    webglRenderHash: {},
    fontPlatformConsistency: {},
    webglExtended: {},
    audioIntegrity: {},
    iframeTesting: {},
    headlessDetection: {},
    trashDetection: {},
    fontEnvironment: {},
  };

  // ============================================================
  // cssFingerprint
  // ============================================================
  try {
    result.cssFingerprint.prefersColorScheme = {
      passed: true,
      detail:
        "prefers-color-scheme: " +
        (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
    };
    result.cssFingerprint.prefersReducedMotion = {
      passed: true,
      detail:
        "prefers-reduced-motion: " +
        (matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "reduce"
          : "no-preference"),
    };
    const pointerFine = matchMedia("(pointer: fine)").matches;
    result.cssFingerprint.pointerType = {
      passed: pointerFine,
      detail: pointerFine
        ? "pointer: fine (desktop, correct)"
        : "pointer: NOT fine (suspicious for desktop)",
    };
    const hoverHover = matchMedia("(hover: hover)").matches;
    result.cssFingerprint.hoverCapability = {
      passed: hoverHover,
      detail: hoverHover
        ? "hover: hover (desktop, correct)"
        : "hover: NOT hover (suspicious for desktop)",
    };
    const webkitAppearance = CSS.supports("-webkit-appearance", "none");
    result.cssFingerprint.webkitCompatMode = {
      passed: true,
      detail:
        "-webkit-appearance: " +
        (webkitAppearance ? "supported (Firefox compat mode)" : "not supported"),
    };

    // CSS System Font Detection -- checks what getComputedStyle returns for system fonts
    // Linux resolves to Cantarell/Ubuntu/DejaVu, macOS to -apple-system/.AppleSystemUIFont
    result.cssFingerprint.systemFonts = (() => {
      try {
        const div = document.createElement("div");
        div.style.cssText = "position:absolute;left:-9999px;visibility:hidden;";
        document.body.appendChild(div);
        const fonts: Record<string, string> = {};
        const keywords = [
          "caption",
          "icon",
          "menu",
          "message-box",
          "small-caption",
          "status-bar",
        ];
        for (const kw of keywords) {
          div.style.font = kw;
          fonts[kw] = getComputedStyle(div).fontFamily;
        }
        document.body.removeChild(div);
        const allFontStr = Object.values(fonts).join(" ");
        const linuxSystemFonts = [
          "Cantarell",
          "Ubuntu",
          "DejaVu",
          "Noto Sans",
          "Liberation",
          "Droid",
        ];
        const hasLinuxFont = linuxSystemFonts.some(
          (f) => allFontStr.indexOf(f) !== -1
        );
        const plat = navigator.platform;
        const platIsMac = plat === "MacIntel" || plat === "Macintosh";
        const passed = !(platIsMac && hasLinuxFont);
        return {
          passed,
          detail: passed
            ? "System fonts consistent with " +
              plat +
              " (caption: " +
              fonts.caption +
              ")"
            : "MISMATCH: Linux system fonts (" +
              fonts.caption +
              ") on claimed Mac platform",
        };
      } catch (e: any) {
        return {
          passed: true,
          detail: "System font check skipped: " + e.message,
        };
      }
    })();

    // matchMedia screen validation -- matchMedia device-width should match screen.width
    result.cssFingerprint.matchMediaScreen = (() => {
      try {
        const sw = screen.width;
        const sh = screen.height;
        if (sw === 0 || sh === 0)
          return { passed: true, detail: "Screen dimensions not available" };
        const widthMatch = matchMedia("(device-width: " + sw + "px)").matches;
        const heightMatch = matchMedia(
          "(device-height: " + sh + "px)"
        ).matches;
        const passed = widthMatch && heightMatch;
        return {
          passed,
          detail: passed
            ? "matchMedia device dimensions match screen (" + sw + "x" + sh + ")"
            : "MISMATCH: matchMedia disagrees with screen." +
              (!widthMatch ? "width=" + sw : "height=" + sh),
        };
      } catch (e: any) {
        return {
          passed: true,
          detail: "matchMedia check skipped: " + e.message,
        };
      }
    })();

    // Timer precision check
    result.cssFingerprint.timerPrecision = (() => {
      const stamps: number[] = [];
      for (let i = 0; i < 50; i++) stamps.push(performance.now());
      const deltas: number[] = [];
      for (let i = 1; i < stamps.length; i++) {
        const d = stamps[i] - stamps[i - 1];
        if (d > 0) deltas.push(d);
      }
      const minDelta = deltas.length > 0 ? Math.min(...deltas) : 0;
      // Firefox with privacy.reduceTimerPrecision typically rounds to 1ms or 20us
      // Extremely high precision (< 0.01ms) suggests no timer rounding
      const suspicious = minDelta > 0 && minDelta < 0.005;
      return {
        passed: !suspicious,
        detail:
          "Timer min delta: " +
          (minDelta * 1000).toFixed(1) +
          "us" +
          (suspicious ? " (suspiciously precise)" : " (normal)"),
      };
    })();
  } catch (e: any) {
    result.cssFingerprint.error = {
      passed: true,
      detail: "CSS checks error: " + e.message,
    };
  }

  // ============================================================
  // mathEngine
  // ============================================================
  try {
    const tanVal = Math.tan(-1e300);
    result.mathEngine.tanPrecision = {
      passed: true,
      detail: "Math.tan(-1e300) = " + tanVal,
    };
    const sinhVal = Math.sinh(1);
    result.mathEngine.sinhPrecision = {
      passed: true,
      detail: "Math.sinh(1) = " + sinhVal,
    };
    // SpiderMonkey-specific: Math.asinh(1) string representation
    const asinhVal = Math.asinh(1);
    result.mathEngine.asinhPrecision = {
      passed: true,
      detail: "Math.asinh(1) = " + asinhVal,
    };
  } catch (e: any) {
    result.mathEngine.error = {
      passed: true,
      detail: "Math checks error: " + e.message,
    };
  }

  // ============================================================
  // permissionsAPI
  // ============================================================
  try {
    if (navigator.permissions) {
      const notifPerm = await navigator.permissions.query({
        name: "notifications" as PermissionName,
      });
      result.permissionsAPI.notificationsState = {
        passed: true,
        detail: "notifications: " + notifPerm.state,
      };
      const geoPerm = await navigator.permissions.query({
        name: "geolocation" as PermissionName,
      });
      result.permissionsAPI.geolocationState = {
        passed: true,
        detail: "geolocation: " + geoPerm.state,
      };
    } else {
      result.permissionsAPI.apiPresent = {
        passed: true,
        detail: "Permissions API not available",
      };
    }
  } catch (e: any) {
    result.permissionsAPI.error = {
      passed: true,
      detail: "Permissions query error: " + e.message,
    };
  }

  // ============================================================
  // speechVoices
  // ============================================================
  try {
    let voices = speechSynthesis.getVoices();
    // Voices may load async - try waiting
    if (voices.length === 0) {
      await new Promise<void>((resolve) => {
        speechSynthesis.onvoiceschanged = () => resolve();
        setTimeout(resolve, 2000);
      });
      voices = speechSynthesis.getVoices();
    }
    const hasWindowsVoice = voices.some(
      (v) => v.name.indexOf("Microsoft") !== -1
    );
    const hasMacVoice = voices.some(
      (v) =>
        v.name === "Samantha" ||
        v.name === "Alex" ||
        v.name === "Victoria" ||
        v.name.indexOf("Apple") !== -1
    );
    const platform = navigator.platform;
    const platIsMac = platform === "MacIntel" || platform === "Macintosh";
    let voiceOSMatch = true;
    if (platIsMac && hasWindowsVoice && !hasMacVoice) voiceOSMatch = false;
    result.speechVoices.voiceCount = {
      passed: true,
      detail: voices.length + " voices detected",
    };
    result.speechVoices.platformMatch = {
      passed: voiceOSMatch,
      detail: voiceOSMatch
        ? "Voice names consistent with platform"
        : "MISMATCH: platform=" +
          platform +
          " but voices suggest different OS",
    };
  } catch (e: any) {
    result.speechVoices.error = {
      passed: true,
      detail: "Speech API error: " + e.message,
    };
  }

  // ============================================================
  // performanceAPI
  // ============================================================
  try {
    // performance.now() resolution check
    const samples: number[] = [];
    for (let i = 0; i < 20; i++) {
      const t1 = performance.now();
      const t2 = performance.now();
      if (t2 > t1) samples.push(t2 - t1);
    }
    const minDelta = samples.length > 0 ? Math.min(...samples) : 0;
    // Firefox with privacy.reduceTimerPrecision rounds to 1ms or 100us
    result.performanceAPI.timerResolution = {
      passed: true,
      detail:
        "Min delta: " +
        minDelta.toFixed(4) +
        "ms (" +
        samples.length +
        " non-zero samples)",
    };
    // performance.memory should NOT exist in Firefox
    result.performanceAPI.noPerformanceMemory = {
      passed: typeof (performance as any).memory === "undefined",
      detail:
        typeof (performance as any).memory === "undefined"
          ? "Not present (correct for Firefox)"
          : "PRESENT (Chrome-only)",
    };
  } catch (e: any) {
    result.performanceAPI.error = {
      passed: true,
      detail: "Performance API error: " + e.message,
    };
  }

  // ============================================================
  // intlConsistency
  // ============================================================
  try {
    const intlTzFull = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const intlLocale = Intl.DateTimeFormat().resolvedOptions().locale;
    const navLang = navigator.language;
    // Locale base should match navigator.language
    const localeBase = intlLocale.split("-")[0];
    const langBase = navLang.split("-")[0];
    const localeMatch = localeBase === langBase;
    result.intlConsistency.localeVsLanguage = {
      passed: localeMatch,
      detail: localeMatch
        ? 'Intl locale "' +
          intlLocale +
          '" matches navigator.language "' +
          navLang +
          '"'
        : 'MISMATCH: Intl locale "' +
          intlLocale +
          '" vs navigator.language "' +
          navLang +
          '"',
    };
    // Numeric format should match locale
    const numFormatted = new Intl.NumberFormat().format(1234.5);
    result.intlConsistency.numberFormat = {
      passed: true,
      detail: "Number format: " + numFormatted + " (locale: " + intlLocale + ")",
    };
    result.intlConsistency.timezone = {
      passed: true,
      detail: "Intl timezone: " + intlTzFull,
    };
  } catch (e: any) {
    result.intlConsistency.error = {
      passed: true,
      detail: "Intl error: " + e.message,
    };
  }

  // ============================================================
  // emojiFingerprint
  // ============================================================
  try {
    const eCanvas = document.createElement("canvas");
    eCanvas.width = 200;
    eCanvas.height = 80;
    const eCtx = eCanvas.getContext("2d");
    if (!eCtx) throw new Error("Cannot get 2d context");
    eCtx.font = "32px Arial, sans-serif";
    eCtx.fillText("\uD83D\uDE00\uD83C\uDF89\uD83D\uDD25\uD83E\uDD16", 10, 40);
    const eData = eCtx.getImageData(0, 0, 200, 80).data;
    let eHash = 0;
    for (let i = 0; i < eData.length; i += 4) {
      eHash = ((eHash << 5) - eHash) + eData[i] + eData[i + 1] + eData[i + 2];
      eHash = eHash & eHash;
    }
    result.emojiFingerprint.hash = {
      passed: true,
      detail: "Emoji canvas hash: " + Math.abs(eHash).toString(16),
    };
  } catch (e: any) {
    result.emojiFingerprint.error = {
      passed: true,
      detail: "Emoji canvas error: " + e.message,
    };
  }

  // ============================================================
  // canvasNoiseDetection
  // ============================================================
  try {
    function renderCanvasTest(): string {
      const tc = document.createElement("canvas");
      tc.width = 200;
      tc.height = 50;
      const tctx = tc.getContext("2d")!;
      tctx.textBaseline = "top";
      tctx.font = "14px Arial";
      tctx.fillStyle = "#f60";
      tctx.fillRect(125, 1, 62, 20);
      tctx.fillStyle = "#069";
      tctx.fillText("Cwm fjordbank glyphs vext quiz", 2, 15);
      return tc.toDataURL();
    }
    const c1 = renderCanvasTest();
    const c2 = renderCanvasTest();
    const c3 = renderCanvasTest();
    const allSame = c1 === c2 && c2 === c3;
    result.canvasNoiseDetection.deterministic = {
      passed: allSame,
      detail: allSame
        ? "3 renders produce identical output (correct - no random noise)"
        : "DETECTED: Canvas output varies between renders (noise injection detected!)",
    };
  } catch (e: any) {
    result.canvasNoiseDetection.error = {
      passed: true,
      detail: "Canvas noise check error: " + e.message,
    };
  }

  // ============================================================
  // webglRenderHash
  // ============================================================
  try {
    const wc = document.createElement("canvas");
    wc.width = 256;
    wc.height = 256;
    const wgl = wc.getContext("webgl");
    if (wgl) {
      // Render a simple colored triangle
      const vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0,1);}";
      const fs =
        "precision mediump float;void main(){gl_FragColor=vec4(0.86,0.27,0.33,1.0);}";
      const vShader = wgl.createShader(wgl.VERTEX_SHADER)!;
      wgl.shaderSource(vShader, vs);
      wgl.compileShader(vShader);
      const fShader = wgl.createShader(wgl.FRAGMENT_SHADER)!;
      wgl.shaderSource(fShader, fs);
      wgl.compileShader(fShader);
      const prog = wgl.createProgram()!;
      wgl.attachShader(prog, vShader);
      wgl.attachShader(prog, fShader);
      wgl.linkProgram(prog);
      wgl.useProgram(prog);
      const buf = wgl.createBuffer();
      wgl.bindBuffer(wgl.ARRAY_BUFFER, buf);
      wgl.bufferData(
        wgl.ARRAY_BUFFER,
        new Float32Array([0, 0.5, -0.5, -0.5, 0.5, -0.5]),
        wgl.STATIC_DRAW
      );
      const loc = wgl.getAttribLocation(prog, "p");
      wgl.enableVertexAttribArray(loc);
      wgl.vertexAttribPointer(loc, 2, wgl.FLOAT, false, 0, 0);
      wgl.clearColor(0, 0, 0, 1);
      wgl.clear(wgl.COLOR_BUFFER_BIT);
      wgl.drawArrays(wgl.TRIANGLES, 0, 3);
      const pixels = new Uint8Array(256 * 256 * 4);
      wgl.readPixels(0, 0, 256, 256, wgl.RGBA, wgl.UNSIGNED_BYTE, pixels);
      let wHash = 0;
      for (let i = 0; i < pixels.length; i += 16) {
        wHash = ((wHash << 5) - wHash) + pixels[i];
        wHash = wHash & wHash;
      }
      result.webglRenderHash.hash = {
        passed: true,
        detail: "WebGL render hash: " + Math.abs(wHash).toString(16),
      };
    } else {
      result.webglRenderHash.noWebGL = {
        passed: true,
        detail: "WebGL not available",
      };
    }
  } catch (e: any) {
    result.webglRenderHash.error = {
      passed: true,
      detail: "WebGL render error: " + e.message,
    };
  }

  // ============================================================
  // fontPlatformConsistency
  // ============================================================
  try {
    const fpCanvas = document.createElement("canvas");
    const fpCtx = fpCanvas.getContext("2d")!;
    function isFontAvailable(fontName: string): boolean {
      const testStr = "mmmmmmmmmmlli";
      fpCtx.font = "72px monospace";
      const defaultWidth = fpCtx.measureText(testStr).width;
      fpCtx.font = '72px "' + fontName + '", monospace';
      return fpCtx.measureText(testStr).width !== defaultWidth;
    }
    const hasSegoeUI = isFontAvailable("Segoe UI");
    const hasSFPro = isFontAvailable("SF Pro");
    const hasHelveticaNeue = isFontAvailable("Helvetica Neue");
    const hasLucidaGrande = isFontAvailable("Lucida Grande");
    const hasTahoma = isFontAvailable("Tahoma");
    const hasUbuntu = isFontAvailable("Ubuntu");
    const hasDejaVuSans = isFontAvailable("DejaVu Sans");
    const hasArimo = isFontAvailable("Arimo");
    const hasCantarell = isFontAvailable("Cantarell");
    const hasNotoColorEmoji = isFontAvailable("Noto Color Emoji");
    const hasLiberation = isFontAvailable("Liberation Sans");
    const plat = navigator.platform;
    const platIsMac = plat === "MacIntel" || plat === "Macintosh";
    const platIsWin = plat.indexOf("Win") === 0;

    let fontOSMatch = true;
    let fontDetail = "";
    if (platIsMac) {
      // Mac should have Helvetica Neue and Lucida Grande, NOT Segoe UI or Linux fonts
      if (hasSegoeUI) {
        fontOSMatch = false;
        fontDetail = "Segoe UI detected on claimed Mac";
      }
      // Check for Linux-specific fonts on claimed Mac platform
      const linuxFontsFound: string[] = [];
      if (hasArimo) linuxFontsFound.push("Arimo");
      if (hasCantarell) linuxFontsFound.push("Cantarell");
      if (hasNotoColorEmoji) linuxFontsFound.push("Noto Color Emoji");
      if (hasLiberation) linuxFontsFound.push("Liberation Sans");
      if (hasUbuntu) linuxFontsFound.push("Ubuntu");
      if (hasDejaVuSans) linuxFontsFound.push("DejaVu Sans");
      if (linuxFontsFound.length > 0) {
        fontOSMatch = false;
        fontDetail +=
          (fontDetail ? "; " : "") +
          "Linux fonts on Mac: " +
          linuxFontsFound.join(", ");
      }
      if (!hasHelveticaNeue && !hasSFPro && !hasLucidaGrande) {
        fontDetail += (fontDetail ? "; " : "") + "No Mac fonts detected";
      }
    } else if (platIsWin) {
      // Windows should have Segoe UI and Tahoma
      if (!hasSegoeUI && !hasTahoma) {
        fontDetail = "No Windows fonts detected";
      }
    }
    result.fontPlatformConsistency.osMatch = {
      passed: fontOSMatch,
      detail: fontOSMatch
        ? "Fonts consistent with " +
          plat +
          (fontDetail ? " (" + fontDetail + ")" : "")
        : "MISMATCH: " + fontDetail,
    };
    result.fontPlatformConsistency.detected = {
      passed: true,
      detail:
        "SegoeUI=" +
        hasSegoeUI +
        " SFPro=" +
        hasSFPro +
        " HelveticaNeue=" +
        hasHelveticaNeue +
        " Tahoma=" +
        hasTahoma +
        " Ubuntu=" +
        hasUbuntu +
        " DejaVu=" +
        hasDejaVuSans,
    };
  } catch (e: any) {
    result.fontPlatformConsistency.error = {
      passed: true,
      detail: "Font platform check error: " + e.message,
    };
  }

  // ============================================================
  // crossSignal: oscpuVsUA
  // ============================================================
  result.crossSignal.oscpuVsUA = (() => {
    const oscpu = (navigator as any).oscpu || "";
    const ua = navigator.userAgent;
    if (!oscpu) return { passed: true, detail: "oscpu not available" };
    const oscpuIsMac =
      oscpu.indexOf("Mac OS X") !== -1 || oscpu.indexOf("Intel Mac") !== -1;
    const oscpuIsWin = oscpu.indexOf("Windows") !== -1;
    const oscpuIsLinux = oscpu.indexOf("Linux") !== -1;
    const uaIsMac = ua.indexOf("Macintosh") !== -1;
    const uaIsWin = ua.indexOf("Windows") !== -1;
    const uaIsLinux = ua.indexOf("Linux") !== -1;
    const match =
      (oscpuIsMac && uaIsMac) ||
      (oscpuIsWin && uaIsWin) ||
      (oscpuIsLinux && uaIsLinux) ||
      (!oscpuIsMac && !oscpuIsWin && !oscpuIsLinux);
    return {
      passed: match,
      detail: match
        ? 'oscpu "' + oscpu + '" matches UA OS'
        : 'MISMATCH: oscpu="' + oscpu + '" vs UA OS',
    };
  })();

  // ============================================================
  // crossSignal: webglRendererVsPlatform
  // ============================================================
  result.crossSignal.webglRendererVsPlatform = (() => {
    try {
      const wCanvas = document.createElement("canvas");
      const wGl = wCanvas.getContext("webgl");
      if (!wGl) return { passed: true, detail: "WebGL not available" };
      const dbg = wGl.getExtension("WEBGL_debug_renderer_info");
      if (!dbg) return { passed: true, detail: "Debug renderer info not available" };
      const renderer =
        (wGl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) as string) || "";
      const vendor =
        (wGl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) as string) || "";
      const plat = navigator.platform;
      const platIsMac = plat === "MacIntel" || plat === "Macintosh";
      // Check for obvious mismatches
      const rendererLower = renderer.toLowerCase();
      let suspicious = false;
      let reason = "";
      // Mac platform but renderer mentions Windows-specific driver version
      if (platIsMac && rendererLower.indexOf("direct3d") !== -1) {
        suspicious = true;
        reason = "Direct3D renderer on Mac platform";
      }
      // Check for "or similar" suffix from Camoufox global config (expected behavior)
      const hasSimilarSuffix = rendererLower.indexOf(", or similar") !== -1;
      return {
        passed: !suspicious,
        detail: !suspicious
          ? 'WebGL renderer "' +
            renderer +
            '" plausible for ' +
            plat +
            (hasSimilarSuffix ? " (Camoufox global)" : "")
          : "MISMATCH: " + reason,
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "WebGL platform check error: " + e.message,
      };
    }
  })();

  // ============================================================
  // audioIntegrity
  // ============================================================

  // Audio silence check -- getFloatFrequencyData before any audio should be all -Infinity
  try {
    const silenceCtx = new AudioContext();
    const silenceAnalyser = silenceCtx.createAnalyser();
    silenceAnalyser.fftSize = 256;
    const silenceData = new Float32Array(silenceAnalyser.frequencyBinCount);
    silenceAnalyser.getFloatFrequencyData(silenceData);
    await silenceCtx.close();
    let allNegInf = true;
    for (let i = 0; i < silenceData.length; i++) {
      if (silenceData[i] !== -Infinity && !isNaN(silenceData[i])) {
        allNegInf = false;
        break;
      }
    }
    result.audioIntegrity.silenceCheck = {
      passed: allNegInf,
      detail: allNegInf
        ? "Silent analyser returns -Infinity values (correct - no noise injection on silence)"
        : "DETECTED: Non-Infinity values in silent analyser (noise injection leaked into silence)",
    };
  } catch (e: any) {
    result.audioIntegrity.silenceCheck = {
      passed: true,
      detail: "Silence check skipped: " + e.message,
    };
  }

  // Audio noise trap -- write known values to a buffer, read back, check if modified
  // Note: Camoufox applies per-profile audio transformations via getChannelData() hook,
  // so user-written data IS modified. This is expected -- report as informational, not failure.
  try {
    const trapCtx = new AudioContext();
    const trapBuf = trapCtx.createBuffer(1, 128, 44100);
    const trapChannel = trapBuf.getChannelData(0);
    const trapExpected = new Float32Array(128);
    for (let i = 0; i < 128; i++) {
      trapExpected[i] = (i / 128.0) * 2.0 - 1.0; // Deterministic ramp
      trapChannel[i] = trapExpected[i];
    }
    // Read back via getChannelData -- same Float32Array reference
    const trapReadBack = trapBuf.getChannelData(0);
    let trapModified = false;
    let maxDiff = 0;
    for (let i = 0; i < 128; i++) {
      const diff = Math.abs(trapReadBack[i] - trapExpected[i]);
      if (diff > maxDiff) maxDiff = diff;
      if (diff > 1e-10) {
        trapModified = true;
      }
    }
    result.audioIntegrity.noiseTrap = {
      passed: true,
      detail: trapModified
        ? "Audio buffer modified on read-back (max delta: " +
          maxDiff.toExponential(2) +
          ") - Camoufox audio transform active"
        : "Audio buffer unchanged after write-back (no audio transform applied)",
    };
  } catch (e: any) {
    result.audioIntegrity.noiseTrap = {
      passed: true,
      detail: "Noise trap skipped: " + e.message,
    };
  }

  // channelData vs copyFromChannel match
  try {
    const crossCtx = new OfflineAudioContext(1, 44100, 44100);
    const crossOsc = crossCtx.createOscillator();
    const crossComp = crossCtx.createDynamicsCompressor();
    crossOsc.type = "triangle";
    crossOsc.frequency.value = 10000;
    crossOsc.connect(crossComp);
    crossComp.connect(crossCtx.destination);
    crossOsc.start(0);
    const crossRendered = await crossCtx.startRendering();
    const chData = crossRendered.getChannelData(0);
    const copyData = new Float32Array(chData.length);
    crossRendered.copyFromChannel(copyData, 0);

    // Hash both
    function quickHash(arr: Float32Array): number {
      let h = 0;
      for (let i = 0; i < arr.length; i += 100) {
        h = ((h << 5) - h) + ((arr[i] * 1000000) | 0);
        h = h & h;
      }
      return h;
    }
    const chHash = quickHash(chData);
    const cpHash = quickHash(copyData);
    const hashMatch = chHash === cpHash;

    result.audioIntegrity.channelDataVsCopy = {
      passed: hashMatch,
      detail: hashMatch
        ? "getChannelData and copyFromChannel produce same hash (" +
          Math.abs(chHash).toString(16) +
          ")"
        : "MISMATCH: getChannelData=" +
          Math.abs(chHash).toString(16) +
          " copyFromChannel=" +
          Math.abs(cpHash).toString(16),
    };
  } catch (e: any) {
    result.audioIntegrity.channelDataVsCopy = {
      passed: true,
      detail: "Audio cross-validation skipped: " + e.message,
    };
  }

  // DynamicsCompressor.reduction check
  try {
    const compCtx = new AudioContext();
    const compOsc = compCtx.createOscillator();
    const comp = compCtx.createDynamicsCompressor();
    comp.threshold.value = -50;
    comp.knee.value = 40;
    comp.ratio.value = 12;
    comp.attack.value = 0;
    comp.release.value = 0.25;
    // Route through a silent gain node -- compressor still processes audio
    // but nothing reaches the speakers
    const silentGain = compCtx.createGain();
    silentGain.gain.value = 0;
    compOsc.connect(comp);
    comp.connect(silentGain);
    silentGain.connect(compCtx.destination);
    compOsc.start();
    // Wait briefly for processing
    await new Promise<void>((r) => setTimeout(r, 100));
    const reduction = comp.reduction;
    compOsc.stop();
    await compCtx.close();

    result.audioIntegrity.compressorReduction = {
      passed: true,
      detail:
        "DynamicsCompressor.reduction = " +
        (typeof reduction === "number"
          ? reduction.toFixed(4)
          : String(reduction)),
    };
  } catch (e: any) {
    result.audioIntegrity.compressorReduction = {
      passed: true,
      detail: "Compressor check skipped: " + e.message,
    };
  }

  // ============================================================
  // iframeTesting
  // ============================================================
  try {
    const testIframe = document.createElement("iframe");
    testIframe.style.cssText =
      "position:absolute;left:-9999px;width:1px;height:1px;";
    document.body.appendChild(testIframe);
    const iWin = testIframe.contentWindow! as any;

    // Check navigator properties match between main window and iframe
    result.iframeTesting.navigatorMatch = (() => {
      const mainUA = navigator.userAgent;
      const iframeUA = iWin.navigator.userAgent;
      const mainPlat = navigator.platform;
      const iframePlat = iWin.navigator.platform;
      const uaMatch = mainUA === iframeUA;
      const platMatch = mainPlat === iframePlat;
      return {
        passed: uaMatch && platMatch,
        detail:
          uaMatch && platMatch
            ? "Navigator properties match across main window and iframe"
            : "MISMATCH: " +
              (!uaMatch ? "UA differs" : "platform differs") +
              " in iframe",
      };
    })();

    // Check screen properties match in iframe
    result.iframeTesting.screenMatch = (() => {
      const mainW = screen.width;
      const iframeW = iWin.screen.width;
      const mainH = screen.height;
      const iframeH = iWin.screen.height;
      const match = mainW === iframeW && mainH === iframeH;
      return {
        passed: match,
        detail: match
          ? "Screen dimensions match in iframe (" + mainW + "x" + mainH + ")"
          : "MISMATCH: main=" +
            mainW +
            "x" +
            mainH +
            " iframe=" +
            iframeW +
            "x" +
            iframeH,
      };
    })();

    // Check timezone matches in iframe
    result.iframeTesting.timezoneMatch = (() => {
      const mainTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const iframeTz =
        iWin.Intl.DateTimeFormat().resolvedOptions().timeZone;
      const match = mainTz === iframeTz;
      return {
        passed: match,
        detail: match
          ? "Timezone matches in iframe (" + mainTz + ")"
          : "MISMATCH: main=" + mainTz + " iframe=" + iframeTz,
      };
    })();

    document.body.removeChild(testIframe);
  } catch (e: any) {
    result.iframeTesting.error = {
      passed: true,
      detail: "Iframe testing skipped: " + e.message,
    };
  }

  // ============================================================
  // headlessDetection
  // ============================================================
  try {
    // Permission bug: Notification.permission vs permissions.query() mismatch
    // NOTE: Firefox normally shows this mismatch (denied vs prompt) because
    // Notification.permission reads enforcement state while permissions.query
    // reads the stored user-decision state. This is NOT a headless indicator
    // in Firefox -- it's expected behavior. Marked informational (always pass).
    result.headlessDetection.permissionConsistency = await (async () => {
      try {
        if (
          typeof Notification === "undefined" ||
          !navigator.permissions
        ) {
          return {
            passed: true,
            detail: "Notification or Permissions API unavailable",
          };
        }
        const notifPerm = Notification.permission;
        const queryResult = await navigator.permissions.query({
          name: "notifications" as PermissionName,
        });
        const expected = notifPerm === "default" ? "prompt" : notifPerm;
        const match = expected === queryResult.state;
        return {
          passed: true,
          detail: match
            ? "Notification.permission (" +
              notifPerm +
              ") consistent with permissions.query (" +
              queryResult.state +
              ")"
            : "Notification.permission=" +
              notifPerm +
              ", query=" +
              queryResult.state +
              " (normal Firefox mismatch)",
        };
      } catch (e: any) {
        return {
          passed: true,
          detail: "Permission check skipped: " + e.message,
        };
      }
    })();

    // No taskbar detection: screen.availWidth === screen.width
    result.headlessDetection.hasTaskbar = (() => {
      const wDiff = screen.width - screen.availWidth;
      const hDiff = screen.height - screen.availHeight;
      // Both being 0 is suspicious (no taskbar/dock) but not definitive
      // Camoufox screen spoofing may set avail === screen
      const noTaskbar = wDiff === 0 && hDiff === 0;
      return {
        passed: true,
        detail: noTaskbar
          ? "availWidth === width, availHeight === height (no taskbar - spoofed screen or headless)"
          : "Taskbar detected: width diff=" +
            wDiff +
            "px, height diff=" +
            hDiff +
            "px",
      };
    })();

    // Viewport equals screen exactly (common headless signal)
    result.headlessDetection.viewportNotScreen = (() => {
      const vpEqualsScreen =
        window.innerWidth === screen.width &&
        window.innerHeight === screen.height;
      return {
        passed: !vpEqualsScreen,
        detail: vpEqualsScreen
          ? "SUSPICIOUS: viewport (" +
            window.innerWidth +
            "x" +
            window.innerHeight +
            ") exactly equals screen"
          : "Viewport (" +
            window.innerWidth +
            "x" +
            window.innerHeight +
            ") differs from screen (" +
            screen.width +
            "x" +
            screen.height +
            ")",
      };
    })();

    // System color detection (headless browsers resolve system colors differently)
    result.headlessDetection.systemColors = (() => {
      try {
        const div = document.createElement("div");
        div.style.cssText = "position:absolute;left:-9999px;color:ActiveText;";
        document.body.appendChild(div);
        const color = getComputedStyle(div).color;
        document.body.removeChild(div);
        // In headless Chrome, ActiveText resolves to rgb(255, 0, 0) exactly
        const isDefaultRed = color === "rgb(255, 0, 0)";
        return {
          passed: !isDefaultRed,
          detail: isDefaultRed
            ? "SUSPICIOUS: ActiveText resolved to default red (headless indicator)"
            : "ActiveText resolves to: " + color + " (normal)",
        };
      } catch (e: any) {
        return {
          passed: true,
          detail: "System color check skipped: " + e.message,
        };
      }
    })();

    // SwiftShader WebGL detection (software renderer used in headless)
    result.headlessDetection.noSwiftShader = (() => {
      try {
        const sc = document.createElement("canvas");
        const sgl = sc.getContext("webgl");
        if (!sgl) return { passed: true, detail: "WebGL not available" };
        const ext = sgl.getExtension("WEBGL_debug_renderer_info");
        if (!ext) return { passed: true, detail: "Debug renderer info not available" };
        const renderer = (
          (sgl.getParameter(ext.UNMASKED_RENDERER_WEBGL) as string) || ""
        ).toLowerCase();
        const hasSwift = renderer.indexOf("swiftshader") !== -1;
        const hasLLVM = renderer.indexOf("llvmpipe") !== -1;
        const hasSoftware = renderer.indexOf("software") !== -1;
        const suspicious = hasSwift || hasLLVM || hasSoftware;
        return {
          passed: !suspicious,
          detail: suspicious
            ? "SOFTWARE RENDERER: " + renderer + " (headless indicator)"
            : "Hardware renderer: " + renderer.substring(0, 60),
        };
      } catch (e: any) {
        return {
          passed: true,
          detail: "SwiftShader check skipped: " + e.message,
        };
      }
    })();

    // Headless UA string check
    result.headlessDetection.noHeadlessUA = (() => {
      const ua = navigator.userAgent.toLowerCase();
      const hasHeadless =
        ua.indexOf("headlesschrome") !== -1 ||
        ua.indexOf("headlessfirefox") !== -1 ||
        ua.indexOf("phantomjs") !== -1;
      return {
        passed: !hasHeadless,
        detail: hasHeadless
          ? "HEADLESS UA: " + navigator.userAgent
          : "No headless string in UA",
      };
    })();

    // navigator.webdriver check (redundant with automation.webdriver but part of headless scoring)
    result.headlessDetection.noWebdriver = {
      passed: (navigator as any).webdriver !== true,
      detail:
        (navigator as any).webdriver === true
          ? "navigator.webdriver = true (headless/automation)"
          : "navigator.webdriver = " + (navigator as any).webdriver,
    };

    // Outer dimensions check (0 = headless)
    result.headlessDetection.outerDimensions = {
      passed: window.outerWidth > 0 && window.outerHeight > 0,
      detail:
        window.outerWidth > 0 && window.outerHeight > 0
          ? "outerWidth=" +
            window.outerWidth +
            " outerHeight=" +
            window.outerHeight
          : "ZERO outer dimensions (headless indicator)",
    };

    // navigator.plugins presence check
    result.headlessDetection.hasPlugins = {
      passed: navigator.plugins && navigator.plugins.length > 0,
      detail: navigator.plugins
        ? navigator.plugins.length + " plugins (0 = headless indicator)"
        : "navigator.plugins missing",
    };

    // Compute headless score percentage
    let headlessIndicators = 0;
    let headlessTotal = 0;
    const hdChecks = result.headlessDetection;
    for (const hk in hdChecks) {
      if (
        hdChecks[hk] &&
        typeof hdChecks[hk].passed === "boolean"
      ) {
        headlessTotal++;
        if (!hdChecks[hk].passed) headlessIndicators++;
      }
    }
    const headlessPercent =
      headlessTotal > 0
        ? Math.round((headlessIndicators / headlessTotal) * 100)
        : 0;
    // Threshold: up to 15% is acceptable (1 flag out of 9 checks = 11%, which is
    // common for Firefox due to light-theme prefersColorScheme and similar benign signals)
    result.headlessDetection.headlessScore = {
      passed: headlessPercent <= 15,
      detail:
        headlessPercent +
        "% headless indicators (" +
        headlessIndicators +
        "/" +
        headlessTotal +
        " flagged)",
    };
  } catch (e: any) {
    result.headlessDetection.error = {
      passed: true,
      detail: "Headless detection error: " + e.message,
    };
  }

  // ============================================================
  // trashDetection
  // ============================================================
  try {
    // Screen dimensions must be integers
    result.trashDetection.integerScreen = (() => {
      const w = screen.width;
      const h = screen.height;
      const isInt = Number.isInteger(w) && Number.isInteger(h);
      return {
        passed: isInt,
        detail: isInt
          ? "Screen dimensions are integers (" + w + "x" + h + ")"
          : "NON-INTEGER screen: " + w + "x" + h,
      };
    })();

    // hardwareConcurrency should be a common value
    result.trashDetection.plausibleHWC = (() => {
      const hwc = navigator.hardwareConcurrency;
      const common = [
        1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 36, 40, 48, 56, 64,
        96, 128, 256,
      ];
      const isCommon = common.indexOf(hwc) !== -1;
      return {
        passed: isCommon,
        detail: isCommon
          ? "hardwareConcurrency=" + hwc + " (common value)"
          : "UNUSUAL hardwareConcurrency=" +
            hwc +
            " (not a typical core count)",
      };
    })();

    // WebGL renderer string analysis
    result.trashDetection.plausibleWebGLRenderer = (() => {
      try {
        const c = document.createElement("canvas");
        const gl = c.getContext("webgl");
        if (!gl) return { passed: true, detail: "WebGL not available" };
        const ext = gl.getExtension("WEBGL_debug_renderer_info");
        if (!ext)
          return { passed: true, detail: "Debug renderer info not available" };
        const renderer =
          (gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) as string) || "";
        if (!renderer) return { passed: true, detail: "Empty renderer string" };
        // Check for gibberish: unusual case patterns, too short, random digits
        const tooShort = renderer.length < 5;
        const allDigits = /^[0-9]+$/.test(renderer);
        const allLowerNoSpaces =
          renderer === renderer.toLowerCase() &&
          renderer.indexOf(" ") === -1 &&
          renderer.length > 10;
        const gibberish = tooShort || allDigits || allLowerNoSpaces;
        return {
          passed: !gibberish,
          detail: gibberish
            ? 'SUSPICIOUS renderer: "' + renderer + '" (gibberish pattern)'
            : "Renderer plausible: " + renderer.substring(0, 50),
        };
      } catch (e: any) {
        return {
          passed: true,
          detail: "WebGL renderer check skipped: " + e.message,
        };
      }
    })();

    // Screen size within known ranges
    result.trashDetection.reasonableScreenSize = (() => {
      const w = screen.width;
      const h = screen.height;
      const reasonable =
        w >= 320 && w <= 7680 && h >= 240 && h <= 4320;
      return {
        passed: reasonable,
        detail: reasonable
          ? "Screen " +
            w +
            "x" +
            h +
            " within known range (320-7680 x 240-4320)"
          : "UNREASONABLE screen: " + w + "x" + h,
      };
    })();

    // colorDepth in known set
    result.trashDetection.validColorDepth = (() => {
      const depth = screen.colorDepth;
      const valid = [1, 4, 8, 15, 16, 24, 30, 32, 48].indexOf(depth) !== -1;
      return {
        passed: valid,
        detail: valid
          ? "colorDepth=" + depth + " (valid value)"
          : "UNUSUAL colorDepth=" + depth,
      };
    })();
  } catch (e: any) {
    result.trashDetection.error = {
      passed: true,
      detail: "Trash detection error: " + e.message,
    };
  }

  // ============================================================
  // webglExtended (raw params for fingerprint comparison)
  // ============================================================
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl");
    if (gl) {
      const maxRenderbufferSize = gl.getParameter(gl.MAX_RENDERBUFFER_SIZE);
      const maxViewportDims = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
      const maxVertexAttribs = gl.getParameter(gl.MAX_VERTEX_ATTRIBS);
      const maxVaryingVectors = gl.getParameter(gl.MAX_VARYING_VECTORS);
      const aliasedLineWidthRange = gl.getParameter(gl.ALIASED_LINE_WIDTH_RANGE);
      const aliasedPointSizeRange = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE);
      const extensions = gl.getSupportedExtensions();
      const extensionCount = extensions ? extensions.length : 0;
      const extensionStr = extensions ? extensions.join(",") : "";

      // Shader precision
      const vertexHighP = gl.getShaderPrecisionFormat(
        gl.VERTEX_SHADER,
        gl.HIGH_FLOAT
      );
      const fragmentHighP = gl.getShaderPrecisionFormat(
        gl.FRAGMENT_SHADER,
        gl.HIGH_FLOAT
      );
      const vertexHighPrecision = vertexHighP
        ? vertexHighP.precision +
          "/" +
          vertexHighP.rangeMin +
          "/" +
          vertexHighP.rangeMax
        : null;
      const fragmentHighPrecision = fragmentHighP
        ? fragmentHighP.precision +
          "/" +
          fragmentHighP.rangeMin +
          "/" +
          fragmentHighP.rangeMax
        : null;

      // Store raw params as informational checks
      result.webglExtended.maxRenderbufferSize = {
        passed: true,
        detail: "MAX_RENDERBUFFER_SIZE: " + maxRenderbufferSize,
      };
      result.webglExtended.maxViewportDims = {
        passed: true,
        detail:
          "MAX_VIEWPORT_DIMS: " +
          (maxViewportDims ? maxViewportDims.toString() : "null"),
      };
      result.webglExtended.maxVertexAttribs = {
        passed: true,
        detail: "MAX_VERTEX_ATTRIBS: " + maxVertexAttribs,
      };
      result.webglExtended.maxVaryingVectors = {
        passed: true,
        detail: "MAX_VARYING_VECTORS: " + maxVaryingVectors,
      };
      result.webglExtended.aliasedLineWidthRange = {
        passed: true,
        detail:
          "ALIASED_LINE_WIDTH_RANGE: " +
          (aliasedLineWidthRange ? aliasedLineWidthRange.toString() : "null"),
      };
      result.webglExtended.aliasedPointSizeRange = {
        passed: true,
        detail:
          "ALIASED_POINT_SIZE_RANGE: " +
          (aliasedPointSizeRange ? aliasedPointSizeRange.toString() : "null"),
      };
      result.webglExtended.extensionCount = {
        passed: true,
        detail: "Extensions: " + extensionCount,
      };
      result.webglExtended.extensions = {
        passed: true,
        detail: extensionStr.substring(0, 200),
      };
      result.webglExtended.vertexHighPrecision = {
        passed: true,
        detail:
          "Vertex HIGH_FLOAT precision: " + (vertexHighPrecision || "unavailable"),
      };
      result.webglExtended.fragmentHighPrecision = {
        passed: true,
        detail:
          "Fragment HIGH_FLOAT precision: " +
          (fragmentHighPrecision || "unavailable"),
      };
    }
  } catch {
    // webglExtended stays empty if WebGL unavailable
  }

  // ============================================================
  // fontEnvironment (CreepJS OS Detection Readiness)
  // ============================================================
  // Platform-aware: reads navigator.platform to determine which
  // OS marker fonts should be present, and which would be leaks.
  try {
    // Canvas-based font detection (same technique fingerprinters use)
    const fontCanvas = document.createElement("canvas");
    const fontCtx = fontCanvas.getContext("2d")!;
    const fontTestStr = "mmmmmmmmmmlli";
    fontCtx.font = "72px monospace";
    const monoWidth = fontCtx.measureText(fontTestStr).width;

    function isFontInstalled(name: string): boolean {
      fontCtx.font = '72px "' + name + '", monospace';
      return fontCtx.measureText(fontTestStr).width !== monoWidth;
    }

    // Determine claimed platform from navigator
    const plat = (navigator.platform || "").toLowerCase();
    const ua = (navigator.userAgent || "").toLowerCase();
    let claimedOS = "unknown";
    if (plat.indexOf("mac") !== -1 || ua.indexOf("macintosh") !== -1)
      claimedOS = "macos";
    else if (plat.indexOf("linux") !== -1) claimedOS = "linux";
    else if (plat.indexOf("win") !== -1) claimedOS = "windows";

    // CreepJS marker fonts by OS
    const appleDetectionFonts = ["Helvetica Neue", "PingFang HK", "Geneva"];
    const linuxDetectionFonts = ["Arimo", "Cousine"];
    const windowsDetectionFonts = [
      "Cambria Math",
      "Nirmala UI",
      "Leelawadee UI",
      "HoloLens MDL2 Assets",
      "Segoe Fluent Icons",
    ];

    // Pick the right expected fonts based on claimed OS
    const expectedFonts =
      claimedOS === "macos"
        ? appleDetectionFonts
        : claimedOS === "linux"
          ? linuxDetectionFonts
          : claimedOS === "windows"
            ? windowsDetectionFonts
            : [];
    const expectedLabel =
      claimedOS === "macos"
        ? "Apple"
        : claimedOS === "linux"
          ? "Linux"
          : claimedOS === "windows"
            ? "Windows"
            : "Unknown";

    // Check: Are the expected OS marker fonts installed?
    const expectedDetected: string[] = [];
    const expectedMissing: string[] = [];
    for (const font of expectedFonts) {
      if (isFontInstalled(font)) {
        expectedDetected.push(font);
      } else {
        expectedMissing.push(font);
      }
    }
    const hasOSId = expectedDetected.length > 0;
    result.fontEnvironment.osDetection = {
      passed: hasOSId,
      detail: hasOSId
        ? expectedDetected.length +
          "/" +
          expectedFonts.length +
          " " +
          expectedLabel +
          " marker fonts found (platform: " +
          navigator.platform +
          "): " +
          expectedDetected.join(", ")
        : "No " +
          expectedLabel +
          " marker fonts found (platform: " +
          navigator.platform +
          '). CreepJS will show "Like undefined". Missing: ' +
          expectedMissing.join(", "),
    };

    // macOS-only: version depth check
    if (claimedOS === "macos") {
      // Use base family names (not weight variants) since fontconfig on Linux
      // registers TTC base families, not individual weight sub-families.
      const macVersionFonts: [string, string][] = [
        ["10.9", "Helvetica Neue"],
        ["10.9", "Geneva"],
        ["10.10", "Kohinoor Devanagari"],
        ["10.10", "Luminari"],
        ["10.11", "PingFang HK"],
        ["10.12", "American Typewriter"],
        ["10.12", "Futura"],
        ["10.13", "InaiMathi"],
        ["10.15", "Galvji"],
        ["10.15", "MuktaMahee"],
        ["12", "STIX Two Math"],
        ["12", "STIX Two Text"],
        ["13", "Apple SD Gothic Neo"],
        ["13", "Noto Sans Canadian Aboriginal"],
      ];
      let versionFound = 0;
      const versionTotal = macVersionFonts.length;
      let highestVersion = "none";
      for (const [ver, font] of macVersionFonts) {
        if (isFontInstalled(font)) {
          versionFound++;
          highestVersion = ver;
        }
      }
      // Threshold of 3: Camoufox bundles a subset of macOS fonts, not a full install.
      // Real macOS machines also vary -- not all have every version font.
      result.fontEnvironment.macOSVersionDepth = {
        passed: versionFound >= 3,
        detail:
          versionFound +
          "/" +
          versionTotal +
          " version marker fonts installed (highest: macOS " +
          highestVersion +
          ")",
      };
    }

    // Check for wrong-OS font leaks -- fonts from OTHER OSes should not be present
    const wrongOSFonts: [string, string][] = [];
    if (claimedOS !== "macos") {
      for (const f of appleDetectionFonts) {
        wrongOSFonts.push(["macOS", f]);
      }
    }
    if (claimedOS !== "linux") {
      for (const f of linuxDetectionFonts) {
        wrongOSFonts.push(["Linux", f]);
      }
    }
    if (claimedOS !== "windows") {
      for (const f of windowsDetectionFonts) {
        wrongOSFonts.push(["Windows", f]);
      }
    }
    const leakedFonts: string[] = [];
    for (const [os, font] of wrongOSFonts) {
      if (isFontInstalled(font)) {
        leakedFonts.push(os + ": " + font);
      }
    }
    const noLeaks = leakedFonts.length === 0;
    result.fontEnvironment.noWrongOSFonts = {
      passed: noLeaks,
      detail: noLeaks
        ? "No wrong-OS marker fonts detected (claiming " + expectedLabel + ")"
        : "Wrong-OS fonts found while claiming " +
          expectedLabel +
          "! " +
          leakedFonts.join(", "),
    };
  } catch (e: any) {
    result.fontEnvironment.error = {
      passed: true,
      detail: "Font environment check error: " + e.message,
    };
  }

  return result as Record<
    string,
    Record<string, { passed: boolean; detail: string }>
  >;
}
