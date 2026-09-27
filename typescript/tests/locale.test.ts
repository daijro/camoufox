import { describe, expect, it } from "vitest";
import { InvalidLocale } from "../src/exceptions.js";
import { handleLocale, handleLocales, normalizeLocale } from "../src/locale.js";

describe("normalizeLocale", () => {
	it("splits language and region", () => {
		const locale = normalizeLocale("en-US");
		expect(locale.language).toBe("en");
		expect(locale.region).toBe("US");
		expect(locale.asString).toBe("en-US");
	});

	// Parity with pythonlib: the script is the LANGUAGE's Suppress-Script
	// (record['Suppress-Script']), not the tag's explicit script subtag.
	it("uses the language's suppress-script, not the tag's", () => {
		const locale = normalizeLocale("zh-Hans-CN");
		expect(locale.language).toBe("zh");
		expect(locale.script).toBeUndefined();
		expect(locale.region).toBe("CN");
	});

	it("adds the implicit suppress-script", () => {
		expect(normalizeLocale("en-US").script).toBe("Latn");
		expect(normalizeLocale("fr-FR").script).toBe("Latn");
	});

	it("rejects a locale with no region", () => {
		expect(() => normalizeLocale("en")).toThrow(InvalidLocale);
	});

	it("rejects nonsense", () => {
		expect(() => normalizeLocale("not a locale")).toThrow(InvalidLocale);
	});
});

describe("Locale.asConfig", () => {
	it("emits the intl config keys", () => {
		expect(normalizeLocale("fr-FR").asConfig()).toEqual({
			"locale:language": "fr",
			"locale:region": "FR",
			"locale:script": "Latn",
		});
	});

	it("omits the script when the language has no suppress-script", () => {
		expect(normalizeLocale("zh-Hant-TW").asConfig()).toEqual({
			"locale:language": "zh",
			"locale:region": "TW",
		});
	});
});

describe("handleLocale", () => {
	it("resolves a bare region to a plausible language", async () => {
		const locale = await handleLocale("JP");
		expect(locale.region).toBe("JP");
		expect(locale.language).toBeTruthy();
	});

	it("passes a full tag straight through", async () => {
		expect((await handleLocale("pt-BR")).asString).toBe("pt-BR");
	});

	it("keeps a bare language when the region is not required", async () => {
		expect((await handleLocale("de", true)).asString).toBe("de");
	});
});

describe("handleLocales", () => {
	it("uses the first locale for the intl config", async () => {
		const config: Record<string, any> = {};
		await handleLocales("fr-FR", config);
		expect(config["locale:language"]).toBe("fr");
		expect(config["locale:region"]).toBe("FR");
		expect(config["locale:all"]).toBeUndefined();
	});

	it("writes locale:all for a comma-separated list, deduplicated", async () => {
		const config: Record<string, any> = {};
		await handleLocales("en-US, fr-FR, en-US, de", config);
		expect(config["locale:language"]).toBe("en");
		expect(config["locale:all"]).toBe("en-US, fr-FR, de");
	});

	it("accepts an array as well as a string", async () => {
		const config: Record<string, any> = {};
		await handleLocales(["es-ES", "ca-ES"], config);
		expect(config["locale:all"]).toBe("es-ES, ca-ES");
	});
});

describe("StatisticalLocaleSelector (numpy parity)", () => {
	it("sums like numpy (pairwise)", async () => {
		const { pairwiseSum } = await import("../src/locales.js");
		// Values from numpy: 200 x 0.1 sums to 20.0 pairwise (20.000000000000014
		// sequentially); the 115-element one exercises the 8-way unroll + tail.
		expect(pairwiseSum(Array.from({ length: 200 }, () => 0.1))).toBe(20);
		const mixed = Array.from({ length: 23 }, () => [
			0.3, 0.7, 1.1, 2.9, 0.01,
		]).flat();
		expect(pairwiseSum(mixed)).toBe(115.22999999999999);
		expect(pairwiseSum([1, 2, 3])).toBe(6);
	});

	it("picks by searchsorted(right) of one uniform draw", async () => {
		const { localeDeps, weightedChoice } = await import("../src/locales.js");
		const before = localeDeps.random;
		try {
			localeDeps.random = () => 0.5;
			expect(weightedChoice(["a", "b", "c"], [0.25, 0.25, 0.5])).toBe("c");
			localeDeps.random = () => 0.49;
			expect(weightedChoice(["a", "b", "c"], [0.25, 0.25, 0.5])).toBe("b");
			localeDeps.random = () => 0;
			expect(weightedChoice(["a", "b"], [0, 1])).toBe("b");
		} finally {
			localeDeps.random = before;
		}
	});
});
