# Standalone release contract (mandatory; Milestone 2 not accepted)

**Status: NOT YET STANDALONE.** Do not market, merge, or ship as production-ready.

## Required before accepting Milestone 2

- [ ] Windows x64 installer includes Electron frontend and a bundled engine executable (or embedded private Python runtime), all Python wheels, templates, reference assets and PDF utilities; no system Python, pip, Node or Claude profile required.
- [ ] Startup launches, health-checks and stops the local engine automatically, with safe process ownership and actionable error handling.
- [ ] All application file paths resolve from installed resources or user-selected data directory; no OneDrive or developer home directory assumptions.
- [ ] Intake and referral PDF extraction operate from bundled modules and dependencies, including scanned documents and validation of uncertain fields.
- [ ] Interview preparation, medication reconciliation, pathology handling, manual clinical findings, report generation and local report preview are complete with AI switched off.
- [ ] Existing approved HMR DOCX template is bundled and rendered faithfully; the current generic DOCX renderer is a temporary development implementation, **not accepted as final**.
- [ ] DOCX-to-PDF export works without a Claude skill or a separately installed Office/LibreOffice requirement, or a supported bundled converter is supplied.
- [ ] Reference search and the findings library use bundled, licensed resources; never silently use external user-profile skill files.
- [ ] Offline startup and core patient workflows pass on a clean Windows virtual machine without any developer tools.
- [ ] Installation, upgrade, database migration, backup/restore and rollback are verified without losing patient data.
- [ ] Security: no unauthenticated patient file access, clinical AI off by default, local encryption and privacy threat assessment.
- [ ] Clinical: synthetic HMR cases cover conflicting actual use, uncertain medicines, renal impairment, pathology units and report formatting.
- [ ] Third-party MIMS/PPA/SMS features are explicitly optional with accurate status; core work remains available when disconnected.
- [ ] Full desktop end-to-end tests, signed release artifacts and installer smoke tests pass.

## No false completion claims

Milestone 2's current commits provide a manual foundation only. They do not
satisfy this contract. Missing bundled extraction assets must be replaced with
working implementations, not just error messages. No milestone 3 clinical
feature expansion until standalone gaps are closed.
