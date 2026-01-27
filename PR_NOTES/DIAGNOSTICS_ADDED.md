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

Current run id: 21383413241 (in progress)

Finding: Previous Windows runs failed because multibuild did not create a `camoufox-*` source directory; the Verify step exited with "No camoufox-* directory found." I added direct and internal start-shell logging to capture `multibuild` and `mach` output and will paste relevant excerpts below when available.

Next steps:
- Monitor run 21383413241; when it completes I will extract and append the multibuild/mach logs here and recommend targeted fixes.