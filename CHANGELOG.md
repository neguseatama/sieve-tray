# Changelog

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
