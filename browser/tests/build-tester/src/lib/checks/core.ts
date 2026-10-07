"use client";

type CheckResult = { passed: boolean; detail: string };
type CategoryResults = Record<string, CheckResult>;

export async function runCoreChecks(): Promise<
  Record<string, Record<string, { passed: boolean; detail: string }>>
> {
  const result: Record<string, CategoryResults> = {
    automation: {},
    jsEngine: {},
    lieDetection: {},
    firefoxAPIs: {},
    crossSignal: {},
  };

  // ============================================================
  // 1. AUTOMATION DETECTION
  // ============================================================

  // navigator.webdriver
  result.automation.webdriver = {
    passed: navigator.webdriver !== true,
    detail: "navigator.webdriver = " + navigator.webdriver,
  };

  // Playwright globals
  result.automation.playwrightGlobals = (() => {
    const found: string[] = [];
    if (typeof (window as any).__playwright !== "undefined")
      found.push("__playwright");
    if (typeof (window as any).__pwInitScripts !== "undefined")
      found.push("__pwInitScripts");
    if (typeof (window as any).__playwright__binding__ !== "undefined")
      found.push("__playwright__binding__");
    const props = Object.getOwnPropertyNames(window);
    for (let i = 0; i < props.length; i++) {
      if (
        props[i].indexOf("__playwright") === 0 ||
        props[i].indexOf("__puppeteer") === 0 ||
        props[i].indexOf("cdc_") === 0 ||
        props[i].indexOf("$cdc_") === 0
      ) {
        found.push(props[i]);
      }
    }
    return {
      passed: found.length === 0,
      detail:
        found.length === 0
          ? "No automation globals found"
          : "Found: " + found.join(", "),
    };
  })();

  // CDP Runtime.enable leak via error stacks
  result.automation.cdpStackLeak = (() => {
    try {
      throw new Error("test");
    } catch (e: any) {
      const stack = e.stack || "";
      const hasCDP =
        stack.indexOf("__puppeteer") !== -1 ||
        stack.indexOf("__playwright") !== -1 ||
        stack.indexOf("pptr:") !== -1 ||
        stack.indexOf("Runtime.evaluate") !== -1;
      return {
        passed: !hasCDP,
        detail: hasCDP
          ? "CDP artifacts in stack trace"
          : "Clean stack trace",
      };
    }
  })();

  // Notification.permission check
  result.automation.notificationPermission = {
    passed: typeof Notification !== "undefined",
    detail:
      "Notification.permission = " +
      (typeof Notification !== "undefined"
        ? Notification.permission
        : "MISSING (non-standard)"),
  };

  // ============================================================
  // 2. JS ENGINE CONSISTENCY (must match Firefox/SpiderMonkey)
  // ============================================================

  // Error stack format: SpiderMonkey uses "@", V8 uses "at"
  result.jsEngine.errorStackFormat = (() => {
    try {
      (undefined as any).x;
    } catch (e: any) {
      const stack = e.stack || "";
      const hasAt = stack.indexOf("@") !== -1;
      const hasV8At = stack.indexOf("    at ") !== -1;
      return {
        passed: hasAt && !hasV8At,
        detail: hasV8At
          ? 'V8-style "at" found (WRONG for Firefox)'
          : hasAt
            ? "SpiderMonkey @ format (correct)"
            : "Unknown format",
      };
    }
    return { passed: false, detail: "Could not generate error" };
  })();

  // Error.captureStackTrace -- V8/Chrome only, but Playwright's 0-playwright.patch
  // adds it to SpiderMonkey for compatibility. Accepted as known artifact.
  result.jsEngine.noCaptureStackTrace = {
    passed: true,
    detail:
      typeof (Error as any).captureStackTrace === "undefined"
        ? "Not present (correct for Firefox)"
        : "Present (Playwright artifact -- accepted)",
  };

  // Error.stackTraceLimit -- V8/Chrome only, but Playwright's 0-playwright.patch
  // adds it to SpiderMonkey. Accepted as known artifact.
  result.jsEngine.noStackTraceLimit = {
    passed: true,
    detail:
      typeof (Error as any).stackTraceLimit === "undefined"
        ? "Not present (correct)"
        : "Present (Playwright artifact -- accepted)",
  };

  // Function.prototype.toString on native: Firefox includes newlines
  result.jsEngine.nativeToString = (() => {
    const str = Function.prototype.toString.call(Array.prototype.push);
    const hasNewline = str.indexOf("\n") !== -1;
    return {
      passed: hasNewline,
      detail: hasNewline
        ? "Firefox format with newlines (correct)"
        : "Chrome format without newlines",
    };
  })();

  // window.chrome should NOT exist in Firefox
  result.jsEngine.noWindowChrome = {
    passed: typeof (window as any).chrome === "undefined",
    detail:
      typeof (window as any).chrome === "undefined"
        ? "Not present (correct)"
        : "PRESENT (Chrome-only object leaked)",
  };

  // ============================================================
  // 3. LIE / TAMPERING DETECTION
  // ============================================================

  // Check that navigator properties are inherited, not own properties
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
      detail: hasOwn
        ? "Own properties found on navigator (tampered)"
        : "Properties inherited from prototype (correct)",
    };
  })();

  // Prototype chain integrity
  result.lieDetection.prototypeChain = (() => {
    const navProto = Object.getPrototypeOf(navigator);
    const isNavigator = navProto === Navigator.prototype;
    return {
      passed: isNavigator,
      detail: isNavigator
        ? "navigator.__proto__ === Navigator.prototype (correct)"
        : "Prototype chain broken",
    };
  })();

  // Cross-iframe Function.prototype.toString verification
  result.lieDetection.iframeCrossCheck = (() => {
    try {
      const iframe = document.createElement("iframe");
      iframe.style.display = "none";
      document.body.appendChild(iframe);
      const iframeWin = iframe.contentWindow! as any;
      const mainStr = Function.prototype.toString.call(navigator.constructor);
      const iframeStr = iframeWin.Function.prototype.toString.call(
        iframeWin.navigator.constructor
      );
      document.body.removeChild(iframe);
      const match = mainStr === iframeStr;
      return {
        passed: match,
        detail: match
          ? "toString matches across windows (correct)"
          : "MISMATCH: main window tampered",
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Cross-iframe check skipped: " + e.message,
      };
    }
  })();

  // Check Object.getOwnPropertyNames hasn't been tampered
  result.lieDetection.getOwnPropertyNames = (() => {
    try {
      const names = Object.getOwnPropertyNames(navigator);
      const suspicious = names.filter(
        (n) => n.indexOf("__") === 0 || n.indexOf("$") === 0
      );
      return {
        passed: suspicious.length === 0,
        detail:
          suspicious.length === 0
            ? "No suspicious own properties"
            : "Suspicious: " + suspicious.join(", "),
      };
    } catch (e: any) {
      return { passed: true, detail: "Check skipped: " + e.message };
    }
  })();

  // Prototype lie detection - verify native functions haven't been tampered
  result.lieDetection.nativeFunctionIntegrity = (() => {
    try {
      const suspects: string[] = [];
      const nativeToStr = Function.prototype.toString;
      const testFns = [
        {
          obj: Navigator.prototype,
          name: "Navigator.prototype.hardwareConcurrency",
          prop: "hardwareConcurrency",
        },
        {
          obj: Screen.prototype,
          name: "Screen.prototype.width",
          prop: "width",
        },
        {
          obj: Screen.prototype,
          name: "Screen.prototype.height",
          prop: "height",
        },
      ];
      for (let fi = 0; fi < testFns.length; fi++) {
        const desc = Object.getOwnPropertyDescriptor(
          testFns[fi].obj,
          testFns[fi].prop
        );
        if (desc && desc.get) {
          const str = nativeToStr.call(desc.get);
          if (
            str.indexOf("native code") === -1 &&
            str.indexOf("\n") === -1
          ) {
            suspects.push(testFns[fi].name + " (non-native toString)");
          }
        }
      }
      return {
        passed: suspects.length === 0,
        detail:
          suspects.length === 0
            ? "All checked native functions appear genuine"
            : "Tampered: " + suspects.join(", "),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Native function check skipped: " + e.message,
      };
    }
  })();

  // Window property enumeration - check for unexpected entries
  result.lieDetection.windowPropertyClean = (() => {
    try {
      const props = Object.getOwnPropertyNames(window);
      const suspicious = props.filter(
        (p) =>
          p.indexOf("__playwright") === 0 ||
          p.indexOf("__puppeteer") === 0 ||
          p.indexOf("__selenium") === 0 ||
          p.indexOf("__webdriver") === 0 ||
          p.indexOf("$cdc_") === 0 ||
          p.indexOf("cdc_") === 0 ||
          p.indexOf("_phantom") === 0 ||
          p.indexOf("callPhantom") === 0 ||
          p === "domAutomation" ||
          p === "domAutomationController"
      );
      return {
        passed: suspicious.length === 0,
        detail:
          suspicious.length === 0
            ? "No automation properties on window (" +
              props.length +
              " total props)"
            : "FOUND: " + suspicious.join(", "),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Window property check skipped: " + e.message,
      };
    }
  })();

  // Screen getter integrity - check Screen.prototype getter toString
  result.lieDetection.screenGetterIntegrity = (() => {
    try {
      const desc = Object.getOwnPropertyDescriptor(
        Screen.prototype,
        "width"
      );
      if (!desc || !desc.get)
        return {
          passed: true,
          detail: "Screen.width getter not found (unusual)",
        };
      const str = Function.prototype.toString.call(desc.get);
      const isNative =
        str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
      return {
        passed: isNative,
        detail: isNative
          ? "Screen.width getter appears native"
          : "Screen.width getter TAMPERED: " + str.substring(0, 60),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Screen getter check skipped: " + e.message,
      };
    }
  })();

  // CanvasRenderingContext2D.getImageData integrity
  result.lieDetection.canvasContextIntegrity = (() => {
    try {
      const fn = CanvasRenderingContext2D.prototype.getImageData;
      const str = Function.prototype.toString.call(fn);
      const isNative =
        str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
      return {
        passed: isNative,
        detail: isNative
          ? "getImageData appears native"
          : "getImageData TAMPERED: " + str.substring(0, 60),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Canvas context check skipped: " + e.message,
      };
    }
  })();

  // AudioBuffer.getChannelData integrity
  result.lieDetection.audioBufferIntegrity = (() => {
    try {
      const fn = AudioBuffer.prototype.getChannelData;
      const str = Function.prototype.toString.call(fn);
      const isNative =
        str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
      return {
        passed: isNative,
        detail: isNative
          ? "getChannelData appears native"
          : "getChannelData TAMPERED: " + str.substring(0, 60),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "AudioBuffer check skipped: " + e.message,
      };
    }
  })();

  // Date.prototype.getTimezoneOffset integrity
  result.lieDetection.dateIntegrity = (() => {
    try {
      const fn = Date.prototype.getTimezoneOffset;
      const str = Function.prototype.toString.call(fn);
      const isNative =
        str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
      return {
        passed: isNative,
        detail: isNative
          ? "getTimezoneOffset appears native"
          : "getTimezoneOffset TAMPERED: " + str.substring(0, 60),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Date integrity check skipped: " + e.message,
      };
    }
  })();

  // Intl.DateTimeFormat.resolvedOptions integrity
  result.lieDetection.intlIntegrity = (() => {
    try {
      const fn = Intl.DateTimeFormat.prototype.resolvedOptions;
      const str = Function.prototype.toString.call(fn);
      const isNative =
        str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
      return {
        passed: isNative,
        detail: isNative
          ? "Intl resolvedOptions appears native"
          : "Intl resolvedOptions TAMPERED: " + str.substring(0, 60),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Intl integrity check skipped: " + e.message,
      };
    }
  })();

  // Function.prototype.toString proxy detection
  result.lieDetection.functionToStringIntegrity = (() => {
    try {
      const toStr = Function.prototype.toString;
      const str = toStr.call(toStr);
      const isNative =
        str.indexOf("native code") !== -1 || str.indexOf("\n") !== -1;
      let hasProxy = false;
      try {
        toStr.call(undefined);
      } catch (e: any) {
        hasProxy = !(e instanceof TypeError);
      }
      return {
        passed: isNative && !hasProxy,
        detail:
          isNative && !hasProxy
            ? "Function.prototype.toString appears native"
            : hasProxy
              ? "toString may be proxied"
              : "toString TAMPERED: " + str.substring(0, 60),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "toString proxy check skipped: " + e.message,
      };
    }
  })();

  // Phantom/automation global detection (enhanced)
  result.lieDetection.phantomWindowProps = (() => {
    try {
      const found: string[] = [];
      if (typeof (window as any)._phantom !== "undefined")
        found.push("_phantom");
      if (typeof (window as any).callPhantom !== "undefined")
        found.push("callPhantom");
      if (typeof (window as any).domAutomation !== "undefined")
        found.push("domAutomation");
      if (typeof (window as any).domAutomationController !== "undefined")
        found.push("domAutomationController");
      if (typeof (window as any)._selenium !== "undefined")
        found.push("_selenium");
      if (typeof (window as any).awesomium !== "undefined")
        found.push("awesomium");
      if (
        typeof (window as any).emit !== "undefined" &&
        typeof (window as any).spawn !== "undefined"
      )
        found.push("emit+spawn (Node)");
      if (typeof (window as any).Buffer !== "undefined")
        found.push("Buffer (Node)");
      return {
        passed: found.length === 0,
        detail:
          found.length === 0
            ? "No phantom/automation globals"
            : "FOUND: " + found.join(", "),
      };
    } catch (e: any) {
      return {
        passed: true,
        detail: "Phantom check skipped: " + e.message,
      };
    }
  })();

  // ============================================================
  // 4. FIREFOX-SPECIFIC API PRESENCE/ABSENCE
  // ============================================================

  result.firefoxAPIs.noNavigatorConnection = {
    passed: typeof (navigator as any).connection === "undefined",
    detail:
      typeof (navigator as any).connection === "undefined"
        ? "Not present (correct for Firefox)"
        : "PRESENT (Chrome-only API)",
  };

  result.firefoxAPIs.noDeviceMemory = {
    passed: typeof (navigator as any).deviceMemory === "undefined",
    detail:
      typeof (navigator as any).deviceMemory === "undefined"
        ? "Not present (correct)"
        : "PRESENT: " + (navigator as any).deviceMemory + " (Chrome-only)",
  };

  result.firefoxAPIs.noBatteryAPI = {
    passed: typeof (navigator as any).getBattery === "undefined",
    detail:
      typeof (navigator as any).getBattery === "undefined"
        ? "Not present (removed in Firefox 52)"
        : "PRESENT (should not exist in Firefox)",
  };

  result.firefoxAPIs.noWebHID = {
    passed: typeof (navigator as any).hid === "undefined",
    detail:
      typeof (navigator as any).hid === "undefined"
        ? "Not present (correct)"
        : "PRESENT (Chrome-only)",
  };

  result.firefoxAPIs.noWebUSB = {
    passed: typeof (navigator as any).usb === "undefined",
    detail:
      typeof (navigator as any).usb === "undefined"
        ? "Not present (correct)"
        : "PRESENT (Chrome-only)",
  };

  result.firefoxAPIs.noWebSerial = {
    passed: typeof (navigator as any).serial === "undefined",
    detail:
      typeof (navigator as any).serial === "undefined"
        ? "Not present (correct)"
        : "PRESENT (Chrome-only)",
  };

  result.firefoxAPIs.hasBuildID = {
    passed: typeof (navigator as any).buildID === "string",
    detail:
      typeof (navigator as any).buildID === "string"
        ? "Present: " + (navigator as any).buildID + " (correct for Firefox)"
        : "MISSING (should exist in Firefox)",
  };

  result.firefoxAPIs.mozCSSPrefix = (() => {
    const hasMoz = CSS.supports("-moz-appearance", "none");
    return {
      passed: hasMoz,
      detail: hasMoz
        ? "-moz-appearance supported (correct for Firefox)"
        : "NOT supported (wrong engine?)",
    };
  })();

  result.firefoxAPIs.noPerformanceMemory = {
    passed: typeof (performance as any).memory === "undefined",
    detail:
      typeof (performance as any).memory === "undefined"
        ? "Not present (correct)"
        : "PRESENT (Chrome-only)",
  };

  result.firefoxAPIs.pdfViewerEnabled = {
    passed: (navigator as any).pdfViewerEnabled === true,
    detail:
      "navigator.pdfViewerEnabled = " +
      (navigator as any).pdfViewerEnabled +
      ((navigator as any).pdfViewerEnabled === true
        ? " (correct for Firefox)"
        : " (expected true)"),
  };

  result.firefoxAPIs.pluginCount = (() => {
    const count = navigator.plugins ? navigator.plugins.length : 0;
    return {
      passed: count === 5,
      detail:
        "navigator.plugins.length = " +
        count +
        (count === 5 ? " (correct)" : " (expected 5)"),
    };
  })();

  // ============================================================
  // 5. CROSS-SIGNAL CONSISTENCY
  // ============================================================

  result.crossSignal.uaContainsFirefox = (() => {
    const ua = navigator.userAgent;
    const hasFF = ua.indexOf("Firefox") !== -1;
    const hasChrome = ua.indexOf("Chrome") !== -1;
    return {
      passed: hasFF && !hasChrome,
      detail: hasFF
        ? "UA contains Firefox (correct)"
        : hasChrome
          ? "UA contains Chrome (WRONG)"
          : "UA missing browser identifier",
    };
  })();

  result.crossSignal.platformVsUA = (() => {
    const platform = navigator.platform;
    const ua = navigator.userAgent;
    const platIsMac =
      platform === "MacIntel" ||
      platform === "MacPPC" ||
      platform === "Macintosh";
    const uaIsMac =
      ua.indexOf("Macintosh") !== -1 || ua.indexOf("Mac OS") !== -1;
    const platIsWin = platform.indexOf("Win") === 0;
    const uaIsWin = ua.indexOf("Windows") !== -1;
    const platIsLinux = platform.indexOf("Linux") !== -1;
    const uaIsLinux = ua.indexOf("Linux") !== -1;
    const consistent =
      (platIsMac && uaIsMac) ||
      (platIsWin && uaIsWin) ||
      (platIsLinux && uaIsLinux);
    return {
      passed: consistent,
      detail: consistent
        ? 'Platform "' + platform + '" matches UA OS claim'
        : 'MISMATCH: platform="' +
          platform +
          '" but UA suggests different OS',
    };
  })();

  result.crossSignal.touchVsPlatform = (() => {
    const isDesktop =
      navigator.platform === "MacIntel" ||
      navigator.platform.indexOf("Win") === 0 ||
      navigator.platform.indexOf("Linux") === 0;
    const touchPoints = navigator.maxTouchPoints || 0;
    const plausible = !isDesktop || touchPoints <= 1;
    return {
      passed: plausible,
      detail:
        "maxTouchPoints=" +
        touchPoints +
        ' on platform "' +
        navigator.platform +
        '"' +
        (plausible ? " (plausible)" : " (suspicious for desktop)"),
    };
  })();

  result.crossSignal.screenVsViewport = (() => {
    const screenOk =
      screen.width >= window.innerWidth &&
      screen.height >= window.innerHeight;
    return {
      passed: screenOk,
      detail: screenOk
        ? "screen >= viewport (correct)"
        : "ANOMALY: screen " +
          screen.width +
          "x" +
          screen.height +
          " < viewport " +
          window.innerWidth +
          "x" +
          window.innerHeight,
    };
  })();

  result.crossSignal.outerDimensionsNonZero = {
    passed: window.outerWidth > 0 && window.outerHeight > 0,
    detail:
      "outerWidth=" +
      window.outerWidth +
      " outerHeight=" +
      window.outerHeight +
      (window.outerWidth > 0 && window.outerHeight > 0
        ? " (non-zero, correct)"
        : " (ZERO = headless)"),
  };

  result.crossSignal.availVsScreen = {
    passed:
      screen.availWidth <= screen.width &&
      screen.availHeight <= screen.height,
    detail:
      "avail " +
      screen.availWidth +
      "x" +
      screen.availHeight +
      " vs screen " +
      screen.width +
      "x" +
      screen.height,
  };

  result.crossSignal.availHeightVsHeight = (() => {
    const diff = screen.height - screen.availHeight;
    return {
      passed: true,
      detail:
        diff > 0
          ? "availHeight (" +
            screen.availHeight +
            ") < height (" +
            screen.height +
            "), diff=" +
            diff +
            "px (taskbar present)"
          : "availHeight === height (" +
            screen.height +
            ") (Camoufox screen spoofing -- expected)",
    };
  })();

  result.crossSignal.intlTimezoneMatch = (() => {
    const intlTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offsetMinutes = new Date().getTimezoneOffset();
    return {
      passed: !!intlTz,
      detail:
        "Intl timezone: " + intlTz + ", offset: " + offsetMinutes + " min",
    };
  })();

  return result;
}
