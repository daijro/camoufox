import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, NoReturn, Optional, Tuple, Union

import base64
import orjson
from playwright._impl._driver import compute_driver_executable

from camoufox.pkgman import LOCAL_DATA
from camoufox.gpudisplay import GpuDisplay, prove_gpu
from camoufox.humanize import custom_engines
from camoufox.utils import launch_options, start_virtual_display
from camoufox.virtdisplay import VirtualDisplay

LAUNCH_SCRIPT: Path = LOCAL_DATA / "launchServer.js"


def camel_case(snake_str: str) -> str:
    """
    Convert a string to camelCase
    """
    if len(snake_str) < 2:
        return snake_str
    camel_case_str = ''.join(x.capitalize() for x in snake_str.lower().split('_'))
    return ("_" if snake_str[0] == "_" else "") + camel_case_str[0].lower() + camel_case_str[1:]


def to_camel_case_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a dictionary to camelCase
    """
    return {camel_case(key): value for key, value in data.items()}


def get_nodejs() -> str:
    """
    Get the bundled Node.js executable
    """
    # Note: Older versions of Playwright return a string rather than a tuple.
    _nodejs: Union[str, Tuple[str, ...]] = compute_driver_executable()[0]
    if isinstance(_nodejs, tuple):
        return _nodejs[0]
    return _nodejs


def launch_server(**kwargs) -> NoReturn:
    """
    Launch a Playwright server. Takes the same arguments as `Camoufox()`.
    Prints the websocket endpoint to the console.

    Note: persistent contexts are not servable. Playwright's `launchServer`
    routes through `BrowserType.launch()`, and its `PlaywrightServer` only
    accepts a `preLaunchedBrowser` -- there is no way to expose a persistent
    `BrowserContext` over a websocket endpoint. Reject those options up front
    rather than accepting them and silently launching a throwaway profile.
    """
    for unsupported in ('persistent_context', 'user_data_dir'):
        if kwargs.get(unsupported):
            raise ValueError(
                f"launch_server() does not support {unsupported!r}: Playwright cannot "
                "serve a persistent context over a websocket endpoint. Use "
                f"Camoufox(persistent_context=True, ...) in-process instead."
            )
        kwargs.pop(unsupported, None)

    if custom_engines(kwargs.get('humanize')):
        raise ValueError(
            "launch_server() cannot run custom() humanize engines: they run in the process that drives "
            "the page. Serve with raw() on those channels, and on the client call "
            "camoufox.humanize.attach_custom(browser, humanize) on the connected browser."
        )

    virtual_display, kwargs['headless'] = start_virtual_display(
        kwargs.get('headless'), kwargs.get('debug'), kwargs
    )
    try:
        _serve(launch_options(**kwargs), virtual_display)
    finally:
        if virtual_display:
            virtual_display.kill()


def _prove_served_gpu(process: subprocess.Popen, display: GpuDisplay) -> None:
    """Pass the server's output through, and once it prints its endpoint, check
    that its browser renders on the GPU."""
    from playwright.sync_api import sync_playwright

    def prove(endpoint: str) -> None:
        with sync_playwright() as playwright:
            browser = playwright.firefox.connect(endpoint)
            try:
                prove_gpu(browser, display)
            finally:
                browser.close()

    assert process.stdout is not None
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        endpoint = re.search(r'ws://\S+', line)
        if endpoint:
            # The sync API refuses to start inside a running asyncio loop.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(prove, endpoint.group(0)).result()
            break
    threading.Thread(target=shutil.copyfileobj, args=(process.stdout, sys.stdout), daemon=True).start()


def _serve(config: Dict[str, Any], virtual_display: Optional[VirtualDisplay] = None) -> NoReturn:
    """Run launchServer.js with `config` until the Node process exits."""
    nodejs = get_nodejs()
    gpu_display = virtual_display if isinstance(virtual_display, GpuDisplay) else None

    data = orjson.dumps(to_camel_case_dict(config))

    # The Playwright driver's package directory, which bundles playwright-core.
    driver_package = Path(nodejs).parent / "package"

    process = subprocess.Popen(  # nosec
        [
            nodejs,
            str(LAUNCH_SCRIPT),
            str(driver_package),
        ],
        cwd=driver_package,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE if gpu_display else None,
        text=True,
    )
    # Send one newline-delimited configuration frame, then keep the pipe open.
    # The Node process treats EOF as a shutdown request and can close Playwright
    # cleanly before exiting, which removes its temporary browser profile.
    assert process.stdin is not None
    stdin = process.stdin
    encoded_config = base64.b64encode(data).decode() + '\n'

    def close_stdin() -> None:
        if stdin.closed:
            return
        try:
            stdin.close()
        except OSError:
            pass

    def shutdown_process() -> None:
        """Ask Node to close BrowserServer, then reap it with bounded fallbacks."""
        close_stdin()
        if process.poll() is not None:
            process.wait()
            return
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    try:
        stdin.write(encoded_config)
        stdin.flush()
        if gpu_display:
            _prove_served_gpu(process, gpu_display)
        process.wait()
    except OSError as error:
        # If Node failed before reading the frame, preserve its exit status
        # instead of masking the original failure with a pipe exception.
        shutdown_process()
        raise RuntimeError(
            f"Server process terminated unexpectedly with exit code {process.returncode}"
        ) from error
    except BaseException:
        shutdown_process()
        raise
    finally:
        close_stdin()

    # Add an explicit exception to satisfy the NoReturn type hint.
    raise RuntimeError(
        f"Server process terminated unexpectedly with exit code {process.returncode}"
    )
