import sqlite3
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import orjson


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
    # Map OS to probability column
    os_map = {'win': 'windows', 'mac': 'macos', 'lin': 'linux'}
    if os not in os_map:
        raise ValueError(f'Invalid OS: {os}. Must be one of: {", ".join(os_map)}')
    os = os_map[os]

    # Get database path relative to this file
    db_path = Path(__file__).parent / 'webgl_data.db'

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if vendor and renderer:
        # Get specific vendor/renderer pair and verify it exists for this OS
        cursor.execute(
            f'SELECT vendor, renderer, data, {os} FROM webgl_fingerprints WHERE vendor = ? AND renderer = ?',
            (vendor, renderer),
        )
        result = cursor.fetchone()

        if not result:
            raise ValueError(f'No WebGL data found for vendor "{vendor}" and renderer "{renderer}"')

        if result[3] <= 0:  # Check OS-specific probability
            # Get a list of possible (vendor, renderer) pairs for this OS
            cursor.execute(
                f'SELECT DISTINCT vendor, renderer FROM webgl_fingerprints WHERE {os} > 0'
            )
            possible_pairs = cursor.fetchall()
            raise ValueError(
                f'Vendor "{vendor}" and renderer "{renderer}" combination not valid for {os.title()}.\n'
                f'Possible pairs: {", ".join(str(pair) for pair in possible_pairs)}'
            )

        conn.close()
        return orjson.loads(result[2])

    # Get all vendor/renderer pairs and their probabilities for this OS
    cursor.execute(f'SELECT vendor, renderer, data, {os} FROM webgl_fingerprints WHERE {os} > 0')
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
