"""random.Random sequences for tests/pyrandom.test.ts (stdlib only).

Imported by identity_golden.py, and runnable on its own under any CPython to
check that the recorded sequences do not depend on the Python version:

    python3.10 typescript/scripts/golden/pyrandom_cases.py > /tmp/310.json
    python3.12 typescript/scripts/golden/pyrandom_cases.py > /tmp/312.json
    .venv/bin/python typescript/scripts/golden/pyrandom_cases.py > /tmp/314.json
"""

import json
import sys
from random import Random

SEEDS = [0, 1, 2, 7, 42, 99, 12345, 2**31 - 1, 2**32 - 1, 2**32, 2**32 + 1, 2**53 + 3,
         2**64 - 1, 2**64 + 5, 123456789012345678901234567890, -7, -(2**40)]
STR_SEEDS = ['', 'hello', 'camoufox', 'héllo wörld 😀']


def seed_json(seed):
    return {'int': str(seed)} if isinstance(seed, int) else {'str': seed}


def cases():
    out = []
    for seed in SEEDS + STR_SEEDS:
        r = Random(seed)
        case = {'seed': seed_json(seed)}
        case['random'] = [r.random() for _ in range(8)]
        case['getrandbits'] = [[k, str(r.getrandbits(k))] for k in (1, 2, 5, 8, 16, 31, 32, 33, 40, 53, 64, 65, 100, 0)]
        case['randbelow'] = [[n, r._randbelow(n)] for n in (1, 2, 3, 10, 100, 1000, 2**31, 2**32 - 1, 2**32 + 7, 10**15)]
        case['randrange'] = [
            [[10], r.randrange(10)],
            [[5, 15], r.randrange(5, 15)],
            [[-20, -3], r.randrange(-20, -3)],
            [[0, 100, 7], r.randrange(0, 100, 7)],
            [[100, 0, -3], r.randrange(100, 0, -3)],
        ]
        case['randint'] = [[a, b, r.randint(a, b)] for a, b in ((1, 6), (0, 0), (-5, 5), (1, 4294967295), (0, 2**40))]
        pop = list('abcdefghijklmnopqrstuvwxyz')
        case['choice'] = [r.choice(pop) for _ in range(5)]
        case['choices'] = {
            'plain': r.choices(pop, k=6),
            'weights': r.choices(pop[:5], weights=[0.1, 0.5, 2.0, 1.25, 0.15], k=6),
            'cum_weights': r.choices(pop[:4], cum_weights=[1, 3, 6, 10], k=6),
        }
        shuffled = list(range(20))
        r.shuffle(shuffled)
        case['shuffle'] = shuffled
        # sample: the pool branch (n <= setsize) and the set branch (n > setsize)
        case['sample'] = [
            [n, k, r.sample(range(n), k)]
            for n, k in ((5, 5), (10, 3), (21, 6), (22, 6), (30, 5), (40, 10), (100, 4), (100, 6),
                         (500, 30), (1000, 7), (60, 50), (1, 0), (300, 300))
        ]
        case['uniform'] = [r.uniform(-3.5, 10.25) for _ in range(3)]
        case['after'] = r.random()
        out.append(case)
    return out


if __name__ == '__main__':
    json.dump({'python': sys.version.split()[0], 'cases': cases()}, sys.stdout, sort_keys=True)
