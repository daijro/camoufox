Diagnostics Added: Post-bootstrap logging (CI)

Summary:
- Added post-bootstrap diagnostics to Windows workflows to capture multibuild and mach output.

Details:
- Logs saved in workflow run workspace:
  - `multibuild_download.log` — output of `python3 multibuild.py --bootstrap ...`
  - `multibuild_bootstrap.log` — output of `./mach bootstrap --application-choice=browser ...`
- Added a `Debug: Post-bootstrap workspace & multibuild logs` step in these files:
  - `.github/workflows/lucid-build.yml`
  - `.github/workflows/main.yml`
  - `.github/workflows/archive/lucid-unified-build.yml`

Current run id: 21383783864 (completed — success for build progression)

Finding (observed in logs):
- During `make bootstrap` the start-shell logs showed a failing `rustup` invocation that used a literal path that doesn't resolve on Windows runners:

    fatal error: command '~/.cargo/bin/rustup target add "x86_64-apple-darwin"' failed

  This was visible when we captured direct multibuild and start-shell logs.

- Packaging did not produce installer artifacts in some runs which led to the uploader message:

    No files were found with the provided path: camoufox-*/obj-*/dist/install/sea/*.zip. No artifacts will be uploaded.

What I changed:
- `scripts/patch.py`: Replaced the hardcoded `~/.cargo/bin/rustup` call with a portable lookup using `shutil.which('rustup')` and a fallback to `~/.cargo/bin/rustup`. If no rustup binary is found, the script now prints a message and skips rust target addition instead of failing the bootstrap.

- Windows workflows (`.github/workflows/lucid-build.yml`, `.github/workflows/main.yml`, `.github/workflows/archive/lucid-unified-build.yml`): Added a `Verify Packages` step that ensures the packaged installers exist after `./mach package`. If missing, the step prints diagnostic logs and fails the job (making the error explicit). Also added an `Upload Build Logs` step (runs `if: always()`) to upload the captured multibuild/start-shell and Chocolatey logs as an artifact for easier debugging.

Next steps:
- Push these changes and re-run the Windows workflows to see if the rustup-related bootstrap errors are eliminated and if packaging produces artifacts. The new `lucid-build-logs` artifact will contain the logs needed for diagnosis if failures persist.
