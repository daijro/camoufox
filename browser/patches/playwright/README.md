# Playwright Patches

| File                 | Purpose                                                                                                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0-playwright.patch` | Playwright's Firefox patch ([`bootstrap.diff`](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff)), ported to this Firefox version and carrying Camoufox's own changes to the same files. It is not a verbatim copy. |
| `1-leak-fixes.patch` | Reverts the part of `0-playwright.patch` a page can read: `navigator.webdriver` is `false`, as in a Firefox nobody is driving.                                                                                                                               |
