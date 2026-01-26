This PR implements Windows CI improvements:

- Adds pip caching to speed CI runs (`actions/cache` for pip).
- Adds an optional MSVC installation step (gated by `INSTALL_MSVC` env var, default `false`).
- Adds Windows Build Prerequisites documentation to `README.md`.
- Adds an optional MSVC install step (commented/gated) and cleans up build steps.

Changes are on branch `ci/windows-build-improvements`.

Links:
- Issue: (replace with issue number after creation, e.g. `Closes #<issue-number>`)

Notes for reviewers:
- The MSVC install is optional and disabled by default to avoid slowing CI.
- If you'd like MSVC enabled in CI, set `INSTALL_MSVC=true` in workflow or enable manually.

---

To create the issue and PR using GitHub CLI (requires auth):

1. Authenticate: `gh auth login`
2. Create the issue: `gh issue create --title "Windows Build Pipeline Improvements — install prereqs, fix arch, robust packaging, docs" --body-file ISSUE_BODY.md --label ci`
3. Create the PR: `gh pr create --title "ci: Windows build pipeline improvements" --body-file PR_BODY.md --base main --head ci/windows-build-improvements`

If you prefer I can create the issue/PR for you once `gh auth` is configured on this environment or via your GitHub token.
