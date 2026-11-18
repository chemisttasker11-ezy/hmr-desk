# HMR Desk source

HMR Desk is a Windows desktop application and local Python service for medication-review workflows. The repository contains source code, not a patient workspace, credentials, clinical templates, or the external report-building skill. Some features require separate local setup below.

## Windows setup

Install Node.js with npm and Python 3.14 for Windows. In PowerShell, from the repository root:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location desktop
npm ci
Set-Location ..
```

The engine uses the repository root as its workspace; keep `HMR Desk/engine`, `scripts/intake`, `Android_SMS_Integration`, and the three helper directories at their current relative paths. Start the engine in one PowerShell window:

```powershell
Set-Location '<repository-root>\HMR Desk\engine'
& '<repository-root>\.venv\Scripts\python.exe' service.py
```

In another window, run `npm start` from `desktop`. The app creates `%USERPROFILE%\HMR-Desk-data\app-config.json` on first launch. Quit the app and edit its `base` value to the absolute repository root using JSON-escaped backslashes; leave `api` as `http://127.0.0.1:8767` and `tokenFile` pointing to the engine's generated `api_token`. Restart the app. Optionally set `sheetUrl` to your own spreadsheet URL. The app control endpoint uses localhost port 8768. Keep the generated tokens and all local data private.

In Settings, enter the pharmacist name, contact and location. The included clinic mappings are empty: populate `HMR Desk/engine/clinics.json` and `scripts/intake/gp_clinics.json` locally if needed; do not commit practice data. The PPA helper ships with blank pharmacist fields in `PPA Claim Helper/content.js`; configure them locally before use. Sign in to external portals yourself. SMS requires a separately configured Android SMSGate bridge and Tailscale connection; no credentials or phone configuration are supplied.

## External requirements and limitations

Report extraction, creation and related AI workflows also depend on the separately installed Australian HMR report skill at `%USERPROFILE%\.claude\skills\australian-hmr-report`. Its `scripts` must provide `extract.py`, `build.py`, `make_interview.py`, `word2pdf.ps1`, `example-spec.json` and, for similar-case lookup, `find_cases.py`. Obtain and configure that skill separately, including its own dependencies and appropriate non-patient template. This repository does not provide it. PDF extraction may use Poppler `pdftotext` on PATH; scanned referrals need the Windows OCR PowerShell helper. Word-to-PDF conversion requires Microsoft Word. The interview pack expects a locally supplied `TEMPLATES\PPA Consent.pdf` or `.docx`. Optional AI features require their separately configured command-line agents and accounts. Without these external components, affected features cannot be assumed to work.

The Windows installer built by `npm run dist` in `desktop` packages the Electron app only. Python, the engine service, helper scripts and external dependencies must also be installed and configured. The engine creates its local database and API token in `%USERPROFILE%\HMR-Desk-data`; `HMR_DATA_DIR` and `HMR_DB` can override its data locations. Patient folders and outputs remain local and must not be committed.

## Development

Run `npm test` from `desktop`; `npm run smoke` exercises the Electron fixture and `npm run dist` builds the Windows installer. The Python tests are in `HMR Desk/engine`; run the desired `test_*.py` script from that directory with the virtual environment active. Some scripts exercise environment-specific integrations and require additional fixtures. The mock API can be started with `node dev/mock-api.js` from `desktop`; set `HMR_API=http://127.0.0.1:8767` and `HMR_TOKEN=mock` before starting the desktop app. Do not expose a live patient database to tests.

### Offline suggestion library availability

The current engine looks for local suggestion inputs under its application resource root,
`assets/references`: `case-index.jsonl`, `finding-library.md` and `brainstorm-index.md`.
`brainstorm-v2.pdf` is optional. None of that reviewed reference corpus is supplied by this
repository. The application-owned `drug_classes.json` mapping is packaged separately; it
is not a substitute for the missing library or a validated clinical ruleset.

If required inputs are missing or unreadable, the suggestions endpoint returns an explicit
503 unavailable error. The evidence-context endpoint remains usable. Do not treat source
regressions with synthetic fixtures as evidence that a production suggestion library is
installed or clinically validated. Do not copy a private case index, patient-derived files,
or licensed references into the repository or a distributable. Any future resource source
needs a separate provenance, privacy and distribution-rights review before use.
