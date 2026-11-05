# Changelog

## [1.2.0] - 2026-11-05

### Added
- **Up-to-date engines in one screen**: the bundled Sieve Crowd is now
  upstream 0.8.2 (the sha256-pinned character table `chartable_v1.json`
  ships with it via package-data; every vendored file is byte-identical
  to the upstream tag) and the bundled Sieve Redact is upstream 0.9.0.
  The latest Crowd/Redact conversion, verification and receipt work is
  available from the existing anonymize/sanitize screens unchanged.
- **Neutral wording for unobserved formats** (design doc §3.5-1): Lens
  reports a missing optional extractor and a truly unknown suffix as the
  same null observation (measured on Lens 0.20.2/0.21.1 - there is no
  distinguishing signal), so the document detail dialog shows
  "This format was not observed." / 「この形式は観測できませんでした。」
  instead of the raw "Unsupported format: <suffix>" engine text. The
  classification (`engine_unavailable`) and the closed 8-item reason
  vocabulary are unchanged.

### Changed
- **Engine floors**: `sieve-lens` raised to `>=0.20.2` (the first
  release carrying all 13 refusal codes Tray's classification maps to
  detail labels, including `unsupported_namespace`); the full suite is
  measured green on both 0.20.2 and 0.21.1. `sieve-referee` stays at
  `>=1.3.0` (suite measured green on 1.3.0 and 1.5.0). `sieve-scope`
  stays at `>=1.3.0` (the only published release).
- **Referee 1.5.0 follow-up**: the quantifier audit lane surfaces the 7
  certainty-marker vocabulary items referee 1.5.0 added (必然的に /
  不可避的に / 自ずと / おのずと / 疑いようがない / 疑いようもない /
  言うまでもなく) in the audit tab, both report renderings and history
  without dropping rows. Vocab names are engine strings displayed as-is
  (measured: Tray keeps no i18n indirection for them).
- **Crowd history allowlist unchanged**: Crowd 0.8.2 adds no item the
  crowd screen reads (the receipt JSON gains `result.missing_suppressed`
  and `settings.missing_value_policy` only), so no key was added to the
  storage allowlist; table data (header/rows) stays out of the stored
  payload and pre-existing history rows keep loading.

## [1.1.0] - 2026-11-05

### Added
- **The third observation state "unobserved"**: files Tray could not
  observe (the engine refused extraction, the source does not parse, the
  file is unreadable, too large for Tray's own read limit, behind a
  symbolic link, or the required engine/extension is unavailable) are no
  longer invisible or indistinguishable from "clean". They are reported
  with a closed vocabulary of reasons in the results table, the summary
  counts, the saved history and the HTML/Markdown reports, each with the
  note that unobserved means the observation did not establish - not
  that the file is problem-free.

### Changed
- **Crowd run history keeps only display/report fields**: the saved
  payload is now an allowlist (input/output paths, record/risk numbers,
  status/reason, receipt text) instead of the full run summary, so
  anonymized table data (header/rows) is never written to
  `history.db`. Existing records are sanitized on read, and a one-time
  idempotent migration scrubs stored payloads and vacuums the database.
- **Tray's own reads are capped and link-safe**: `.py`/`.txt`/`.md`
  reads stop at the 8 MiB limit (reported as `too_large`), symbolic
  links are neither followed nor read (`symlink_skipped`), special files
  are never opened (`unreadable`), and empty or comment-only sources are
  reported (`not_applicable`) instead of being silently dropped from the
  comparison.

Earlier history: this file starts at 1.1.0; for previous versions see
the git history.
