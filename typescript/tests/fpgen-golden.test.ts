/**
 * The deterministic half of fpgen: everything that does not depend on the
 * random draw must be IDENTICAL to Python fpgen 1.3.0 on the same pinned model.
 * Fixtures: scripts/golden/fpgen_golden.py.
 *
 *  - the parsed network (nodes, parents, value ids, ancestor sets, and a digest
 *    of every probability table in document order, bit for bit);
 *  - the value store (offset table, base85 ids, and every referenced value);
 *  - condition handling: conditions -> evidence, including nested paths,
 *    predicates, alternatives, casefolding, and the errors it raises;
 *  - beam-search distributions (NETWORK.trace), float for float, including
 *    cases that prune the beam;
 *  - the public trace(), query() and draw-independent generate() outputs.
 */
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
	Generator,
	getModel,
	query,
	type TraceResult,
	trace,
} from "../src/fpgen/index.js";
import { base85ToInt } from "../src/fpgen/pyjson.js";
import { buildEvidence, type EvidenceMap } from "../src/fpgen/utils.js";
import { fixture, fromFixture, MODEL } from "./fpgen-setup.js";

const sha = (s: string) =>
	createHash("sha256").update(s, "utf-8").digest("hex");

function floatHex(x: number): string {
	const b = Buffer.alloc(8);
	b.writeDoubleBE(x);
	return b.toString("hex");
}

/** Same canonical form as cpt_canonical() in the golden script. */
function cptCanonical(o: unknown): string {
	if (o instanceof Map) {
		return `{${[...o].map(([k, v]) => `${JSON.stringify(k)}:${cptCanonical(v)}`).join(",")}}`;
	}
	return floatHex(o as number);
}

function evidenceFixture(evidence: EvidenceMap): [string, string[]][] {
	return [...evidence].map(([k, v]) => [
		k,
		[...v].sort((a, b) => base85ToInt(a) - base85ToInt(b)),
	]);
}

function plainTrace(res: unknown): unknown {
	if (Array.isArray(res)) {
		return res.map((r: TraceResult) => ({
			value: r.value,
			probability: r.probability,
		}));
	}
	return Object.fromEntries(
		Object.entries(res as object).map(([k, v]) => [k, plainTrace(v)]),
	);
}

/** Python prints a lambda's address; compare the rest of the message. */
const normFn = (m: string) => m.replace(/\(<function .*?>\)/g, "(<fn>)");

describe.skipIf(!MODEL.ok)("fpgen network structure == Python", () => {
	const golden = fixture("structure.json");

	it("is built from the pinned model", () => {
		expect(golden.pin).toBe(
			"6530b8322cdaa4ec042921c8d9a0369a0e6e0269ba636c01a7203e4a2f109936",
		);
	});

	it("has the same nodes, parents, value ids, ancestors and tables", () => {
		const { network } = getModel();
		expect(network.nodeNames).toEqual(golden.nodeNames);
		expect(network.nodesInSamplingOrder.length).toBe(golden.nodes.length);
		network.nodesInSamplingOrder.forEach((node, i) => {
			const g = golden.nodes[i];
			expect(node.name).toBe(g.name);
			expect(node.parentNames).toEqual(g.parentNames);
			expect(node.possibleValues).toEqual(g.possibleValues);
			expect([...network.getAllAncestors(node.name)].sort()).toEqual(
				g.ancestors,
			);
			// Order-sensitive digest: catches a table re-ordered by a JS object.
			expect(sha(cptCanonical(node.probabilities)), node.name).toBe(
				g.cptSha256,
			);
		});
	});

	it("looks nodes up case-insensitively", () => {
		const { network } = getModel();
		expect(network.nodesByName.get("NAVIGATOR.USERAGENT")?.name).toBe(
			"navigator.userAgent",
		);
	});

	it("reads the same value offset table", () => {
		const { valuePairs } = getModel();
		expect(valuePairs.length).toBe(golden.valuePairs.count);
		expect(sha(valuePairs.map(([o, n]) => `${o}:${n};`).join(""))).toBe(
			golden.valuePairs.sha256,
		);
	});

	it("decodes base85 value ids identically", () => {
		const { network } = getModel();
		const ids = [
			...new Set(network.nodesInSamplingOrder.flatMap((n) => n.possibleValues)),
		].sort((a, b) => base85ToInt(a) - base85ToInt(b));
		expect(ids.length).toBe(golden.base85.count);
		expect(sha(ids.map((i) => `${i}=${base85ToInt(i)};`).join(""))).toBe(
			golden.base85.sha256,
		);
		for (const [id, n] of Object.entries(golden.base85.samples)) {
			expect(base85ToInt(id)).toBe(n);
		}
	});
});

describe.skipIf(!MODEL.ok)("fpgen value store == Python", () => {
	const golden = fixture("values.json");

	it("returns the same text for sampled ids", () => {
		const model = getModel();
		const ids = golden.samples.map((s: any) => s.id);
		const texts = model.lookupValueList(ids);
		golden.samples.forEach((s: any, i: number) => {
			expect(Buffer.byteLength(texts[i]), s.id).toBe(s.length);
			expect(sha(texts[i]), s.id).toBe(s.sha256);
			if (s.text !== undefined) expect(texts[i]).toBe(s.text);
		});
		expect(model.lookupValue(ids[0])).toBe(texts[0]);
	});

	it("returns the same text for every referenced value", () => {
		const model = getModel();
		const ids = [
			...new Set(
				model.network.nodesInSamplingOrder.flatMap((n) => n.possibleValues),
			),
		].sort((a, b) => base85ToInt(a) - base85ToInt(b));
		expect(ids.length).toBe(golden.idCount);
		const h = createHash("sha256");
		for (let n = 0; n < ids.length; n += 500) {
			for (const t of model.lookupValueList(ids.slice(n, n + 500))) {
				h.update(sha(t));
			}
		}
		expect(h.digest("hex")).toBe(golden.allIdsDigest);
	}, 60_000);
});

describe.skipIf(!MODEL.ok)("fpgen conditions and beam search == Python", () => {
	const golden = fixture("conditions.json");

	it("covers beam pruning", () => {
		const pruned = golden.cases.reduce((a: number, c: any) => a + c.pruned, 0);
		expect(pruned).toBeGreaterThan(0);
	});

	for (const c of golden.cases) {
		it(`${c.name}: same evidence and bit-identical distributions`, () => {
			const evidence: EvidenceMap = new Map();
			buildEvidence(fromFixture(c.conditions), evidence);
			expect(evidenceFixture(evidence)).toEqual(c.evidence);

			const { network } = getModel();
			for (const [target, dist] of Object.entries(c.traces)) {
				// Same keys, same order, same doubles.
				expect([...network.trace(target, evidence)], target).toEqual(dist);
			}
		});
	}

	for (const e of golden.errors) {
		it(`${e.name}: ${e.error ?? "relaxed"}`, () => {
			const evidence: EvidenceMap = new Map();
			const run = () =>
				buildEvidence(fromFixture(e.conditions), evidence, e.strict);
			if (e.error) {
				let caught: Error | undefined;
				try {
					run();
				} catch (err) {
					caught = err as Error;
				}
				expect(caught?.name).toBe(e.error);
				expect(normFn(caught?.message ?? "")).toBe(normFn(e.message));
			} else {
				run();
				expect(evidenceFixture(evidence)).toEqual(e.evidence);
			}
		});
	}
});

describe.skipIf(!MODEL.ok)("fpgen public API == Python", () => {
	const golden = fixture("api.json");

	for (const t of golden.traces) {
		it(`trace(): ${t.name}`, () => {
			const res = trace(t.target, fromFixture(t.conditions), t.options);
			expect(plainTrace(res)).toEqual(t.result);
		});
	}

	it("Generator.trace() inherits the generator's conditions", () => {
		const g = new Generator({ browser: "Firefox", os: "Windows" });
		expect(plainTrace(g.trace("navigator.platform"))).toEqual(
			golden.generatorTrace,
		);
	});

	for (const q of golden.queries) {
		it(`query(${q.target}, ${JSON.stringify(q.options)})`, () => {
			expect(query(q.target, q.options)).toEqual(q.result);
		});
	}

	for (const q of golden.queryErrors) {
		it(`query(${q.target}) raises ${q.error}`, () => {
			expect(() => query(q.target)).toThrow(
				expect.objectContaining({ name: q.error, message: q.message }),
			);
		});
	}

	for (const d of golden.deterministic) {
		it(`generate(): ${d.name}`, () => {
			for (let i = 0; i < 10; i++) {
				expect(new Generator().generate(d.conditions, d.options)).toEqual(
					d.result,
				);
			}
		});
	}

	it("produces the same output shape", () => {
		const g = new Generator({ browser: "Firefox" });
		expect(Object.keys(g.generate()).sort()).toEqual(
			golden.shapes.topLevelKeys,
		);
		expect(
			Object.keys(g.generate(null, { target: "navigator" })).sort(),
		).toEqual(golden.shapes.navigatorKeys);
		expect(
			Object.keys(g.generate(null, { flatten: true }))
				.filter((k) => k.startsWith("navigator."))
				.sort(),
		).toEqual(golden.shapes.flatKeysSample);
	});
});
