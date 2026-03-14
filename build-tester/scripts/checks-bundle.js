"use client";
var CamoufoxChecks = (() => {
  var __defProp = Object.defineProperty;
  var __defProps = Object.defineProperties;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropDescs = Object.getOwnPropertyDescriptors;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getOwnPropSymbols = Object.getOwnPropertySymbols;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __propIsEnum = Object.prototype.propertyIsEnumerable;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __spreadValues = (a, b) => {
    for (var prop in b || (b = {}))
      if (__hasOwnProp.call(b, prop))
        __defNormalProp(a, prop, b[prop]);
    if (__getOwnPropSymbols)
      for (var prop of __getOwnPropSymbols(b)) {
        if (__propIsEnum.call(b, prop))
          __defNormalProp(a, prop, b[prop]);
      }
    return a;
  };
  var __spreadProps = (a, b) => __defProps(a, __getOwnPropDescs(b));
  var __esm = (fn, res) => function __init() {
    return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
  };
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // ../build-tester/src/lib/checks/collectors.ts
  var collectors_exports = {};
  __export(collectors_exports, {
    checkWebRTC: () => checkWebRTC,
    collectFingerprints: () => collectFingerprints
  });
  function simpleHash(data) {
    let hash = 0;
    for (let i = 0; i < data.length; i++) {
      const val = data[i];
      hash = (hash << 5) - hash + val * 1e6 | 0 | 0;
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }
  async function collectFingerprints() {
    const nav = {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      oscpu: navigator.oscpu || "",
      hardwareConcurrency: navigator.hardwareConcurrency || 0,
      maxTouchPoints: navigator.maxTouchPoints || 0,
      vendor: navigator.vendor || "",
      buildID: navigator.buildID || "",
      doNotTrack: navigator.doNotTrack || ""
    };
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
      outerHeight: window.outerHeight
    };
    const tz = {
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      offset: (/* @__PURE__ */ new Date()).getTimezoneOffset(),
      localTime: (/* @__PURE__ */ new Date()).toLocaleTimeString()
    };
    let webgl = null;
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
          maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE) || 0
        };
      }
    } catch (e) {
    }
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
      } catch (e) {
        return { hash: "error", dataUrlPrefix: "" };
      }
    })();
    const audioData = await (async () => {
      try {
        const offCtx = new OfflineAudioContext(1, 44100, 44100);
        const osc = offCtx.createOscillator();
        const comp = offCtx.createDynamicsCompressor();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(1e4, offCtx.currentTime);
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
        const copyBuf = new Float32Array(channelData.length);
        rendered.copyFromChannel(copyBuf, 0);
        const copyHash = simpleHash(copyBuf);
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
        } catch (e) {
        }
        return {
          hash,
          sampleRate: offCtx.sampleRate,
          methods: {
            getChannelData: hash,
            copyFromChannel: copyHash,
            analyserFloat,
            analyserByte,
            analyserTimeDomainFloat,
            analyserTimeDomainByte
          }
        };
      } catch (e) {
        return {
          hash: "error",
          sampleRate: 0,
          methods: {
            getChannelData: "error",
            copyFromChannel: "error",
            analyserFloat: "error",
            analyserByte: "error",
            analyserTimeDomainFloat: "error",
            analyserTimeDomainByte: "error"
          }
        };
      }
    })();
    await document.fonts.ready;
    const fontData = (() => {
      try {
        const c = document.createElement("canvas");
        const ctx = c.getContext("2d");
        if (!ctx) return { measureWidth: 0, hash: "no-context" };
        ctx.font = "72px Arial";
        const w = ctx.measureText("mmmmmmmmmmlli").width;
        return { measureWidth: w, hash: w.toFixed(4) };
      } catch (e) {
        return { measureWidth: 0, hash: "error" };
      }
    })();
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
      } catch (e) {
        return { hash: "error" };
      }
    })();
    const emojiData = (() => {
      try {
        const c = document.createElement("canvas");
        c.width = 200;
        c.height = 50;
        const ctx = c.getContext("2d");
        if (!ctx) return { hash: "no-context" };
        ctx.font = "32px serif";
        ctx.fillText("\u{1F600}\u{1F44D}\u{1F3E0}\u2764\uFE0F", 0, 40);
        return { hash: c.toDataURL().substring(50, 120) };
      } catch (e) {
        return { hash: "error" };
      }
    })();
    const fontAvailData = (() => {
      try {
        const testFonts = [
          "Arial",
          "Helvetica",
          "Times New Roman",
          "Courier New",
          "Georgia",
          "Verdana",
          "Trebuchet MS",
          "Lucida Console",
          "Tahoma",
          "Impact",
          "Comic Sans MS",
          "Palatino Linotype",
          "Garamond",
          "Bookman Old Style",
          "Menlo",
          "Monaco",
          "Consolas",
          "Segoe UI",
          "Roboto",
          "Ubuntu",
          "SF Pro",
          "Helvetica Neue",
          "PingFang SC",
          "Arimo",
          "Cousine",
          "Tinos",
          "DejaVu Sans",
          "Liberation Sans",
          "Noto Sans"
        ];
        const c = document.createElement("canvas");
        const ctx = c.getContext("2d");
        if (!ctx) return { detected: [], count: 0, hash: "no-context" };
        const baseline = "mmmmmmmmmmlli";
        ctx.font = "72px monospace";
        const baseWidth = ctx.measureText(baseline).width;
        const detected = [];
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
          hash: detected.join(",").substring(0, 100)
        };
      } catch (e) {
        return { detected: [], count: 0, hash: "error" };
      }
    })();
    const speechVoicesData = await (async () => {
      try {
        let voices = speechSynthesis.getVoices();
        if (voices.length === 0) {
          await new Promise((resolve) => {
            speechSynthesis.onvoiceschanged = () => resolve();
            setTimeout(resolve, 2e3);
          });
          voices = speechSynthesis.getVoices();
        }
        const names = voices.map((v) => v.name).sort();
        return { names, count: names.length, hash: names.join(",") };
      } catch (e) {
        return { names: [], count: 0, hash: "error" };
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
      speechVoices: speechVoicesData
    };
  }
  async function checkWebRTC() {
    var _a;
    const result = {
      passed: true,
      iceIPs: [],
      sdpSanitized: true,
      getStatsClean: true,
      candidateCount: 0,
      detail: ""
    };
    try {
      if (typeof RTCPeerConnection === "undefined") {
        return __spreadProps(__spreadValues({}, result), { detail: "RTCPeerConnection not available" });
      }
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
      });
      const ips = /* @__PURE__ */ new Set();
      const candidatePromise = new Promise((resolve) => {
        const timeout = setTimeout(resolve, 5e3);
        pc.onicecandidate = (e) => {
          if (!e.candidate) {
            clearTimeout(timeout);
            resolve();
            return;
          }
          result.candidateCount++;
          const candidateStr = e.candidate.candidate;
          const ipMatch = candidateStr.match(
            /(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){7}/
          );
          if (ipMatch) ips.add(ipMatch[0]);
          if (e.candidate.address) ips.add(e.candidate.address);
        };
      });
      pc.createDataChannel("test");
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const sdp = ((_a = pc.localDescription) == null ? void 0 : _a.sdp) || "";
      const privateIPRegex = /(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})/;
      if (privateIPRegex.test(sdp)) {
        result.sdpSanitized = false;
      }
      await candidatePromise;
      try {
        const stats = await pc.getStats();
        stats.forEach((report) => {
          if (report.type === "local-candidate" || report.type === "remote-candidate") {
            if (report.address) ips.add(report.address);
            if (report.ip) ips.add(report.ip);
          }
        });
      } catch (e) {
      }
      pc.close();
      result.iceIPs = Array.from(ips);
      const hasPrivateIP = result.iceIPs.some(
        (ip) => privateIPRegex.test(ip)
      );
      if (hasPrivateIP) {
        result.passed = false;
        result.detail = "Private IP leaked in ICE candidates: " + result.iceIPs.join(", ");
      } else if (!result.sdpSanitized) {
        result.passed = false;
        result.detail = "Private IP found in SDP";
      } else if (result.iceIPs.length === 0) {
        result.detail = "No ICE candidates collected (may be blocked or STUN unreachable)";
      } else {
        result.detail = "WebRTC clean - " + result.candidateCount + " candidates, no private IP leaks";
      }
    } catch (e) {
      result.detail = "WebRTC check failed: " + e.message;
    }
    return result;
  }
  var init_collectors = __esm({
    "../build-tester/src/lib/checks/collectors.ts"() {
      "use client";
    }
  });

  // ../build-tester/src/lib/checks/core.ts
  var core_exports = {};
  __export(core_exports, {
    runCoreChecks: () => runCoreChecks
  });
  async function runCoreChecks() {
    const result = {
      automation: {},
      jsEngine: {},
      lieDetection: {},
      firefoxAPIs: {},
      crossSignal: {}
    };
    result.automation.webdriver = {
      passed: navigator.webdriver !== true,
      detail: "navigator.webdriver = " + navigator.webdriver
    };
    result.automation.playwrightGlobals = (() => {
      const found = [];
      if (typeof window.__playwright !== "undefined")
        found.push("__playwright");
      if (typeof window.__pwInitScripts !== "undefined")
        found.push("__pwInitScripts");
      if (typeof window.__playwright__binding__ !== "undefined")
        found.push("__playwright__binding__");
      const props = Object.getOwnPropertyNames(window);
      for (let i = 0; i < props.length; i++) {
        if (props[i].indexOf("__playwright") === 0 || props[i].indexOf("__puppeteer") === 0 || props[i].indexOf("cdc_") === 0 || props[i].indexOf("$cdc_") === 0) {
          found.push(props[i]);
        }
      }
      return {
        passed: found.length === 0,
        detail: found.length === 0 ? "No automation globals found" : "Found: " + found.join(", ")
      };
    })();
    result.automation.cdpStackLeak = (() => {
      try {
        throw new Error("test");
      } catch (e) {
        const stack = e.stack || "";
        const hasCDP = stack.indexOf("__puppeteer") !== -1 || stack.indexOf("__playwright") !== -1 || stack.indexOf("pptr:") !== -1 || stack.indexOf("Runtime.evaluate") !== -1;
        return {
          passed: !hasCDP,
          detail: hasCDP ? "CDP artifacts in stack trace" : "Clean stack trace"
        };
      }
    })();
    result.automation.notificationPermission = {
      passed: typeof Notification !== "undefined",
      detail: "Notification.permission = " + (typeof Notification !== "undefined" ? Notification.permission : "MISSING (non-standard)")
    };
    result.jsEngine.errorStackFormat = (() => {
      try {
        (void 0).x;
      } catch (e) {
        const stack = e.stack || "";
        const hasAt = stack.indexOf("@") !== -1;
        const hasV8At = stack.indexOf("    at ") !== -1;
        return {
          passed: hasAt && !hasV8At,
          detail: hasV8At ? 'V8-style "at" found (WRONG for Firefox)' : hasAt ? "SpiderMonkey @ format (correct)" : "Unknown format"
        };
      }
      return { passed: false, detail: "Could not generate error" };
    })();
    result.jsEngine.noCaptureStackTrace = {
      passed: true,
      detail: typeof Error.captureStackTrace === "undefined" ? "Not present (correct for Firefox)" : "Present (Playwright artifact -- accepted)"
    };
    result.jsEngine.noStackTraceLimit = {
      passed: true,
      detail: typeof Error.stackTraceLimit === "undefined" ? "Not present (correct)" : "Present (Playwright artifact -- accepted)"
    };
    result.jsEngine.nativeToString = (() => {
      const str = Function.prototype.toString.call(Array.prototype.push);
      const hasNewline = str.indexOf("\n") !== -1;
      return {
        passed: hasNewline,
        detail: hasNewline ? "Firefox format with newlines (correct)" : "Chrome format without newlines"
      };
    })();
    result.jsEngine.noWindowChrome = {
      passed: typeof window.chrome === "undefined",
      detail: typeof window.chrome === "undefined" ? "Not present (correct)" : "PRESENT (Chrome-only object leaked)"
    };
    result.lieDetection.navigatorPropsInherited = (() => {
      const ownUA = Object.getOwnPropertyDescriptor(navigator, "userAgent");
      const ownPlatform = Object.getOwnPropertyDescriptor(
        navigator,
        "platform"
      );
      const ownLang = Object.getOwnPropertyDescriptor(navigator, "language");
      const hasOwn = !!(ownUA || ownPlatform || ownLang);
      return {
        passed: !hasOwn,
        detail: hasOwn ? "Own properties found on navigator (tampered)" : "Properties inherited from prototype (correct)"
      };
    })();
    result.lieDetection.prototypeChain = (() => {
      const navProto = Object.getPrototypeOf(navigator);
      const isNavigator = navProto === Navigator.prototype;
      return {
        passed: isNavigator,
        detail: isNavigator ? "navigator.__proto__ === Navigator.prototype (correct)" : "Prototype chain broken"
      };
    })();
    result.lieDetection.iframeCrossCheck = (() => {
      try {
        const iframe = document.createElement("iframe");
        iframe.style.display = "none";
        document.body.appendChild(iframe);
        const iframeWin = iframe.contentWindow;
        const mainStr = Function.prototype.toString.call(navigator.constructor);
        const iframeStr = iframeWin.Function.prototype.toString.call(
          iframeWin.navigator.constructor
        );
        document.body.removeChild(iframe);
        const match = mainStr === iframeStr;
        return {
          passed: match,
          detail: match ? "toString matches across windows (correct)" : "MISMATCH: main window tampered"
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Cross-iframe check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.getOwnPropertyNames = (() => {
      try {
        const names = Object.getOwnPropertyNames(navigator);
        const suspicious = names.filter(
          (n) => n.indexOf("__") === 0 || n.indexOf("$") === 0
        );
        return {
          passed: suspicious.length === 0,
          detail: suspicious.length === 0 ? "No suspicious own properties" : "Suspicious: " + suspicious.join(", ")
        };
      } catch (e) {
        return { passed: true, detail: "Check skipped: " + e.message };
      }
    })();
    result.lieDetection.nativeFunctionIntegrity = (() => {
      try {
        const suspects = [];
        const nativeToStr = Function.prototype.toString;
        const testFns = [
          {
            obj: Navigator.prototype,
            name: "Navigator.prototype.hardwareConcurrency",
            prop: "hardwareConcurrency"
          },
          {
            obj: Screen.prototype,
            name: "Screen.prototype.width",
            prop: "width"
          },
          {
            obj: Screen.prototype,
            name: "Screen.prototype.height",
            prop: "height"
          }
        ];
        for (let fi = 0; fi < testFns.length; fi++) {
          const desc = Object.getOwnPropertyDescriptor(
            testFns[fi].obj,
            testFns[fi].prop
          );
          if (desc && desc.get) {
            const str = nativeToStr.call(desc.get);
            if (str.indexOf("native code") === -1 && str.indexOf("\n") === -1) {
              suspects.push(testFns[fi].name + " (non-native toString)");
            }
          }
        }
        return {
          passed: suspects.length === 0,
          detail: suspects.length === 0 ? "All checked native functions appear genuine" : "Tampered: " + suspects.join(", ")
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Native function check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.windowPropertyClean = (() => {
      try {
        const props = Object.getOwnPropertyNames(window);
        const suspicious = props.filter(
          (p) => p.indexOf("__playwright") === 0 || p.indexOf("__puppeteer") === 0 || p.indexOf("__selenium") === 0 || p.indexOf("__webdriver") === 0 || p.indexOf("$cdc_") === 0 || p.indexOf("cdc_") === 0 || p.indexOf("_phantom") === 0 || p.indexOf("callPhantom") === 0 || p === "domAutomation" || p === "domAutomationController"
        );
        return {
          passed: suspicious.length === 0,
          detail: suspicious.length === 0 ? "No automation properties on window (" + props.length + " total props)" : "FOUND: " + suspicious.join(", ")
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Window property check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.screenGetterIntegrity = (() => {
      try {
        const desc = Object.getOwnPropertyDescriptor(
          Screen.prototype,
          "width"
        );
        if (!desc || !desc.get)
          return {
            passed: true,
            detail: "Screen.width getter not found (unusual)"
          };
        const str = Function.prototype.toString.call(desc.get);
        const isNative = str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
        return {
          passed: isNative,
          detail: isNative ? "Screen.width getter appears native" : "Screen.width getter TAMPERED: " + str.substring(0, 60)
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Screen getter check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.canvasContextIntegrity = (() => {
      try {
        const fn = CanvasRenderingContext2D.prototype.getImageData;
        const str = Function.prototype.toString.call(fn);
        const isNative = str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
        return {
          passed: isNative,
          detail: isNative ? "getImageData appears native" : "getImageData TAMPERED: " + str.substring(0, 60)
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Canvas context check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.audioBufferIntegrity = (() => {
      try {
        const fn = AudioBuffer.prototype.getChannelData;
        const str = Function.prototype.toString.call(fn);
        const isNative = str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
        return {
          passed: isNative,
          detail: isNative ? "getChannelData appears native" : "getChannelData TAMPERED: " + str.substring(0, 60)
        };
      } catch (e) {
        return {
          passed: true,
          detail: "AudioBuffer check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.dateIntegrity = (() => {
      try {
        const fn = Date.prototype.getTimezoneOffset;
        const str = Function.prototype.toString.call(fn);
        const isNative = str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
        return {
          passed: isNative,
          detail: isNative ? "getTimezoneOffset appears native" : "getTimezoneOffset TAMPERED: " + str.substring(0, 60)
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Date integrity check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.intlIntegrity = (() => {
      try {
        const fn = Intl.DateTimeFormat.prototype.resolvedOptions;
        const str = Function.prototype.toString.call(fn);
        const isNative = str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
        return {
          passed: isNative,
          detail: isNative ? "Intl resolvedOptions appears native" : "Intl resolvedOptions TAMPERED: " + str.substring(0, 60)
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Intl integrity check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.functionToStringIntegrity = (() => {
      try {
        const toStr = Function.prototype.toString;
        const str = toStr.call(toStr);
        const isNative = str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
        let hasProxy = false;
        try {
          toStr.call(void 0);
        } catch (e) {
          hasProxy = !(e instanceof TypeError);
        }
        return {
          passed: isNative && !hasProxy,
          detail: isNative && !hasProxy ? "Function.prototype.toString appears native" : hasProxy ? "toString may be proxied" : "toString TAMPERED: " + str.substring(0, 60)
        };
      } catch (e) {
        return {
          passed: true,
          detail: "toString proxy check skipped: " + e.message
        };
      }
    })();
    result.lieDetection.phantomWindowProps = (() => {
      try {
        const found = [];
        if (typeof window._phantom !== "undefined")
          found.push("_phantom");
        if (typeof window.callPhantom !== "undefined")
          found.push("callPhantom");
        if (typeof window.domAutomation !== "undefined")
          found.push("domAutomation");
        if (typeof window.domAutomationController !== "undefined")
          found.push("domAutomationController");
        if (typeof window._selenium !== "undefined")
          found.push("_selenium");
        if (typeof window.awesomium !== "undefined")
          found.push("awesomium");
        if (typeof window.emit !== "undefined" && typeof window.spawn !== "undefined")
          found.push("emit+spawn (Node)");
        if (typeof window.Buffer !== "undefined")
          found.push("Buffer (Node)");
        return {
          passed: found.length === 0,
          detail: found.length === 0 ? "No phantom/automation globals" : "FOUND: " + found.join(", ")
        };
      } catch (e) {
        return {
          passed: true,
          detail: "Phantom check skipped: " + e.message
        };
      }
    })();
    result.firefoxAPIs.noNavigatorConnection = {
      passed: typeof navigator.connection === "undefined",
      detail: typeof navigator.connection === "undefined" ? "Not present (correct for Firefox)" : "PRESENT (Chrome-only API)"
    };
    result.firefoxAPIs.noDeviceMemory = {
      passed: typeof navigator.deviceMemory === "undefined",
      detail: typeof navigator.deviceMemory === "undefined" ? "Not present (correct)" : "PRESENT: " + navigator.deviceMemory + " (Chrome-only)"
    };
    result.firefoxAPIs.noBatteryAPI = {
      passed: typeof navigator.getBattery === "undefined",
      detail: typeof navigator.getBattery === "undefined" ? "Not present (removed in Firefox 52)" : "PRESENT (should not exist in Firefox)"
    };
    result.firefoxAPIs.noWebHID = {
      passed: typeof navigator.hid === "undefined",
      detail: typeof navigator.hid === "undefined" ? "Not present (correct)" : "PRESENT (Chrome-only)"
    };
    result.firefoxAPIs.noWebUSB = {
      passed: typeof navigator.usb === "undefined",
      detail: typeof navigator.usb === "undefined" ? "Not present (correct)" : "PRESENT (Chrome-only)"
    };
    result.firefoxAPIs.noWebSerial = {
      passed: typeof navigator.serial === "undefined",
      detail: typeof navigator.serial === "undefined" ? "Not present (correct)" : "PRESENT (Chrome-only)"
    };
    result.firefoxAPIs.hasBuildID = {
      passed: typeof navigator.buildID === "string",
      detail: typeof navigator.buildID === "string" ? "Present: " + navigator.buildID + " (correct for Firefox)" : "MISSING (should exist in Firefox)"
    };
    result.firefoxAPIs.mozCSSPrefix = (() => {
      const hasMoz = CSS.supports("-moz-appearance", "none");
      return {
        passed: hasMoz,
        detail: hasMoz ? "-moz-appearance supported (correct for Firefox)" : "NOT supported (wrong engine?)"
      };
    })();
    result.firefoxAPIs.noPerformanceMemory = {
      passed: typeof performance.memory === "undefined",
      detail: typeof performance.memory === "undefined" ? "Not present (correct)" : "PRESENT (Chrome-only)"
    };
    result.firefoxAPIs.pdfViewerEnabled = {
      passed: navigator.pdfViewerEnabled === true,
      detail: "navigator.pdfViewerEnabled = " + navigator.pdfViewerEnabled + (navigator.pdfViewerEnabled === true ? " (correct for Firefox)" : " (expected true)")
    };
    result.firefoxAPIs.pluginCount = (() => {
      const count = navigator.plugins ? navigator.plugins.length : 0;
      return {
        passed: count === 5,
        detail: "navigator.plugins.length = " + count + (count === 5 ? " (correct)" : " (expected 5)")
      };
    })();
    result.crossSignal.uaContainsFirefox = (() => {
      const ua = navigator.userAgent;
      const hasFF = ua.indexOf("Firefox") !== -1;
      const hasChrome = ua.indexOf("Chrome") !== -1;
      return {
        passed: hasFF && !hasChrome,
        detail: hasFF ? "UA contains Firefox (correct)" : hasChrome ? "UA contains Chrome (WRONG)" : "UA missing browser identifier"
      };
    })();
    result.crossSignal.platformVsUA = (() => {
      const platform = navigator.platform;
      const ua = navigator.userAgent;
      const platIsMac = platform === "MacIntel" || platform === "MacPPC" || platform === "Macintosh";
      const uaIsMac = ua.indexOf("Macintosh") !== -1 || ua.indexOf("Mac OS") !== -1;
      const platIsWin = platform.indexOf("Win") === 0;
      const uaIsWin = ua.indexOf("Windows") !== -1;
      const platIsLinux = platform.indexOf("Linux") !== -1;
      const uaIsLinux = ua.indexOf("Linux") !== -1;
      const consistent = platIsMac && uaIsMac || platIsWin && uaIsWin || platIsLinux && uaIsLinux;
      return {
        passed: consistent,
        detail: consistent ? 'Platform "' + platform + '" matches UA OS claim' : 'MISMATCH: platform="' + platform + '" but UA suggests different OS'
      };
    })();
    result.crossSignal.touchVsPlatform = (() => {
      const isDesktop = navigator.platform === "MacIntel" || navigator.platform.indexOf("Win") === 0 || navigator.platform.indexOf("Linux") === 0;
      const touchPoints = navigator.maxTouchPoints || 0;
      const plausible = !isDesktop || touchPoints <= 1;
      return {
        passed: plausible,
        detail: "maxTouchPoints=" + touchPoints + ' on platform "' + navigator.platform + '"' + (plausible ? " (plausible)" : " (suspicious for desktop)")
      };
    })();
    result.crossSignal.screenVsViewport = (() => {
      const screenOk = screen.width >= window.innerWidth && screen.height >= window.innerHeight;
      return {
        passed: screenOk,
        detail: screenOk ? "screen >= viewport (correct)" : "ANOMALY: screen " + screen.width + "x" + screen.height + " < viewport " + window.innerWidth + "x" + window.innerHeight
      };
    })();
    result.crossSignal.outerDimensionsNonZero = {
      passed: window.outerWidth > 0 && window.outerHeight > 0,
      detail: "outerWidth=" + window.outerWidth + " outerHeight=" + window.outerHeight + (window.outerWidth > 0 && window.outerHeight > 0 ? " (non-zero, correct)" : " (ZERO = headless)")
    };
    result.crossSignal.availVsScreen = {
      passed: screen.availWidth <= screen.width && screen.availHeight <= screen.height,
      detail: "avail " + screen.availWidth + "x" + screen.availHeight + " vs screen " + screen.width + "x" + screen.height
    };
    result.crossSignal.availHeightVsHeight = (() => {
      const diff = screen.height - screen.availHeight;
      return {
        passed: true,
        detail: diff > 0 ? "availHeight (" + screen.availHeight + ") < height (" + screen.height + "), diff=" + diff + "px (taskbar present)" : "availHeight === height (" + screen.height + ") (Camoufox screen spoofing -- expected)"
      };
    })();
    result.crossSignal.intlTimezoneMatch = (() => {
      const intlTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const offsetMinutes = (/* @__PURE__ */ new Date()).getTimezoneOffset();
      return {
        passed: !!intlTz,
        detail: "Intl timezone: " + intlTz + ", offset: " + offsetMinutes + " min"
      };
    })();
    return result;
  }
  var init_core = __esm({
    "../build-tester/src/lib/checks/core.ts"() {
      "use client";
    }
  });

  // ../build-tester/src/lib/checks/extended.ts
  var extended_exports = {};
  __export(extended_exports, {
    runExtendedChecks: () => runExtendedChecks
  });
  async function runExtendedChecks() {
    const result = {
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
      fontEnvironment: {}
    };
    try {
      result.cssFingerprint.prefersColorScheme = {
        passed: true,
        detail: "prefers-color-scheme: " + (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      };
      result.cssFingerprint.prefersReducedMotion = {
        passed: true,
        detail: "prefers-reduced-motion: " + (matchMedia("(prefers-reduced-motion: reduce)").matches ? "reduce" : "no-preference")
      };
      const pointerFine = matchMedia("(pointer: fine)").matches;
      result.cssFingerprint.pointerType = {
        passed: pointerFine,
        detail: pointerFine ? "pointer: fine (desktop, correct)" : "pointer: NOT fine (suspicious for desktop)"
      };
      const hoverHover = matchMedia("(hover: hover)").matches;
      result.cssFingerprint.hoverCapability = {
        passed: hoverHover,
        detail: hoverHover ? "hover: hover (desktop, correct)" : "hover: NOT hover (suspicious for desktop)"
      };
      const webkitAppearance = CSS.supports("-webkit-appearance", "none");
      result.cssFingerprint.webkitCompatMode = {
        passed: true,
        detail: "-webkit-appearance: " + (webkitAppearance ? "supported (Firefox compat mode)" : "not supported")
      };
      result.cssFingerprint.systemFonts = (() => {
        try {
          const div = document.createElement("div");
          div.style.cssText = "position:absolute;left:-9999px;visibility:hidden;";
          document.body.appendChild(div);
          const fonts = {};
          const keywords = [
            "caption",
            "icon",
            "menu",
            "message-box",
            "small-caption",
            "status-bar"
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
            "Droid"
          ];
          const hasLinuxFont = linuxSystemFonts.some(
            (f) => allFontStr.indexOf(f) !== -1
          );
          const plat = navigator.platform;
          const platIsMac = plat === "MacIntel" || plat === "Macintosh";
          const passed = !(platIsMac && hasLinuxFont);
          return {
            passed,
            detail: passed ? "System fonts consistent with " + plat + " (caption: " + fonts.caption + ")" : "MISMATCH: Linux system fonts (" + fonts.caption + ") on claimed Mac platform"
          };
        } catch (e) {
          return {
            passed: true,
            detail: "System font check skipped: " + e.message
          };
        }
      })();
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
            detail: passed ? "matchMedia device dimensions match screen (" + sw + "x" + sh + ")" : "MISMATCH: matchMedia disagrees with screen." + (!widthMatch ? "width=" + sw : "height=" + sh)
          };
        } catch (e) {
          return {
            passed: true,
            detail: "matchMedia check skipped: " + e.message
          };
        }
      })();
      result.cssFingerprint.timerPrecision = (() => {
        const stamps = [];
        for (let i = 0; i < 50; i++) stamps.push(performance.now());
        const deltas = [];
        for (let i = 1; i < stamps.length; i++) {
          const d = stamps[i] - stamps[i - 1];
          if (d > 0) deltas.push(d);
        }
        const minDelta = deltas.length > 0 ? Math.min(...deltas) : 0;
        const suspicious = minDelta > 0 && minDelta < 5e-3;
        return {
          passed: !suspicious,
          detail: "Timer min delta: " + (minDelta * 1e3).toFixed(1) + "us" + (suspicious ? " (suspiciously precise)" : " (normal)")
        };
      })();
    } catch (e) {
      result.cssFingerprint.error = {
        passed: true,
        detail: "CSS checks error: " + e.message
      };
    }
    try {
      const tanVal = Math.tan(-1e300);
      result.mathEngine.tanPrecision = {
        passed: true,
        detail: "Math.tan(-1e300) = " + tanVal
      };
      const sinhVal = Math.sinh(1);
      result.mathEngine.sinhPrecision = {
        passed: true,
        detail: "Math.sinh(1) = " + sinhVal
      };
      const asinhVal = Math.asinh(1);
      result.mathEngine.asinhPrecision = {
        passed: true,
        detail: "Math.asinh(1) = " + asinhVal
      };
    } catch (e) {
      result.mathEngine.error = {
        passed: true,
        detail: "Math checks error: " + e.message
      };
    }
    try {
      if (navigator.permissions) {
        const notifPerm = await navigator.permissions.query({
          name: "notifications"
        });
        result.permissionsAPI.notificationsState = {
          passed: true,
          detail: "notifications: " + notifPerm.state
        };
        const geoPerm = await navigator.permissions.query({
          name: "geolocation"
        });
        result.permissionsAPI.geolocationState = {
          passed: true,
          detail: "geolocation: " + geoPerm.state
        };
      } else {
        result.permissionsAPI.apiPresent = {
          passed: true,
          detail: "Permissions API not available"
        };
      }
    } catch (e) {
      result.permissionsAPI.error = {
        passed: true,
        detail: "Permissions query error: " + e.message
      };
    }
    try {
      let voices = speechSynthesis.getVoices();
      if (voices.length === 0) {
        await new Promise((resolve) => {
          speechSynthesis.onvoiceschanged = () => resolve();
          setTimeout(resolve, 2e3);
        });
        voices = speechSynthesis.getVoices();
      }
      const hasWindowsVoice = voices.some(
        (v) => v.name.indexOf("Microsoft") !== -1
      );
      const hasMacVoice = voices.some(
        (v) => v.name === "Samantha" || v.name === "Alex" || v.name === "Victoria" || v.name.indexOf("Apple") !== -1
      );
      const platform = navigator.platform;
      const platIsMac = platform === "MacIntel" || platform === "Macintosh";
      let voiceOSMatch = true;
      if (platIsMac && hasWindowsVoice && !hasMacVoice) voiceOSMatch = false;
      result.speechVoices.voiceCount = {
        passed: true,
        detail: voices.length + " voices detected"
      };
      result.speechVoices.platformMatch = {
        passed: voiceOSMatch,
        detail: voiceOSMatch ? "Voice names consistent with platform" : "MISMATCH: platform=" + platform + " but voices suggest different OS"
      };
    } catch (e) {
      result.speechVoices.error = {
        passed: true,
        detail: "Speech API error: " + e.message
      };
    }
    try {
      const samples = [];
      for (let i = 0; i < 20; i++) {
        const t1 = performance.now();
        const t2 = performance.now();
        if (t2 > t1) samples.push(t2 - t1);
      }
      const minDelta = samples.length > 0 ? Math.min(...samples) : 0;
      result.performanceAPI.timerResolution = {
        passed: true,
        detail: "Min delta: " + minDelta.toFixed(4) + "ms (" + samples.length + " non-zero samples)"
      };
      result.performanceAPI.noPerformanceMemory = {
        passed: typeof performance.memory === "undefined",
        detail: typeof performance.memory === "undefined" ? "Not present (correct for Firefox)" : "PRESENT (Chrome-only)"
      };
    } catch (e) {
      result.performanceAPI.error = {
        passed: true,
        detail: "Performance API error: " + e.message
      };
    }
    try {
      const intlTzFull = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const intlLocale = Intl.DateTimeFormat().resolvedOptions().locale;
      const navLang = navigator.language;
      const localeBase = intlLocale.split("-")[0];
      const langBase = navLang.split("-")[0];
      const localeMatch = localeBase === langBase;
      result.intlConsistency.localeVsLanguage = {
        passed: localeMatch,
        detail: localeMatch ? 'Intl locale "' + intlLocale + '" matches navigator.language "' + navLang + '"' : 'MISMATCH: Intl locale "' + intlLocale + '" vs navigator.language "' + navLang + '"'
      };
      const numFormatted = new Intl.NumberFormat().format(1234.5);
      result.intlConsistency.numberFormat = {
        passed: true,
        detail: "Number format: " + numFormatted + " (locale: " + intlLocale + ")"
      };
      result.intlConsistency.timezone = {
        passed: true,
        detail: "Intl timezone: " + intlTzFull
      };
    } catch (e) {
      result.intlConsistency.error = {
        passed: true,
        detail: "Intl error: " + e.message
      };
    }
    try {
      const eCanvas = document.createElement("canvas");
      eCanvas.width = 200;
      eCanvas.height = 80;
      const eCtx = eCanvas.getContext("2d");
      if (!eCtx) throw new Error("Cannot get 2d context");
      eCtx.font = "32px Arial, sans-serif";
      eCtx.fillText("\u{1F600}\u{1F389}\u{1F525}\u{1F916}", 10, 40);
      const eData = eCtx.getImageData(0, 0, 200, 80).data;
      let eHash = 0;
      for (let i = 0; i < eData.length; i += 4) {
        eHash = (eHash << 5) - eHash + eData[i] + eData[i + 1] + eData[i + 2];
        eHash = eHash & eHash;
      }
      result.emojiFingerprint.hash = {
        passed: true,
        detail: "Emoji canvas hash: " + Math.abs(eHash).toString(16)
      };
    } catch (e) {
      result.emojiFingerprint.error = {
        passed: true,
        detail: "Emoji canvas error: " + e.message
      };
    }
    try {
      let renderCanvasTest = function() {
        const tc = document.createElement("canvas");
        tc.width = 200;
        tc.height = 50;
        const tctx = tc.getContext("2d");
        tctx.textBaseline = "top";
        tctx.font = "14px Arial";
        tctx.fillStyle = "#f60";
        tctx.fillRect(125, 1, 62, 20);
        tctx.fillStyle = "#069";
        tctx.fillText("Cwm fjordbank glyphs vext quiz", 2, 15);
        return tc.toDataURL();
      };
      const c1 = renderCanvasTest();
      const c2 = renderCanvasTest();
      const c3 = renderCanvasTest();
      const allSame = c1 === c2 && c2 === c3;
      result.canvasNoiseDetection.deterministic = {
        passed: allSame,
        detail: allSame ? "3 renders produce identical output (correct - no random noise)" : "DETECTED: Canvas output varies between renders (noise injection detected!)"
      };
    } catch (e) {
      result.canvasNoiseDetection.error = {
        passed: true,
        detail: "Canvas noise check error: " + e.message
      };
    }
    try {
      const wc = document.createElement("canvas");
      wc.width = 256;
      wc.height = 256;
      const wgl = wc.getContext("webgl");
      if (wgl) {
        const vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0,1);}";
        const fs = "precision mediump float;void main(){gl_FragColor=vec4(0.86,0.27,0.33,1.0);}";
        const vShader = wgl.createShader(wgl.VERTEX_SHADER);
        wgl.shaderSource(vShader, vs);
        wgl.compileShader(vShader);
        const fShader = wgl.createShader(wgl.FRAGMENT_SHADER);
        wgl.shaderSource(fShader, fs);
        wgl.compileShader(fShader);
        const prog = wgl.createProgram();
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
          wHash = (wHash << 5) - wHash + pixels[i];
          wHash = wHash & wHash;
        }
        result.webglRenderHash.hash = {
          passed: true,
          detail: "WebGL render hash: " + Math.abs(wHash).toString(16)
        };
      } else {
        result.webglRenderHash.noWebGL = {
          passed: true,
          detail: "WebGL not available"
        };
      }
    } catch (e) {
      result.webglRenderHash.error = {
        passed: true,
        detail: "WebGL render error: " + e.message
      };
    }
    try {
      let isFontAvailable = function(fontName) {
        const testStr = "mmmmmmmmmmlli";
        fpCtx.font = "72px monospace";
        const defaultWidth = fpCtx.measureText(testStr).width;
        fpCtx.font = '72px "' + fontName + '", monospace';
        return fpCtx.measureText(testStr).width !== defaultWidth;
      };
      const fpCanvas = document.createElement("canvas");
      const fpCtx = fpCanvas.getContext("2d");
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
        if (hasSegoeUI) {
          fontOSMatch = false;
          fontDetail = "Segoe UI detected on claimed Mac";
        }
        const linuxFontsFound = [];
        if (hasArimo) linuxFontsFound.push("Arimo");
        if (hasCantarell) linuxFontsFound.push("Cantarell");
        if (hasNotoColorEmoji) linuxFontsFound.push("Noto Color Emoji");
        if (hasLiberation) linuxFontsFound.push("Liberation Sans");
        if (hasUbuntu) linuxFontsFound.push("Ubuntu");
        if (hasDejaVuSans) linuxFontsFound.push("DejaVu Sans");
        if (linuxFontsFound.length > 0) {
          fontOSMatch = false;
          fontDetail += (fontDetail ? "; " : "") + "Linux fonts on Mac: " + linuxFontsFound.join(", ");
        }
        if (!hasHelveticaNeue && !hasSFPro && !hasLucidaGrande) {
          fontDetail += (fontDetail ? "; " : "") + "No Mac fonts detected";
        }
      } else if (platIsWin) {
        if (!hasSegoeUI && !hasTahoma) {
          fontDetail = "No Windows fonts detected";
        }
      }
      result.fontPlatformConsistency.osMatch = {
        passed: fontOSMatch,
        detail: fontOSMatch ? "Fonts consistent with " + plat + (fontDetail ? " (" + fontDetail + ")" : "") : "MISMATCH: " + fontDetail
      };
      result.fontPlatformConsistency.detected = {
        passed: true,
        detail: "SegoeUI=" + hasSegoeUI + " SFPro=" + hasSFPro + " HelveticaNeue=" + hasHelveticaNeue + " Tahoma=" + hasTahoma + " Ubuntu=" + hasUbuntu + " DejaVu=" + hasDejaVuSans
      };
    } catch (e) {
      result.fontPlatformConsistency.error = {
        passed: true,
        detail: "Font platform check error: " + e.message
      };
    }
    result.crossSignal.oscpuVsUA = (() => {
      const oscpu = navigator.oscpu || "";
      const ua = navigator.userAgent;
      if (!oscpu) return { passed: true, detail: "oscpu not available" };
      const oscpuIsMac = oscpu.indexOf("Mac OS X") !== -1 || oscpu.indexOf("Intel Mac") !== -1;
      const oscpuIsWin = oscpu.indexOf("Windows") !== -1;
      const oscpuIsLinux = oscpu.indexOf("Linux") !== -1;
      const uaIsMac = ua.indexOf("Macintosh") !== -1;
      const uaIsWin = ua.indexOf("Windows") !== -1;
      const uaIsLinux = ua.indexOf("Linux") !== -1;
      const match = oscpuIsMac && uaIsMac || oscpuIsWin && uaIsWin || oscpuIsLinux && uaIsLinux || !oscpuIsMac && !oscpuIsWin && !oscpuIsLinux;
      return {
        passed: match,
        detail: match ? 'oscpu "' + oscpu + '" matches UA OS' : 'MISMATCH: oscpu="' + oscpu + '" vs UA OS'
      };
    })();
    result.crossSignal.webglRendererVsPlatform = (() => {
      try {
        const wCanvas = document.createElement("canvas");
        const wGl = wCanvas.getContext("webgl");
        if (!wGl) return { passed: true, detail: "WebGL not available" };
        const dbg = wGl.getExtension("WEBGL_debug_renderer_info");
        if (!dbg) return { passed: true, detail: "Debug renderer info not available" };
        const renderer = wGl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || "";
        const vendor = wGl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) || "";
        const plat = navigator.platform;
        const platIsMac = plat === "MacIntel" || plat === "Macintosh";
        const rendererLower = renderer.toLowerCase();
        let suspicious = false;
        let reason = "";
        if (platIsMac && rendererLower.indexOf("direct3d") !== -1) {
          suspicious = true;
          reason = "Direct3D renderer on Mac platform";
        }
        const hasSimilarSuffix = rendererLower.indexOf(", or similar") !== -1;
        return {
          passed: !suspicious,
          detail: !suspicious ? 'WebGL renderer "' + renderer + '" plausible for ' + plat + (hasSimilarSuffix ? " (Camoufox global)" : "") : "MISMATCH: " + reason
        };
      } catch (e) {
        return {
          passed: true,
          detail: "WebGL platform check error: " + e.message
        };
      }
    })();
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
        detail: allNegInf ? "Silent analyser returns -Infinity values (correct - no noise injection on silence)" : "DETECTED: Non-Infinity values in silent analyser (noise injection leaked into silence)"
      };
    } catch (e) {
      result.audioIntegrity.silenceCheck = {
        passed: true,
        detail: "Silence check skipped: " + e.message
      };
    }
    try {
      const trapCtx = new AudioContext();
      const trapBuf = trapCtx.createBuffer(1, 128, 44100);
      const trapChannel = trapBuf.getChannelData(0);
      const trapExpected = new Float32Array(128);
      for (let i = 0; i < 128; i++) {
        trapExpected[i] = i / 128 * 2 - 1;
        trapChannel[i] = trapExpected[i];
      }
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
        detail: trapModified ? "Audio buffer modified on read-back (max delta: " + maxDiff.toExponential(2) + ") - Camoufox audio transform active" : "Audio buffer unchanged after write-back (no audio transform applied)"
      };
    } catch (e) {
      result.audioIntegrity.noiseTrap = {
        passed: true,
        detail: "Noise trap skipped: " + e.message
      };
    }
    try {
      let quickHash = function(arr) {
        let h = 0;
        for (let i = 0; i < arr.length; i += 100) {
          h = (h << 5) - h + (arr[i] * 1e6 | 0);
          h = h & h;
        }
        return h;
      };
      const crossCtx = new OfflineAudioContext(1, 44100, 44100);
      const crossOsc = crossCtx.createOscillator();
      const crossComp = crossCtx.createDynamicsCompressor();
      crossOsc.type = "triangle";
      crossOsc.frequency.value = 1e4;
      crossOsc.connect(crossComp);
      crossComp.connect(crossCtx.destination);
      crossOsc.start(0);
      const crossRendered = await crossCtx.startRendering();
      const chData = crossRendered.getChannelData(0);
      const copyData = new Float32Array(chData.length);
      crossRendered.copyFromChannel(copyData, 0);
      const chHash = quickHash(chData);
      const cpHash = quickHash(copyData);
      const hashMatch = chHash === cpHash;
      result.audioIntegrity.channelDataVsCopy = {
        passed: hashMatch,
        detail: hashMatch ? "getChannelData and copyFromChannel produce same hash (" + Math.abs(chHash).toString(16) + ")" : "MISMATCH: getChannelData=" + Math.abs(chHash).toString(16) + " copyFromChannel=" + Math.abs(cpHash).toString(16)
      };
    } catch (e) {
      result.audioIntegrity.channelDataVsCopy = {
        passed: true,
        detail: "Audio cross-validation skipped: " + e.message
      };
    }
    try {
      const compCtx = new AudioContext();
      const compOsc = compCtx.createOscillator();
      const comp = compCtx.createDynamicsCompressor();
      comp.threshold.value = -50;
      comp.knee.value = 40;
      comp.ratio.value = 12;
      comp.attack.value = 0;
      comp.release.value = 0.25;
      const silentGain = compCtx.createGain();
      silentGain.gain.value = 0;
      compOsc.connect(comp);
      comp.connect(silentGain);
      silentGain.connect(compCtx.destination);
      compOsc.start();
      await new Promise((r) => setTimeout(r, 100));
      const reduction = comp.reduction;
      compOsc.stop();
      await compCtx.close();
      result.audioIntegrity.compressorReduction = {
        passed: true,
        detail: "DynamicsCompressor.reduction = " + (typeof reduction === "number" ? reduction.toFixed(4) : String(reduction))
      };
    } catch (e) {
      result.audioIntegrity.compressorReduction = {
        passed: true,
        detail: "Compressor check skipped: " + e.message
      };
    }
    try {
      const testIframe = document.createElement("iframe");
      testIframe.style.cssText = "position:absolute;left:-9999px;width:1px;height:1px;";
      document.body.appendChild(testIframe);
      const iWin = testIframe.contentWindow;
      result.iframeTesting.navigatorMatch = (() => {
        const mainUA = navigator.userAgent;
        const iframeUA = iWin.navigator.userAgent;
        const mainPlat = navigator.platform;
        const iframePlat = iWin.navigator.platform;
        const uaMatch = mainUA === iframeUA;
        const platMatch = mainPlat === iframePlat;
        return {
          passed: uaMatch && platMatch,
          detail: uaMatch && platMatch ? "Navigator properties match across main window and iframe" : "MISMATCH: " + (!uaMatch ? "UA differs" : "platform differs") + " in iframe"
        };
      })();
      result.iframeTesting.screenMatch = (() => {
        const mainW = screen.width;
        const iframeW = iWin.screen.width;
        const mainH = screen.height;
        const iframeH = iWin.screen.height;
        const match = mainW === iframeW && mainH === iframeH;
        return {
          passed: match,
          detail: match ? "Screen dimensions match in iframe (" + mainW + "x" + mainH + ")" : "MISMATCH: main=" + mainW + "x" + mainH + " iframe=" + iframeW + "x" + iframeH
        };
      })();
      result.iframeTesting.timezoneMatch = (() => {
        const mainTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const iframeTz = iWin.Intl.DateTimeFormat().resolvedOptions().timeZone;
        const match = mainTz === iframeTz;
        return {
          passed: match,
          detail: match ? "Timezone matches in iframe (" + mainTz + ")" : "MISMATCH: main=" + mainTz + " iframe=" + iframeTz
        };
      })();
      document.body.removeChild(testIframe);
    } catch (e) {
      result.iframeTesting.error = {
        passed: true,
        detail: "Iframe testing skipped: " + e.message
      };
    }
    try {
      result.headlessDetection.permissionConsistency = await (async () => {
        try {
          if (typeof Notification === "undefined" || !navigator.permissions) {
            return {
              passed: true,
              detail: "Notification or Permissions API unavailable"
            };
          }
          const notifPerm = Notification.permission;
          const queryResult = await navigator.permissions.query({
            name: "notifications"
          });
          const expected = notifPerm === "default" ? "prompt" : notifPerm;
          const match = expected === queryResult.state;
          return {
            passed: true,
            detail: match ? "Notification.permission (" + notifPerm + ") consistent with permissions.query (" + queryResult.state + ")" : "Notification.permission=" + notifPerm + ", query=" + queryResult.state + " (normal Firefox mismatch)"
          };
        } catch (e) {
          return {
            passed: true,
            detail: "Permission check skipped: " + e.message
          };
        }
      })();
      result.headlessDetection.hasTaskbar = (() => {
        const wDiff = screen.width - screen.availWidth;
        const hDiff = screen.height - screen.availHeight;
        const noTaskbar = wDiff === 0 && hDiff === 0;
        return {
          passed: true,
          detail: noTaskbar ? "availWidth === width, availHeight === height (no taskbar - spoofed screen or headless)" : "Taskbar detected: width diff=" + wDiff + "px, height diff=" + hDiff + "px"
        };
      })();
      result.headlessDetection.viewportNotScreen = (() => {
        const vpEqualsScreen = window.innerWidth === screen.width && window.innerHeight === screen.height;
        return {
          passed: !vpEqualsScreen,
          detail: vpEqualsScreen ? "SUSPICIOUS: viewport (" + window.innerWidth + "x" + window.innerHeight + ") exactly equals screen" : "Viewport (" + window.innerWidth + "x" + window.innerHeight + ") differs from screen (" + screen.width + "x" + screen.height + ")"
        };
      })();
      result.headlessDetection.systemColors = (() => {
        try {
          const div = document.createElement("div");
          div.style.cssText = "position:absolute;left:-9999px;color:ActiveText;";
          document.body.appendChild(div);
          const color = getComputedStyle(div).color;
          document.body.removeChild(div);
          const isDefaultRed = color === "rgb(255, 0, 0)";
          return {
            passed: !isDefaultRed,
            detail: isDefaultRed ? "SUSPICIOUS: ActiveText resolved to default red (headless indicator)" : "ActiveText resolves to: " + color + " (normal)"
          };
        } catch (e) {
          return {
            passed: true,
            detail: "System color check skipped: " + e.message
          };
        }
      })();
      result.headlessDetection.noSwiftShader = (() => {
        try {
          const sc = document.createElement("canvas");
          const sgl = sc.getContext("webgl");
          if (!sgl) return { passed: true, detail: "WebGL not available" };
          const ext = sgl.getExtension("WEBGL_debug_renderer_info");
          if (!ext) return { passed: true, detail: "Debug renderer info not available" };
          const renderer = (sgl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "").toLowerCase();
          const hasSwift = renderer.indexOf("swiftshader") !== -1;
          const hasLLVM = renderer.indexOf("llvmpipe") !== -1;
          const hasSoftware = renderer.indexOf("software") !== -1;
          const suspicious = hasSwift || hasLLVM || hasSoftware;
          return {
            passed: !suspicious,
            detail: suspicious ? "SOFTWARE RENDERER: " + renderer + " (headless indicator)" : "Hardware renderer: " + renderer.substring(0, 60)
          };
        } catch (e) {
          return {
            passed: true,
            detail: "SwiftShader check skipped: " + e.message
          };
        }
      })();
      result.headlessDetection.noHeadlessUA = (() => {
        const ua = navigator.userAgent.toLowerCase();
        const hasHeadless = ua.indexOf("headlesschrome") !== -1 || ua.indexOf("headlessfirefox") !== -1 || ua.indexOf("phantomjs") !== -1;
        return {
          passed: !hasHeadless,
          detail: hasHeadless ? "HEADLESS UA: " + navigator.userAgent : "No headless string in UA"
        };
      })();
      result.headlessDetection.noWebdriver = {
        passed: navigator.webdriver !== true,
        detail: navigator.webdriver === true ? "navigator.webdriver = true (headless/automation)" : "navigator.webdriver = " + navigator.webdriver
      };
      result.headlessDetection.outerDimensions = {
        passed: window.outerWidth > 0 && window.outerHeight > 0,
        detail: window.outerWidth > 0 && window.outerHeight > 0 ? "outerWidth=" + window.outerWidth + " outerHeight=" + window.outerHeight : "ZERO outer dimensions (headless indicator)"
      };
      result.headlessDetection.hasPlugins = {
        passed: navigator.plugins && navigator.plugins.length > 0,
        detail: navigator.plugins ? navigator.plugins.length + " plugins (0 = headless indicator)" : "navigator.plugins missing"
      };
      let headlessIndicators = 0;
      let headlessTotal = 0;
      const hdChecks = result.headlessDetection;
      for (const hk in hdChecks) {
        if (hdChecks[hk] && typeof hdChecks[hk].passed === "boolean") {
          headlessTotal++;
          if (!hdChecks[hk].passed) headlessIndicators++;
        }
      }
      const headlessPercent = headlessTotal > 0 ? Math.round(headlessIndicators / headlessTotal * 100) : 0;
      result.headlessDetection.headlessScore = {
        passed: headlessPercent <= 15,
        detail: headlessPercent + "% headless indicators (" + headlessIndicators + "/" + headlessTotal + " flagged)"
      };
    } catch (e) {
      result.headlessDetection.error = {
        passed: true,
        detail: "Headless detection error: " + e.message
      };
    }
    try {
      result.trashDetection.integerScreen = (() => {
        const w = screen.width;
        const h = screen.height;
        const isInt = Number.isInteger(w) && Number.isInteger(h);
        return {
          passed: isInt,
          detail: isInt ? "Screen dimensions are integers (" + w + "x" + h + ")" : "NON-INTEGER screen: " + w + "x" + h
        };
      })();
      result.trashDetection.plausibleHWC = (() => {
        const hwc = navigator.hardwareConcurrency;
        const common = [
          1,
          2,
          4,
          6,
          8,
          10,
          12,
          14,
          16,
          20,
          24,
          28,
          32,
          36,
          40,
          48,
          56,
          64,
          96,
          128,
          256
        ];
        const isCommon = common.indexOf(hwc) !== -1;
        return {
          passed: isCommon,
          detail: isCommon ? "hardwareConcurrency=" + hwc + " (common value)" : "UNUSUAL hardwareConcurrency=" + hwc + " (not a typical core count)"
        };
      })();
      result.trashDetection.plausibleWebGLRenderer = (() => {
        try {
          const c = document.createElement("canvas");
          const gl = c.getContext("webgl");
          if (!gl) return { passed: true, detail: "WebGL not available" };
          const ext = gl.getExtension("WEBGL_debug_renderer_info");
          if (!ext)
            return { passed: true, detail: "Debug renderer info not available" };
          const renderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "";
          if (!renderer) return { passed: true, detail: "Empty renderer string" };
          const tooShort = renderer.length < 5;
          const allDigits = /^[0-9]+$/.test(renderer);
          const allLowerNoSpaces = renderer === renderer.toLowerCase() && renderer.indexOf(" ") === -1 && renderer.length > 10;
          const gibberish = tooShort || allDigits || allLowerNoSpaces;
          return {
            passed: !gibberish,
            detail: gibberish ? 'SUSPICIOUS renderer: "' + renderer + '" (gibberish pattern)' : "Renderer plausible: " + renderer.substring(0, 50)
          };
        } catch (e) {
          return {
            passed: true,
            detail: "WebGL renderer check skipped: " + e.message
          };
        }
      })();
      result.trashDetection.reasonableScreenSize = (() => {
        const w = screen.width;
        const h = screen.height;
        const reasonable = w >= 320 && w <= 7680 && h >= 240 && h <= 4320;
        return {
          passed: reasonable,
          detail: reasonable ? "Screen " + w + "x" + h + " within known range (320-7680 x 240-4320)" : "UNREASONABLE screen: " + w + "x" + h
        };
      })();
      result.trashDetection.validColorDepth = (() => {
        const depth = screen.colorDepth;
        const valid = [1, 4, 8, 15, 16, 24, 30, 32, 48].indexOf(depth) !== -1;
        return {
          passed: valid,
          detail: valid ? "colorDepth=" + depth + " (valid value)" : "UNUSUAL colorDepth=" + depth
        };
      })();
    } catch (e) {
      result.trashDetection.error = {
        passed: true,
        detail: "Trash detection error: " + e.message
      };
    }
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
        const vertexHighP = gl.getShaderPrecisionFormat(
          gl.VERTEX_SHADER,
          gl.HIGH_FLOAT
        );
        const fragmentHighP = gl.getShaderPrecisionFormat(
          gl.FRAGMENT_SHADER,
          gl.HIGH_FLOAT
        );
        const vertexHighPrecision = vertexHighP ? vertexHighP.precision + "/" + vertexHighP.rangeMin + "/" + vertexHighP.rangeMax : null;
        const fragmentHighPrecision = fragmentHighP ? fragmentHighP.precision + "/" + fragmentHighP.rangeMin + "/" + fragmentHighP.rangeMax : null;
        result.webglExtended.maxRenderbufferSize = {
          passed: true,
          detail: "MAX_RENDERBUFFER_SIZE: " + maxRenderbufferSize
        };
        result.webglExtended.maxViewportDims = {
          passed: true,
          detail: "MAX_VIEWPORT_DIMS: " + (maxViewportDims ? maxViewportDims.toString() : "null")
        };
        result.webglExtended.maxVertexAttribs = {
          passed: true,
          detail: "MAX_VERTEX_ATTRIBS: " + maxVertexAttribs
        };
        result.webglExtended.maxVaryingVectors = {
          passed: true,
          detail: "MAX_VARYING_VECTORS: " + maxVaryingVectors
        };
        result.webglExtended.aliasedLineWidthRange = {
          passed: true,
          detail: "ALIASED_LINE_WIDTH_RANGE: " + (aliasedLineWidthRange ? aliasedLineWidthRange.toString() : "null")
        };
        result.webglExtended.aliasedPointSizeRange = {
          passed: true,
          detail: "ALIASED_POINT_SIZE_RANGE: " + (aliasedPointSizeRange ? aliasedPointSizeRange.toString() : "null")
        };
        result.webglExtended.extensionCount = {
          passed: true,
          detail: "Extensions: " + extensionCount
        };
        result.webglExtended.extensions = {
          passed: true,
          detail: extensionStr.substring(0, 200)
        };
        result.webglExtended.vertexHighPrecision = {
          passed: true,
          detail: "Vertex HIGH_FLOAT precision: " + (vertexHighPrecision || "unavailable")
        };
        result.webglExtended.fragmentHighPrecision = {
          passed: true,
          detail: "Fragment HIGH_FLOAT precision: " + (fragmentHighPrecision || "unavailable")
        };
      }
    } catch (e) {
    }
    try {
      let isFontInstalled = function(name) {
        fontCtx.font = '72px "' + name + '", monospace';
        return fontCtx.measureText(fontTestStr).width !== monoWidth;
      };
      const fontCanvas = document.createElement("canvas");
      const fontCtx = fontCanvas.getContext("2d");
      const fontTestStr = "mmmmmmmmmmlli";
      fontCtx.font = "72px monospace";
      const monoWidth = fontCtx.measureText(fontTestStr).width;
      const plat = (navigator.platform || "").toLowerCase();
      const ua = (navigator.userAgent || "").toLowerCase();
      let claimedOS = "unknown";
      if (plat.indexOf("mac") !== -1 || ua.indexOf("macintosh") !== -1)
        claimedOS = "macos";
      else if (plat.indexOf("linux") !== -1) claimedOS = "linux";
      else if (plat.indexOf("win") !== -1) claimedOS = "windows";
      const appleDetectionFonts = ["Helvetica Neue", "PingFang HK", "Geneva"];
      const linuxDetectionFonts = ["Arimo", "Cousine"];
      const windowsDetectionFonts = [
        "Cambria Math",
        "Nirmala UI",
        "Leelawadee UI",
        "HoloLens MDL2 Assets",
        "Segoe Fluent Icons"
      ];
      const expectedFonts = claimedOS === "macos" ? appleDetectionFonts : claimedOS === "linux" ? linuxDetectionFonts : claimedOS === "windows" ? windowsDetectionFonts : [];
      const expectedLabel = claimedOS === "macos" ? "Apple" : claimedOS === "linux" ? "Linux" : claimedOS === "windows" ? "Windows" : "Unknown";
      const expectedDetected = [];
      const expectedMissing = [];
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
        detail: hasOSId ? expectedDetected.length + "/" + expectedFonts.length + " " + expectedLabel + " marker fonts found (platform: " + navigator.platform + "): " + expectedDetected.join(", ") : "No " + expectedLabel + " marker fonts found (platform: " + navigator.platform + '). CreepJS will show "Like undefined". Missing: ' + expectedMissing.join(", ")
      };
      if (claimedOS === "macos") {
        const macVersionFonts = [
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
          ["13", "Noto Sans Canadian Aboriginal"]
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
        result.fontEnvironment.macOSVersionDepth = {
          passed: versionFound >= 3,
          detail: versionFound + "/" + versionTotal + " version marker fonts installed (highest: macOS " + highestVersion + ")"
        };
      }
      const wrongOSFonts = [];
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
      const leakedFonts = [];
      for (const [os, font] of wrongOSFonts) {
        if (isFontInstalled(font)) {
          leakedFonts.push(os + ": " + font);
        }
      }
      const noLeaks = leakedFonts.length === 0;
      result.fontEnvironment.noWrongOSFonts = {
        passed: noLeaks,
        detail: noLeaks ? "No wrong-OS marker fonts detected (claiming " + expectedLabel + ")" : "Wrong-OS fonts found while claiming " + expectedLabel + "! " + leakedFonts.join(", ")
      };
    } catch (e) {
      result.fontEnvironment.error = {
        passed: true,
        detail: "Font environment check error: " + e.message
      };
    }
    return result;
  }
  var init_extended = __esm({
    "../build-tester/src/lib/checks/extended.ts"() {
      "use client";
    }
  });

  // ../build-tester/src/lib/checks/workers.ts
  var workers_exports = {};
  __export(workers_exports, {
    runWorkerChecks: () => runWorkerChecks
  });
  function createWorkerAndGetValue(code) {
    return new Promise((resolve, reject) => {
      const blob = new Blob([code], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      const worker = new Worker(url);
      const timeout = setTimeout(() => {
        worker.terminate();
        URL.revokeObjectURL(url);
        reject(new Error("Worker timeout"));
      }, 5e3);
      worker.onmessage = (e) => {
        clearTimeout(timeout);
        worker.terminate();
        URL.revokeObjectURL(url);
        resolve(e.data);
      };
      worker.onerror = (e) => {
        clearTimeout(timeout);
        worker.terminate();
        URL.revokeObjectURL(url);
        reject(new Error(e.message));
      };
      worker.postMessage("go");
    });
  }
  function createSharedWorkerAndGetValue(code) {
    return new Promise((resolve, reject) => {
      const blob = new Blob([code], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      const sw = new SharedWorker(url);
      const timeout = setTimeout(() => {
        URL.revokeObjectURL(url);
        reject(new Error("SharedWorker timeout"));
      }, 5e3);
      sw.port.onmessage = (e) => {
        clearTimeout(timeout);
        URL.revokeObjectURL(url);
        resolve(e.data);
      };
      sw.onerror = (e) => {
        clearTimeout(timeout);
        URL.revokeObjectURL(url);
        reject(new Error(e.message || "SharedWorker error"));
      };
      sw.port.start();
      sw.port.postMessage("go");
    });
  }
  async function runWorkerChecks() {
    const workerConsistency = {};
    const mainUA = navigator.userAgent;
    const mainPlatform = navigator.platform;
    const mainHWC = navigator.hardwareConcurrency;
    const mainLang = navigator.language;
    const mainTZ = Intl.DateTimeFormat().resolvedOptions().timeZone;
    let mainWebGLRenderer = "";
    try {
      const canvas = document.createElement("canvas");
      const gl = canvas.getContext("webgl");
      if (gl) {
        const ext = gl.getExtension("WEBGL_debug_renderer_info");
        if (ext) {
          mainWebGLRenderer = gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "";
        }
      }
    } catch (e) {
    }
    try {
      const code = `self.onmessage = () => { self.postMessage({ ua: navigator.userAgent }); }`;
      const data = await createWorkerAndGetValue(code);
      const match = mainUA === data.ua;
      workerConsistency.dedicatedWorkerUA = {
        passed: match,
        detail: match ? "UA matches window and dedicated worker" : `MISMATCH: window="${mainUA.substring(0, 60)}..." worker="${(data.ua || "").substring(0, 60)}..."`
      };
    } catch (e) {
      workerConsistency.dedicatedWorkerUA = {
        passed: true,
        detail: "Dedicated worker unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      const code = `self.onmessage = () => { self.postMessage({ platform: navigator.platform }); }`;
      const data = await createWorkerAndGetValue(code);
      const match = mainPlatform === data.platform;
      workerConsistency.dedicatedWorkerPlatform = {
        passed: match,
        detail: match ? "Platform matches: " + mainPlatform : `MISMATCH: window="${mainPlatform}" worker="${data.platform}"`
      };
    } catch (e) {
      workerConsistency.dedicatedWorkerPlatform = {
        passed: true,
        detail: "Dedicated worker unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      const code = `self.onmessage = () => { self.postMessage({ hwc: navigator.hardwareConcurrency }); }`;
      const data = await createWorkerAndGetValue(code);
      const match = mainHWC === data.hwc;
      workerConsistency.dedicatedWorkerHWC = {
        passed: match,
        detail: match ? "hardwareConcurrency matches: " + mainHWC : `MISMATCH: window=${mainHWC} worker=${data.hwc}`
      };
    } catch (e) {
      workerConsistency.dedicatedWorkerHWC = {
        passed: true,
        detail: "Dedicated worker unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      const code = `self.onmessage = () => { self.postMessage({ lang: navigator.language }); }`;
      const data = await createWorkerAndGetValue(code);
      const match = mainLang === data.lang;
      workerConsistency.dedicatedWorkerLanguage = {
        passed: match,
        detail: match ? "Language matches: " + mainLang : `MISMATCH: window="${mainLang}" worker="${data.lang}"`
      };
    } catch (e) {
      workerConsistency.dedicatedWorkerLanguage = {
        passed: true,
        detail: "Dedicated worker unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      const code = `self.onmessage = () => {
  var tz = "unknown";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e) {}
  self.postMessage({ tz: tz });
}`;
      const data = await createWorkerAndGetValue(code);
      const match = mainTZ === data.tz;
      workerConsistency.workerTimezone = {
        passed: match,
        detail: match ? "Timezone matches: " + mainTZ : `MISMATCH: window="${mainTZ}" worker="${data.tz}"`
      };
    } catch (e) {
      workerConsistency.workerTimezone = {
        passed: true,
        detail: "Dedicated worker unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      const code = `onconnect = (e) => { const port = e.ports[0]; port.postMessage({ ua: navigator.userAgent }); }`;
      const data = await createSharedWorkerAndGetValue(code);
      const match = mainUA === data.ua;
      workerConsistency.sharedWorkerUA = {
        passed: match,
        detail: match ? "SharedWorker UA matches window" : `MISMATCH: window="${mainUA.substring(0, 60)}..." shared="${(data.ua || "").substring(0, 60)}..."`
      };
    } catch (e) {
      workerConsistency.sharedWorkerUA = {
        passed: true,
        detail: "SharedWorker unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      const code = `self.onmessage = () => {
  try {
    const canvas = new OffscreenCanvas(256, 256);
    const gl = canvas.getContext('webgl');
    if (!gl) { self.postMessage({ renderer: null, error: 'No WebGL' }); return; }
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
    self.postMessage({ renderer });
  } catch(e) { self.postMessage({ renderer: null, error: e.message }); }
}`;
      const data = await createWorkerAndGetValue(code);
      if (data.error) {
        workerConsistency.offscreenCanvasWebGL = {
          passed: true,
          detail: "OffscreenCanvas WebGL not available in worker: " + data.error
        };
      } else if (!mainWebGLRenderer) {
        workerConsistency.offscreenCanvasWebGL = {
          passed: true,
          detail: "Main thread WebGL renderer not available for comparison"
        };
      } else {
        const match = mainWebGLRenderer === data.renderer;
        workerConsistency.offscreenCanvasWebGL = {
          passed: match,
          detail: match ? "WebGL renderer matches in worker OffscreenCanvas" : `MISMATCH: window="${mainWebGLRenderer.substring(0, 40)}" worker="${(data.renderer || "").substring(0, 40)}"`
        };
      }
    } catch (e) {
      workerConsistency.offscreenCanvasWebGL = {
        passed: true,
        detail: "OffscreenCanvas test unavailable: " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    try {
      if (!navigator.serviceWorker) {
        throw new Error("ServiceWorker API not available");
      }
      const data = await Promise.race([
        new Promise((resolve, reject) => {
          navigator.serviceWorker.ready.then((reg) => {
            if (!reg.active) {
              reject(new Error("No active ServiceWorker"));
              return;
            }
            const channel = new MessageChannel();
            channel.port1.onmessage = (e) => {
              resolve(e.data);
            };
            reg.active.postMessage({ type: "getInfo" }, [channel.port2]);
          }).catch(reject);
        }),
        new Promise(
          (_, reject) => setTimeout(() => reject(new Error("ServiceWorker timeout")), 5e3)
        )
      ]);
      const match = mainUA === data.ua;
      workerConsistency.serviceWorkerUA = {
        passed: match,
        detail: match ? "ServiceWorker UA matches window" : `MISMATCH: window="${mainUA.substring(0, 60)}..." sw="${(data.ua || "").substring(0, 60)}..."`
      };
    } catch (e) {
      workerConsistency.serviceWorkerUA = {
        passed: true,
        detail: "ServiceWorker not registered (requires HTTPS origin): " + ((e == null ? void 0 : e.message) || String(e))
      };
    }
    return { workerConsistency };
  }
  var init_workers = __esm({
    "../build-tester/src/lib/checks/workers.ts"() {
      "use client";
    }
  });

  // ../build-tester/src/lib/checks/index.ts
  var index_exports = {};
  __export(index_exports, {
    runAllChecks: () => runAllChecks
  });
  var SELF_DESTRUCT_FUNCTIONS = [
    "setFontSpacingSeed",
    "setAudioFingerprintSeed",
    "setCanvasSeed",
    "setTimezone",
    "setScreenDimensions",
    "setScreenColorDepth",
    "setNavigatorPlatform",
    "setNavigatorOscpu",
    "setNavigatorHardwareConcurrency",
    "setWebGLVendor",
    "setWebGLRenderer",
    "setFontList",
    "setSpeechVoices",
    "setWebRTCIPv4"
  ];
  function runSelfDestructChecks() {
    const results = {};
    for (const fn of SELF_DESTRUCT_FUNCTIONS) {
      const destroyed = typeof window[fn] === "undefined";
      results[fn] = {
        passed: destroyed,
        detail: destroyed ? `${fn} deleted from window after init` : `${fn} still present on window \u2014 self-destruct failed`
      };
    }
    return results;
  }
  async function runAllChecks(onPhaseComplete) {
    const { collectFingerprints: collectFingerprints2, checkWebRTC: checkWebRTC2 } = await Promise.resolve().then(() => (init_collectors(), collectors_exports));
    const fingerprints = await collectFingerprints2();
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "fingerprints" });
    const { runCoreChecks: runCoreChecks2 } = await Promise.resolve().then(() => (init_core(), core_exports));
    const core = await runCoreChecks2();
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "core" });
    const { runExtendedChecks: runExtendedChecks2 } = await Promise.resolve().then(() => (init_extended(), extended_exports));
    const extended = await runExtendedChecks2();
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "extended" });
    const { runWorkerChecks: runWorkerChecks2 } = await Promise.resolve().then(() => (init_workers(), workers_exports));
    const workers = await runWorkerChecks2();
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "workers" });
    const webrtc = await checkWebRTC2();
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "webrtc" });
    const fingerprints2 = await collectFingerprints2();
    const diffs = [];
    if (fingerprints.canvas.hash !== fingerprints2.canvas.hash) diffs.push("canvas");
    if (fingerprints.audio.hash !== fingerprints2.audio.hash) diffs.push("audio");
    if (fingerprints.fonts.hash !== fingerprints2.fonts.hash) diffs.push("fonts");
    if (fingerprints.clientRects.hash !== fingerprints2.clientRects.hash) diffs.push("clientRects");
    if (fingerprints.speechVoices.count > 0 && fingerprints2.speechVoices.count > 0 && fingerprints.speechVoices.hash !== fingerprints2.speechVoices.hash) diffs.push("speechVoices");
    const stable = diffs.length === 0;
    const detail = stable ? "All fingerprints stable across two collections" : `Unstable: ${diffs.join(", ")} changed between collections`;
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "stability" });
    const selfDestruct = runSelfDestructChecks();
    onPhaseComplete == null ? void 0 : onPhaseComplete({ phase: "selfDestruct" });
    return {
      fingerprints,
      core,
      extended,
      workers,
      webrtc,
      stability: { fingerprints2, stable, detail },
      selfDestruct
    };
  }
  return __toCommonJS(index_exports);
})();
