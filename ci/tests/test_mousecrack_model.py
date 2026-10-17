"""Juggler's port of mousecrack's network against the original model.

browser/additions/juggler/input/mousecrack/model.js evaluates mousecrack's LSTMs in
plain JavaScript because Juggler cannot load onnxruntime. These tests run it
under Node, with no browser:
- its outputs must match onnxruntime's on the original ONNX model
  (data/mousecrack-reference.json, recorded once with onnxruntime-node);
- and generated paths must reach their targets.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MOUSECRACK = REPO / "browser" / "additions" / "juggler" / "input" / "mousecrack"
REFERENCE = Path(__file__).parent / "data" / "mousecrack-reference.json"

LOAD = f"""
import {{readFileSync}} from 'node:fs';
const mc = await import({json.dumps((MOUSECRACK / 'model.js').as_uri())});
const bytes = readFileSync({json.dumps(str(MOUSECRACK / 'model.bin'))});
const weights = new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
const model = new mc.MousecrackModel(weights, JSON.parse(readFileSync({json.dumps(str(MOUSECRACK / 'model.json'))}, 'utf8')));
"""


def run_node(body):
    node = shutil.which("node")
    assert node, "node is required to test Juggler's mousecrack port"
    out = subprocess.run([node, "--input-type=module", "-e", LOAD + body],
                         capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


def test_port_matches_onnxruntime():
    reference = json.loads(REFERENCE.read_text())
    got = run_node(f"""
const sequences = {json.dumps([s['inputs'] for s in reference['sequences']])};
console.log(JSON.stringify(sequences.map(inputs => {{
  const sequence = model.start();
  return inputs.map(input => Array.from(sequence.step(input)));
}})));
""")
    for mine, ref in zip(got, reference["sequences"]):
        for step_mine, step_ref in zip(mine, ref["expected"]):
            for a, b in zip(step_mine, step_ref):
                assert abs(a - b) <= 1e-4 * max(1.0, abs(b)), (a, b)


def test_paths_reach_their_targets():
    # A seeded source so the result is reproducible; the moves span short and
    # long distances on a 1920x1080 field.
    result = run_node("""
let state = 0x9e3779b9;
const random = () => {
  state = (state + 0x6d2b79f5) >>> 0;
  let t = state;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return (((t ^ (t >>> 14)) >>> 0) + 1) / 4294967297;
};
const moves = [];
for (let i = 0; i < 40; i++) {
  const start = {x: 50 + random() * 1820, y: 50 + random() * 980};
  const end = i % 4 ? {x: 50 + random() * 1820, y: 50 + random() * 980}
                    : {x: start.x + 40 + random() * 40, y: start.y + 20};
  const {path, converged} = mc.generatePath(model, start, end, random);
  const last = path[path.length - 1];
  moves.push({converged, endsOnTarget: last.x === Math.round(end.x) && last.y === Math.round(end.y),
              timesIncrease: path.every((p, k) => k === 0 || p.t > path[k - 1].t)});
}
console.log(JSON.stringify(moves));
""")
    assert all(m["endsOnTarget"] and m["timesIncrease"] for m in result)
    # CursorTrajectory.js retries a draw that does not arrive; most must.
    assert sum(m["converged"] for m in result) >= 36
