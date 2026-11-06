# Changelog

## [1.4.0] - 2026-11-06

### Added
- **Table observation (`scan`) in the Crowd tab**: pick one CSV (UTF-8 or
  CP932) or `.xlsx` file and Crowd 0.9.0's one-page HTML report of how the
  table currently looks — roles, groups, hidden-character findings; no cell
  values — opens in the system browser. The HTML is Crowd's output byte for
  byte (Tray never post-processes it); it is written to a user-only temp
  file (mode 0600), never enters the history, is swept at the next start
  and removed at exit, and a "Save scan HTML as..." action writes the very
  same bytes to a chosen path. Refused inputs surface through the existing
  closed-vocabulary code wording — no values, no traceback.
- **First-launch guidance and distribution verification**: each release
  now publishes a `SHA256SUMS.txt` list of the three assets next to the
  binaries, and the release workflow attaches a build-provenance
  attestation (`actions/attest@v4`; free for public repositories). The
  README (en/ja) gains a short "First launch" section — macOS "Open
  Anyway", Windows "More info → Run anyway" — plus the SHA-256 check.

### Changed
- **Three-stage coloring of unobserved rows (design §3.2)**: the closed
  8-reason vocabulary is grouped into remedy (amber `#fff4d6`; refused,
  parse_failed, unreadable, too_large, symlink_skipped), environment (the
  v1.3.0 gray `#f0f0f0`; engine_unavailable) and excluded (faint gray
  `#f8f8f8`; not_applicable, empty_input). The row background follows the
  stage in the GUI and the HTML report; the reason text stays in the row;
  the aggregate line shows only when something is unobserved; the
  zero-unobserved reports (HTML and Markdown) stay byte-identical to
  v1.3.0.
- **Input notes shape (design §3.3)**: Crowd's per-input observations move
  to the top of the result details as a short bulleted list under the
  "About the input" heading, without color or icon; they stay hidden when
  there is nothing to note.

## [1.3.0] - 2026-11-06

### Added
- **Crowd 0.9.0 vendored (engine update)**: the Anonymize tab now reads
  CP932 (Windows-31J) CSVs and Excel `.xlsx` workbooks through the same
  engine (`sieve_crowd.tabular.read_input`). The character code is
  auto-detected only — a UTF-8 BOM, then strict UTF-8, then strict
  CP932; anything else is refused — with no encoding UI (design doc
  §3.2). Crowd's stderr-equivalent notices (encoding adoption, sheet
  selection, missing formula caches) surface in the result details of
  the tab and nowhere else: they never enter the table area or the
  history payload (the allowlist is unchanged; 0.9.0 added no output
  items — report.py and inspect.py are byte-identical to 0.8.2).
- **Redact 0.10.0 vendored (engine update)**: the sanitize screens get
  the pixel-limit refusal (images beyond 64,000,000 pixels are refused
  up front with a readable message through the existing error path —
  no traceback) and the wider phone observation (`090ー1234ー5678` /
  `090ｰ1234ｰ5678` — full-width and half-width katakana long-vowel
  marks — are observed and masked like the hyphenated twin). The
  existing text anonymization output is byte-identical (golden mold).
- **Engine "could not observe" folds into unobserved (design doc
  §3.4)**: Scope's `skipped` entries (1.3.1+) land in the unobserved
  list with the engine's own closed vocabulary; `scores: null` pairs
  (H1=0) are handled safely; an out-of-vocabulary reason falls to
  `parse_failed` with the original string kept out of the results;
  Tray's own pre-classification and an engine skip pointing at the
  same path count once (the engine's reason wins). Engines without
  the keys (scope 1.3.0, referee 1.5.x) behave exactly as v1.2.0.
- **Series character-code policy in Tray's own reads (design doc
  §3.5)**: `_read_limited` (the 8 MiB-limited read feeding Scope and
  Referee) now decodes strictly — UTF-8 BOM, strict UTF-8, strict
  CP932 — and anything else is recorded as unobserved `refused`
  (detail `unsupported_encoding`). `errors="replace"` is gone
  (v1.0.0 read with replace; the 8 MiB limit arrived in v1.1.0, the
  strict policy only now — measured on the tags), so a CP932 file
  now yields the same result as its UTF-8 twin and no replacement
  character can leak into a result. UTF-16/UTF-32 BOMs refuse
  outright.

### Changed
- **README alignment**: `README.md` (English) now follows
  `README.ja.md` again — same heading structure, same version; the
  limitations section is unchanged (not extended).
- **Referee `skipped` note (measured)**: referee 1.5.1's `skipped`
  payload lives in its CLI/dashboard layer; the `batch_evaluate`
  library API Tray calls returns no such key, so Tray's text lane
  keeps the v1.2.0 behavior (the key-less branch design doc §3.4
  allows). Folding it in awaits an upstream library key.

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
