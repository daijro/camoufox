/**
 * The random half of fpgen. Python draws with random.random() and this port
 * with Math.random(), so single fingerprints cannot be compared; their
 * distributions can. For each scenario the Python golden script recorded the
 * marginal counts of key fields over 3000 full generate() calls
 * (fixtures/fpgen/stats.json); this draws its own sample and runs a two-sample
 * chi-square homogeneity test per field.
 *
 * alpha is 1e-4 per field (30 fields -> ~0.3% chance of a spurious failure per
 * run). A real divergence -- a mis-ordered table, a wrong renormalisation, a
 * condition that filters differently -- shows up as p ~ 0.
 */
import { describe, expect, it } from "vitest";
import { Generator } from "../src/fpgen/index.js";
import { fixture, fromFixture, MODEL } from "./fpgen-setup.js";

const N_TS = Number(process.env.FPGEN_STATS_N ?? 2000);
const ALPHA = 1e-4;

/** Mirror of fields() in scripts/golden/fpgen_golden.py. */
function fields(fp: Record<string, any>): Record<string, string> {
	const ua: string = fp.navigator.userAgent;
	const m = /\(([^)]*)\)/.exec(ua);
	const rv = /rv:(\d+)/.exec(ua);
	return {
		os: fp.os,
		uaPlatform: m ? m[1].split("; rv:")[0] : "",
		firefoxMajor: rv ? rv[1] : "",
		screen: `${fp.screen.width}x${fp.screen.height}`,
		hardwareConcurrency: String(fp.navigator.hardwareConcurrency),
		gpuVendor: fp.gpu.vendor,
	};
}

/* Regularised upper incomplete gamma Q(a, x) (Numerical Recipes gammq). */
function lnGamma(x: number): number {
	const c = [
		76.18009172947146, -86.50532032941678, 24.01409824083091,
		-1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5,
	];
	let y = x;
	const tmp = x + 5.5 - (x + 0.5) * Math.log(x + 5.5);
	let ser = 1.000000000190015;
	for (const cj of c) ser += cj / ++y;
	return -tmp + Math.log((Math.sqrt(2 * Math.PI) * ser) / x);
}

function gammaQ(a: number, x: number): number {
	if (x <= 0) return 1;
	const gln = lnGamma(a);
	if (x < a + 1) {
		let ap = a;
		let sum = 1 / a;
		let del = sum;
		for (let n = 0; n < 1000; n++) {
			del *= x / ++ap;
			sum += del;
			if (Math.abs(del) < Math.abs(sum) * 1e-15) break;
		}
		return 1 - sum * Math.exp(-x + a * Math.log(x) - gln);
	}
	let b = x + 1 - a;
	let c = 1 / 1e-300;
	let d = 1 / b;
	let h = d;
	for (let i = 1; i < 1000; i++) {
		const an = -i * (i - a);
		b += 2;
		d = an * d + b;
		if (Math.abs(d) < 1e-300) d = 1e-300;
		c = b + an / c;
		if (Math.abs(c) < 1e-300) c = 1e-300;
		d = 1 / d;
		const del = d * c;
		h *= del;
		if (Math.abs(del - 1) < 1e-15) break;
	}
	return Math.exp(-x + a * Math.log(x) - gln) * h;
}

interface Comparison {
	p: number;
	df: number;
	tvd: number;
	/** Categories with >= 1% share in one sample and absent from the other. */
	missing: string[];
}

/**
 * Two-sample chi-square homogeneity test. Categories too thin for the
 * approximation (expected < 5 in either sample) are pooled into one.
 */
function compare(
	py: Record<string, number>,
	ts: Record<string, number>,
): Comparison {
	const nPy = Object.values(py).reduce((a, b) => a + b, 0);
	const nTs = Object.values(ts).reduce((a, b) => a + b, 0);
	const total = nPy + nTs;
	const cats = [...new Set([...Object.keys(py), ...Object.keys(ts)])];

	let tvd = 0;
	const missing: string[] = [];
	for (const k of cats) {
		const a = (py[k] ?? 0) / nPy;
		const b = (ts[k] ?? 0) / nTs;
		tvd += Math.abs(a - b) / 2;
		if ((a >= 0.01 && !ts[k]) || (b >= 0.01 && !py[k])) missing.push(k);
	}

	const rows: [number, number][] = [];
	const pooled: [number, number] = [0, 0];
	for (const k of cats) {
		const a = py[k] ?? 0;
		const b = ts[k] ?? 0;
		const col = a + b;
		if ((col * nPy) / total < 5 || (col * nTs) / total < 5) {
			pooled[0] += a;
			pooled[1] += b;
		} else {
			rows.push([a, b]);
		}
	}
	if (pooled[0] + pooled[1] > 0) rows.push(pooled);
	if (rows.length < 2) return { p: 1, df: 0, tvd, missing };

	let stat = 0;
	for (const [a, b] of rows) {
		const col = a + b;
		const ea = (col * nPy) / total;
		const eb = (col * nTs) / total;
		stat += (a - ea) ** 2 / ea + (b - eb) ** 2 / eb;
	}
	const df = rows.length - 1;
	return { p: gammaQ(df / 2, stat / 2), df, tvd, missing };
}

describe("chi-square helper", () => {
	it("gives textbook p-values", () => {
		// chi2(df=1) = 3.841 -> p = 0.05; chi2(df=10) = 18.307 -> p = 0.05
		expect(gammaQ(0.5, 3.841 / 2)).toBeCloseTo(0.05, 3);
		expect(gammaQ(5, 18.307 / 2)).toBeCloseTo(0.05, 3);
	});

	it("rejects clearly different samples and accepts equal ones", () => {
		expect(compare({ a: 500, b: 500 }, { a: 800, b: 200 }).p).toBeLessThan(
			1e-10,
		);
		expect(compare({ a: 500, b: 500 }, { a: 500, b: 500 }).p).toBeCloseTo(1);
	});
});

const STATS = fixture("stats.json");

describe.skipIf(!MODEL.ok)(
	`fpgen draws match Python's distribution (${N_TS} TS vs ${STATS.n} Python per scenario)`,
	() => {
		const report: string[] = [];
		const tsCounts: Record<string, Record<string, Record<string, number>>> = {};

		for (const scenario of STATS.scenarios) {
			it(scenario.name, () => {
				const conditions = fromFixture(scenario.conditions);
				const gen = new Generator();
				const counts: Record<string, Record<string, number>> = {};
				for (let i = 0; i < N_TS; i++) {
					for (const [k, v] of Object.entries(
						fields(gen.generate(conditions)),
					)) {
						counts[k] ??= {};
						counts[k][v] = (counts[k][v] ?? 0) + 1;
					}
				}
				tsCounts[scenario.name] = counts;
				for (const [field, py] of Object.entries(
					scenario.counts as Record<string, Record<string, number>>,
				)) {
					const r = compare(py, counts[field] ?? {});
					report.push(
						`${scenario.name.padEnd(29)} ${field.padEnd(20)} p=${r.p.toExponential(2)} df=${String(r.df).padStart(2)} TVD=${r.tvd.toFixed(3)}`,
					);
					expect(r.missing, `${field}: categories missing`).toEqual([]);
					expect(r.p, `${field}: chi-square p-value`).toBeGreaterThan(ALPHA);
				}
			}, 180_000);
		}

		it("report, and a negative control: the test can tell scenarios apart", () => {
			console.log(`fpgen marginals, TS vs Python:\n${report.join("\n")}`);
			expect(report.length).toBe(STATS.scenarios.length * 6);
			// TS Windows draws against Python's unconstrained-OS draws: the same
			// test must reject these, or it could not catch a real divergence.
			const pyAny = STATS.scenarios.find((s: any) => s.name === "firefox_any");
			const ctl = compare(
				pyAny.counts.gpuVendor,
				tsCounts.firefox_windows.gpuVendor,
			);
			console.log(
				`negative control (gpuVendor, any vs windows): p=${ctl.p.toExponential(2)}`,
			);
			expect(ctl.p).toBeLessThan(1e-10);
		});
	},
);
