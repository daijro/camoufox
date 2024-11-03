import asyncio
import os
import socket
import threading
import time
from enum import Enum
from typing import List

import orjson

from .exceptions import InvalidAddonPath, InvalidDebugPort, MissingDebugPort


class DefaultAddons(Enum):
    """
    Default addons to be downloaded
    """

    UBO = "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi"
    # Disable by default. Not always necessary, and increases the memory footprint of Camoufox.
    # BPC = "https://gitflic.ru/project/magnolia1234/bpc_uploads/blob/raw?file=bypass_paywalls_clean-latest.xpi"


def get_debug_port(args: List[str]) -> int:
    """
    Gets the debug port from the args, or creates a new one if not provided
    """
    for i, arg in enumerate(args):
        # Search for debugger server port
        if arg == "-start-debugger-server":
            # If arg is found but no port is provided, raise an error
            if i + 1 >= len(args):
                raise MissingDebugPort(f"No debug port provided: {args}")
            debug_port = args[i + 1]
            # Try to parse the debug port as an integer
            try:
                return int(debug_port)
            except ValueError as e:
                raise InvalidDebugPort(
                    f"Error parsing debug port. Must be an integer: {debug_port}"
                ) from e

    # Create new debugger server port
    debug_port_int = get_open_port()
    # Add -start-debugger-server {debug_port} to args
    args.extend(["-start-debugger-server", str(debug_port_int)])

    return debug_port_int


def confirm_paths(paths: List[str]) -> None:
    """
    Confirms that the addon paths are valid
    """
    for path in paths:
        if not os.path.isdir(path):
            raise InvalidAddonPath(path)
        if not os.path.exists(os.path.join(path, 'manifest.json')):
            raise InvalidAddonPath(
                'manifest.json is missing. Addon path must be a path to an extracted addon.'
            )


def get_open_port() -> int:
    """
    Gets an open port
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]


def threaded_try_load_addons(debug_port_int: int, addons_list: List[str]) -> None:
    """
    Tries to load addons (in a separate thread)
    """
    thread = threading.Thread(
        target=try_load_addons, args=(debug_port_int, addons_list), daemon=True
    )
    thread.start()


def try_load_addons(debug_port_int: int, addons_list: List[str]) -> None:
    """
    Tries to load addons
    """
    # Wait for the server to be open
    while True:
        try:
            with socket.create_connection(("localhost", debug_port_int)):
                break
        except ConnectionRefusedError:
            time.sleep(0.05)

    # Load addons
    asyncio.run(load_all_addons(debug_port_int, addons_list))


async def load_all_addons(debug_port_int: int, addons_list: List[str]) -> None:
    """
    Loads all addons
    """
    addon_loaders = [LoadFirefoxAddon(debug_port_int, addon) for addon in addons_list]
    await asyncio.gather(*[addon_loader.load() for addon_loader in addon_loaders])


class LoadFirefoxAddon:
    '''
    Firefox addon loader
    https://github.com/daijro/hrequests/blob/main/hrequests/extensions.py#L95
    '''

    def __init__(self, port, addon_path):
        self.port: int = port
        self.addon_path: str = addon_path
        self.success: bool = False
        self.buffers: list = []
        self.remaining_bytes: int = 0

    async def load(self):
        reader, writer = await asyncio.open_connection('localhost', self.port)
        writer.write(self._format_message({"to": "root", "type": "getRoot"}))
        await writer.drain()

        while True:
            data = await reader.read(100)  # Adjust buffer size as needed
            if not data:
                break
            await self._process_data(writer, data)

        writer.close()
        await writer.wait_closed()
        return self.success

    async def _process_data(self, writer, data):
        while data:
            if self.remaining_bytes == 0:
                index = data.find(b':')
                if index == -1:
                    self.buffers.append(data)
                    return

                total_data = b''.join(self.buffers) + data
                size, _, remainder = total_data.partition(b':')

                try:
                    self.remaining_bytes = int(size)
                except ValueError as e:
                    raise ValueError("Invalid state") from e

                data = remainder

            if len(data) < self.remaining_bytes:
                self.remaining_bytes -= len(data)
                self.buffers.append(data)
                return
            else:
                self.buffers.append(data[: self.remaining_bytes])
                message = orjson.loads(b''.join(self.buffers))
                self.buffers.clear()

                await self._on_message(writer, message)

                data = data[self.remaining_bytes :]
                self.remaining_bytes = 0

    async def _on_message(self, writer, message):
        if "addonsActor" in message:
            writer.write(
                self._format_message(
                    {
                        "to": message["addonsActor"],
                        "type": "installTemporaryAddon",
                        "addonPath": self.addon_path,
                    }
                )
            )
            await writer.drain()

        if "addon" in message:
            self.success = True
            writer.write_eof()

        if "error" in message:
            writer.write_eof()

    def _format_message(self, data):
        raw = orjson.dumps(data)
        return f"{len(raw)}:".encode() + raw
