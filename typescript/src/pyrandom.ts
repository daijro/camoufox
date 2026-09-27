/**
 * A bit-exact port of CPython's `random.Random` (MT19937).
 *
 * The Python launcher seeds every per-identity draw (fonts, voices, media
 * devices) with `random.Random(seed)`, so the same identity must draw the same
 * values here. Seeding follows `random_seed()` in Modules/_randommodule.c
 * (init_by_array over the 32-bit words of abs(seed)); the methods follow
 * Lib/random.py. Every method below returns the same values on CPython 3.10
 * through 3.14 (checked by the golden fixtures).
 */
import { createHash, randomBytes } from "node:crypto";

const N = 624;
const M = 397;
const MATRIX_A = 0x9908b0df;
const UPPER_MASK = 0x80000000;
const LOWER_MASK = 0x7fffffff;

export type PySeed = number | bigint | string | null | undefined;

function seedToKey(seed: number | bigint): Uint32Array {
	let n = typeof seed === "bigint" ? seed : BigInt(seed);
	if (n < 0n) n = -n;
	const words: number[] = [];
	if (n === 0n) words.push(0);
	while (n > 0n) {
		words.push(Number(n & 0xffffffffn));
		n >>= 32n;
	}
	return Uint32Array.from(words);
}

export class PyRandom {
	private mt = new Uint32Array(N);
	private mti = N + 1;

	constructor(seed?: PySeed) {
		this.seed(seed);
	}

	/**
	 * random.seed(a): an int (number/bigint), a str (version 2: the str's
	 * UTF-8 bytes followed by their SHA-512), or None for OS entropy.
	 */
	seed(a?: PySeed): void {
		if (a === null || a === undefined) {
			const bytes = randomBytes(N * 4);
			const key = new Uint32Array(N);
			for (let i = 0; i < N; i++) key[i] = bytes.readUInt32LE(i * 4);
			this.initByArray(key);
			return;
		}
		if (typeof a === "string") {
			const utf8 = Buffer.from(a, "utf-8");
			const digest = createHash("sha512").update(utf8).digest();
			const all = Buffer.concat([utf8, digest]);
			a = all.length ? BigInt(`0x${all.toString("hex")}`) : 0n;
		}
		if (typeof a === "number" && !Number.isInteger(a)) {
			throw new TypeError("PyRandom only seeds from integers and strings");
		}
		this.initByArray(seedToKey(a));
	}

	private initGenrand(s: number): void {
		const mt = this.mt;
		mt[0] = s >>> 0;
		for (let i = 1; i < N; i++) {
			const prev = mt[i - 1] ^ (mt[i - 1] >>> 30);
			mt[i] = (Math.imul(1812433253, prev) + i) >>> 0;
		}
		this.mti = N;
	}

	private initByArray(key: Uint32Array): void {
		const mt = this.mt;
		this.initGenrand(19650218);
		let i = 1;
		let j = 0;
		const keyLength = key.length;
		for (let k = Math.max(N, keyLength); k; k--) {
			const prev = mt[i - 1] ^ (mt[i - 1] >>> 30);
			mt[i] = ((mt[i] ^ Math.imul(prev, 1664525)) + key[j] + j) >>> 0;
			i++;
			j++;
			if (i >= N) {
				mt[0] = mt[N - 1];
				i = 1;
			}
			if (j >= keyLength) j = 0;
		}
		for (let k = N - 1; k; k--) {
			const prev = mt[i - 1] ^ (mt[i - 1] >>> 30);
			mt[i] = ((mt[i] ^ Math.imul(prev, 1566083941)) - i) >>> 0;
			i++;
			if (i >= N) {
				mt[0] = mt[N - 1];
				i = 1;
			}
		}
		mt[0] = 0x80000000;
		this.mti = N;
	}

	/** genrand_uint32 */
	genrandUint32(): number {
		const mt = this.mt;
		let y: number;
		if (this.mti >= N) {
			let kk = 0;
			for (; kk < N - M; kk++) {
				y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
				mt[kk] = mt[kk + M] ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0);
			}
			for (; kk < N - 1; kk++) {
				y = (mt[kk] & UPPER_MASK) | (mt[kk + 1] & LOWER_MASK);
				mt[kk] = mt[kk + (M - N)] ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0);
			}
			y = (mt[N - 1] & UPPER_MASK) | (mt[0] & LOWER_MASK);
			mt[N - 1] = mt[M - 1] ^ (y >>> 1) ^ (y & 1 ? MATRIX_A : 0);
			this.mti = 0;
		}
		y = mt[this.mti++];
		y ^= y >>> 11;
		y ^= (y << 7) & 0x9d2c5680;
		y ^= (y << 15) & 0xefc60000;
		y ^= y >>> 18;
		return y >>> 0;
	}

	/** random.random(): a float in [0, 1) with 53 random bits. */
	random(): number {
		const a = this.genrandUint32() >>> 5;
		const b = this.genrandUint32() >>> 6;
		return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
	}

	/** random.getrandbits(k) as a bigint (any k >= 0). */
	getrandbitsBig(k: number): bigint {
		if (k < 0) throw new RangeError("number of bits must be non-negative");
		if (k === 0) return 0n;
		if (k <= 32) return BigInt(this.genrandUint32() >>> (32 - k));
		let result = 0n;
		let shift = 0n;
		for (let left = k; left > 0; left -= 32) {
			let r = this.genrandUint32();
			if (left < 32) r >>>= 32 - left;
			result |= BigInt(r) << shift;
			shift += 32n;
		}
		return result;
	}

	/** random.getrandbits(k) as a number (k <= 53). */
	getrandbits(k: number): number {
		if (k < 0) throw new RangeError("number of bits must be non-negative");
		if (k === 0) return 0;
		if (k <= 32) return this.genrandUint32() >>> (32 - k);
		if (k > 53)
			throw new RangeError("use getrandbitsBig for more than 53 bits");
		const lo = this.genrandUint32();
		const hi = this.genrandUint32() >>> (64 - k);
		return hi * 4294967296 + lo;
	}

	/** random._randbelow(n): an int in [0, n). */
	randbelow(n: number): number {
		if (n <= 0) return 0;
		const k = bitLength(n);
		let r = this.getrandbits(k);
		while (r >= n) r = this.getrandbits(k);
		return r;
	}

	/** random.randrange(start[, stop[, step]]) */
	randrange(start: number, stop?: number, step = 1): number {
		if (
			!Number.isInteger(start) ||
			(stop !== undefined && !Number.isInteger(stop)) ||
			!Number.isInteger(step)
		) {
			throw new TypeError("randrange() arguments must be integers");
		}
		if (stop === undefined) {
			if (step !== 1) throw new TypeError("Missing a non-None stop argument");
			if (start > 0) return this.randbelow(start);
			throw new RangeError("empty range for randrange()");
		}
		const width = stop - start;
		if (step === 1) {
			if (width > 0) return start + this.randbelow(width);
			throw new RangeError(`empty range in randrange(${start}, ${stop})`);
		}
		let n: number;
		if (step > 0) n = Math.floor((width + step - 1) / step);
		else if (step < 0) n = Math.floor((width + step + 1) / step);
		else throw new RangeError("zero step for randrange()");
		if (n <= 0)
			throw new RangeError(
				`empty range in randrange(${start}, ${stop}, ${step})`,
			);
		return start + step * this.randbelow(n);
	}

	/** random.randint(a, b): an int in [a, b]. */
	randint(a: number, b: number): number {
		return this.randrange(a, b + 1);
	}

	/** random.choice(seq) */
	choice<T>(seq: ArrayLike<T>): T {
		if (!seq.length)
			throw new RangeError("Cannot choose from an empty sequence");
		return seq[this.randbelow(seq.length)];
	}

	/** random.choices(population, weights=None, *, cum_weights=None, k=1) */
	choices<T>(
		population: ArrayLike<T>,
		{
			weights,
			cumWeights,
			k = 1,
		}: { weights?: number[]; cumWeights?: number[]; k?: number } = {},
	): T[] {
		const n = population.length;
		const out: T[] = [];
		if (!cumWeights) {
			if (!weights) {
				for (let i = 0; i < k; i++)
					out.push(population[Math.floor(this.random() * n)]);
				return out;
			}
			cumWeights = [];
			let acc = 0;
			weights.forEach((w, i) => {
				acc = i === 0 ? w : acc + w;
				(cumWeights as number[]).push(acc);
			});
		} else if (weights) {
			throw new TypeError("Cannot specify both weights and cumulative weights");
		}
		if (cumWeights.length !== n) {
			throw new RangeError(
				"The number of weights does not match the population",
			);
		}
		const total = cumWeights[n - 1] + 0.0;
		if (total <= 0.0)
			throw new RangeError("Total of weights must be greater than zero");
		if (!Number.isFinite(total))
			throw new RangeError("Total of weights must be finite");
		const hi = n - 1;
		for (let i = 0; i < k; i++) {
			out.push(
				population[bisectRight(cumWeights, this.random() * total, 0, hi)],
			);
		}
		return out;
	}

	/** random.shuffle(x), in place. */
	shuffle<T>(x: T[]): void {
		for (let i = x.length - 1; i > 0; i--) {
			const j = this.randbelow(i + 1);
			[x[i], x[j]] = [x[j], x[i]];
		}
	}

	/** random.sample(population, k), including its pool-vs-set branch. */
	sample<T>(population: ArrayLike<T>, k: number): T[] {
		const n = population.length;
		if (!(k >= 0 && k <= n)) {
			throw new RangeError("Sample larger than population or is negative");
		}
		const result: T[] = new Array(k);
		let setsize = 21;
		if (k > 5) setsize += 4 ** Math.ceil(Math.log(k * 3) / Math.log(4));
		if (n <= setsize) {
			const pool = Array.from(population);
			for (let i = 0; i < k; i++) {
				const j = this.randbelow(n - i);
				result[i] = pool[j];
				pool[j] = pool[n - i - 1];
			}
		} else {
			const selected = new Set<number>();
			for (let i = 0; i < k; i++) {
				let j = this.randbelow(n);
				while (selected.has(j)) j = this.randbelow(n);
				selected.add(j);
				result[i] = population[j];
			}
		}
		return result;
	}

	/** random.uniform(a, b) */
	uniform(a: number, b: number): number {
		return a + (b - a) * this.random();
	}
}

function bitLength(n: number): number {
	return n === 0 ? 0 : Math.trunc(Math.abs(n)).toString(2).length;
}

function bisectRight(a: number[], x: number, lo: number, hi: number): number {
	while (lo < hi) {
		const mid = (lo + hi) >>> 1;
		if (x < a[mid]) hi = mid;
		else lo = mid + 1;
	}
	return lo;
}

/**
 * The module-level generator: Python's `random.random()`, `random.choice()`
 * and friends all draw from one shared `Random` instance, and so do the TS
 * functions that mirror an unseeded Python draw. Seed it (`pyRandom.seed(n)`)
 * to reproduce a Python run that called `random.seed(n)`.
 */
export const pyRandom = new PyRandom();
