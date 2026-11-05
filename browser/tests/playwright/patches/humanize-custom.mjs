// The TypeScript half of humanize-custom.py: the same session through the
// camoufox launcher, with the same functions, draw for draw.
//
//   node browser/tests/playwright/patches/humanize-custom.mjs <typescript/dist/index.js> <seed> [camoufox-bin]
//
// Prints {log, events, state} as JSON for the Python guard to compare.
import {pathToFileURL} from 'node:url';

const [distPath, seed, executablePath] = process.argv.slice(2);
const {Camoufox, Screen, custom} = await import(pathToFileURL(distPath).href);

const BODY = `<body style="margin:0;height:5000px">
  <input id="name" style="position:absolute;left:40px;top:120px;width:200px">
  <button id="near" style="position:absolute;left:500px;top:300px;width:50px;height:20px">near</button>
  <button id="far" style="position:absolute;left:100px;top:2600px;width:80px;height:30px">far</button>
  <div id="box" style="position:absolute;left:600px;top:380px;width:300px;height:200px;overflow:auto">
    <div style="height:1500px"><button id="deep" style="margin-top:1100px">deep</button></div>
  </div>
</body>`;
const RECORDER = `() => {
  window.rec = [];
  const round = v => Math.round(v * 100) / 100;
  for (const type of ['mousemove', 'mousedown', 'mouseup', 'click', 'keydown', 'keyup', 'wheel'])
    addEventListener(type, e => rec.push([type, e.isTrusted, round(e.clientX ?? 0), round(e.clientY ?? 0),
                                          e.key ?? '', round(e.deltaY ?? 0)]), true);
}`;
// Wheel scrolling lands asynchronously; wait until the page stops moving so
// the next measurement does not depend on timing.
const SETTLE = () => new Promise(resolve => {
  let last = scrollY, same = 0;
  const tick = () => {
    if (scrollY === last) { if (++same >= 10) return resolve(scrollY); }
    else { same = 0; last = scrollY; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
});

function referenceEngines(log) {
  const at = {x: 0, y: 0};
  const move = async (page, x, y, {rng, play}) => {
    log.push(['mouse', x, y]);
    const n = 8 + Math.floor(rng() * 8);
    const [sx, sy] = [at.x, at.y];
    const steps = [];
    for (let i = 1; i <= n; i++) {
      const f = i / n;
      const ease = f * f * (3 - 2 * f);
      const jitter = (rng() - 0.5) * 6 * (1 - f);
      steps.push(['move', sx + (x - sx) * ease + jitter, sy + (y - sy) * ease - jitter, i * 12]);
    }
    at.x = x;
    at.y = y;
    return play(steps);
  };
  const keys = async (page, text, {original, rng, play, kind}) => {
    log.push(['keyboard', kind, text]);
    if (kind === 'press')
      return original();
    const steps = [];
    let t = 0;
    for (const ch of text) {
      steps.push(['key', ch, 'down', t]);
      t += 30 + Math.floor(rng() * 40);
      steps.push(['key', ch, 'up', t]);
      t += 20 + Math.floor(rng() * 60);
    }
    return play(steps);
  };
  const scroll = async (page, target, {original, rng, play}) => {
    if (Array.isArray(target)) {
      log.push(['scroll', target]);
      const n = 3 + Math.floor(rng() * 3);
      return play(Array.from({length: n}, (_, i) => ['wheel', target[0] / n, target[1] / n, i * 16]));
    }
    log.push(['scroll', 'locator']);
    const distance = await target.evaluate(e => {
      const r = e.getBoundingClientRect();
      return r.top + r.height / 2 - innerHeight / 2;
    });
    const steps = [];
    let done = 0;
    let t = 0;
    while (Math.abs(distance - done) > 1) {
      const chunk = Math.floor(Math.max(-120, Math.min(120, distance - done)) * (0.8 + rng() * 0.2) + 0.5);
      if (chunk === 0)
        break;
      steps.push(['wheel', 0, chunk, t]);
      done += chunk;
      t += 16 + Math.floor(rng() * 10);
    }
    await play(steps);
    await page.evaluate(SETTLE);
    return original();
  };
  return {move, keys, scroll};
}

const log = [];
const {move, keys, scroll} = referenceEngines(log);
const options = {
  headless: true,
  os: 'linux',
  // A screen that holds the 1000x700 page: one that cannot clamps the page
  // (one machine, one screen), and the replay compares pages of one size.
  screen: new Screen({minWidth: 1100, minHeight: 800}),
  humanize: {mouse: custom(move), keyboard: custom(keys), scroll: custom(scroll), seed: BigInt(seed)},
};
if (executablePath)
  options.executable_path = executablePath;
const browser = await Camoufox(options);
try {
  const page = await browser.newPage({viewport: {width: 1000, height: 700}});
  await page.setContent(BODY);
  // A string evaluates as an expression here, so call the function it holds.
  await page.evaluate(`(${RECORDER})()`);
  await page.mouse.move(300, 200);
  await page.mouse.wheel(0, 360);
  await page.evaluate(SETTLE);
  await page.mouse.wheel(0, -360);
  await page.evaluate(SETTLE);
  await page.locator('#near').click();
  await page.locator('#name').fill('Hi there');
  await page.keyboard.press('Tab');
  await page.locator('#far').click();
  const state = await page.evaluate(
      "[document.querySelector('#name').value, Math.round(scrollY)," +
      " (r => r.top >= 0 && r.bottom <= innerHeight)(document.querySelector('#far').getBoundingClientRect())]");
  const events = await page.evaluate('rec');
  process.stdout.write(JSON.stringify({log, events, state}));
} finally {
  await browser.close();
}
