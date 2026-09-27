/**
 * The pinned fpgen model: a copy of scripts/data/fpgen-model.json.
 *
 * That file is the single source of truth for the Python build; this constant
 * is its twin for the npm package, which does not ship the repo's scripts/.
 * tests/fpgen-model.test.ts fails if the two ever disagree, so bumping the
 * model means editing both (the sha256 is the gate in each).
 *
 * See scripts/pin-fpgen-model.py for why fpgen's own downloader is not used:
 * it disables TLS verification, never checks a digest, and its "first listed
 * release" rule cannot reach this tag.
 */

export interface ModelPin {
	readonly tag: string;
	readonly asset: string;
	readonly size: number;
	readonly sha256: string;
	readonly url: string;
	readonly repo: string;
	readonly files: readonly string[];
}

export const MODEL_PIN: ModelPin = {
	tag: "model-2/2026",
	asset: "model-release.zip",
	size: 1564571,
	sha256: "6530b8322cdaa4ec042921c8d9a0369a0e6e0269ba636c01a7203e4a2f109936",
	url: "https://github.com/scrapfly/fingerprint-generator/releases/download/model-2/2026/model-release.zip",
	repo: "scrapfly/fingerprint-generator",
	files: ["fingerprint-network.json.zst", "values.dat.zst", "values.json.zst"],
};
