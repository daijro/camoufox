/**
 * PyRandom contract checks. The bit-exact sequences (every method, 21 seeds,
 * recorded under CPython 3.10-3.14 alike) live in identity-golden.test.ts.
 */
import { describe, expect, it } from "vitest";
import { PyRandom, pyRandom } from "../src/pyrandom.js";

describe("PyRandom", () => {
	it("matches CPython's first draws for well-known seeds", () => {
		// python3 -c "import random; r=random.Random(42); print(r.random())"
		expect(new PyRandom(42).random()).toBe(0.6394267984578837);
		expect(new PyRandom(0).random()).toBe(0.8444218515250481);
	});

	it("seeds from abs(n), like CPython", () => {
		expect(new PyRandom(-7).random()).toBe(new PyRandom(7).random());
		expect(new PyRandom(2n ** 70n).random()).not.toBe(new PyRandom(0).random());
	});

	it("reseeding restarts the stream", () => {
		const r = new PyRandom(5);
		const first = [r.random(), r.random()];
		r.seed(5);
		expect([r.random(), r.random()]).toEqual(first);
	});

	it("unseeded generators differ", () => {
		expect(new PyRandom().random()).not.toBe(new PyRandom().random());
	});

	it("raises where CPython raises", () => {
		const r = new PyRandom(1);
		expect(() => r.choice([])).toThrow();
		expect(() => r.sample([1, 2], 3)).toThrow(/larger than population/);
		expect(() => r.randrange(5, 5)).toThrow(/empty range/);
		expect(() => r.randrange(0, 10, 0)).toThrow(/zero step/);
		expect(() => r.choices([1, 2], { weights: [1], k: 1 })).toThrow();
		expect(() => new PyRandom(1.5)).toThrow();
	});

	it("keeps sample() results distinct in both branches", () => {
		const r = new PyRandom(3);
		for (const [n, k] of [
			[10, 10],
			[1000, 50],
		]) {
			const s = r.sample(
				Array.from({ length: n }, (_, i) => i),
				k,
			);
			expect(new Set(s).size).toBe(k);
		}
	});

	it("exposes a shared module-level generator", () => {
		pyRandom.seed(42);
		expect(pyRandom.random()).toBe(0.6394267984578837);
	});
});
