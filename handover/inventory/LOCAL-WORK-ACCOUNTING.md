# Local work accounting (code only)

Compared against live origin at main 46d7df2457a34a866413c3dd8e6166fc0c823fe6. Comparisons are by file hash or line set. Nothing here was run, and nothing is accepted for clinical use. Source preservation is not acceptance.

| Item | Finding | Where preserved |
|---|---|---|
| Candidate worktree (PR29 head 5c9b486 + compat + held + renderer wording, including two new test files) | Tracked diff matches the compat and held patches line for line | Branch `wip/pr29-candidate-nov21` (07a6f38, then the notes commit 8a83fa2) |
| Wired original-builder adapter v3 + template-review aid v2 | Main-based, separate from the PR29 line | Branch `handover-renderer-review-aid` (6c3d87e) |
| Local clones cand-07e/64a/faf/rg2/v6, manifest-184, rebuild-* and qualify-8e78795 | Committed heads on origin. Tracked changes empty. Untracked content was only generated build output, with one exception (the package-lock diff). | Nothing further |
| rebuild-fixed and rebuild2 untracked sets | Every blob already exists in some origin commit (historical snapshots) | On origin |
| Older divergent local working copy, 19 source files | Not on origin. Based on an unrelated root (b0a0a86). Differs from main by about 100 to 2,400 changed lines per file. | Branch `wip/local-m2-divergent-snapshot` (09545ee). UNMERGED, not for main. |
| Unrelated root b0a0a86 (the same repo as the row above) | Of about 300 tracked blobs, 298 are identical to origin objects and 2 are unique | The 2 unique files (`engine/db.py` and `engine/test_referral_identity.py`) are preserved on that same branch |
| rebuild-297e780 `desktop/package-lock.json` | Real local change, only `"peer": true` flag churn from another npm version | Exact diff in this folder: `rebuild-297e780-desktop-package-lock-peer-flags.diff`. Not applied. |
| Brainstorm-derived reference tables (`engine/assets/` in cand-07e and scratch-reftest) | Two files: tables JSON 500,687 bytes, sha256 FB0E52A19F038CE053EE79F446B222C12E90848B8B0DEFAE2149992A0A480B8E; manifest 138 bytes, sha256 AE80009DD4678624B00E1D383C6514223AF9DDB4531A73F11F27D97855DD8CAC. Earlier "directory empty" statements were wrong. | LOCAL ONLY AND PRIVATE. Never published. Listed as a dependency only. |

Excluded by role: virtualenv folders, `engine/build/` output, caches, profiles and runtime data.

Limits: the unique files were scanned for personal data and secrets by line matching only. None found (matches were variable names). The older line has not been run. A fresh clone cannot exercise the original report builder or the reference-table features without the private assets listed in HANDOVER section 6.
