# Medicine reference data foundation

Status: developer foundation, not clinical-release approval. These modules do not
change patient records, prescribing, SMS, the Electron UI, or the existing engine
API. They work on a **separate reference database**, never `hmr.db`. No network
requests occur during app startup or module import. Pharmacist review is required
before using the sig library or matching results in clinical workflows.

## Sources and licence gates

| Source | Purpose and format | Access and reuse |
| --- | --- | --- |
| AMT / NCTS | National medicine concepts, Australian preferred terms and synonyms, generic/brand abstractions, form and grouped strength relationships. Monthly combined SNOMED CT-AU RF2 Snapshot ZIP. | Free access for Australian use after accepting the NCTS/SNOMED and national terminology agreements. Register using your own authorised identity or organisation. Do not bundle releases or derivative terminology in a distribution until the applicable licence permits it. Overseas use or a mobile app requires contacting SNOMED International. |
| PBS | Subsidised listings, PBS item/program identifiers, AMT crosswalks, price-disclosure originator flag, substitution groups and restrictions. Official monthly API CSV ZIP; JSON/CSV REST API also exists. | Public API access is free and needs no login. **Free access is not a verified blanket commercial redistribution licence.** The website copyright terms reserve rights. Confirm the terms for your intended product use/redistribution with PBS before shipping a populated catalogue. |
| TGA ARTG | Registered/listed medicine entries, including complementary medicines, vitamins and supplements. User-exported CSV, with explicit header mapping if needed. | Publicly searchable/exportable, but TGA's current general copyright terms prohibit commercial reuse/retransmission without prior written approval. Obtain applicable written permission or a specific data licence before commercial use. No TGA dataset is bundled here. |
| MIMS / AusDI | Later options for clinical monographs, interactions and richer decision support. | Commercial licences and vendor integration terms required. No price or API entitlement is assumed here. |

AMT is the terminology backbone. PBS is an overlay, not a complete list of all
medicines. ARTG registration/listing does not establish pharmacy stock, actual
marketing, suitability, or clinical efficacy. Not all therapeutic goods supplied
under special access/exemptions appear as ordinary ARTG entries. These sources
together still do not justify an unqualified claim of "every available product".
ARTG-listed does not mean "non-PBS"; cross-source overlap remains unresolved until
an exact, reviewed identifier mapping exists.

Important corrections to common assumptions:

- `originator_brand_indicator=N` does **not** mean generic. PBS defines this as an
  originator designation **for price disclosure**. Preserve it, and the distinct
  `innovator_indicator`, as separate source facts. Generic status stays unknown.
- `brand_substitution_group_id` indicates a publisher-defined equivalence group,
  not automatic authority to substitute for a particular patient. Null means no
  group is supplied. Never group solely by ingredient or brand text.
- PBS can publish local non-AMT identifiers before AMT catches up. Preserve both
  `amt_code` and `non_amt_code`; never assume every PBS code is an AMT concept.
- Current AMT v4 uses concrete strength values and changed relationship types.
  Do not import a v3-only seven-root hierarchy or parse strengths out of names.
- A source licence has its own conditions. Public download availability and this
  repository's code licence do not grant rights over source datasets.

## Repository layout

- `HMR Desk/engine/medicine_data/`: Python standard-library-only reference modules.
- `HMR Desk/engine/medicine_data/sigs.json`: curated draft sig entries.
- `HMR Desk/engine/tests/medicine_data/`: synthetic unit fixtures, built in tests.
- `scripts/medicines/catalog.py`: manual import/search/sig CLI.
- `scripts/medicines/download_pbs.py`: one-shot official PBS bulk downloader.

No runtime dependencies were added. Commands below run from the repository root
with Python 3.10+ (including the project's Python 3.14). Quote paths with spaces.
Use an environment outside the live patient workspace for first validation.

## Quick start: sig lookup without downloading any dataset

```powershell
python scripts/medicines/catalog.py sig --text "BD; with food"
python scripts/medicines/catalog.py sig --text "OD"
```

The first returns a review suggestion, `times_per_day=2`, and full-English text.
The second is unresolved: OD can mean daily or right eye. Neither saves or applies
a prescription. The entire library is a draft that needs the owner's pharmacist
review. Instructions such as crushing, food timing, patch handling, storage and
course completion are **product-specific input phrases**, not universal advice.
They are never automatically attached to a medicine.

### Sig schema and behaviour

139 entries cover frequency, timing and instructions, with 220 recognised
phrases/aliases. Each has an ID, category, aliases, safety classification,
warning, structured fields and patient-facing English where unambiguous.

Structured fields include `times_per_day`, `interval_hours`, `interval_days`,
`times_per_week`, `calendar_months`, `total_doses`, `as_needed`, timing tags,
days of week and instruction tags. An interval is not collapsed into a daily
frequency: "every 12 hours" and "twice a day" remain distinct. Monthly schedules
are calendar months, never a guessed 30 days. Weekly dosing requires exact days;
PRN needs indication, interval and maximum dose confirmed separately.

`parse(text)` matches one exact phrase or explicit semicolon-separated phrases.
It preserves the original text. Unknown input, ambiguous/error-prone aliases,
multiple frequencies or multiple timing constraints return **no actionable
structure and no patient text**. It deliberately does not parse arbitrary
prescription prose or ignore unknown trailing text.

`render(entry_ids, pharmacist_confirmed=True)` renders chosen canonical entries
in full English. Without explicit confirmation it raises. Unsafe legacy IDs are
not renderable even with that flag; resolve them to confirmed canonical phrases
first. All parse results still carry `review_required=true`. The confirmation flag
is an API contract for the future review UI, not an audited clinical sign-off.
`render_structure()` also accepts one exact known structured mapping and rejects
unknown fields or invented frequencies; compound plans use confirmed canonical IDs.

The Commission's November 2024 recommendations prefer terms in full. BD, TDS,
QID, mane, nocte, PRN and stat are limited to written presentations in the cited
guidance, not endorsed as patient-facing digital abbreviations. OD/QD/QOD/QDS,
Q1H/Q4H and similar legacy aliases are retained only to detect unsafe input.
The library's custom phrase list is not a Commission-certified terminology set.

## PBS monthly import (works without an account)

1. Open the current [PBS publications page](https://pbs.gov.au/browse/publications).
2. Copy the **PBS API CSV files** ZIP link for the effective month. Do not guess a
   URL or endpoint version. Do not use old discontinued drug.txt/XML formats.
3. Download one ZIP, then import it using the actual schedule code found in its
   `tables_as_csv/schedules.csv`. The importer accepts only schedules effective
   on or before the local date. Validate the date if importing around midnight.

Example verified on 16 November 2026 (replace with the current publication when
updating, rather than assuming this month forever):

```powershell
python scripts/medicines/download_pbs.py --url "https://pbs.gov.au/publication/schedule/2026/11/2026-11-01-PBS-API-CSV-files.zip?variant=3" --output "$HOME/HMR-Desk-data/reference-downloads/pbs-2026-11.zip"
python scripts/medicines/catalog.py pbs --input "$HOME/HMR-Desk-data/reference-downloads/pbs-2026-11.zip" --db "$HOME/HMR-Desk-data/medicine-reference.sqlite" --release 4753 --source-url "https://pbs.gov.au/publication/schedule/2026/11/2026-11-01-PBS-API-CSV-files.zip?variant=3"
python scripts/medicines/catalog.py search --db "$HOME/HMR-Desk-data/medicine-reference.sqlite" --text "rifaximin"
```

The downloader issues one bulk request, validates the ZIP and atomically replaces
the destination. It does not retry or poll. HTTP 429 is a stop: honour Retry-After
and wait at least 20 seconds before a manual retry. The public REST API's one
request/20 seconds limit is shared across all users. Do not call it per keystroke,
per patient, per product or from multiple background workers. The ZIP path avoids
needing to guess the current REST API version. There is no embedded API key.

The importer validates actual v3-style CSV headers, schedule codes and effective
dates; retains **all CSV tables** in `source_row`; and exposes one autocomplete
record per `(program_code, pbs_code, li_item_id)`. Restriction text remains in
`restrictions`, linked via `item-restriction-relationships`, with additional text
fragments in the related tables. Do not display one fragment as a complete
eligibility rule. Treat raw HTML as data: never inject it into the UI unsanitised.
This foundation stores the relationships; it does not adjudicate PBS eligibility.

### Real validation evidence

The committed loader/downloader were run against the official November 2026 ZIP:

- Schedule code: `4753`, effective `2026-11-01`.
- ZIP size: `4,521,523` bytes.
- SHA-256: `3631dd5f3d593f1cb99f8be77a669e03972e65cd9e4c91e9076c63d480b12dbe`.
- Imported listings: `15,365`.
- Search by brand and generic worked; all source CSV tables were retained.
- The ZIP, raw records and generated SQLite database are deliberately **not**
  committed. Tests use synthetic shapes, not a redistributed PBS/AMT dataset.

## AMT download from the NCTS syndication API (monthly update)

`scripts/medicines/download_ncts.py` fetches the newest SNOMED CT-AU (AMT) RF2
Snapshot from the NCTS National Syndication Server. Steps it performs, in order:

1. Request an OAuth2 access token (`grant_type=client_credentials`) from
   `https://api.healthterminologies.gov.au/oauth2/token`.
2. Read `https://api.healthterminologies.gov.au/syndication/v1/syndication.xml`.
3. Pick the newest `SCT_RF2_SNAPSHOT` entry (by release date in the entry).
4. Download its ZIP with `Authorization: Bearer <token>`.
5. Check the ZIP size and SHA-256 against the feed (`length` and
   `ncts:sha256Hash`). A mismatch discards the file. Only then is it saved.

Redirects to any host other than `api.healthterminologies.gov.au` are refused, so the
token is never sent elsewhere. Sources for the flow: the NCTS implementer hub
([common tasks](https://implementer.digitalhealth.gov.au/ncts/common-tasks-when-integrating-with-the-ncts)),
the official [NCTS syndication client](https://github.com/AuDigitalHealth/ncts-syndication-client),
and a live check that the token endpoint answers `invalid_client` to a bad credential
while an unknown path returns 404. It has not yet been run with the real credential.

### Client ID and client secret setup

1. Sign in to the NCTS portal (healthterminologies.gov.au) with the NCTS account for
   this project (`<project NCTS account email>`) and open **Clients** (top right). Create
   a client credential for "HMR Desk".
2. The Client ID and Client Secret must never be committed, pasted into chat, or put
   on a command line. They are kept in the password vault entry **"NCTS syndication
   API client (HMR Desk)"** (username = Client ID, password = Client Secret).
3. For the importer, put them in a local env file outside this repository (the script
   refuses a file inside the checkout):

```text
# %USERPROFILE%\HMR-Desk-data\secrets\ncts.env
HMR_NCTS_CLIENT_ID=your-client-id
HMR_NCTS_CLIENT_SECRET=your-client-secret
```

   Restrict the folder to your Windows account. As an alternative, set the same two
   variables in the environment of the process, for example from a secret store. The
   importer reads `HMR_NCTS_ENV_FILE` or `--env-file` if the file is elsewhere.

### Run

```powershell
python scripts/medicines/download_ncts.py --output-dir "$HOME/HMR-Desk-data/reference-downloads"
# prints release (YYYYMMDD), file path, size and the verified SHA-256
python scripts/medicines/catalog.py amt --input "$HOME/HMR-Desk-data/reference-downloads/ncts-sct-au-YYYYMMDD-snapshot.zip" --db "$HOME/HMR-Desk-data/medicine-reference.sqlite" --release YYYYMMDD --source-url "https://api.healthterminologies.gov.au/syndication/v1/syndication.xml" --accept-ncts-licence
```

The download is one sequential run of a ZIP of roughly 400 MB. Existing output files
are not overwritten. Tests use synthetic feeds only (`test_ncts_download.py`).

### Licence and access conditions

- **Annual Statement of Usage:** NCTS access depends on completing the annual survey
  each June. Missing it can lose access. Put a reminder in the owner calendar.
- **Use in Australia:** the licence answers recorded for this account were "No" to use
  outside Australia. The restriction is on how the data is used. These terms do not say
  which machine may perform the download. Use the data, and the built database, only
  within the licence; check the current NCTS and SNOMED affiliate terms before any use
  or transfer outside Australia.
- The `--accept-ncts-licence` flag records the operator's precondition, not proof of a
  licence. Do not bundle the ZIP or derived terminology in a distribution.
- NCTS also publishes official Java and .NET syndication clients
  ([ncts-syndication-client](https://github.com/AuDigitalHealth/ncts-syndication-client)).
  They are an alternative to this script; this script avoids a JVM dependency.

## AMT setup and import (manual download alternative, owner action required)

1. Register/sign in to the [NCTS portal](https://implementer.digitalhealth.gov.au/ncts/licensing)
   under your own authorised identity or organisation and accept the agreements.
2. Download the current **combined SNOMED CT-AU + AMT RF2 Snapshot** release. Keep
   the original ZIP in local reference-downloads. This implementation does not
   scrape sign-in, create your licence, or fabricate medicine data.
3. Confirm release notes/model compatibility and use the release's YYYYMMDD date:

```powershell
# Replace these placeholders with your actual local ZIP and release date.
python scripts/medicines/catalog.py amt --input "C:/local/path/your-licensed-release.zip" --db "$HOME/HMR-Desk-data/medicine-reference.sqlite" --release YYYYMMDD --source-url "https://implementer.digitalhealth.gov.au/ncts/licensing" --accept-ncts-licence
```

Replace the source URL with the exact release landing page used for your download
(without credentials or signed-token query strings). The example uses the licensing
page as a setup reference only.

The licence flag records the operator's explicit precondition, not proof that a
licence exists. The owner is responsible for accepting the applicable agreements.
FHIR/NCTS APIs are an alternative future adapter; this PR implements the RF2
route only, which permits offline autocomplete after import.

The importer reads active Snapshot concepts, descriptions, Australian language
refset preferences, seven-box memberships, inferred relationships and concrete
strength relationships. It handles consolidated simple-refset files, selects
Australian preferred terms rather than US/GB preferences, retains aliases, and
rejects missing Australian preferred terms, unsupported schemas, empty imports
and release-date/filename mismatches.

Autocomplete rows preserve concept ID, box type (MP/MPUU/MPP/TP/TPUU/TPP/CTPP),
complete preferred term, explicit brand/form where modelled, strength role groups
(including substance, value and unit IDs) and raw relationships. Generic names
for branded rows are populated only when there is a single exact nearest generic
ancestor reachable through imported box concepts. Ingredient and precise-
ingredient names are preserved separately as attributes, never falsely joined
into a generic medicine name. Missing/inherited properties stay null. A future
terminology resolver can add complete ancestor traversal through non-box nodes.
Never interpret null as absence of an ingredient, strength or form.

This loader has **synthetic RF2 tests only**, not a full licensed AMT release
validation. Run it on the owner's actual release and review output before UI
integration or clinical use. Large Snapshot ZIPs may take minutes and substantial
memory; this is a manual maintenance job, not an app startup task.

## ARTG import (export and commercial permission needed)

Use the [ARTG visualisation tool guide](https://www.tga.gov.au/products/regulations-all-products/about-australian-register-therapeutic-goods-artg/about-artg-search-visualisation-tool)
to export **medicine** details, not the whole mixed devices register. Full ARTG
exports can require four therapeutic-type exports; a summary export may omit
ingredients/form. Only active medicine rows are accepted into autocomplete.
The source CSV must include ID, product name, therapeutic type and status.
If these are absent, export full details or provide a checked column mapping.

```powershell
python scripts/medicines/catalog.py artg --input "C:/local/path/artg-medicines.csv" --db "$HOME/HMR-Desk-data/medicine-reference.sqlite" --release "export-YYYY-MM-DD" --source-url "https://www.tga.gov.au/resources/artg"
```

Default headers are `ARTG ID`, `Product Name`, `Therapeutic Type`, `ARTG Status`,
with optional `Good Name`, `Active Ingredient`, `Dosage Form`, `Product Category`.
Exports can vary: `--column-map mapping.json` accepts logical keys `id`, `name`,
`type`, `status`, `good_name`, `ingredients`, `form`, `category` mapped to the
actual header names. For example `{"id":"ARTG Id","name":"Product name"}`.
Check the contents, not just successful import. Conflicting rows with the same ID
are rejected for explicit consolidation; they are not silently overwritten.
No live ARTG export has been tested in this PR. Only synthetic fixtures are used.
No SOAP integration is claimed: the documented user CSV export is the supported
route. A missing ARTG medicine is not proof it cannot legally be supplied.

## Database, updates and rollback

`medicine` holds source-specific autocomplete records. `source_row` retains raw
PBS/ARTG tables; AMT relationship data is preserved in the medicine detail JSON.
`source_release` records source, release, import UTC timestamp, input SHA-256,
source URL and row count. SQLite `user_version=1` guards schema compatibility.
No patient data belongs in this database. Source IDs are strings, not floats.

Imports replace only their own source in one SQLite transaction. A malformed,
empty or failed import leaves that source's previous snapshot intact. Keep the
original downloaded archives and back up the reference DB before a monthly run.
For strongest operational rollback, import into a **candidate copy** of the DB,
review counts, releases and known generic/brand searches, close readers, and swap
it into service only after approval. Retain the prior DB for rollback. There is
no scheduler or updater enabled by this PR and no deletion of download archives.

Recommended monthly sequence:

1. Check licences/permissions and release notes; obtain effective releases.
2. Back up the reference DB, import AMT into a candidate copy.
3. Import the current PBS ZIP into that same candidate; check exact AMT links,
   nulls, local identifiers, row-count differences, restrictions and withdrawals.
4. Refresh ARTG medicine exports only within permission; review active/status
   handling, duplicate rows and header mappings.
5. Run tests and spot-check known brands, strengths, forms and older withdrawn
   records. Review sig changes separately with a pharmacist.
6. Promote the candidate manually and preserve provenance and the prior DB.

Absent from a source is **unknown**, not a negative subsidy/availability flag.
A PBS source record means listed for that schedule, not that an individual patient
qualifies. Data age and source release must be visible beside future UI results.
Cross-source merging is not automatic. Search results preserve their source/code
and use parameterised SQL with escaped wildcard input.

## Tests and next build sequence

```powershell
python -m unittest discover -s "HMR Desk/engine/tests/medicine_data" -v
```

Tests include RF2 Australian dialect selection and concrete strengths, PBS null
and originator semantics, restriction retention, full-snapshot idempotence and
rollback, future-effective schedule rejection, malformed headers, ARTG filtering,
patient DB protection, unsafe sigs, unknown text, conflicts and render confirmation.

Next: owner NCTS registration and licensed-release import validation; permission
checks for distributed PBS/ARTG content; pharmacist review of sig entries; then
wire a read-only local search adapter into the engine and a user-reviewed
selection UI. Keep exact selected IDs and original referral text. Only after that
add report-template rendering and reconciliation workflows. No automated dosing,
substitution, eligibility assessment, interaction engine, report sending or claims
are enabled by this foundation.

## Primary references (checked 16 November 2026)

- NCTS licences: https://implementer.digitalhealth.gov.au/ncts/licensing
- AMT/NCTS FAQs: https://implementer.digitalhealth.gov.au/ncts/faqs
- NCTS APIs: https://implementer.digitalhealth.gov.au/ncts/ncts-apis
- AMT model: https://implementer.digitalhealth.gov.au/system/files/documents/dh-4181-2025-australian-medicines-terminology-model-specification-v1.1.pdf
- AMT v3/v4 migration: https://www.healthterminologies.gov.au/library/AMT-v3-to-v4-change-summary-2.pdf?_filename=AMT-v3-to-v4-change-summary-2.pdf
- AMT refsets: https://confluence.hl7.org/spaces/HAFWG/pages/220695053/NCTS+ValueSet+Definitions
- PBS API and limits: https://data.pbs.gov.au/api/pbs-api.html
- PBS public access: https://data.pbs.gov.au/api/api-public.html
- PBS downloads: https://pbs.gov.au/browse/publications
- PBS data dictionary: https://data.pbs.gov.au/download/api/files/PBS-API-V3-Data-Dictionary-v3-8.pdf
- PBS copyright: https://www.pbs.gov.au/info/general/copyright
- TGA export guide: https://www.tga.gov.au/products/regulations-all-products/about-australian-register-therapeutic-goods-artg/about-artg-search-visualisation-tool
- TGA copyright: https://www.tga.gov.au/about-us/using-our-website/copyright
- Safe terminology: https://www.safetyandquality.gov.au/resources/recommendations-safe-use-medicines-terminology
- Full November 2024 recommendations: https://www.safetyandquality.gov.au/sites/default/files/resources/attachments/recommendations-for-safe-use-of-medicines-terminology.pdf
