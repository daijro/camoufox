/**
 * Locale data structures, validation and the statistical locale selector.
 *
 * TypeScript twin of pythonlib/camoufox/locales.py.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import tags from "language-tags";
import xml2js from "xml2js";
import {
	InvalidLocale,
	UnknownLanguage,
	UnknownTerritory,
} from "./exceptions.js";
import { LOCAL_DATA } from "./paths.js";
import { LeakWarning } from "./warnings.js";

/*
 * Data structures for locale and geolocation info
 */

/**
 * Stores locale, region, and script information.
 */
export class Locale {
	constructor(
		public language: string,
		public region?: string,
		public script?: string,
	) {}

	get asString(): string {
		if (this.region) {
			return `${this.language}-${this.region}`;
		}
		return this.language;
	}

	/**
	 * Converts the locale to an intl config object.
	 */
	asConfig(): Record<string, string> {
		if (!this.region) {
			throw new Error("AssertionError: Locale.asConfig() needs a region");
		}
		const data: Record<string, string> = {
			"locale:region": this.region,
			"locale:language": this.language,
		};
		if (this.script) {
			data["locale:script"] = this.script;
		}
		return data;
	}
}

/**
 * Stores geolocation information.
 */
export class Geolocation {
	constructor(
		public readonly locale: Locale,
		public readonly longitude: number,
		public readonly latitude: number,
		public readonly timezone: string,
		public readonly accuracy?: number,
	) {}

	/**
	 * Converts the geolocation to a config object.
	 */
	asConfig(): Record<string, any> {
		const data: Record<string, any> = {
			"geolocation:longitude": this.longitude,
			"geolocation:latitude": this.latitude,
			timezone: this.timezone,
			...this.locale.asConfig(),
		};
		if (this.accuracy) {
			data["geolocation:accuracy"] = this.accuracy;
		}
		return data;
	}
}

/*
 * Helpers to validate and normalize locales
 */

/**
 * Verifies that a locale is valid. Takes either language-region or language.
 */
export function verifyLocale(loc: string): void {
	if (tags.check(loc)) {
		return;
	}
	throw InvalidLocale.invalidInput(loc);
}

/**
 * Normalizes and validates a locale code.
 *
 * The script is the LANGUAGE's Suppress-Script ("Latn" for "en"), exactly as
 * pythonlib does -- not the tag's explicit script subtag. Parity note: that
 * makes "en-US" come out as en/Latn/US, and "zh-Hans-CN" as zh/(none)/CN.
 */
export function normalizeLocale(locale: string): Locale {
	verifyLocale(locale);

	// Parse the locale
	const parser = tags(locale);
	const region = parser.region();
	if (!region) {
		throw InvalidLocale.invalidInput(locale);
	}

	const language = parser.language();
	if (!language) {
		throw InvalidLocale.invalidInput(locale);
	}
	const suppressScript = language.script();

	// Return a formatted locale object
	return new Locale(
		language.format(),
		region.format(),
		suppressScript ? suppressScript.format() : undefined,
	);
}

/**
 * Handles a locale input, normalizing it if necessary.
 */
export async function handleLocale(
	locale: string,
	ignoreRegion: boolean = false,
): Promise<Locale> {
	// If the caller passed `language-region` or `language-script-region`, normalize it.
	if (locale.length > 3) {
		return normalizeLocale(locale);
	}

	// Case: caller passed a `region` and needs a full locale
	try {
		return await SELECTOR.fromRegion(locale);
	} catch (e) {
		if (!(e instanceof UnknownTerritory)) throw e;
	}

	// Case: caller passed a `language`, and doesn't care about the region
	if (ignoreRegion) {
		verifyLocale(locale);
		return new Locale(locale);
	}

	// Case: caller passed a `language` and wants a region
	let language: Locale | undefined;
	try {
		language = await SELECTOR.fromLanguage(locale);
	} catch (e) {
		if (!(e instanceof UnknownLanguage)) throw e;
	}
	if (language) {
		LeakWarning.warn("no_region");
		return language;
	}

	// Locale is not in a valid format.
	throw InvalidLocale.invalidInput(locale);
}

/**
 * Handles a list of locales, writing them into the config.
 */
export async function handleLocales(
	locales: string | string[],
	config: Record<string, any>,
): Promise<void> {
	const list =
		typeof locales === "string"
			? locales.split(",").map((loc) => loc.trim())
			: locales;

	// First, handle the first locale. This will be used for the intl api.
	const intlLocale = await handleLocale(list[0]);
	Object.assign(config, intlLocale.asConfig());

	if (list.length < 2) {
		return;
	}

	// If additional locales were passed, validate them.
	// Note: in this case, we do not need the region.
	const resolved: string[] = [];
	for (const locale of list) {
		resolved.push((await handleLocale(locale, true)).asString);
	}
	config["locale:all"] = joinUnique(resolved);
}

/**
 * Joins a sequence of strings without duplicates.
 */
function joinUnique(seq: string[]): string {
	return [...new Set(seq)].join(", ");
}

/*
 * Gets a random language based on the territory code.
 */

interface TerritoryElement {
	$: Record<string, string>;
	languagePopulation?: Array<{ $: Record<string, string> }>;
}

let unicodeInfo: Promise<TerritoryElement[]> | null = null;

/**
 * Fetches supplemental data from the territoryInfo.xml file.
 * Source: https://raw.githubusercontent.com/unicode-org/cldr/master/common/supplemental/supplementalData.xml
 */
export function getUnicodeInfo(): Promise<TerritoryElement[]> {
	if (!unicodeInfo) {
		unicodeInfo = (async () => {
			const data = await fs.promises.readFile(
				path.join(LOCAL_DATA, "territoryInfo.xml"),
			);
			const parsed = await new xml2js.Parser().parseStringPromise(data);
			const territories = parsed?.territoryInfo?.territory;
			if (!territories) {
				throw new Error("Failed to load territoryInfo.xml");
			}
			return territories as TerritoryElement[];
		})();
	}
	return unicodeInfo;
}

/** float(element.get(attr, 0)) */
function asFloat(attrs: Record<string, string>, attr: string): number {
	const raw = attrs[attr];
	if (raw === undefined) return 0;
	const value = Number(raw.trim());
	if (Number.isNaN(value)) {
		throw new Error(`could not convert string to float: '${raw}'`);
	}
	return value;
}

/**
 * numpy's pairwise summation (np.sum over a 1-D float64 array), so the
 * normalised probabilities are bit-identical to the Python selector's.
 */
export function pairwiseSum(values: readonly number[]): number {
	const sum = (lo: number, n: number): number => {
		if (n < 8) {
			let res = 0;
			for (let i = 0; i < n; i++) res += values[lo + i];
			return res;
		}
		if (n <= 128) {
			const r = values.slice(lo, lo + 8);
			let i = 8;
			for (; i < n - (n % 8); i += 8) {
				for (let j = 0; j < 8; j++) r[j] += values[lo + i + j];
			}
			let res = r[0] + r[1] + (r[2] + r[3]) + (r[4] + r[5] + (r[6] + r[7]));
			for (; i < n; i++) res += values[lo + i];
			return res;
		}
		let n2 = Math.floor(n / 2);
		n2 -= n2 % 8;
		return sum(lo, n2) + sum(lo + n2, n - n2);
	};
	return sum(0, values.length);
}

/**
 * Injection point for the selector's one random draw (tests pin it).
 * `random()` plays numpy's RandomState.random_sample().
 */
export const localeDeps = {
	random: (): number => Math.random(),
};

/**
 * numpy.random.choice(items, p=probabilities): searchsorted(right) of one
 * uniform draw in the renormalised CDF.
 */
export function weightedChoice<T>(
	items: readonly T[],
	p: readonly number[],
): T {
	const cdf: number[] = [];
	let acc = 0;
	for (const x of p) {
		acc += x;
		cdf.push(acc);
	}
	const last = cdf[cdf.length - 1];
	for (let i = 0; i < cdf.length; i++) cdf[i] /= last;
	const u = localeDeps.random();
	let idx = 0;
	while (idx < cdf.length && cdf[idx] <= u) idx++;
	return items[Math.min(idx, items.length - 1)];
}

/**
 * Selects a random locale based on statistical data. Takes either a territory
 * code or a language code, and generates a Locale.
 */
export class StatisticalLocaleSelector {
	/**
	 * Calculates a random language based on the territory code, based on the
	 * probability that a person speaks the language in the territory.
	 */
	private async loadTerritoryData(
		isoCode: string,
	): Promise<[string[], number[]]> {
		const territories = await getUnicodeInfo();
		const territory = territories.find((t) => t.$?.type === isoCode);
		if (!territory) {
			throw new UnknownTerritory(`Unknown territory: ${isoCode}`);
		}

		const langPopulations = territory.languagePopulation;
		if (!langPopulations?.length) {
			throw new Error(`No language data found for region: ${isoCode}`);
		}

		const languages = langPopulations.map((lang) => lang.$.type);
		const percentages = langPopulations.map((lang) =>
			asFloat(lang.$, "populationPercent"),
		);

		return this.normalizeProbabilities(languages, percentages);
	}

	/**
	 * Calculates a random region for a language based on the total speakers of
	 * the language in that region.
	 */
	private async loadLanguageData(
		language: string,
	): Promise<[string[], number[]]> {
		const territories = (await getUnicodeInfo()).filter((t) =>
			t.languagePopulation?.some((lp) => lp.$?.type === language),
		);
		if (!territories.length) {
			throw new UnknownLanguage(
				`No region data found for language: ${language}`,
			);
		}

		const regions: string[] = [];
		const percentages: number[] = [];

		for (const terr of territories) {
			const region = terr.$?.type;
			if (region === undefined) continue; // Skip if region is not found

			const langPop = terr.languagePopulation?.find(
				(lp) => lp.$?.type === language,
			);
			if (!langPop) continue;

			regions.push(region);
			percentages.push(
				((asFloat(langPop.$, "populationPercent") *
					asFloat(terr.$, "literacyPercent")) /
					10_000) *
					asFloat(terr.$, "population"),
			);
		}

		if (!regions.length) {
			throw new Error(`No valid region data found for language: ${language}`);
		}

		return this.normalizeProbabilities(regions, percentages);
	}

	/** Normalize probabilities. */
	normalizeProbabilities(
		items: string[],
		freq: number[],
	): [string[], number[]] {
		const total = pairwiseSum(freq);
		return [items, freq.map((f) => f / total)];
	}

	/**
	 * Get a random locale based on the territory ISO code.
	 */
	async fromRegion(region: string): Promise<Locale> {
		const [languages, probabilities] = await this.loadTerritoryData(region);
		const language = weightedChoice(languages, probabilities).replaceAll(
			"_",
			"-",
		);
		return normalizeLocale(`${language}-${region}`);
	}

	/**
	 * Get a random locale based on the language.
	 */
	async fromLanguage(language: string): Promise<Locale> {
		const [regions, probabilities] = await this.loadLanguageData(language);
		const region = weightedChoice(regions, probabilities);
		return normalizeLocale(`${language}-${region}`);
	}
}

export const SELECTOR = new StatisticalLocaleSelector();
