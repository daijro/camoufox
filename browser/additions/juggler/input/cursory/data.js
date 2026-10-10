/**
 * The recorded-trajectory database.
 *
 * CAMOUFOX: upstream reads `trajectories.json.gz` off disk with node:fs and
 * node:zlib. Here the same data ships inside omni.ja as plain JSON -- the jar is
 * already deflated, so storing it uncompressed costs nothing in the package and
 * saves decompressing it again at runtime -- and is read back over a chrome://
 * channel. The parsed value is identical either way.
 *
 * The read is synchronous so that this module stays a plain import, exactly as
 * upstream is, and so `trajectorySelection.js` can keep building its lookup
 * tables at module scope. It costs one ~2MB read and parse, once per process,
 * and only when something actually imports Cursory -- which, on the Camoufox
 * side, only happens when humanize is turned on and the cursor first moves.
 */

const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');

const TRAJECTORIES_URL = 'chrome://juggler/content/input/cursory/trajectories.json';

/**
 * Read a packaged chrome:// resource as text.
 *
 * Read in a loop rather than in one `available()`-sized go: the URL resolves
 * into omni.ja, and a jar stream is under no obligation to make the whole
 * decompressed entry available at once. The database is pure ASCII (JSON of
 * numbers), so reading it as bytes is already the right text and no charset
 * conversion is involved.
 */
function readPackagedText(url) {
  const channel = NetUtil.newChannel({uri: url, loadUsingSystemPrincipal: true});
  const stream = Components.classes['@mozilla.org/scriptableinputstream;1']
      .createInstance(Components.interfaces.nsIScriptableInputStream);
  stream.init(channel.open());
  try {
    const chunks = [];
    for (let available = stream.available(); available > 0; available = stream.available())
      chunks.push(stream.readBytes(available));
    return chunks.join('');
  } finally {
    stream.close();
  }
}

/**
 * Every recorded trajectory Cursory picks from. The data is the one shipped with
 * the Python original, entry for entry.
 */
export const LOADED_TRAJECTORIES = JSON.parse(readPackagedText(TRAJECTORIES_URL));
