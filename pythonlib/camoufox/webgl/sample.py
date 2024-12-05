import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import orjson

from camoufox.pkgman import OS_ARCH_MATRIX

# Get database path relative to this file
DB_PATH = Path(__file__).parent / 'webgl_data.db'


def sample_webgl(
    os: str, vendor: Optional[str] = None, renderer: Optional[str] = None
) -> Dict[str, str]:
    """
    Sample a random WebGL vendor/renderer combination and its data based on OS probabilities.
    Optionally use a specific vendor/renderer pair.

    Args:
        os: Operating system ('win', 'mac', or 'lin')
        vendor: Optional specific vendor to use
        renderer: Optional specific renderer to use (requires vendor to be set)

    Returns:
        Dict containing WebGL data including vendor, renderer and additional parameters

    Raises:
        ValueError: If invalid OS provided or no data found for OS/vendor/renderer
    """
    # Check that the OS is valid (avoid SQL injection)
    if os not in OS_ARCH_MATRIX:
        raise ValueError(f'Invalid OS: {os}. Must be one of: win, mac, lin')

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if vendor and renderer:
        # Get specific vendor/renderer pair and verify it exists for this OS
        cursor.execute(
            f'SELECT vendor, renderer, data, {os} FROM webgl_fingerprints '  # nosec
            'WHERE vendor = ? AND renderer = ?',
            (vendor, renderer),
        )
        result = cursor.fetchone()

        if not result:
            raise ValueError(f'No WebGL data found for vendor "{vendor}" and renderer "{renderer}"')

        if result[3] <= 0:  # Check OS-specific probability
            # Get a list of possible (vendor, renderer) pairs for this OS
            cursor.execute(
                f'SELECT DISTINCT vendor, renderer FROM webgl_fingerprints WHERE {os} > 0'  # nosec
            )
            possible_pairs = cursor.fetchall()
            raise ValueError(
                f'Vendor "{vendor}" and renderer "{renderer}" combination not valid for {os.title()}.\n'
                f'Possible pairs: {", ".join(str(pair) for pair in possible_pairs)}'
            )

        conn.close()
        return orjson.loads(result[2])

    # Get all vendor/renderer pairs and their probabilities for this OS
    cursor.execute(
        f'SELECT vendor, renderer, data, {os} FROM webgl_fingerprints WHERE {os} > 0'  # nosec
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        raise ValueError(f'No WebGL data found for OS: {os}')

    # Split into separate arrays
    _, _, data_strs, probs = map(list, zip(*results))

    # Convert probabilities to numpy array and normalize
    probs_array = np.array(probs, dtype=np.float64)
    probs_array = probs_array / probs_array.sum()

    # Sample based on probabilities
    idx = np.random.choice(len(probs_array), p=probs_array)

    # Parse the JSON data string
    return orjson.loads(data_strs[idx])


def get_possible_pairs() -> Dict[str, List[Tuple[str, str]]]:
    """
    Get all possible (vendor, renderer) pairs for all OS, where the probability is greater than 0.
    """
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all vendor/renderer pairs for each OS where probability > 0
    result: Dict[str, List[Tuple[str, str]]] = {}
    for os_type in OS_ARCH_MATRIX:
        cursor.execute(
            'SELECT DISTINCT vendor, renderer FROM webgl_fingerprints '
            f'WHERE {os_type} > 0 ORDER BY {os_type} DESC',  # nosec
        )
        result[os_type] = cursor.fetchall()

    conn.close()
    return result
