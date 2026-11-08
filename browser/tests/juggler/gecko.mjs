// Just enough of the Gecko globals for Juggler's input modules to load under
// Node: ChromeUtils.importESModule for the resource:// URLs they import lazily,
// and the channel read Cursory's data.js does for its recordings.
import * as fs from 'node:fs';
import * as path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const JUGGLER = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../additions/juggler');

const modules = new Map();

function readerFor(url) {
  const file = path.join(JUGGLER, url.replace('resource://gre/modules/juggler/', ''));
  return {file};
}

globalThis.Components = {
  classes: {
    '@mozilla.org/scriptableinputstream;1': {
      createInstance: () => {
        let text = '';
        return {
          init(channel) { text = fs.readFileSync(channel.file, 'latin1'); },
          available: () => text.length,
          readBytes(n) { const chunk = text.slice(0, n); text = text.slice(n); return chunk; },
          close() {},
        };
      },
    },
  },
  interfaces: {nsIScriptableInputStream: {}},
};

globalThis.ChromeUtils = {
  importESModule(url) {
    if (url === 'resource://gre/modules/NetUtil.sys.mjs')
      return {NetUtil: {newChannel: ({uri}) => ({open: () => readerFor(uri)})}};
    const module = modules.get(url);
    if (!module)
      throw new Error(`not loaded under Node: ${url}`);
    return module;
  },
};

/** Import a Juggler module by its path under browser/additions/juggler/. */
export async function load(relative) {
  const module = await import(pathToFileURL(path.join(JUGGLER, relative)).href);
  modules.set(`resource://gre/modules/juggler/${relative}`, module);
  return module;
}

// CursorTrajectory.js imports Cursory lazily through its resource:// URL.
await load('input/cursory/cursory.js');
