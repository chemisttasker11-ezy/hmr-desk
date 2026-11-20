# Database encryption (SQLCipher)

The patient database (`hmr.db`) is encrypted at rest with SQLCipher (`sqlcipher3-wheels`).

- **Key**: 32 random bytes in `hmr.key` beside the database. On Windows it is wrapped with DPAPI (tied to the Windows user). On Linux (development and CI only) it is a 0600 file.
- **Recovery key**: the same key as grouped Base32 text with a checksum, shown at setup (Settings > Data protection) and kept visible until the user confirms they stored it. After confirmation it cannot be shown again. "Make a new recovery key" re-keys the database; an interrupted re-key is settled on the next start (`hmr.key.pending`).
- **Existing installs**: a plain `hmr.db` is exported with `sqlcipher_export` to a sibling file, verified (integrity check, schema version, row counts per table), swapped in, and the plain file is overwritten and deleted. Plain `hmr-backup-*.db` and `.migration-snapshots` files are encrypted the same way. A failure before the swap leaves the original untouched.
- **Missing key**: if the database is encrypted and no key works, the engine exits with code 3 and never creates a new key. `engine_main.py --recover-key` reads a recovery key from standard input and re-seals it for the current Windows user.
- **Backup bundles**: format unchanged. The database snapshot inside the passphrase-encrypted `.hmrbak` is plain SQLite, so a restore on a new PC needs only the passphrase; the engine encrypts it with that PC's key on first connect.
- **Tests and automation**: `HMR_DB_KEY` (64 hex characters) overrides the key file.
- **Later**: a first-launch guard for the draft vault can read `status()` in `dbkey.py` without changes to database code.
