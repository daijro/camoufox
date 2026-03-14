import re
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────

PROXIES_FILE = Path(__file__).parent / "proxies.txt"
BUILD_TESTER_DIR = Path(__file__).parent.parent / "build-tester"

# ─── Check category labels ────────────────────────────────────────────────────

CATEGORY_LABELS = {
    "automation": "Automation Detection",
    "jsEngine": "JS Engine",
    "lieDetection": "Lie Detection",
    "firefoxAPIs": "Firefox APIs",
    "crossSignal": "Cross-Signal",
    "cssFingerprint": "CSS Fingerprint",
    "mathEngine": "Math Engine",
    "permissionsAPI": "Permissions",
    "speechVoices": "Speech Voices",
    "performanceAPI": "Performance",
    "intlConsistency": "Intl Consistency",
    "emojiFingerprint": "Emoji",
    "canvasNoiseDetection": "Canvas Noise",
    "webglRenderHash": "WebGL Render",
    "fontPlatformConsistency": "Font Platform",
    "audioIntegrity": "Audio Integrity",
    "iframeTesting": "Iframe Testing",
    "workerConsistency": "Workers",
    "headlessDetection": "Headless Detection",
    "trashDetection": "Trash Detection",
    "fontEnvironment": "Font Environment",
}

# ─── ANSI colors ──────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(s: str) -> str:
    return ANSI_ESCAPE_RE.sub("", s)


def grade_color(g: str) -> str:
    if g == "A":
        return GREEN
    if g in ("B", "C"):
        return YELLOW
    return RED


# ─── Certificate box drawing ──────────────────────────────────────────────────

BOX_W = 60


def box_line(inner: str) -> str:
    visible = len(strip_ansi(inner))
    return f"║{inner}{' ' * max(0, BOX_W - visible)}║"


def box_sep() -> str:
    return f"╠{'═' * BOX_W}╣"


def box_top() -> str:
    return f"╔{'═' * BOX_W}╗"


def box_bot() -> str:
    return f"╚{'═' * BOX_W}╝"


# ─── ASCII art ────────────────────────────────────────────────────────────────

CAT_ART = r"""    /\_____/\
   /  o   o  \
  ( ==  ^  == )
   )         (
  (  )     (  )
 ( (  )   (  ) )
(__(__)___(__)__)"""
