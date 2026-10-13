#!/usr/bin/env python3
"""Launch the Python camoufox with a fixed identity and run the shared page probe.

Used by tests/e2e.test.ts to compare the TypeScript launcher against Python on
the same binary and the same identity, and by ci/run_install.py to launch the
installed package (node_probe.mjs is its Node twin):

    echo '{"mode": "headless", "url": "...", "kwargs": {...}}' | \
        .venv/bin/python typescript/scripts/e2e/python_probe.py

Prints one JSON object: {"probe": <probe result>, "config": <CAMOU_CONFIG>}.
`mode` is "config-only" (launch_options() alone), "headless" (Camoufox(...) -> new_page),
"persistent" (Camoufox(persistent_context=True, user_data_dir=...)), "virtual"
(Camoufox(headless="virtual")), "context"
(Camoufox(...) -> NewContext(browser, preset=req["preset"]) -> new_page) or "interact"
("headless", then click #button and type req["text"] into #input; adds the page's
"events" and the input's "value").

stdout carries the JSON and nothing else: pythonlib prints to stdout (e.g.
"Skipping unknown patch" when the binary predates a config key), so everything
the launch prints is sent to stderr instead.
"""

import contextlib
import json
import sys
import tempfile
import warnings
from pathlib import Path

from camoufox.sync_api import Camoufox, NewContext
from camoufox.utils import launch_options

PROBE = (Path(__file__).resolve().parent.parent.parent / 'tests' / 'fixtures' / 'e2e' / 'probe.js').read_text()


def config_of(options):
    env = options['env']
    chunks = sorted((int(k.rsplit('_', 1)[1]), v) for k, v in env.items() if k.startswith('CAMOU_CONFIG_'))
    return json.loads(''.join(v for _, v in chunks))


def main():
    req = json.loads(sys.stdin.read())
    with contextlib.redirect_stdout(sys.stderr):
        out = run(req)
    json.dump(out, sys.stdout)


def run(req):
    kwargs = req['kwargs']
    warnings.simplefilter('ignore')
    config = config_of(launch_options(**kwargs))
    if req['mode'] == 'config-only':
        return {'config': config}
    if req['mode'] == 'context':
        with Camoufox(**kwargs) as browser:
            context = NewContext(browser, preset=req['preset'])
            page = context.new_page()
            page.goto(req['url'])
            return {'probe': page.evaluate(PROBE), 'config': config}
    with tempfile.TemporaryDirectory() as profile:
        extra = {'persistent_context': True, 'user_data_dir': profile} if req['mode'] == 'persistent' else {}
        if req['mode'] == 'virtual':
            extra = {'headless': 'virtual'}
            kwargs = {k: v for k, v in kwargs.items() if k != 'headless'}
        with Camoufox(**kwargs, **extra) as browser:
            page = browser.new_page()
            page.goto(req['url'])
            if req['mode'] == 'virtual':
                # As the TS side does: Firefox defers enumerateDevices() until
                # the document has focus, which a headful window on a bare Xvfb
                # only sometimes gets. Wait for it, as a user's window has it.
                for _ in range(50):
                    page.bring_to_front()
                    if page.evaluate('document.hasFocus()'):
                        break
                    page.wait_for_timeout(200)
                else:
                    raise RuntimeError('the headful page never got focus on Xvfb')
            probe = page.evaluate(PROBE)
            if req['mode'] == 'interact':
                return {'probe': probe, **interact(page, req['text'])}
    return {'probe': probe, 'config': config}


def interact(page, text):
    """Click ci/run_install.py's button, type into its input, and read back what the page logged."""
    page.locator('#button').click()
    page.locator('#input').press_sequentially(text)
    events = [json.loads(line) for line in page.locator('#events').text_content().splitlines()]
    return {'events': events, 'value': page.locator('#input').input_value()}


if __name__ == '__main__':
    main()
