# Changelog

## [2.2.0] - 2026-11-14

### Added
- **File list and check code (`manifest`)**: list a folder into a
  handoff receipt - every regular file as path/bytes/sha256 in
  relative POSIX form sorted by UTF-8 name bytes (NFC never applied,
  a name that is not valid UTF-8 rides as path null + path_hex),
  duplicates confirmed by real byte comparison, and the whole-folder
  checksum as the hash tree of docs/manifest-format.md §1.
  `--against` diffs a folder into the closed five states
  (same/changed/removed/added/moved, moved pairs bound per sha group
  with one ambiguous_move per multi-candidate group). The receipt
  keeps the 2.1.1 frame (receipt_version 1) and is written last; a
  run without the key stays byte-identical in shape.
- **Check code (`--key-file`)**: gate/cohort/manifest/pack share the
  optional key file - the receipt gains the check_code section
  (key_id = the first 8 HMAC bytes in hex, check_code = HMAC over the
  whole-folder checksum and the canonical receipt body,
  docs/manifest-format.md §2). `verify` gains `--key-file` and
  `--root`, adds exactly two not_verifiable reasons
  (`code_key_missing` / `code_key_mismatch`) while the file-list
  check keeps running and its results still land in items, and keeps
  the 0/1/2 exit codes and the published vocabulary; a real
  difference still dominates not_verifiable, so the list results are
  never hidden.
- **Rename and audit-names**: `rename` plans by default and never
  touches the source - `--apply` builds the renamed copy at
  <out>/renamed (the rule fields are closed - seq / seq:width / stem
  / ext / hash8 / parent - and collisions are detected at the plan
  stage over exact + casefold + NFC against each other and the
  existing directories); `audit-names` audits files AND directories
  with the closed 8 symbols and reports path + symbol only. The
  handoff carries the rule, the counts and the mapping hash only -
  the names stay in local/rename-plan.json
  (docs/rename-procedure.md).
- **Pack and unpack**: `pack` writes the deterministic zip (entries
  in bare-path byte order, 1980-01-01 00:00:00 stamps, ZIP_STORED by
  default, --deflate on file entries only) at `-o` itself next to a
  handoff/pack-receipt.json carrying zip_sha256 and the
  manifest-identical whole-folder checksum; `unpack` runs every
  safety check (absolute path, `..` component, drive letter, and
  collision over exact/casefold/file-inside-file) BEFORE creating
  anything and refuses with zero extraction (exit 1, the receipt
  still written); the roundtrip is byte-identical including empty
  directories.
- **verify.html (`--verify-page`)**: manifest/pack can write the
  self-contained handoff/verify.html BEFORE the receipt and record
  its sha256 in the optional verify_page section - the file list is
  embedded as escaped canonical JSON (a file name cannot close the
  script block), the SHA-256 is a pure-JS core checked against 4
  known values, and the receiver picks a folder (webkitdirectory)
  and reads every file through Blob.slice in 1 MiB chunks; same /
  changed / missing / extra is shown on screen only in plain ja and
  en - no network, no external references, and the check-code
  verification stays with Sieve Tray's verify.
- **Draw (`draw`)**: a verifiable draw over a roster - key(x) =
  SHA-256(UTF-8(seed) || NUL || x), the items ordered by key bytes
  and dealt round-robin into k groups (--groups, or --size so the
  last group can be short); the result with the names lands in
  local/draw-result.json (written before the receipt) and the
  receipt carries the roster hash, the public seed, the parameters
  and the result hash - never the names. docs/draw-procedure.md
  spells the procedure byte by byte with two measured known values
  (KV-D1/KV-D2) and the seed warning sentence.
- **The PDF clause**: the Gate document lane short-circuits a PDF to
  unobserved / engine_unavailable (detail
  pdf_visible_extraction_disabled) BEFORE any engine.observe call,
  regardless of pypdf presence - pypdf's visible extraction ignores
  the 3 Tr render mode, so observing a PDF is where the invisible
  text would start to leak.
- **GUI**: the sidebar grows to twelve pages - the three new pages
  (en: Manifest & Check Code / Rename / Draw, ja: ファイル一覧と照合コード /
  名前の整理 / 抽選・班分け) run the real engines behind the same
  manners (a description written from the actual behavior, a tooltip
  on every part, a placeholder in the result field), the scan
  operation row shows on the scan pages only, and the settings ride
  the menu as a PreferencesRole action (macOS relocates it into the
  application menu, Windows/Linux keep it in the window menu). The
  new pages render uncut at the 880x560 minimum under ja/en and a
  dark palette, and last_page restores them too.
- **README and docs**: the Gate/Cohort sections are rewritten for the
  general software-manual style (the old technical paragraphs moved
  verbatim into docs/receipt-reference.md with one link line in each
  README), the three new features get sections in the same four
  manners (what it does, up to 3 numbered steps, one command block,
  one docs link), and the screenshots are re-shot offscreen at
  1042x900 for both languages (8 shots) with the icon at width 96.

### Changed
- **Lens extra**: the dependency is now
  sieve-lens[html-css-full]>=0.22.0 (the floor unchanged) - measured
  2026-11-14 in a fresh venv: a bare install cannot observe the
  hidden HTML text (the item is reported engine_unavailable) while
  the same input is observed and flagged once tinycss2 + cssselect2
  are present; pypdf stays out because the Gate PDF lane
  short-circuits by design with or without it. Both READMEs name the
  extra packages in the install note.
- **Screen vocabulary**: the screen strings and the new docs follow
  the M2 vocabulary ruling (キーファイル / 処理記録); the ja wording
  drops the legacy words and docs/manifest-format.md says 順序付け
  (sort key).

## [2.1.1] - 2026-11-13

### Fixed
- **The windows leg of the three-OS Test matrix (run #84: 18 failed,
  five root classes)**: every path string entering a ScanResult, a
  report and the history takes the canonical POSIX-slash form (the
  gate-walk idiom, and `_posix_path_str` at the storage boundary) while
  the engine still opens the native path; the two sample generators pin
  `ZipInfo.create_system = 3` and write the cohort MANIFEST through
  `write_bytes`; the mold fixtures are written with fixed LF
  (`newline=""`); the POSIX-only observation scenarios (the unreadable
  chmod lane, the mkfifo lane, the keygen 0o600 pin) ride the v1.4.0
  `os.name == "posix"` idiom; the GUI startup-geometry pins accept the
  platform layout minimum (`max(decision, minimumSizeHint())`); and the
  single-image sanitize history pin compares the canonical form the
  boundary certifies. The repository pins its own checkout
  normalization (`.gitattributes`: `* text=auto eol=lf`), so every text
  file checks out in the canonical LF form the byte-pins certify on all
  three runners.
- **gate --self-check rides the 0/1/2 exit codes** (CH-T21): 0 = the
  expected observations matched, 1 = a difference, 2 = could not run -
  a difference now exits 1 and fails CI, the same contract the cohort
  leg already had.
- **GUI wording**: the Gate result gains its placeholder (GU-T06), the
  About credits Sieve Order and the tagline names the export (GU-T08),
  the base picker asks for files (GU-T18), the history header fits
  (GU-T19).

### Changed
- **The Test workflow rides the three release OS legs** (ubuntu-24.04 /
  windows-latest / macos-15 on Python 3.12, fail-fast: false): the
  distributed Windows/macOS builds are tested on their own runners, and
  the vendored sieve_redact verification is checkout-normalization-proof.
- **Release trials without publishing**: release.yml gained
  workflow_dispatch - the three-OS build and the two frozen-artifact
  self-checks run headlessly (the frozen GUI entry dispatches
  gate|cohort --self-check to the CLI before QApplication, exit 1/2
  fails the release) while every Release attach sits behind the push
  guard.
- **Release assets take the tag, and the body comes from the
  CHANGELOG** (the 2026-11-13 ruling): the asset names ride
  github.ref_name (SieveTray-v2.1.1-windows.zip and siblings), the
  SHA-256 list and the provenance attestation follow the built zips,
  and the release body is the CHANGELOG section of the tag version,
  extracted by tools/extract_changelog.py - a tag without its CHANGELOG
  section fails the release structurally.
- **Version notation is unified** (the 2026-11-13 ruling): the README
  titles carry the release version as their single version literal,
  downloads point at releases/latest with the asset names described
  generically, and one test pins pyproject (dynamic attr) ==
  __version__ == the first CHANGELOG section == both README titles;
  the six version observation pins follow the bump.

### Note
- 2.1.0 was published to PyPI only - no GitHub tag/Release was cut for
  it (the 2026-11-11 ruling: the pre-fix workflow must not turn a
  v2.1.0 tag into a Release), and PyPI 2.1.0 stays as published. The
  first GitHub tag/Release is v2.1.1.

## [2.1.0] - 2026-11-10

### Added
- **Cohort (the M2 comparison lane)**: pick a submissions folder (plus
  optional base documents) and Cohort compares the submissions against
  each other - Scope's strip_base_sources removes the base text from
  each side (the letter §3.5 span contract), the remaining spans are
  matched, and a pair is flagged when either side reaches 700 per mille
  (the recorded match_per_mille is the higher of the two sides, so an
  inclusion is not missed). The result is a local HTML report (en/ja)
  with the leading line, the marked spans (capped; located by character
  offsets - characters, not tokens; the only token counts are the
  base-removal ratios) and a deterministic SVG graph, plus a
  privacy-checked sharing record: the record identifies items and pairs
  by sequence number only - submission file names (where the personal
  names live) never reach the handoff side, while the local report
  keeps the names. CLI `cohort` (`--base`, `--lang`, `--no-paths`) and
  a GUI "Compare Submissions / 提出物の比較" tab (the ninth sidebar
  page) with the comparison run outside the UI thread (busy-bar
  progress, live engine messages, report/record openers, sample
  self-check).
- **Verification**: `verify` recognizes the sieve-cohort receipt (the
  receipt-only handoff defaults to outputs_only), cross-checks the
  summary arithmetic in every scope (flagged == listed pairs, per-lane
  counts, GREEN == total - RED - YELLOW; a record that does not hold
  together is not_verifiable / summary_inconsistent), hashes the given
  base files against the recorded settings (settings_unavailable on a
  mismatch, required for replay when the record has bases), and replays
  run_cohort with the recorded settings; the verify CLI gains `--base`.
- **Sample pack**: `samples/cohort/` - the seven shapes (the paraphrased
  essay pair, the quotes+bibliography pair, the verbatim assignment
  with --base, the hidden vanish .docx, the unrelated submission, the
  renamed-identifier .py pair, and the .js pair where the excerpt side
  alone reaches 937 per mille) with MANIFEST.json (the sha256 list, the
  run config and the measured expectations - never a digest) and
  `cohort --self-check` (exit 0 matched / 1 difference / 2 could not
  run); generate.py rebuilds every file byte-identically.
- **History**: a dedicated `cohort_runs` allowlist table (no paths, no
  bodies) wired into run_cohort with the gate rule that a broken
  storage never fails the run.
- **Sidebar navigation**: the pages move into a left sidebar
  (QListWidget + QStackedWidget, 160-240px with elide+tooltip,
  Ctrl+1..9, last-page restore), and the window gains the geometry
  restore/reset menu (addendum §3.1).

### Changed
- **Screen wording (addendum §3.2)**: Gate is "Export for Sharing /
  共有前の書き出し" and its receipt is the "sharing record /
  書き出し記録" on the screen; every Gate and Cohort control carries a
  §3.3 tooltip including the SHA-256 sentence on the fingerprint
  checkbox. The sidebar rows keep the original 6px padding and every
  row state names an explicit text colour, so the fixed light sidebar
  stays readable under an OS dark theme (selected row: explicit
  background + colour).
- **Receipt ruling (§2-5, the 2026-11-10 instruction)**: the sharing
  record identifies items and pairs by sequence number only
  (include_paths off) while the input fingerprints stay; the READMEs
  gain the one-line --no-paths advice for CLI runs whose submission
  file names carry personal names.
- **Wheel and distribution (§3.10)**: the two sample packs (gate/* and
  cohort/*) travel in the wheel as package-data, so `gate --self-check`
  / `cohort --self-check` run from an installed wheel; the distribution
  smoke runs from the wheel (measured: gate 13/13, cohort 19/19, exit
  0, in a fresh venv).  The distribution half joins the contract (the
  2026-11-11 ruling): every release.yml bundle carries both packs
  (`--add-data "samples/cohort"` on Windows and macOS), the frozen
  artifact runs both self-checks headlessly right after the build and
  any exit code but 0 fails the release (measured on Linux: gate 13/13
  and cohort 19/19, exit 0, with no display available - and the
  missing-pack state measured at exit 2 / sample_pack_not_available),
  `workflow_dispatch` joins the tag push for the no-publish trial run
  (the release attach sits behind the push guard), and the frozen GUI
  entry dispatches `gate|cohort --self-check` to the CLI before
  QApplication so a self-check run never opens a window.
- **Dependency floors**: sieve-scope raised from >=1.3.0 to >=1.5.0 and
  sieve-referee from >=1.3.0 to >=1.6.0 (sieve-lens stays >=0.22.0) -
  the cohort lane consumes Scope's strip_base_sources and the letter
  §3.5 span contract, and Referee's explanation spans, the
  quotes/bibliography citation split and the 16-char base minimum. All
  three floors are published on PyPI (measured 2026-11-10).

## [2.0.0] - 2026-11-08

### Added
- **Gate (the M1 quarantine lane)**: pick a folder and one pass keeps only
  the visible text of the documents, replaces personal data with Redact's
  label mode (sequential per-occurrence labels), observes the hidden text
  for AI-instruction vocabulary (Lens x Order coupling - only the not-
  visible segments, first 10,000 chars each, up to 500 segments per
  document, truncations and skips recorded), and splits the output into
  `handoff/` (what gets passed on) and `local/` (the operator report and
  the engine receipts with content_sha256).  The normalized receipt
  (`handoff/gate-receipt.json`, written last) carries counts, hashes and
  closed-vocabulary codes - never bodies, hidden text or the replaced
  values.  CLI `gate` / `verify` shapes (the legacy
  `<input folder> -o report.html` shape is unchanged) and a GUI "Gate"
  tab (en/ja).
- **HTML observation lane** (§3.2 as amended 2026-11-08): Lens core does
  not detect `<style>`-rule hiding, so Gate uses the extras lane
  (html_css_selectors) with a charset pre-check done by Gate itself
  (BOM UTF-8 -> strict UTF-8 -> strict CP932 -> refused; CP932 HTML is
  observed through a user-only UTF-8 temp copy removed afterwards).
  Measured (0.22.0): the extras lane reports a rule match as a css_hidden
  segment while its body emitter still marks the matched body visible, so
  Gate fails closed - such an HTML is `not_produced` (`engine_refused`)
  and its visible text is never written to `handoff/`.  Without the
  extras lane the HTML is `not_produced` (`engine_unavailable`).
- **Verification**: `verify` re-checks a receipt at three scopes
  (outputs_only / inputs_and_outputs / replay); overall is match /
  differs / not_verifiable with CLI exit codes 0 / 1 / 2 and closed
  reason vocabularies (7 item reasons, 5 not-verifiable reasons).
- **Sample pack**: `samples/gate/` (13 harmless samples across the 10
  §3.5 categories) with `MANIFEST.json` (SHA-256 + expected
  observations, never a digest); deterministic regeneration via
  `tools/make_gate_samples.py`; a self-check (GUI button and
  `gate --self-check`) compares the expected observations.
- **History**: a dedicated `gate_runs` table (allowlisted counts,
  receipt digest, engine versions; no paths, no bodies), added with
  `CREATE TABLE IF NOT EXISTS`; the existing tables stay untouched.

### Changed
- Vendored Redact 0.11.0 (the certified M1 implementation) and vendored
  sieve-order v1.1.0 (both byte-identical to upstream); `sieve-lens`
  floor raised to the published 0.22.0.  The receipt reports the
  redaction counts as `redact.by_mode` (the earlier draft's
  `redact.aliases` was renamed: 0.11.0 labels occurrences sequentially
  and shares one counter with `label`, so mode counts are the accurate
  vocabulary).

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
