# camoufox

The Node.js launcher for [Camoufox](https://camoufox.com), the anti-detect
Firefox build.

```sh
npm install camoufox playwright-core
npx camoufox fetch
```

```js
import { Camoufox } from "camoufox";
```

This package is the `camoucore/camoufox` launcher from
[camoucore](https://github.com/CamouBrowser/camoucore) under its own name, at
one exact camoucore version, plus the browser release it was tested with
(`camoufox/camoufox_pin/browser-pin.json`). `npx camoufox mcp` serves the
browser over MCP.

- Usage and launch options: [camoucore's camoufox docs](https://github.com/CamouBrowser/camoucore/blob/main/typescript/camoucore/docs/camoufox.md)
- MCP server: [docs/mcp.md](https://github.com/CamouBrowser/camoucore/blob/main/typescript/camoucore/docs/mcp.md)
- The browser: [daijro/camoufox](https://github.com/daijro/camoufox)

Launcher bugs and pull requests go to camoucore; browser ones to
daijro/camoufox. This package is MIT licensed (LICENSE); the browser it
downloads is under the Mozilla Public License 2.0.
