#!/usr/bin/env python3
"""Export mousecrack's standard model to the flat file Juggler loads.

mousecrack (https://github.com/puffinsoft/mousecrack, MIT) ships its trained
network as Keras weights (train/model.h5) and as ONNX. Juggler cannot run
onnxruntime, so browser/additions/juggler/input/mousecrack/ runs the network itself,
from these weights:

    model.bin   every tensor as little-endian float32, in the order of LAYOUT
    model.json  the source commit and each tensor's name, shape and offset

Usage:
    pip install h5py numpy
    python3 browser/scripts/export-mousecrack-weights.py <mousecrack checkout>

The checkout must be at SOURCE_COMMIT; the input's sha256 is checked so a
different model cannot be exported under this name by accident.
"""

import hashlib
import json
import sys
from pathlib import Path

import h5py
import numpy as np

SOURCE_REPO = 'https://github.com/puffinsoft/mousecrack'
SOURCE_COMMIT = '6c704e4'
MODEL_H5 = 'train/model.h5'
SOURCE_SHA256 = '2eac338602a84530a7b1e8e05dd14c54f98b46dfcc796b89f6bdf74f04feca91'

OUT = Path(__file__).resolve().parent.parent / 'additions' / 'juggler' / 'input' / 'mousecrack'

# Keras layout: kernel [inputs, 4*units] and recurrent_kernel [units, 4*units],
# gates in the order input, forget, cell, output.
LAYOUT = [
    ('lstm0.kernel', 'lstm/lstm/lstm_cell/kernel:0'),
    ('lstm0.recurrent_kernel', 'lstm/lstm/lstm_cell/recurrent_kernel:0'),
    ('lstm0.bias', 'lstm/lstm/lstm_cell/bias:0'),
    ('lstm1.kernel', 'lstm_1/lstm_1/lstm_cell/kernel:0'),
    ('lstm1.recurrent_kernel', 'lstm_1/lstm_1/lstm_cell/recurrent_kernel:0'),
    ('lstm1.bias', 'lstm_1/lstm_1/lstm_cell/bias:0'),
    ('dense.kernel', 'dense/dense/kernel:0'),
    ('dense.bias', 'dense/dense/bias:0'),
]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1]) / MODEL_H5
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        sys.exit(f'{src}: sha256 {digest}, expected {SOURCE_SHA256} ({SOURCE_COMMIT})')

    blob = bytearray()
    tensors = []
    with h5py.File(src, 'r') as f:
        for name, key in LAYOUT:
            data = np.asarray(f[key], dtype='<f4')
            tensors.append({'name': name, 'shape': list(data.shape), 'offset': len(blob) // 4})
            blob += data.tobytes(order='C')

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'model.bin').write_bytes(bytes(blob))
    manifest = {
        'source': f'{SOURCE_REPO} {SOURCE_COMMIT} {MODEL_H5}',
        'source_sha256': digest,
        'bin_sha256': hashlib.sha256(bytes(blob)).hexdigest(),
        'tensors': tensors,
    }
    (OUT / 'model.json').write_text(json.dumps(manifest, indent=1) + '\n')
    print(f'{len(blob) // 4} floats -> {OUT / "model.bin"}')


if __name__ == '__main__':
    main()
