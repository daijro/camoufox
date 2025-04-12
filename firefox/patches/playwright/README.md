# Playwright Patches

| File                 | Purpose                                                                                                                                                                                                                    |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `0-playwright.patch` | Playwright's upstream patches. Needs to be kept up to date with [this file](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff). Will branch off if upstream is out of date. |
| `0-leak-fixes.patch` | Undos certain patches from `0-playwright.patch`.                                                                                                                                                                           |
