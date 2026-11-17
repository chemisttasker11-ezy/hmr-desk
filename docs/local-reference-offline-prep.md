# Private local reference, offline preparation only

This source candidate follows the separately accepted confirmation-safety checkpoint.
Its CI/package/Windows acceptance status must be checked at the exact candidate
commit. It is not merged, deployed or accepted as a clinical release.

## Source and rights

A user-selected Brainstorm PDF stays in its original location. Nothing uploads it,
copies it into the application distribution, adds it to source control, or treats
a subscription as redistribution permission. Registration stores local metadata
(path, byte SHA-256, user-reviewed edition, page count, timestamp, local-use
confirmation). Extracted sections are cached locally. These reference files and
metadata are not claimed to be encrypted. This patch grants no licence rights.

The picker requires explicit local-use confirmation. Replacing an edition requires
registering it again. Deleting/moving/modifying the original makes lookup/opening
unavailable. A local reference is not a substitute for the old-case suggestion
library; no case counts or case index are made from this PDF.

## Entry points and matching

Settings has independent registration and search, available without starting a
patient report or completing an interaction check. The report editor has the same
reference panel. Neither route changes the report or inserts a recommendation.

All search words must occur in a section heading plus the text of one physical
PDF page. This is case-insensitive literal matching, not a diagnosis, synonym
resolver, risk score, currency check or clinical recommendation. A heading-only
match without any query-word match in body text returns no quote. Empty searches
do not return the entire document. At most 20 passages are shown.

Each excerpt is at most 300 extracted characters from one physical page. Spacing
is normalized by extraction; omitted material is marked outside the excerpt.
The physical quote page is distinct from section-start/end pages. Repeated
headings remain separate sections. Edition text is entered from the original by
the user, not inferred as verified metadata. PDF SHA-256 identifies exact bytes;
citation schema version identifies software structure, not clinical validity.

Returned quotes and heading text are rechecked against the exact original page,
not trusted merely because they were present in a cache. Legacy/malformed cache
structures regenerate or fail closed. The original-file button sends only the
hash/page from the renderer, resolves the registered path at the backend,
rechecks bytes in the main process, and opens the existing sandboxed PDF viewer
with #page=N. It does not accept a renderer-supplied path or use a system file
association. The viewer's actual Windows physical-page landing remains unverified.

## Validation boundaries

Synthetic tests cover continuation pages, repeated headings, hash binding,
malformed/modified/missing sources and caches, registry consent, query page
boundaries, production API routes, IPC sender validation, original-page URL,
escaping and no insert controls. Chromium screenshots use a stub renderer and
open callback; they are not packaged Windows acceptance. The supplied reference
has been used only for private parsing checks, never as a fixture or CI asset.

Before release: independent review of this patch, native packaging/CI, isolated
Windows registration/restart/search/original-page acceptance, and clear handling
of any licence conditions remain necessary. This is not medical validation,
full retrieval validation, licensed-source parity or clinical readiness.
