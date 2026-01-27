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

Current run id: 21382826667

Next steps:
- When the run completes I will extract and post relevant log excerpts and suggested fixes.