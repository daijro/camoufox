# Camoufox Tests

Ensures that Playwright functionality is not broken.

---

This directory is based on the original Playwright-Python [tests](https://github.com/microsoft/playwright-python/tree/main/tests).

It has been modified to skip tests that use the following features:

- Injecting JavaScript into the page or writing to DOM. Camoufox's `page.evaluate` only supports reading values, not executing within the page context.
- Overriding the User-Agent.
- Any tests specific to Chromium or Webkit.

---

# Usage

### Setting up the environment

Cd to this directory and run the following command to setup the venv and install the dependencies:

```bash
bash setup-venv.sh
```

### Running the tests

Run via the shell script:

```bash
bash run-tests.sh --headful --executable-path /path/to/camoufox-bin
```

Or through the Makefile:

```bash
make tests headful=true
```

---