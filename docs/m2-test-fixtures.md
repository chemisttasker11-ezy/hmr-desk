# Synthetic acceptance fixtures

No patient documents, names, credentials or records are committed. Existing synthetic fixtures in `HMR Desk/engine/test_manual_foundation.py` cover dose discrepancies, unconfirmed medicine, OTC, cessation and duplicate-name flags. `test_clinical_privacy.py` covers the clinical AI identifier exclusion boundary. `test_service_static_security.py` checks local HTTP cannot serve a patient PDF. `test_app_paths.py` covers writable data/workspace paths and version-only engine startup.

Outstanding mandatory fixture classes (NOT RUN): scanned PDF and OCR uncertainty, rotated and corrupt PDF, complete pathology units/dates/source, multi-page interview, long/short owner-approved reports, signed version history, Windows Unicode path, encrypted backup corruption and restore. Fixtures must be generated using synthetic names, and screenshot/test logs must contain no real identifying details.

Never substitute the `brainstorm V2.0.pdf` for an approved HMR Word layout. It is a clinical reference and needs current-source validation before any prescribing-related logic.
