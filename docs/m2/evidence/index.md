# Milestone 2 evidence index (PR #1, draft)

**Date:** 2026-11-16 (Australia/Brisbane)
**PR:** https://github.com/chemisttasker11-ezy/hmr-desk/pull/1 (draft, not merged)
**Code head this index describes:** `0a0d5545911495c0eef6ac85e774fec733a562ff`
(later commits to this branch that touch only `docs/` do not change the code or CI result below)

## CI for the code head (all synthetic inputs only)

| Workflow | Run | Result |
| --- | --- | --- |
| M2 Windows standalone (windows-2022 build, installed-smoke on windows-latest) | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43827306051 | Success |
| M2 fast synthetic backend regressions | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43827306126 | Success |
| Clinical privacy contract | https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43827306303 | Success |

The previous fully green head was `e6907fa26a0fcbb23103e3c07af76d8cd61af932` (run https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43821014599). The earlier index described commit `5cde3c7`, which is superseded.

CI hosts are GitHub-hosted Windows Server runners, not a clean Windows 11 standard-user machine.

## Changes since e6907fa (audit follow-up)

| Area | Change | Regression tests |
| --- | --- | --- |
| Provenance | Clinical review v2 stores a source page per field (conditions, allergies, medicines, observations); the legacy single `source_page` is still read | `test_clinical_review_pages.py` |
| Backup | Approved template folder and history are included in the encrypted backup; settings are in `hmr.db`; `app-config.json` and the API token are excluded on purpose | `test_backup_template.py`, `restore-activation.test.js` |
| PDF review | PDF opens in a sandboxed bundled viewer window, with no Word or file association needed; Word stays optional | `report-preview-bundled.test.js` (static check of `main.js`) |
| Rollback | Restore activation records a pending-health state; automatic rollback after repeated unhealthy launches, a prompt on engine start failure, and a Settings rollback button | `restore-activation.test.js` |
| Template tables | Generated tables copy the approved template table formatting; generic grid only when the template has no table | `test_template_table_format.py` |
| Release traceability | `installer-manifest.json` records `git_sha` (checkout), `checkout_merge_sha` and `pull_request_head_sha` | CI manifest step |

## Not proven by CI (still open)

- **VM-02:** clean Windows 11 x64 standard-user install and full offline end-to-end run: NOT VERIFIED. This is the owner's test.
- **TEMPLATE-01/02/03:** the real owner-approved HMR DOCX and short/long examples are not in the repo. Reports from the synthetic template are not approved output.
- **SIGNOFF-01:** pharmacist and owner acceptance: OPEN. Any approval statement in the PR description is unverified text, not recorded evidence here.
- **MIG-01/02, INTAKE-01/02, MED/PATH, A11Y-01, PERF-01:** see `docs/m2/issues.md`.
- The post-activation rollback has unit tests only; it has not been exercised in a packaged app on Windows 11.
- The build artifact is an unsigned engineering build and not a clinical release.

**Release:** NOT ACCEPTED. No gate has been waived.
