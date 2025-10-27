#!/usr/bin/env python3
"""
Test WebSocket port remapping functionality.

This script:
1. Starts netcat listeners on specified ports
2. Configures CAMOU_CONFIG with port remapping rules
3. Runs Firefox with test page
4. Cleans up listeners on exit

Usage: python3 browser-tests/test-websocket-port-remapping.py
"""

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List


@dataclass
class PortConfig:
    """Configuration for a test port."""
    port: int
    name: str
    remap: bool  # Whether this port should be remapped
    listen: bool  # Whether to start a listener on this port
    description: str  # Human-readable description of what this test scenario verifies
    remap_target: int = 0  # Target port for remapping (only used if remap=True)


# Test port configuration - each port tests a different scenario
TEST_PORTS = [
    PortConfig(
        port=8888,
        name="control",
        remap=False,
        listen=True,
        description="Control (not remapped, has listener) - should TIMEOUT connecting to real listener"
    ),
    PortConfig(
        port=8889,
        name="remapped-listening",
        remap=True,
        listen=True,
        remap_target=1080,
        description="Remapped port WITH listener (8889→1080) - should fail FAST despite listener"
    ),
    PortConfig(
        port=8890,
        name="remapped-closed",
        remap=True,
        listen=False,
        remap_target=1081,
        description="Remapped port WITHOUT listener (8890→1081) - should fail FAST to closed port"
    ),
    PortConfig(
        port=631,
        name="not-remapped-closed",
        remap=False,
        listen=False,
        description="Not remapped, no listener (CUPS printer port) - should fail FAST naturally"
    ),
    PortConfig(
        port=5901,
        name="not-remapped-vnc",
        remap=False,
        listen=False,
        description="Not remapped, no listener (VNC port) - should fail FAST naturally"
    ),
]


def start_listener(port: int) -> subprocess.Popen:
    """Start a netcat listener on the specified port."""
    print(f"Starting listener on port {port}...", file=sys.stderr)
    proc = subprocess.Popen(
        ["nc", "-l", "127.0.0.1", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return proc


def build_camou_config(ports: List[PortConfig]) -> str:
    """Build CAMOU_CONFIG JSON for port remapping."""
    # Build manual port mappings in "from:to" format
    # Each source port maps to a unique target port
    manual_mappings = [
        f"{p.port}:{p.remap_target}"
        for p in ports if p.remap
    ]

    config = {
        "websocket:remapping:manualPortMappings": manual_mappings
    }

    return json.dumps(config)


def find_project_root() -> str:
    """Find the project root directory (where Makefile is)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Script is in browser-tests/, so parent is project root
    project_root = os.path.dirname(script_dir)

    if not os.path.exists(os.path.join(project_root, "Makefile")):
        print(f"Error: Could not find Makefile in {project_root}", file=sys.stderr)
        sys.exit(1)

    return project_root


def parse_test_results(output: str) -> dict:
    """Extract JSON test results from Firefox output."""
    try:
        start_marker = "__TEST_RESULTS_JSON__"
        end_marker = "__END_TEST_RESULTS__"

        start_idx = output.find(start_marker)
        end_idx = output.find(end_marker)

        if start_idx == -1 or end_idx == -1:
            return None

        json_str = output[start_idx + len(start_marker):end_idx].strip()
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing test results: {e}", file=sys.stderr)
        return None


def validate_result(result: dict, config: PortConfig) -> tuple[bool, str]:
    """Validate a single test result against expected behavior.

    Returns: (passed, reason)
    """
    port = result['port']
    status = result['status']
    duration = result['duration']

    # Expected behavior:
    # 1. Control port with listener (not remapped) -> TIMEOUT (> 1000ms)
    # 2. Remapped ports -> FAST fail (< 500ms) regardless of listener
    # 3. Non-remapped closed ports -> FAST fail (< 100ms)

    if config.remap:
        # Remapped port should fail fast even if it has a listener
        if status == "CLOSED" and duration < 500:
            return True, f"✓ Remapped port failed fast ({duration:.0f}ms < 500ms)"
        else:
            return False, f"✗ Remapped port should fail fast, got {status} in {duration:.0f}ms"

    elif config.listen:
        # Control port with listener should timeout (connection attempt to real server)
        if status == "TIMEOUT" and duration > 1000:
            return True, f"✓ Control port timed out as expected ({duration:.0f}ms > 1000ms)"
        else:
            return False, f"✗ Control port should timeout, got {status} in {duration:.0f}ms"

    else:
        # Non-remapped closed port should fail very fast
        if status == "CLOSED" and duration < 100:
            return True, f"✓ Closed port failed fast ({duration:.0f}ms < 100ms)"
        else:
            return False, f"✗ Closed port should fail fast, got {status} in {duration:.0f}ms"


def print_formatted_results(test_data: dict, port_configs: List[PortConfig]) -> bool:
    """Print test results with scenario descriptions and pass/fail validation.

    Returns: True if all tests passed, False otherwise
    """
    if not test_data or 'results' not in test_data:
        print("ERROR: No test results found in output", file=sys.stderr)
        return False

    # Create port -> config mapping
    port_map = {p.port: p for p in port_configs}

    print("\n" + "=" * 80, file=sys.stderr)
    print("TEST RESULTS:", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    all_passed = True
    passed_count = 0
    failed_count = 0

    for result in test_data['results']:
        port = result['port']
        status = result['status']
        duration = result['duration']

        config = port_map.get(port)
        if config:
            # Validate result
            passed, reason = validate_result(result, config)
            if passed:
                passed_count += 1
            else:
                failed_count += 1
                all_passed = False

            print(f"{config.description}", file=sys.stderr)
            print(f"  → Port {port}: {status} ({duration:.2f}ms)", file=sys.stderr)
            print(f"  {reason}", file=sys.stderr)
        else:
            print(f"  → Port {port}: {status} ({duration:.2f}ms) [UNKNOWN PORT]", file=sys.stderr)
        print("", file=sys.stderr)

    print("=" * 80, file=sys.stderr)
    print(f"SUMMARY: {passed_count} passed, {failed_count} failed", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    if all_passed:
        print("✓ ALL TESTS PASSED - Port remapping defense is working correctly!", file=sys.stderr)
    else:
        print("✗ TESTS FAILED - Port remapping defense has issues", file=sys.stderr)

    print("", file=sys.stderr)
    return all_passed


def main():
    # Find and change to project root
    project_root = find_project_root()
    os.chdir(project_root)
    print(f"Project root: {project_root}", file=sys.stderr)
    print("", file=sys.stderr)

    listeners = []

    try:
        # Start listeners
        for port_config in TEST_PORTS:
            if port_config.listen:
                listener = start_listener(port_config.port)
                listeners.append((port_config.port, listener))
                time.sleep(0.1)  # Brief pause to ensure listener is ready

        # Build CAMOU_CONFIG
        camou_config = build_camou_config(TEST_PORTS)
        print(f"CAMOU_CONFIG={camou_config}", file=sys.stderr)
        print("", file=sys.stderr)

        # Prepare environment
        env = os.environ.copy()
        env["CAMOU_CONFIG"] = camou_config
        env["MOZ_LOG"] = "nsWebSocket:3"  # Enable WebSocket logging

        # Build test URL with port parameters (relative to project root)
        test_ports_param = ",".join(str(p.port) for p in TEST_PORTS)
        test_url = f"file://{project_root}/browser-tests/test-websocket-port-remapping.html?ports={test_ports_param}"

        # Run Firefox and capture output
        # Need --setpref to enable dump() function used in the test HTML
        # Quote the URL to protect special characters from shell interpretation
        args_value = f"--setpref browser.dom.window.dump.enabled=true --headless '{test_url}'"
        print(f"Running: make run args=\"{args_value}\"", file=sys.stderr)
        print("", file=sys.stderr)

        result = subprocess.run(
            ["make", "run", f"args={args_value}"],
            env=env,
            capture_output=True,
            text=True
        )

        # Print all Firefox output
        print(result.stdout)
        print(result.stderr, file=sys.stderr)

        # Parse and display formatted results
        test_data = parse_test_results(result.stdout + result.stderr)
        if test_data:
            all_passed = print_formatted_results(test_data, TEST_PORTS)
            # Exit with status 0 if all tests passed, 1 if any failed
            sys.exit(0 if all_passed else 1)
        else:
            print("WARNING: Could not parse structured test results", file=sys.stderr)
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nTest interrupted", file=sys.stderr)
        sys.exit(130)

    finally:
        # Cleanup listeners
        print("", file=sys.stderr)
        print("Cleaning up listeners...", file=sys.stderr)
        for port, listener in listeners:
            try:
                listener.terminate()
                listener.wait(timeout=2)
                print(f"  Stopped listener on port {port}", file=sys.stderr)
            except subprocess.TimeoutExpired:
                listener.kill()
                print(f"  Killed listener on port {port}", file=sys.stderr)
            except Exception as e:
                print(f"  Error stopping listener on port {port}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
