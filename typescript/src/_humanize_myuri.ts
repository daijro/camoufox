/**
 * myuri() engines: myuri plans each input for the launch identity's OS, and
 * the custom-engine wrappers play the plan through Playwright
 * (_humanize_custom.ts). The TypeScript twin of
 * python/src/camoufox/_humanize_myuri.py. myuri only plans; nothing here runs
 * in the page except its scroll measurement.
 */

import { createRequire } from "node:module";
import { POINTER } from "./_humanize_custom.js";
import { pageFunction } from "./driver_defaults.js";
import { NotInstalledHumanizeExtra } from "./exceptions.js";
import type {
	Channel,
	CustomEngine,
	EngineTools,
	MyuriOptions,
	SeededRng,
} from "./humanize.js";
import type { OsName } from "./utils.js";

type Planner = typeof import("@jwriter20/myuri");
type Point = [number, number];

const MODULE = "@jwriter20/myuri";

// An element still out of view after this many wheel plans (one that moves as
// it scrolls) is brought into view by Playwright's own scroll.
const SCROLL_PASSES = 3;

const VIEWPORT = "() => [innerWidth, innerHeight]";
const CLIENT_ORIGIN =
	"e => { const r = e.getBoundingClientRect(); return [r.x, r.y]; }";

export function requireMyuri(): void {
	try {
		createRequire(import.meta.url).resolve(MODULE);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "MODULE_NOT_FOUND")
			throw error;
		throw new NotInstalledHumanizeExtra(
			`humanize uses myuri, which is not installed. Install it with: npm i ${MODULE}`,
		);
	}
}

let loaded: Promise<Planner> | undefined;
const planner = () => {
	loaded ??= import(MODULE) as Promise<Planner>;
	return loaded;
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** The function that runs myuri on `channel` for an identity on `os`. */
export function engine(
	channel: Channel,
	options: MyuriOptions,
	os: OsName,
): CustomEngine {
	const mouse = async (
		page: any,
		x: number,
		y: number,
		{ original, rng, play, click }: EngineTools,
	) => {
		const plan = await planner();
		let point: Point = [x, y];
		if (click?.box) {
			const [sx, sy] = await cursor(page, rng);
			const at = plan.planPoint(click.box, rng, { start: { x: sx, y: sy } });
			point = [at.x, at.y];
		}
		await moveTo(plan, os, page, point, rng, play);
		if (!click) return;
		const { dwellMs, presses } = plan.planClick(rng, {
			os,
			clickCount: click.clickCount,
		});
		await sleep(dwellMs);
		const span = presses[presses.length - 1][1] - presses[0][0];
		// The press holds each press for `delay` and waits it again between
		// presses, so spread the plan's span evenly over those 2n - 1 intervals.
		return original(...point, { delay: span / (2 * presses.length - 1) });
	};

	const keyboard = async (
		_page: any,
		text: string,
		{ rng, play, kind }: EngineTools,
	) => {
		const plan = await planner();
		const steps =
			kind === "press"
				? plan.planPress(text, rng, { os })
				: plan.planType(text, rng, { os, wpm: options.wpm });
		return play(
			steps.map(([t, action, key]) =>
				action === "insert" ? ["text", key, t] : ["key", key, action, t],
			),
		);
	};

	const scroll = async (
		page: any,
		target: any,
		{ original, rng, play }: EngineTools,
	) => {
		const plan = await planner();
		if (Array.isArray(target))
			return play(wheel(plan, os, target[0], target[1], rng));
		for (let pass = 0; pass < SCROLL_PASSES; pass += 1) {
			const [fromX, fromY] = await cursor(page, rng);
			const step = await target.evaluate(plan.SCROLL_PLAN_JS, {
				finishPosition: plan.SCROLL_FINISH_POSITION,
				pad: plan.SCROLL_PAD,
				edge: plan.SCROLL_EDGE,
				fromX,
				fromY,
			});
			if (!step || step.inView) return;
			// The plan is in the element's frame; the mouse is in the page.
			const box = await target.boundingBox();
			const [left, top] = await target.evaluate(pageFunction(CLIENT_ORIGIN));
			const hover: Point = [
				step.hoverX + box.x - left,
				step.hoverY + box.y - top,
			];
			await moveTo(plan, os, page, hover, rng, play);
			await play(wheel(plan, os, 0, step.deltaY, rng));
		}
		return original();
	};

	return { mouse, keyboard, scroll }[channel] as CustomEngine;
}

/** Where the cursor is. Before the first move it is somewhere in the window,
 * as a person's is when they start. */
async function cursor(page: any, rng: SeededRng): Promise<Point> {
	let here = POINTER.get(page);
	if (!here) {
		const [width, height] = await page.evaluate(pageFunction(VIEWPORT));
		here = [rng() * width, rng() * height];
		POINTER.set(page, here);
	}
	return here;
}

async function moveTo(
	plan: Planner,
	os: OsName,
	page: any,
	point: Point,
	rng: SeededRng,
	play: EngineTools["play"],
) {
	const start = await cursor(page, rng);
	if (start[0] === point[0] && start[1] === point[1]) return;
	await play(
		plan
			.planMove(
				{ x: start[0], y: start[1] },
				{ x: point[0], y: point[1] },
				rng,
				{ os },
			)
			.map(({ x, y, t }) => ["move", x, y, t]),
	);
}

// Camoufox identities point with a mouse, whose wheel turns in notches.
const wheel = (
	plan: Planner,
	os: OsName,
	dx: number,
	dy: number,
	rng: SeededRng,
) => plan.planWheel(dx, dy, rng, { os, device: "mouse" });
