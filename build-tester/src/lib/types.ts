export interface CheckResult {
  passed: boolean;
  detail: string;
}

export interface FingerprintData {
  navigator: {
    userAgent: string;
    platform: string;
    oscpu: string;
    hardwareConcurrency: number;
    maxTouchPoints: number;
    vendor: string;
    buildID: string;
    doNotTrack: string;
  };
  screen: {
    width: number;
    height: number;
    colorDepth: number;
    devicePixelRatio: number;
    availWidth: number;
    availHeight: number;
    pixelDepth: number;
    innerWidth: number;
    innerHeight: number;
    outerWidth: number;
    outerHeight: number;
  };
  timezone: {
    timezone: string;
    offset: number;
    localTime: string;
  };
  webgl: {
    vendor: string;
    renderer: string;
    unmaskedVendor: string;
    unmaskedRenderer: string;
    maxTextureSize: number;
  } | null;
  canvas: { hash: string; dataUrlPrefix: string };
  audio: {
    hash: string;
    sampleRate: number;
    methods: {
      getChannelData: string;
      copyFromChannel: string;
      analyserFloat: string;
      analyserByte: string;
      analyserTimeDomainFloat: string;
      analyserTimeDomainByte: string;
    };
  };
  fonts: { measureWidth: number; hash: string };
  clientRects: { hash: string };
  emojiCanvas: { hash: string };
  fontAvailability: { detected: string[]; count: number; hash: string };
  speechVoices: { names: string[]; count: number; hash: string };
}

export interface WebRTCResult {
  passed: boolean;
  iceIPs: string[];
  sdpSanitized: boolean;
  getStatsClean: boolean;
  candidateCount: number;
  detail: string;
}

export interface TestResults {
  fingerprints: FingerprintData;
  core: Record<string, Record<string, CheckResult>>;
  extended: Record<string, Record<string, CheckResult>>;
  workers: Record<string, Record<string, CheckResult>>;
  webrtc: WebRTCResult;
  stability: { fingerprints2: FingerprintData; stable: boolean; detail: string };
  selfDestruct?: Record<string, CheckResult>; // per-context only; absent for global profiles
}

// Multi-profile types

export interface ProfileConfig {
  name: string;
  os: "macos" | "linux";
  mode: "per-context" | "global";
  platform: string;
  oscpu: string;
  userAgent: string;
  hardwareConcurrency: number;
  screenWidth: number;
  screenHeight: number;
  colorDepth: number;
  timezone: string;
  webglVendor: string;
  webglRenderer: string;
  audioSeed: number;
  canvasSeed: number;
  fontSpacingSeed: number;
  fontList: string[];
  speechVoices?: string[];
}

export interface ProfileResult {
  profile: ProfileConfig;
  results: TestResults;
  matchResults: MatchCheckResult[];
  grade: string;
  passCount: number;
  totalChecks: number;
  error?: string;
}

export interface MatchCheckResult {
  name: string;
  passed: boolean;
  expected: string;
  actual: string;
}

export interface CrossProfileAnalysis {
  macPerContext: {
    uniqueAudio: number;
    uniqueCanvas: number;
    uniqueFonts: number;
    uniqueTimezones: number;
    uniqueScreens: number;
    uniqueVoices: number;
    uniqueWebGL: number;
    uniquePlatforms: number;
    total: number;
  };
  linuxPerContext: {
    uniqueAudio: number;
    uniqueCanvas: number;
    uniqueFonts: number;
    uniqueTimezones: number;
    uniqueScreens: number;
    uniqueVoices: number;
    uniqueWebGL: number;
    uniquePlatforms: number;
    total: number;
  };
}

export interface FullTestResult {
  profiles: ProfileResult[];
  crossProfile: CrossProfileAnalysis;
  overallGrade: string;
  totalPassed: number;
  totalChecks: number;
  timestamp: string;
  binaryPath: string;
}

export interface CertificateData {
  id: string;
  timestamp: string;
  platform: string;
  camoufoxVersion: string;
  passCount: number;
  totalTests: number;
  overallPass: boolean;
  resultsHash: string;
  signature: string;
  sectionResults: { name: string; passed: number; total: number }[];
  failedTests: string[];
  profileCount: number;
  crossProfile?: CrossProfileAnalysis;
}

// SSE event types
export type SSEEvent =
  | { type: "started"; runId: string }
  | { type: "progress"; profileIndex: number; profileName: string; phase: string; total: number }
  | { type: "profile-complete"; profileIndex: number; result: ProfileResult }
  | { type: "complete"; result: FullTestResult }
  | { type: "error"; message: string }
  | { type: "log"; message: string };
