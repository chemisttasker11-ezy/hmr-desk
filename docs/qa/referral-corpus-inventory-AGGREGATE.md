# Private real-referral engineering census — non-identifying aggregate

Date: 22 November 2026 (Australia/Brisbane). Owner-authorised corpus: Google Drive **HMR Ongoing / Declined-Exp / Declined and Expired**. These are real source-file observations, **not** a field-accuracy gold standard or Windows installed-app clinical acceptance.

## Data custody and document inventory

- 65 PDFs from Declined, 49 from Expired: **114/114 original raw PDF bytes opened successfully**, inspected read-only in a private local workspace.
- **706 PDF pages**: 569 pages with at least 25 native extracted characters; **137 native-text-sparse pages**, all image-backed; 184 pages with raster imagery covering at least 60% of the page; 203 pages with one or more PDF images.
- **47 pages with substantial raster imagery and native PDF text** (image coverage at least 20%). All **47** are now flagged by the corrected page audit; the previous five-overlapping-words rule flagged **zero** in this private set. This is detection sensitivity against an image/text layout definition, **not evidence the underlying OCR words are correct**.
- 0 rotated pages and 0 PDF FreeText annotations detected in the cohort. No assumption that these files are unmodified or contain no flattened text.
- The earlier Drive provider text preview gave 98 nonempty and 16 empty responses. These are distinct from page-level native-PDF metrics.

## Production parser baseline, on private real PDF bytes

The repository referral parser (`scripts/intake/intake.py`, `referral.py`, `referral_geometry.py`) was invoked locally on all **114** originals, without creating patient records. Counts are *unverified proposals and warning categories*, never independently validated field truth.

| Metric | Documents or proposals |
| --- | ---: |
| Classed as referral | 94 |
| Classed as GP response | 3 |
| Classed as other | 17 |
| Clinical-summary layout | 67 |
| HMR-form layout | 22 |
| Unknown/scan/other layout | 24 |
| Historical completed-report layout | 1 |
| At least one medicine row proposed | 87 documents |
| No medicine row proposed | 27 documents |
| Medicine rows proposed | 847 rows |
| Proposed rows containing some directions | 463 rows |
| Unattributed-directions review warning | 41 documents |
| Unparsed-section review warning | 80 documents |
| Geometry-based whole-table pairing succeeded | 6 documents |

Patient identity proposal coverage was: name 92, date of birth 89, GP 91, GP provider 89, Medicare 87, patient phone 88, referral date 78, address 83 (all out of 114 documents; may be absent or unreliable and must be independently verified).

A small **12-page** offline OCR diagnostic on text-sparse source pages recovered nonempty text from 4 pages; 8 yielded insufficient text or a local image/OCR failure. This **does not** score character or medical-field accuracy and cannot be extrapolated to the 137 sparse pages. The prior larger OCR batch exceeded the runtime budget; individual-page timeout/exception isolation remains a performance gate.

## What production changes are actually informed by this corpus?

1. **Confirmed bug**: mixed image/native-text detection missed 47/47 mixed pages when many text words overlapped the raster. Fix: both text overlays on scanned images and unread-image regions now produce a source-review warning; different error categories remain explicit.
2. **Safer OCR review**: on mixed PDFs of up to ten pages, run the existing **local** Windows OCR as an independent, visibly unverified comparison to native extracted text. Never splice it into drug, DOB or GP fields or infer missing directions. If OCR is unavailable, abstain and show the original visual review warning. Scanned/sparse pages use the pre-existing local fallback.
3. **Scope**: no changes to Pathology PR #39. No clinical inference, automated verification, report signoff, or modifications to original PDF bytes.

## Accuracy and release decision

- Independent source-to-pixel labels: **0**. Field-level precision/recall and exact directions accuracy: **NOT MEASURED**.
- Patient-separated sealed holdout, two-reader adjudication, and complete owner-machine **500+** historical folder: **NOT AVAILABLE / NOT VALIDATED** in this runtime.
- Windows non-admin offline owner-machine app installation and final DOCX/PDF inspection: **NOT ACCEPTED**.
- No raw or personally identifiable filenames, extracted text, clinical values, patient hashes, screenshots, image crops or reference documents are committed to this PR.
- **DRAFT, CLINICAL RELEASE HOLD**. CI checks validate fictional behaviour; they cannot replace independently adjudicated real cases.
