### Copilot Task: Windows Build Pipeline Improvements

**Objective:**
Enhance the Windows CI workflow to ensure reliable and fast builds for the Lucid project, covering all prerequisite tools and packaging needs.

**Task Steps:**

1. **Add Build Prerequisite Installation:**
   - In `.github/workflows/windows-build.yml`, add steps to install required build tools on the runner using Chocolatey:
     - `make`
     - `aria2`
     - `7zip`
     - `wget`
     - `msitools`

2. **Fix Python Architecture Usage:**
   - Ensure the build command uses `--arch x86_64` (not `x64`).

3. **Make Artifact Packaging Robust:**
   - Update the artifact packaging step so it does not error if some files are missing (log file presence or absence instead).

4. **Update Documentation:**
   - In `README.md`, add a "**Windows Build Prerequisites**" section listing required packages and installation instructions for new contributors.

5. **Optional Enhancements:**
   - (a) Add pip caching to the workflow to speed up repeated CI jobs.
   - (b) Add an MSVC toolchain installation step if C/C++ compilation is required by your build.

**Acceptance Criteria:**
- Workflow runs on `windows-latest` and all dependency/tools install successfully.
- Build does not fail due to missing prereqs.
- Documentation is clear for anyone to set up locally.

---

Please implement the above steps and open a PR referencing this issue.
