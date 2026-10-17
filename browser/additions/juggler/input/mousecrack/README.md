# mousecrack (vendored)

Camoufox's copy of [mousecrack](https://github.com/puffinsoft/mousecrack) at
`6c704e4`: a recurrent network trained on recorded mouse movements, which
synthesizes a path step by step. It is the second cursor generator for
`humanize=True`, chosen with `humanize:engine = "mousecrack"`
(`humanize_engine="mousecrack"` in the Python launcher). Cursory
(`../cursory/`) stays the default.

Licensing: MIT, text in `LICENSE`.

## What it does

Each step feeds the previous step (dx, dy, dt) and the distance left to the
target into two 128-unit LSTMs. A dense layer turns their output into a
5-component Gaussian mixture over the next step, and a step is drawn from it.
Generation stops within 3px of the target or after 500 steps. The path is
then smoothed with a 7-point moving average, as upstream's `move()` does.

## How Camoufox calls it

`../CursorTrajectory.js` is the only caller. It:
- retries a draw that never reaches the target (then falls back to Cursory
  for that move);
- scales the timing into `humanize:minTime`/`maxTime`;
- thins the path to at most 60 events a second, keeping mousecrack's own uneven
  step timing (an even clock would be a metronome).

## Local modifications

- **No onnxruntime.** Upstream runs `model.onnx` with onnxruntime-node, which
  Juggler cannot load. `model.js` evaluates the same network in plain
  JavaScript from `model.bin`/`model.json`, which
  `browser/scripts/export-mousecrack-weights.py` writes from upstream's
  `train/model.h5` (the standard model; the lite one is not vendored, since
  upstream's README says it veers off course more often).
  - Checked against onnxruntime on 1200 steps: max difference 2.4e-5.
- **Stateful LSTMs.** Upstream re-runs the whole history each step. The LSTM
  state is carried instead, which gives the same output at linear cost:
  0.22ms a step, 22ms a median move.
- **Sliced.** `mousecrack.js` yields to the event loop every 24 steps, because
  it runs on the parent process's main thread.
- **No `robotjs`.** Moving the OS cursor is upstream's `move()`; Juggler
  dispatches the points itself.

## Measured behaviour

300 moves on a 1920x1080 field, against 1936 paths from upstream's own
training data and Cursory on the same moves:

| distance | median duration: mousecrack / human / Cursory | median path/straight ratio |
|---|---|---|
| < 100px | 325 / 327 / 295 ms | 1.1 / 1.1 / 1.0 |
| 100-600px | 1060 / 480 / 584 ms | 1.6 / 1.0 / 1.0 |
| >= 600px | 1519 / 723 / 722 ms | 1.3 / 1.1 / 1.0 |

298/300 draws reached the target. Long moves are compressed into
`humanize:maxTime` (1.5s by default) like any other path.
