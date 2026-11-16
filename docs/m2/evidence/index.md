# Milestone 2 evidence index — live implementation

**Date:** 2026-11-16 (Australia/Brisbane)  
**PR:** https://github.com/chemisttasker11-ezy/hmr-desk/pull/1 (draft)  
**Current implementation HEAD when indexed:** `5cde3c7f532a85949ef74671654a7a42fdd69d88`

## Verified earlier baseline (NOT evidence for the new HEAD)

- Baseline `860a3b689a3c19ea9594969c0410721f9a52891f`.
- [Windows standalone build](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030183) passed engineering smoke on Windows Server 2022.
- [Clinical privacy contract](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43796030164) passed.
- Artifact `14193659931`: engineering ZIP only; manifest digest `05d049100ed086c09b560e7bc8f7e8f25f424cadaea252fd9f96b056793a8abe`. **Not an installer EXE checksum.**
- Clean Windows 11 install, clinical acceptance, owner-approved template and full offline end-to-end evidence: **NOT VERIFIED**.

## Work committed on the existing PR (MIG-01 partial)

| Commit | Action | Evidence level |
| --- | --- | --- |
| `e1e2035dde4655eac59e9ff9928960521499bf27` | Introduce schema version 1 and transactional additive migration | Code committed |
| `4b535a61d69f00137c3a113bc216569114d40191` | Add synthetic migration/rollback/future-schema regressions | Tests committed, result pending |
| `5cde3c7f532a85949ef74671654a7a42fdd69d88` | Include migration tests in Windows engineering workflow | CI running when indexed |

Matching-HEAD CI runs:
- [M2 Windows engineering run 43802231023](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43802231023): **IN PROGRESS when indexed**.
- [Clinical privacy contract 43802231007](https://github.com/chemisttasker11-ezy/hmr-desk/actions/runs/43802231007): **IN PROGRESS when indexed**.

## Gate status and proof still required

- **MIG-01 PARTIAL:** SQLite additive migration now versioned and covered by newly committed tests; JSON contracts, historical multi-version fixtures, workspace rollback and installed-app proofs remain open.
- **MIG-02 OPEN:** guided OneDrive/custom workspace migration with source inventory, pre-move backup and atomic activation has not been accepted.
- **INTAKE-01/02 OPEN:** scanned/rotated original page navigation and field-source confirmation in packaged UI.
- **MED-01/PATH-01 OPEN:** full clinical journey, conflict scenarios, downstream stale proof.
- **TEMPLATE-01/02/03 BLOCKED:** canonical approved DOCX and short/long examples not present in reviewed repo; do not release a generic report as approved.
- **BACKUP-01/DRAFT-01 OPEN:** isolated recovery activation, complete data-scope/ACL/DPAPI proof on Windows.
- **VM-02 OPEN:** clean Windows 11 x64 standard-user full offline install and full HMR E2E.
- **SIGNOFF-01 OPEN:** pharmacist and owner formal acceptance.

**Release:** NOT ACCEPTED. No P0/P1 waiver or silent gate override. Only synthetic inputs are permitted in CI evidence. Identifying SMS is a separate authorised pathway; clinical AI defaults OFF.
