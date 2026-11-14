import importlib.util
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "browser" / "tests" / "playwright" / "patches" / "getter-cost-parity.py"
spec = importlib.util.spec_from_file_location("getter_cost_parity", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

RENDERER = "G.getParameter(37446)"
CONTROL_NS = 31.0


def judge(expr, stock_ns, camoufox_ns):
    return guard.judge(expr, stock_ns, camoufox_ns, CONTROL_NS, CONTROL_NS)


def test_the_renderer_round_trip_swinging_either_way_passes():
    """Main's runs after #1038 and #1039: the GPU round trip's cost changed
    between sessions, once in each direction, and failed the guard."""
    assert judge(RENDERER, 15000, 31250) == (False, False)
    assert judge(RENDERER, 33750, 15625) == (False, False)


def test_a_spoof_that_skips_the_renderer_round_trip_fails():
    assert judge(RENDERER, 15000, 60) == (False, True)


def test_other_getters_keep_the_2x_bounds():
    assert judge("screen.width", 78, 160) == (True, False)
    assert judge("screen.width", 78, 30) == (False, True)
    assert judge("screen.width", 78, 83) == (False, False)
