// Just enough of the Gecko globals for Juggler's input modules to load under
// Node: ChromeUtils.importESModule for the resource:// URLs they import.
import * as path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

export const JUGGLER = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../additions/juggler');

const modules = new Map();

globalThis.ChromeUtils = {
  importESModule(url) {
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
