"use client";

import type { CheckResult, TestResults } from "../types";

export interface PhaseResult {
  phase: string;
}

const SELF_DESTRUCT_FUNCTIONS = [
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
  "setWebRTCIPv4",
];

function runSelfDestructChecks(): Record<string, CheckResult> {
  const results: Record<string, CheckResult> = {};
  for (const fn of SELF_DESTRUCT_FUNCTIONS) {
    const destroyed = typeof (window as any)[fn] === "undefined";
    results[fn] = {
      passed: destroyed,
      detail: destroyed
        ? `${fn} deleted from window after init`
        : `${fn} still present on window — self-destruct failed`,
    };
  }
  return results;
}

export async function runAllChecks(
  onPhaseComplete?: (phase: PhaseResult) => void
): Promise<TestResults> {
  // Phase 1: Collect fingerprints
  const { collectFingerprints, checkWebRTC } = await import("./collectors");
  const fingerprints = await collectFingerprints();
  onPhaseComplete?.({ phase: "fingerprints" });

  // Phase 2: Core checks
  const { runCoreChecks } = await import("./core");
  const core = await runCoreChecks();
  onPhaseComplete?.({ phase: "core" });

  // Phase 3: Extended checks
  const { runExtendedChecks } = await import("./extended");
  const extended = await runExtendedChecks();
  onPhaseComplete?.({ phase: "extended" });

  // Phase 4: Worker consistency checks
  const { runWorkerChecks } = await import("./workers");
  const workers = await runWorkerChecks();
  onPhaseComplete?.({ phase: "workers" });

  // Phase 5: WebRTC leak check
  const webrtc = await checkWebRTC();
  onPhaseComplete?.({ phase: "webrtc" });

  // Phase 6: Stability - collect fingerprints again and compare
  const fingerprints2 = await collectFingerprints();
  const diffs: string[] = [];
  if (fingerprints.canvas.hash !== fingerprints2.canvas.hash) diffs.push("canvas");
  if (fingerprints.audio.hash !== fingerprints2.audio.hash) diffs.push("audio");
  if (fingerprints.fonts.hash !== fingerprints2.fonts.hash) diffs.push("fonts");
  if (fingerprints.clientRects.hash !== fingerprints2.clientRects.hash) diffs.push("clientRects");
  // Only compare speechVoices if both collections returned voices.
  if (fingerprints.speechVoices.count > 0 && fingerprints2.speechVoices.count > 0 &&
      fingerprints.speechVoices.hash !== fingerprints2.speechVoices.hash) diffs.push("speechVoices");
  const stable = diffs.length === 0;
  const detail = stable
    ? "All fingerprints stable across two collections"
    : `Unstable: ${diffs.join(", ")} changed between collections`;
  onPhaseComplete?.({ phase: "stability" });

  // Phase 7: Self-destruct — verify init script functions deleted themselves from window
  const selfDestruct = runSelfDestructChecks();
  onPhaseComplete?.({ phase: "selfDestruct" });

  return {
    fingerprints,
    core,
    extended,
    workers,
    webrtc,
    stability: { fingerprints2, stable, detail },
    selfDestruct,
  };
}
