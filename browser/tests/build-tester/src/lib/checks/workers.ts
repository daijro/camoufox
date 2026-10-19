"use client";

type CheckResult = { passed: boolean; detail: string };
type CategoryResults = Record<string, CheckResult>;

function createWorkerAndGetValue<T>(code: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const blob = new Blob([code], { type: "application/javascript" });
    const url = URL.createObjectURL(blob);
    const worker = new Worker(url);
    const timeout = setTimeout(() => {
      worker.terminate();
      URL.revokeObjectURL(url);
      reject(new Error("Worker timeout"));
    }, 5000);
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

function createSharedWorkerAndGetValue<T>(code: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const blob = new Blob([code], { type: "application/javascript" });
    const url = URL.createObjectURL(blob);
    const sw = new SharedWorker(url);
    const timeout = setTimeout(() => {
      URL.revokeObjectURL(url);
      reject(new Error("SharedWorker timeout"));
    }, 5000);
    sw.port.onmessage = (e) => {
      clearTimeout(timeout);
      URL.revokeObjectURL(url);
      resolve(e.data);
    };
    sw.onerror = (e) => {
      clearTimeout(timeout);
      URL.revokeObjectURL(url);
      reject(new Error((e as ErrorEvent).message || "SharedWorker error"));
    };
    sw.port.start();
    sw.port.postMessage("go");
  });
}

export async function runWorkerChecks(): Promise<
  Record<string, Record<string, { passed: boolean; detail: string }>>
> {
  const workerConsistency: CategoryResults = {};

  // Main thread reference values
  const mainUA = navigator.userAgent;
  const mainPlatform = navigator.platform;
  const mainHWC = navigator.hardwareConcurrency;
  const mainLang = navigator.language;
  const mainTZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

  // Get WebGL renderer from main thread for comparison
  let mainWebGLRenderer = "";
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl");
    if (gl) {
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      if (ext) {
        mainWebGLRenderer =
          (gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) as string) || "";
      }
    }
  } catch {
    // ignore
  }

  // dedicatedWorkerUA
  try {
    const code = `self.onmessage = () => { self.postMessage({ ua: navigator.userAgent }); }`;
    const data = await createWorkerAndGetValue<{ ua: string }>(code);
    const match = mainUA === data.ua;
    workerConsistency.dedicatedWorkerUA = {
      passed: match,
      detail: match
        ? "UA matches window and dedicated worker"
        : `MISMATCH: window="${mainUA.substring(0, 60)}..." worker="${(data.ua || "").substring(0, 60)}..."`,
    };
  } catch (e: any) {
    workerConsistency.dedicatedWorkerUA = {
      passed: true,
      detail: "Dedicated worker unavailable: " + (e?.message || String(e)),
    };
  }

  // dedicatedWorkerPlatform
  try {
    const code = `self.onmessage = () => { self.postMessage({ platform: navigator.platform }); }`;
    const data = await createWorkerAndGetValue<{ platform: string }>(code);
    const match = mainPlatform === data.platform;
    workerConsistency.dedicatedWorkerPlatform = {
      passed: match,
      detail: match
        ? "Platform matches: " + mainPlatform
        : `MISMATCH: window="${mainPlatform}" worker="${data.platform}"`,
    };
  } catch (e: any) {
    workerConsistency.dedicatedWorkerPlatform = {
      passed: true,
      detail: "Dedicated worker unavailable: " + (e?.message || String(e)),
    };
  }

  // dedicatedWorkerHWC
  try {
    const code = `self.onmessage = () => { self.postMessage({ hwc: navigator.hardwareConcurrency }); }`;
    const data = await createWorkerAndGetValue<{ hwc: number }>(code);
    const match = mainHWC === data.hwc;
    workerConsistency.dedicatedWorkerHWC = {
      passed: match,
      detail: match
        ? "hardwareConcurrency matches: " + mainHWC
        : `MISMATCH: window=${mainHWC} worker=${data.hwc}`,
    };
  } catch (e: any) {
    workerConsistency.dedicatedWorkerHWC = {
      passed: true,
      detail: "Dedicated worker unavailable: " + (e?.message || String(e)),
    };
  }

  // dedicatedWorkerLanguage
  try {
    const code = `self.onmessage = () => { self.postMessage({ lang: navigator.language }); }`;
    const data = await createWorkerAndGetValue<{ lang: string }>(code);
    const match = mainLang === data.lang;
    workerConsistency.dedicatedWorkerLanguage = {
      passed: match,
      detail: match
        ? "Language matches: " + mainLang
        : `MISMATCH: window="${mainLang}" worker="${data.lang}"`,
    };
  } catch (e: any) {
    workerConsistency.dedicatedWorkerLanguage = {
      passed: true,
      detail: "Dedicated worker unavailable: " + (e?.message || String(e)),
    };
  }

  // workerTimezone
  try {
    const code = `self.onmessage = () => {
  var tz = "unknown";
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch(e) {}
  self.postMessage({ tz: tz });
}`;
    const data = await createWorkerAndGetValue<{ tz: string }>(code);
    const match = mainTZ === data.tz;
    workerConsistency.workerTimezone = {
      passed: match,
      detail: match
        ? "Timezone matches: " + mainTZ
        : `MISMATCH: window="${mainTZ}" worker="${data.tz}"`,
    };
  } catch (e: any) {
    workerConsistency.workerTimezone = {
      passed: true,
      detail: "Dedicated worker unavailable: " + (e?.message || String(e)),
    };
  }

  // sharedWorkerUA
  try {
    const code = `onconnect = (e) => { const port = e.ports[0]; port.postMessage({ ua: navigator.userAgent }); }`;
    const data = await createSharedWorkerAndGetValue<{ ua: string }>(code);
    const match = mainUA === data.ua;
    workerConsistency.sharedWorkerUA = {
      passed: match,
      detail: match
        ? "SharedWorker UA matches window"
        : `MISMATCH: window="${mainUA.substring(0, 60)}..." shared="${(data.ua || "").substring(0, 60)}..."`,
    };
  } catch (e: any) {
    workerConsistency.sharedWorkerUA = {
      passed: true,
      detail: "SharedWorker unavailable: " + (e?.message || String(e)),
    };
  }

  // offscreenCanvasWebGL
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
    const data = await createWorkerAndGetValue<{
      renderer: string | null;
      error?: string;
    }>(code);

    if (data.error) {
      workerConsistency.offscreenCanvasWebGL = {
        passed: true,
        detail:
          "OffscreenCanvas WebGL not available in worker: " + data.error,
      };
    } else if (!mainWebGLRenderer) {
      workerConsistency.offscreenCanvasWebGL = {
        passed: true,
        detail:
          "Main thread WebGL renderer not available for comparison",
      };
    } else {
      const match = mainWebGLRenderer === data.renderer;
      workerConsistency.offscreenCanvasWebGL = {
        passed: match,
        detail: match
          ? "WebGL renderer matches in worker OffscreenCanvas"
          : `MISMATCH: window="${mainWebGLRenderer.substring(0, 40)}" worker="${(data.renderer || "").substring(0, 40)}"`,
      };
    }
  } catch (e: any) {
    workerConsistency.offscreenCanvasWebGL = {
      passed: true,
      detail: "OffscreenCanvas test unavailable: " + (e?.message || String(e)),
    };
  }

  // serviceWorkerUA
  try {
    if (!navigator.serviceWorker) {
      throw new Error("ServiceWorker API not available");
    }

    const data = await Promise.race([
      new Promise<{ ua: string }>((resolve, reject) => {
        navigator.serviceWorker.ready
          .then((reg) => {
            if (!reg.active) {
              reject(new Error("No active ServiceWorker"));
              return;
            }
            const channel = new MessageChannel();
            channel.port1.onmessage = (e) => {
              resolve(e.data);
            };
            reg.active.postMessage({ type: "getInfo" }, [channel.port2]);
          })
          .catch(reject);
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("ServiceWorker timeout")), 5000)
      ),
    ]);

    const match = mainUA === data.ua;
    workerConsistency.serviceWorkerUA = {
      passed: match,
      detail: match
        ? "ServiceWorker UA matches window"
        : `MISMATCH: window="${mainUA.substring(0, 60)}..." sw="${(data.ua || "").substring(0, 60)}..."`,
    };
  } catch (e: any) {
    workerConsistency.serviceWorkerUA = {
      passed: true,
      detail:
        "ServiceWorker not registered (requires HTTPS origin): " +
        (e?.message || String(e)),
    };
  }

  return { workerConsistency };
}
