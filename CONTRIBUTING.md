# Contributing to Camoufox

Thanks for your interest in contributing! Here's how to get started.

## Ways to Contribute

- **Bug reports** — Open an issue with steps to reproduce, expected behavior, and actual behavior.
- **Feature requests** — Open an issue describing the use case and why it's useful.
- **Code contributions** — Fork the repo, make your changes, and open a pull request.
- **Documentation** — Fixes and improvements to docs are always welcome.

## Development Setup
See README.md

## Pull Request Rules

1. Each pull request must be associated with a Github issue
2. Follow the pull request template
3. Keep commits focused — one logical change per commit.
4. Open a PR with a clear description of what you changed and why.
5. All pull requests must pass both the **build-tester** and **service_tests** test suites before merging.

## Testing Requirements

Two test suites must pass before a PR can be merged:

### build-tester

Tests the Camoufox binary in isolation. This verifies that the browser binary itself is functioning correctly — fingerprint properties, header behavior, and other browser-level changes. Run this when you've made changes to the browser source.

### service_tests

Tests the full stack: both the pip package and the binary together. This validates that the Python library correctly launches, configures, and communicates with the browser binary end-to-end. Run this when you've made changes to either the Python package (`pythonlib/`) or anything that affects how the pip package interacts with the binary.

When in doubt, run both.

## Reporting Issues

Please search existing issues before opening a new one. Include:
- Camoufox version
- OS and Python version
- A minimal reproducible example

## Questions

For usage questions, check the [documentation](https://camoufox.com) first. For anything else, open an issue.
