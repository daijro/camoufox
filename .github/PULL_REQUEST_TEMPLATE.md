<!--
This repository is the browser (patches, settings, fonts, the build and its
CI) and the `camoufox` release wrapper, which holds only alias stubs and pins.
The Python and TypeScript launchers (launch options, fingerprints, geoip,
`camoufox fetch`, the CLI, the MCP server) live in CamouBrowser/camoucore; open
driver changes at https://github.com/CamouBrowser/camoucore. CI fails a pull
request here that adds launcher code.
-->

## Related Issue

Closes #

## Description

<!-- What does this PR change and why? -->

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Other

## Testing

<!-- How did you test your changes? Anything a reviewer should run by hand, or
     anything CI cannot reach. -->

<!--
CI runs the full pipeline on this pull request and posts the results as a
comment: build (or the published release, for a change that leaves the browser alone), patch
guards, build-tester, the upstream Playwright suite, leaks, and the stealth
grade. No report needs pasting in here, and no screenshots -- the numbers in
the comment came from a browser built from this branch, which a screenshot
could never show. See ci/README.md to reproduce any gate locally.
-->

## Checklist

- [ ] I have linked a related issue above
- [ ] My changes are focused on a single logical change
- [ ] I have added testing instructions which include the desired result
- [ ] The `All tests passed` check is green (CI runs every suite; see `ci/README.md`)
