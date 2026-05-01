import hashlib
import random
from typing import Union

FingerprintSeed = Union[str, int, bytes]

_SEED_VERSION = b'camoufox:fingerprint-seed:v1'
_UINT32_MAX = 4_294_967_295


def _seed_bytes(seed: FingerprintSeed) -> bytes:
    if isinstance(seed, bool):
        raise TypeError('fingerprint seed must be str, int, or bytes')
    if isinstance(seed, bytes):
        return b'bytes:' + seed
    if isinstance(seed, int):
        return b'int:' + str(seed).encode('ascii')
    if isinstance(seed, str):
        return b'str:' + seed.encode('utf-8')
    raise TypeError('fingerprint seed must be str, int, or bytes')


def _pack_component(value: bytes) -> bytes:
    return len(value).to_bytes(8, 'big') + value


def derive_seed(seed: FingerprintSeed, namespace: str, bits: int = 64) -> int:
    """
    Derive a deterministic integer seed for a specific fingerprint namespace.

    The input is versioned and length-prefixed so different namespaces and seed
    types do not collide when their raw byte representation overlaps.
    """
    if not isinstance(namespace, str):
        raise TypeError('namespace must be a string')
    if not namespace:
        raise ValueError('namespace is required')
    if isinstance(bits, bool) or not isinstance(bits, int):
        raise TypeError('bits must be an integer')
    if bits < 1 or bits > 256:
        raise ValueError('bits must be between 1 and 256')

    material = b''.join((
        _pack_component(_SEED_VERSION),
        _pack_component(namespace.encode('utf-8')),
        _pack_component(_seed_bytes(seed)),
    ))
    value = int.from_bytes(hashlib.sha256(material).digest(), 'big')
    return value >> (256 - bits)


def deterministic_rng(seed: FingerprintSeed, namespace: str) -> random.Random:
    """
    Return a local random generator derived from a fingerprint seed namespace.
    """
    return random.Random(derive_seed(seed, namespace))


def derive_uint32_seed(seed: FingerprintSeed, namespace: str) -> int:
    """
    Derive a non-zero uint32 seed for Camoufox fingerprint noise settings.
    """
    return derive_seed(seed, namespace) % _UINT32_MAX + 1
