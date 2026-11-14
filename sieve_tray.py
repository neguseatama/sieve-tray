"""
Sieve Tray - Route a directory of files to the appropriate Sieve engine.

Usage (CLI):
    python3 sieve_tray.py <input_dir>
    python3 sieve_tray.py <input_dir> -o report.html

Usage (as a library, e.g. from a GUI):
    from sieve_tray import run_scan, render

    result = run_scan(input_dir, progress=my_log_widget.append)
    html_report = render(result)
    # or read result.groups / result.doc_results / result.code_pairs
    # directly to populate a table widget instead of HTML.

Structure:
    input_dir/
        group_a/
            file.py
            document.docx
        group_b/
            ...

Any directory structure works. Files are routed by extension:
  - Code extensions  -> Sieve-Scope (pairwise comparison)
  - Document extensions -> Sieve-Lens (per-file observation)
  - Text extensions (subset of document extensions) -> ALSO Sieve-Referee
    (pairwise paraphrase/plagiarism comparison), since a document can
    independently have hidden content (Lens' concern) and reused/paraphrased
    prose (Referee's concern).
"""

import argparse
import ast
import builtins
import hashlib
import hmac
import html
import json
import os
import stat as stat_module
import sys
import tempfile
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# Single source of truth for the package version. pyproject.toml reads
# this dynamically (see [tool.setuptools.dynamic]) instead of duplicating
# the number, since keeping two copies in sync has already caused drift
# more than once during development.
__version__ = "2.1.1"


CODE_EXTS = {".py"}
DOC_EXTS = {
    ".txt", ".md", ".html", ".htm", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
    ".tif", ".tiff", ".webp",
}
# Plain-text subset of DOC_EXTS that Sieve-Referee can additionally compare
# pairwise. Referee only accepts plain text, so rich formats (.docx, .pdf,
# images, .html) are excluded even though Sieve-Lens still observes them.
TEXT_EXTS = {".txt", ".md"}
IMAGE_EXTS = {".png"}

# ---------------------------------------------------------------------------
# v1.1.0: the third state "unobserved" (design doc §3.1-§3.4).
#
# Everything Tray could not observe is reported with a status and a reason
# from this closed vocabulary - never with free-form error text. The
# vocabulary is fixed by the design document; extending it is a design
# decision and stops the implementation.
# ---------------------------------------------------------------------------
UNOBSERVED_REASONS = frozenset({
    "refused",           # the engine refused extraction (Lens refusal code in detail)
    "parse_failed",      # read, but parsing failed / H1=0 (observation not established)
    "unreadable",        # could not be read (permission, I/O, special file)
    "too_large",         # beyond Tray's own read limit (§3.4)
    "symlink_skipped",   # a symbolic link - not read, not followed (§3.4)
    "engine_unavailable",# required extension/engine missing or failed to install
    "not_applicable",    # empty or statement-less code file - excluded from compare (§3.3)
    "empty_input",       # empty text - nothing for Referee to evaluate (§3.3)
})

# v1.4.0 (design §3.2): the three-stage grouping of the closed 8-reason
# vocabulary.  Every reason sits in exactly one stage (the tests pin the
# partition; a new reason must join this table - extending the vocabulary
# itself stays a design decision).
#   remedy      - file-side measures make the file observable again
#   environment - an engine/environment-side gap, not the file's fault
#   excluded    - by design not a scan target
UNOBSERVED_STAGES = {
    "remedy": frozenset({
        "refused", "parse_failed", "unreadable", "too_large",
        "symlink_skipped"}),
    "environment": frozenset({"engine_unavailable"}),
    "excluded": frozenset({"not_applicable", "empty_input"}),
}

# The stage background colors (design §3.2, the proposal values).  The
# GUI palette is a fixed light theme (no dark mode), and the reason text
# stays in the row, so the color is never the only carrier.
UNOBSERVED_STAGE_BG = {
    "remedy": "#fff4d6",
    "environment": "#f0f0f0",
    "excluded": "#f8f8f8",
}


def unobserved_stage(reason: str) -> str:
    """Return the stage key ('remedy'/'environment'/'excluded') of one
    reason from the closed vocabulary; unknown reasons raise ValueError
    (a new reason has to join UNOBSERVED_STAGES first)."""
    for stage, members in UNOBSERVED_STAGES.items():
        if reason in members:
            return stage
    raise ValueError("unknown unobserved reason: %r" % (reason,))

# The 13 Lens refusal codes known at v1.1.0. A code outside this set keeps
# detail=None so a future Lens cannot leak new strings into reports.
KNOWN_REFUSAL_CODES = frozenset({
    "not_regular_file", "file_too_large", "too_many_entries",
    "part_too_large", "total_too_large", "too_many_elements",
    "doctype_not_allowed", "unsupported_encoding", "duplicate_part",
    "encrypted", "malformed_xml", "main_part_missing",
    "unsupported_namespace",
})

# Tray's own read limit for the files Tray reads itself (.py for Scope,
# .txt/.md for Referee). Lens-owned formats keep Lens' own limits - no
# double capping on this side (design doc §3.4).
TRAY_READ_LIMIT_BYTES = 8 * 1024 * 1024

# Which Lens extensions cover which suffixes: used to mark files
# engine_unavailable when an extension fails to install (design doc §3.1).
_LENS_EXT_SUFFIXES = {
    "sieve_lens_ext.pdf": {".pdf"},
    "sieve_lens_ext.ocr": {".png", ".jpg", ".jpeg", ".gif", ".bmp",
                           ".tif", ".tiff", ".webp"},
    "sieve_lens_ext.image_layers": {".png", ".jpg", ".jpeg", ".gif",
                                    ".bmp", ".tif", ".tiff", ".webp"},
    "sieve_lens_ext.html_css": {".html", ".htm"},
    "sieve_lens_ext.html_css_selectors": {".html", ".htm"},
    "sieve_lens_ext.pdf_images": {".pdf"},
}

# A progress callback takes a single human-readable status string.
# The CLI passes `print`; a GUI can pass e.g. a Qt signal emitter or
# a log-widget's append method. Defaults to doing nothing, so library
# callers never have to supply one.
ProgressCallback = Callable[[str], None]


def _silent(_msg: str) -> None:
    pass


def _posix(p) -> str:
    """Canonical POSIX-slash form of a path string (cohort-m2, run #84).

    Every path string entering a ScanResult (the groups, the document
    results, the unobserved entries) and therefore every report and
    history row is normalized to forward slashes: WindowsPath's str()
    carries backslashes, which leaked into the JSON core hash and
    drifted the cross-OS byte molds (run #84's windows leg).  On POSIX
    this is the identity, so every mold measured on the POSIX runners
    is unchanged - the same canonical form the gate walk already emits
    (the str(rel).replace(os.sep, "/") idiom)."""
    return str(p).replace(os.sep, "/")


@dataclass
class ScanResult:
    """Structured result of a full sieve_tray run.

    GUI code should prefer reading these fields directly (for table
    widgets etc.) rather than parsing the HTML report.
    """
    groups: List[Tuple[str, List[Path]]] = field(default_factory=list)
    doc_results: List[dict] = field(default_factory=list)
    code_pairs: List[dict] = field(default_factory=list)
    text_pairs: List[dict] = field(default_factory=list)
    # v0.8.0: quantifier audit lane (Sieve Referee >=1.3.0).
    # Each entry represents one flagged sentence across the scanned text
    # files; empty list = no flagged sentences (or audit lane not run).
    # See audit_text() for the entry shape.
    audit_results: List[dict] = field(default_factory=list)

    # v0.10.0: crowd run records (newest first) attached at export
    # time for the report's crowd section. Not serialized by
    # to_dict(); the CLI path leaves it None and the section is
    # skipped entirely.
    crowd_runs: Optional[list] = None

    # v1.1.0: file-level entries for things Tray could not observe at all
    # (unreadable, too large, symlink, engine unavailable, ...). Each
    # entry: {"file": str, "engine": str, "reason": <closed vocab>,
    # "detail": str | None}. Document observations carry their own status
    # keys and are not duplicated here.
    unobserved: List[dict] = field(default_factory=list)

    # v1.1.0: how many code pairs Scope short-circuited (observation did
    # establish, but the pair is trivially dissimilar and stays excluded
    # as in v1.0.0). Surfaced in the report so the exclusion is visible.
    short_circuited_excluded: int = 0

    def to_dict(self) -> dict:
        """JSON-serializable form, used by sieve_tray_storage for history."""
        return {
            "groups": [[name, [_posix(p) for p in files]] for name, files in self.groups],
            "doc_results": self.doc_results,
            "code_pairs": self.code_pairs,
            "text_pairs": self.text_pairs,
            "audit_results": self.audit_results,
            "unobserved": self.unobserved,
            "short_circuited_excluded": self.short_circuited_excluded,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScanResult":
        groups = [(name, [Path(p) for p in files]) for name, files in d["groups"]]
        return cls(groups=groups, doc_results=d["doc_results"],
                    code_pairs=d["code_pairs"],
                    text_pairs=d.get("text_pairs", []),
                    audit_results=d.get("audit_results", []),
                    unobserved=d.get("unobserved", []),
                    short_circuited_excluded=d.get("short_circuited_excluded", 0))


def _walk_group(group_dir: Path) -> Tuple[List[Path], List[dict]]:
    """v1.1.0: walk one group directory without following links (design doc §3.4).

    Returns (regular_files, unobserved_entries). Regular files keep the
    v1.0.0 semantics (sorted, is_file()). Symlinked files and directories
    and special files (FIFO, device, ...) become unobserved entries with
    the closed vocabulary, so nothing at or beyond the scan root is read
    through a link and no special file is ever opened.
    """
    files: List[Path] = []
    entries: List[dict] = []

    def _entry(p: Path, reason: str) -> dict:
        return {"file": _posix(p), "engine": "tray",
                "reason": reason, "detail": None}

    for dirpath, dirnames, filenames in os.walk(group_dir, followlinks=False):
        dirnames[:] = sorted(dirnames)
        for name in sorted(dirnames):
            p = Path(dirpath) / name
            if p.is_symlink():
                entries.append(_entry(p, "symlink_skipped"))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink():
                entries.append(_entry(p, "symlink_skipped"))
            elif not p.is_file():
                entries.append(_entry(p, "unreadable"))
            else:
                files.append(p)
    return files, entries


def scan(input_dir: Path) -> List[Tuple[str, List[Path]]]:
    groups = []
    for d in sorted(input_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        files, _entries = _walk_group(d)
        if files:
            groups.append((d.name, files))
    return groups


def split_files(files: List[Path]) -> Tuple[List[Path], List[Path]]:
    code = [f for f in files if f.suffix.lower() in CODE_EXTS]
    doc = [f for f in files if f.suffix.lower() in DOC_EXTS]
    return code, doc


def observe_documents(doc_paths: List[Path],
                       progress: ProgressCallback = _silent) -> List[dict]:
    try:
        from sieve_lens import SieveLensEngine
    except ImportError:
        progress("Note: sieve-lens not installed; marking documents unobserved.")
        return [{
            "path": _posix(f),
            "mask": "0000-000",
            "flagged": False,
            "h_states": {},
            "evidence": {},
            "error": "ImportError",
            "status": "unobserved",
            "unobserved_reason": "engine_unavailable",
            "unobserved_detail": None,
        } for f in doc_paths]

    # v0.11.0 integration fix: install every available Lens extension so
    # PDF/image observation actually works through Tray (same order
    # contract as the dashboard's _build_engine: image_layers chains onto
    # ocr, html_css_selectors supersedes html_css, pdf_images supersedes pdf).
    import importlib
    engine = SieveLensEngine()
    failed_exts: List[str] = []
    for spec in (
        "sieve_lens_ext.pdf:install",
        "sieve_lens_ext.ocr:install",
        "sieve_lens_ext.image_layers:install",
        "sieve_lens_ext.html_css:install",
        "sieve_lens_ext.html_css_selectors:install",
        "sieve_lens_ext.pdf_images:install",
    ):
        mod_name, _, fn_name = spec.partition(":")
        try:
            getattr(importlib.import_module(mod_name), fn_name)(engine)
        except Exception:
            failed_exts.append(mod_name)
    affected: set = set()
    for mod_name in failed_exts:
        affected |= _LENS_EXT_SUFFIXES.get(mod_name, set())

    results = []
    for f in doc_paths:
        try:
            obs = engine.observe(str(f))
            entry = {
                "path": _posix(f),
                "mask": obs.mask,
                "flagged": (obs.mask != "1000-000"
                            and not obs.mask.startswith("0")),
                "h_states": dict(obs.h_states),
                "evidence": dict(obs.evidence),
            }
        except Exception as e:
            entry = {
                "path": _posix(f),
                "mask": "0000-000",
                "flagged": False,
                "h_states": {},
                "evidence": {},
                "error": type(e).__name__,
            }
        status, reason, detail = classify_observation(entry)
        if reason == "parse_failed" and f.suffix.lower() in affected:
            # An extension this suffix needs failed to install (design doc §3.1).
            reason = "engine_unavailable"
        entry["status"] = status
        entry["unobserved_reason"] = reason if status == "unobserved" else None
        entry["unobserved_detail"] = detail if status == "unobserved" else None
        results.append(entry)
    return results


def classify_observation(result: dict) -> Tuple[str, Optional[str], Optional[str]]:
    """v1.1.0: the single classifier for the third state (design doc §3.1).

    Reads only mask / evidence / error from the result dict - never file
    contents or exception messages. Returns (status, unobserved_reason,
    unobserved_detail); reason and detail are None unless status is
    "unobserved". The report, the GUI and the history derivation all read
    through this function, so "flagged" is interpreted in one place.
    """
    err = result.get("error")
    if err is not None:
        cls = getattr(builtins, str(err), None)
        reason = ("unreadable"
                  if isinstance(cls, type) and issubclass(cls, OSError)
                  else "parse_failed")
        return ("unobserved", reason, None)

    mask = str(result.get("mask", ""))
    if not mask:
        # Not even a mask was recorded - derive conservatively (design doc §3.5).
        return ("unobserved", "parse_failed", None)

    evidence = result.get("evidence")
    texts: List[str] = []
    if isinstance(evidence, dict):
        for values in evidence.values():
            if isinstance(values, (list, tuple)):
                texts.extend(str(v) for v in values)
            elif values is not None:
                texts.append(str(values))

    if mask.startswith("0"):
        for t in texts:
            if t.startswith("Extraction refused: "):
                code = t[len("Extraction refused: "):].strip()
                detail = code if code in KNOWN_REFUSAL_CODES else None
                return ("unobserved", "refused", detail)
        # Measured on Lens (v0.21.1): a missing extractor is not an
        # exception but a null observation whose evidence reads
        # "Unsupported format: <suffix>" - an engine-capability gap,
        # not a parse failure of the file.
        for t in texts:
            if t.startswith("Unsupported format:"):
                return ("unobserved", "engine_unavailable", None)
        return ("unobserved", "parse_failed", None)
    if mask == "1000-000":
        return ("clean", None, None)
    return ("flagged", None, None)


def summarize_results(results: List[dict]) -> dict:
    """v1.1.0: pure aggregation over document results (design doc §3.5).

    Returns {"flagged": n, "clean": n, "unobserved": n} plus
    "unobserved_by_reason" keyed by the closed vocabulary. The GUI and
    the report display these numbers; they never recount "flagged"
    themselves.
    """
    counts = {"flagged": 0, "clean": 0, "unobserved": 0}
    by_reason = {reason: 0 for reason in UNOBSERVED_REASONS}
    for r in results:
        status, reason, _detail = classify_observation(r)
        counts[status] += 1
        if status == "unobserved" and reason in by_reason:
            by_reason[reason] += 1
    counts["unobserved_by_reason"] = by_reason
    return counts


def _read_limited(path: Path,
                  limit: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
    """v1.1.0: read at most limit+1 bytes (design doc §3.4).

    Returns (text, None) on success or (None, "too_large") when the file
    exceeds the limit. The OS is never asked for more than limit+1 bytes,
    so oversized files are detected without loading them whole.

    v1.3.0: the decode applies the series-wide character-code policy
    (design doc §3.1): a UTF-8 BOM (utf-8-sig), then strict UTF-8, then
    strict CP932; anything else returns (None, "unsupported_encoding")
    and the caller records the file as unobserved ('refused').
    errors="replace" and "ignore" are never used, and UTF-16/UTF-32
    BOMs refuse outright (v1.0.0 read with errors="replace"; the limit
    arrived in v1.1.0, the strict policy only now).
    """
    if limit is None:
        limit = TRAY_READ_LIMIT_BYTES
    with open(path, "rb") as fh:
        chunk = fh.read(limit + 1)
    if len(chunk) > limit:
        return None, "too_large"
    if (chunk[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
            or chunk[:2] in (b"\xff\xfe", b"\xfe\xff")):
        return None, "unsupported_encoding"
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return chunk.decode(encoding), None
        except UnicodeDecodeError:
            continue
    return None, "unsupported_encoding"


def _scope_pairs_from_analysis(analysis: dict
                               ) -> Tuple[List[dict], int, List[dict]]:
    """v1.3.0: extract Tray's pair list from a Scope analyze_corpus
    result, plus the engine's skipped entries.

    Returns (pairs, excluded, skipped_entries). Pairs keep the v1.1.0
    shape; a scores:null pair (scope 1.3.1+) becomes {}. Skipped
    entries (scope 1.3.1+, each {path, reason}) become unobserved-
    shaped dicts carrying the engine's own closed vocabulary; a reason
    outside the vocabulary falls to parse_failed and the original
    string never surfaces. Engines without the keys (scope 1.3.0)
    behave exactly as v1.2.0.
    """
    pairs = []
    excluded = 0
    for (k1, k2), res in analysis["pair_results"].items():
        if res.get("short_circuited"):
            excluded += 1
            continue
        pairs.append({
            "a": k1,
            "b": k2,
            "mask": res["mask"],
            "h_states": dict(res.get("h_states", {})),
            # scores can be null (scope 1.3.1: H1=0 pair) - never
            # dict(None)
            "scores": dict(res.get("scores") or {}),
        })
    skipped_entries = []
    for item in analysis.get("skipped") or []:
        reason = item.get("reason")
        if reason not in UNOBSERVED_REASONS:
            # out of the closed vocabulary: drop to parse_failed and
            # keep the original string out of the results
            reason = "parse_failed"
        skipped_entries.append(
            {"file": _posix(item.get("path", "")), "engine": "scope",
             "reason": reason, "detail": None})
    return pairs, excluded, skipped_entries


def _merge_unobserved(existing: List[dict], incoming: List[dict]
                      ) -> List[dict]:
    """v1.3.0: fold engine 'skipped' entries into Tray's unobserved
    list without double-counting a path.

    An incoming entry whose file is already recorded replaces the
    earlier entry (the engine's reason wins - it observed the file
    further than Tray's own pre-classification); the rest are appended
    in order. File strings are compared as recorded; Tray writes the
    engine paths in its own {group}/{file} shape before merging.
    """
    merged = list(existing)
    index = {e.get("file"): i for i, e in enumerate(merged)}
    for entry in incoming:
        f = entry.get("file")
        if f in index:
            merged[index[f]] = entry
        else:
            index[f] = len(merged)
            merged.append(entry)
    return merged


def _compare_code_detailed(code_map: Dict[str, str],
                           progress: ProgressCallback = _silent
                           ) -> Tuple[List[dict], int, List[dict]]:
    """v1.1.0: compare_code plus the short-circuit exclusion count.

    Short-circuited pairs keep the v1.0.0 behavior (excluded from the
    pair list), but the count is returned so the report can show that
    the exclusion happened (design doc §3.2). Measured causes in Scope:
    ast.parse failure (0000-000) and H1=1 with H2=0 and H3=0
    (1000-000 - the observation did establish).

    v1.3.0: also returns the engine's skipped entries (scope 1.3.1+;
    empty for scope 1.3.0) so run_scan can fold them into the
    unobserved list without double-counting a path.
    """
    if len(code_map) < 2:
        return [], 0, []
    try:
        from sieve_scope import SieveScopeEngineV1_3, SieveClusterAnalyzerV1_3
    except ImportError:
        progress("Note: sieve-scope not installed; skipping code analysis.")
        return [], 0, []

    engine = SieveScopeEngineV1_3()
    analyzer = SieveClusterAnalyzerV1_3(engine, min_cluster_size=2)
    analysis = analyzer.analyze_corpus(code_map)

    return _scope_pairs_from_analysis(analysis)


def compare_code(code_map: Dict[str, str],
                  progress: ProgressCallback = _silent) -> List[dict]:
    pairs, _excluded, _skipped = _compare_code_detailed(code_map, progress)
    return pairs


def compare_text(text_map: Dict[str, str],
                  progress: ProgressCallback = _silent) -> List[dict]:
    """Pairwise paraphrase/plagiarism screening via Sieve-Referee.

    Only TEXT_EXTS files (plain text: .txt, .md) are eligible - Referee
    takes plain text in, so rich formats never reach this function.
    """
    if len(text_map) < 2:
        return []
    try:
        from sieve_referee import batch_evaluate
    except ImportError:
        progress("Note: sieve-referee not installed; skipping text similarity analysis.")
        return []

    results = batch_evaluate(text_map)
    pairs = []
    for res in results:
        signal = (res.evaluation_signal.value
                  if hasattr(res.evaluation_signal, "value")
                  else str(res.evaluation_signal))
        if signal == "GREEN":
            # GREEN = independently-written pair, nothing to report.
            continue
        pairs.append({
            "a": res.item_id,
            "b": res.matched_peer_id,
            "signal": signal,
            "mask": res.mask,
            "pattern_name": res.pattern_name,
            "reason": res.reason,
            "h_states": {f"H{i + 1}": int(bit) for i, bit in enumerate(res.mask)},
            "scores": {
                "structural_density": res.structural_density,
                "max_structure_similarity": res.max_structure_similarity,
                "max_content_similarity": res.max_content_similarity,
                "coverage": res.coverage,
            },
        })
    return pairs


# v0.8.0: default modifier vocab is sourced from sieve_referee's
# embedded DEFAULT_MODIFIER_VOCAB (the canonical source) so the audit
# lane works out of the box without shipping a separate data file.
# This mirrors sieve_referee's own design (embedded vocab + optional
# file override via --audit-modifier-vocab).
DEFAULT_MODIFIER_VOCAB_PATH = Path(__file__).resolve().parent / "epistemic_modifiers_ja_v1.txt"


def _default_modifier_vocab() -> Tuple[str, ...]:
    """Return the embedded default modifier vocab from sieve_referee.

    Falls back to a local copy if the import fails (e.g. sieve_referee
    <1.3.0). The local copy is kept in sync with sieve_referee v1.3.0's
    DEFAULT_MODIFIER_VOCAB (sha256-pinned in test_sieve_tray_audit).
    """
    try:
        from sieve_referee.quantifier_audit import DEFAULT_MODIFIER_VOCAB
        return DEFAULT_MODIFIER_VOCAB
    except ImportError:
        return (
            "確実に", "紛れもなく", "明白に", "明らかに", "断じて",
            "間違いなく", "疑いなく", "自明に", "例外なく", "一切",
        )


def _load_modifier_vocab(vocab_path: Optional[str]) -> Tuple[str, ...]:
    """Load a modifier-vocab file into a tuple of patterns.

    A None, empty, or non-existent path returns the embedded default
    (sourced from sieve_referee.DEFAULT_MODIFIER_VOCAB). A non-empty
    path that exists is read line by line; # comments and blank lines
    are skipped, matching the format documented at the top of the
    bundled vocab file. An empty or unreadable file also falls back to
    the embedded default.
    """
    if not vocab_path:
        return _default_modifier_vocab()
    path = Path(vocab_path)
    if not path.exists():
        return _default_modifier_vocab()
    patterns: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return tuple(patterns) if patterns else _default_modifier_vocab()


def audit_text(text_map: Dict[str, str],
               modifier_vocab_path: Optional[str] = None,
               progress: ProgressCallback = _silent) -> Tuple[List[dict], Optional[dict]]:
    """Quantifier-audit lane via Sieve-Referee (>=1.3.0).

    Returns (audit_results, summary) where audit_results is a flat list
    of one entry per flagged sentence across all input files, and
    summary is the engine's receipt-level summary dict (or None when
    the audit lane could not run - e.g. sieve-referee <1.3.0 or no
    eligible text files).

    Entry shape (one per flagged sentence):
        {
          "file": <item_id>,
          "sentence_sha256": <64-hex>,
          "sentence_text": <the flagged sentence, truncated to 200 chars>,
          "patterns": [<matched universal-scope patterns>],
          "backing": <theorem|enumerated|sample|unbacked>,
          "scope": <universal|measured>,
          "signal": <GREEN|YELLOW|RED>,
          "pattern_name": <e.g. UNBACKED_UNIVERSAL>,
          "reason": <engine reason, Japanese>,
          "certainty_markers": [<matched modifier-vocab patterns>],
          "modifier_vocab_sha256": <64-hex or None>,
          "modifier_vocab_count": <int or 0>,
        }

    Only sentences whose signal is YELLOW or RED are surfaced - GREEN
    sentences are not 'flagged' and would just clutter the table.
    The audit lane is opt-in per scan: an empty text_map returns ([], None)
    without calling the engine.
    """
    if not text_map:
        return [], None
    try:
        from sieve_referee import audit_documents
    except ImportError:
        progress("Note: sieve-referee not installed; skipping quantifier audit.")
        return [], None

    modifier_vocab = _load_modifier_vocab(modifier_vocab_path)
    try:
        report = audit_documents(
            text_map,
            modifier_vocab=modifier_vocab if modifier_vocab else None,
        )
    except Exception as exc:
        progress(f"Note: quantifier audit failed: {type(exc).__name__}: {exc}")
        return [], None

    audit_results: List[dict] = []
    # worksheets carries per-file sentence detail (with sentence_text);
    # the receipt's documents[].candidates[] carries the same per-sentence
    # fields without sentence_text - we join on sentence_sha256.
    worksheet_by_file = {k: v for k, v in report.worksheets.items()}
    text_by_sha: Dict[str, str] = {}
    for file_id, entries in worksheet_by_file.items():
        for e in entries:
            sha = e.get("sentence_sha256")
            if sha and sha not in text_by_sha:
                # Truncate to keep the table readable and the DB row bounded;
                # the full text is in the worksheet if a future detail view
                # needs it.
                text_by_sha[sha] = (e.get("sentence_text") or "")[:200]

    for doc in report.receipt.get("documents", []):
        file_id = doc.get("item_id", "")
        for cand in doc.get("candidates", []):
            signal = cand.get("signal", "")
            if signal == "GREEN":
                continue
            sha = cand.get("sentence_sha256", "")
            audit_results.append({
                "file": file_id,
                "sentence_sha256": sha,
                "sentence_text": text_by_sha.get(sha, ""),
                "patterns": list(cand.get("patterns", [])),
                "backing": cand.get("backing", ""),
                "scope": cand.get("scope", ""),
                "signal": signal,
                "pattern_name": cand.get("pattern_name", ""),
                "reason": cand.get("reason", ""),
                "certainty_markers": list(cand.get("certainty_markers", [])),
                "modifier_vocab_sha256": report.receipt.get("modifier_vocab_sha256"),
                "modifier_vocab_count": int(report.receipt.get("modifier_vocab_count", 0)),
            })

    summary = {
        "vocab_sha256": report.receipt.get("vocab_sha256"),
        "vocab_count": int(report.receipt.get("vocab_count", 0)),
        "modifier_vocab_sha256": report.receipt.get("modifier_vocab_sha256"),
        "modifier_vocab_count": int(report.receipt.get("modifier_vocab_count", 0)),
        "unverified_remaining": int(report.receipt.get("unverified_remaining", 0)),
        "certainty_flagged": int(report.receipt.get("certainty_flagged", 0)),
        "tag_counts": dict(report.receipt.get("tag_counts", {})),
    }
    return audit_results, summary


def make_region_spec(x, y, w, h, mode, arg=None):
    """Build one region spec string 'x,y,w,h:MODE[:ARG]'.

    Raises ValueError when ARG contains ':' - the engine parser splits
    the spec on colons and would misread it.
    """
    if arg is not None and ":" in arg:
        raise ValueError("region ARG must not contain ':'")
    spec = "%d,%d,%d,%d:%s" % (x, y, w, h, mode)
    if arg is not None:
        spec += ":" + arg
    return spec


def validate_region_spec(spec):
    """Validate a region spec with the vendored engine parser.

    Returns the parsed rect dict; raises ValueError when the engine
    would reject the spec. The engine parser is the single source of
    truth for the spec grammar.
    """
    import sieve_redact

    return sieve_redact.parse_region_spec(spec)


def build_region_config(specs):
    """Build the text of a region-only Redact config file.

    One 'region <spec>' line per spec, no trailing newline. Region
    lines only: the engine rejects rule/builtin lines in image mode.
    """
    return "\n".join("region " + s for s in specs)


def validate_rect(rect, img_w, img_h):
    """Return True when a rect dict (x, y, w, h) lies fully inside an
    img_w x img_h image with positive area. The engine rejects
    out-of-range regions with exit code 2; this pre-check lets callers
    warn before running.
    """
    return (rect["x"] >= 0 and rect["y"] >= 0
            and rect["w"] > 0 and rect["h"] > 0
            and rect["x"] + rect["w"] <= img_w
            and rect["y"] + rect["h"] <= img_h)


def sanitize_file(input_path, config_path, output_path,
                  receipt_path=None) -> dict:
    """Mask a text file through the vendored Redact engine (in-process).

    Runs sieve_redact.main() and maps its exit-code contract
    (0 ok / 1 other / 2 usage / 3 strict) without letting SystemExit
    escape. Returns a summary dict the GUI can surface directly:
    masked_count / integrity_verified / residue come from the receipt,
    which never contains the sensitive body itself. When no receipt
    path is given, one is generated in a temp directory and parsed
    before being discarded, so callers always get the numbers.
    """
    import contextlib
    import io
    import json as _json
    import tempfile

    try:
        import sieve_redact
    except ImportError:
        return {"ok": False, "rc": None, "skipped": True,
                "masked_count": 0, "integrity_verified": False,
                "residue": None, "stdout": "",
                "stderr": "sieve-redact is not available; skipping sanitize."}

    own_tmp = None
    if receipt_path is None:
        own_tmp = tempfile.TemporaryDirectory()
        receipt_path = Path(own_tmp.name) / "receipt.json"

    argv = [str(input_path), "-o", str(output_path),
            "--config", str(config_path), "--receipt", str(receipt_path)]

    out_buf, err_buf = io.StringIO(), io.StringIO()
    rc = None
    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            rc = sieve_redact.main(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            rc = 0
        elif isinstance(code, int):
            rc = code
        else:
            rc = 1
    if rc is None:
        rc = 0

    result = {"ok": rc == 0, "rc": rc, "skipped": False,
              "masked_count": 0, "integrity_verified": False,
              "residue": None,
              "stdout": out_buf.getvalue(), "stderr": err_buf.getvalue()}

    if rc == 0:
        try:
            data = _json.loads(Path(receipt_path).read_text(encoding="utf-8"))
            if "pixel_integrity_verified" in data:
                # Image receipt: pixel integrity is the measured value and
                # rects carries the region rows (total_redactions is a
                # literal 0 in the image contract). byte_integrity_verified
                # is null there (PNG re-encoding changes bytes structurally),
                # so it must never be surfaced as a failure.
                result["masked_count"] = len(data.get("rects", []))
                result["integrity_verified"] = bool(
                    data.get("pixel_integrity_verified", False))
                result["byte_integrity_applicable"] = False
            else:
                result["masked_count"] = data.get("total_redactions", 0)
                result["integrity_verified"] = bool(
                    data.get("byte_integrity_verified", False))
                result["byte_integrity_applicable"] = True
            result["residue"] = data.get("pattern_appearance_in_output")
        except (OSError, ValueError):
            result["integrity_verified"] = False
    if own_tmp is not None:
        own_tmp.cleanup()
    return result

def sanitize_tree(input_dir, config_path, out_root,
                 progress=None) -> dict:
    """Mask every eligible file under input_dir via the vendored Redact
    engine, preserving the relative folder structure and writing a
    receipt next to each output. The config kind selects the target
    extension set (measured against the vendored v0.6.0 engine, where
    a region-only config routes any input to image mode):
      - region-only config  -> .png files; every other file is excluded
      - rule/builtin config -> TEXT_EXTS files (text flow unchanged);
        .png files are excluded
      - mixed / unreadable / invalid config -> tree-level config_error
        and nothing is processed
    Per-file engine failures (out-of-range region, unsupported color
    type or bit depth) keep the tree running. Returns a summary dict
    the GUI can surface: n_files / ok_count / masked_total /
    integrity_bad_count / failed [(rel, result)] / skipped /
    excluded [(rel, reason)] / config_error (None or message). Module
    absence is a tree-level condition (skipped=True) rather than a
    per-file failure.
    """
    try:
        import sieve_redact
    except ImportError:
        return {"n_files": 0, "ok_count": 0, "masked_total": 0,
                "integrity_bad_count": 0, "failed": [], "skipped": True,
                "excluded": [], "config_error": None}

    cfg_path = Path(config_path)
    base = {"n_files": 0, "ok_count": 0, "masked_total": 0,
            "integrity_bad_count": 0, "failed": [], "skipped": False,
            "excluded": [], "config_error": None}

    try:
        cfg_text = cfg_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        base["config_error"] = "cannot read config: %s" % exc
        return base

    try:
        kinds = [k for k, _ in
                 sieve_redact.parse_config_lines(cfg_text, str(cfg_path))]
    except sieve_redact.UsageError as exc:
        base["config_error"] = str(exc)
        return base

    has_region = "region" in kinds
    has_matcher = any(k in ("rule", "builtin") for k in kinds)
    if has_region and has_matcher:
        base["config_error"] = ("config rule/builtin lines cannot be "
                                "combined with image mode (--region)")
        return base

    if has_region:
        target_exts = IMAGE_EXTS
        exclude_any = True     # every non-png file is reported excluded
        exclude_reason = "not a PNG (region config)"
    else:
        target_exts = TEXT_EXTS
        exclude_any = False    # only .png files are reported excluded
        exclude_reason = "PNG not eligible (text config)"

    files = []
    for f in sorted(Path(input_dir).rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in target_exts:
            files.append(f)
        elif exclude_any or ext == ".png":
            base["excluded"].append((f.relative_to(input_dir),
                                     exclude_reason))

    base["n_files"] = len(files)
    for f in files:
        rel = f.relative_to(input_dir)
        out_path = Path(out_root) / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        rec_path = out_path.with_name(out_path.name + ".receipt.json")
        if progress is not None:
            progress(str(rel))
        result = sanitize_file(f, cfg_path, out_path,
                               receipt_path=rec_path)
        if result["ok"]:
            base["ok_count"] += 1
            base["masked_total"] += result["masked_count"]
            if not result["integrity_verified"]:
                base["integrity_bad_count"] += 1
        else:
            base["failed"].append((rel, result))
    return base

def crowd_read_table(path: Path) -> Tuple[list, list, list]:
    """v1.3.0: read a data file through Crowd 0.9.0's input layer.

    Returns (header, rows, notices). The character code is decided by
    the series-wide policy and auto-detection only (design 3.1): a
    UTF-8 BOM, then strict UTF-8, then strict CP932; anything else is
    refused with InputRefused('unsupported_encoding'). No encoding UI
    is offered. ``notices`` are Crowd's one-line stderr observations
    (encoding adoption, sheet selection, missing formula caches): the
    GUI surfaces them in the result details and nowhere else - they
    never enter the table area or the history payload.
    """
    from sieve_crowd.tableio import detect_format
    from sieve_crowd.tabular import read_input
    data = path.read_bytes()
    fmt = detect_format(path.suffix)
    return read_input(data, fmt, path=str(path))


def crowd_refusal_message(code: str, lang: str = "en") -> str:
    """v1.3.0: display wording for a Crowd refusal code.

    Codes map to the i18n keys crowd_refusal_<code> (en/ja
    symmetric); a code without a wording surfaces as the code itself.
    Values are never interpolated - the message carries no file or
    cell data.
    """
    import sieve_tray_i18n
    key = "crowd_refusal_" + str(code)
    strings = sieve_tray_i18n.STRINGS.get(lang)
    if strings and key in strings:
        return sieve_tray_i18n.tr(lang, key)
    return str(code)


def crowd_inspect(header, rows) -> list:
    """Column observations from the crowd engine (no roles guessed).

    Returns one dict per column with the keys name / distinct /
    empty / unique_ratio / shape. Thin in-process wrapper around the
    vendored sieve_crowd package, the same pattern as the Redact
    wrappers above.
    """
    from sieve_crowd import inspect_table
    return inspect_table(header, rows)


def crowd_parse_config(config_text, **overrides):
    """Parse JSON config text into a sieve_crowd Config.

    JSON syntax errors are re-raised as a crowd ConfigError whose
    message carries the line number, so the GUI can point at the
    offending line directly. Crowd-side validation errors (unknown
    keys, k < 2, roles left at '?') propagate as ConfigError
    unchanged. Optional keyword overrides (key=...) pass
    through to sieve_crowd.parse_config, the same contract as
    the crowd CLI --key-file option.
    """
    from sieve_crowd import ConfigError, parse_config
    try:
        obj = json.loads(config_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"the configuration is not valid JSON: line {exc.lineno}: {exc.msg}"
        ) from None
    return parse_config(obj, **overrides)


def _crowd_atomic_write(path, data):
    """Write bytes atomically (tempfile + os.replace), the same
    on-disk contract as the crowd CLI's own writer."""
    import os
    import tempfile
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sieve-tray-crowd-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _crowd_summary(result, lang) -> dict:
    """Map a sieve_crowd Result to a flat summary dict the GUI can
    surface directly.

    Refused runs carry no privacy/result numbers (their receipt has
    none), so those keys come back as None; records_in survives
    because every receipt reports it. after_alone is the crowd's
    records_alone_in_crowd figure - the "After:" number in the
    receipt text - i.e. records still alone on the qi columns after
    generalization and suppression.
    """
    d = result.report.data
    privacy = d.get("privacy") or {}
    res = d.get("result") or {}
    return {
        "ok": result.status == "anonymized",
        "status": result.status,
        "reason": d.get("reason"),
        "header": result.header,
        "rows": result.rows,
        "report_text": result.report.text(lang),
        "report_json": result.report.to_json(),
        "records_in": d.get("input", {}).get("records"),
        "records_out": res.get("records_out"),
        "suppressed": res.get("suppressed"),
        "k_requested": privacy.get("k_requested"),
        "k_achieved": privacy.get("k_achieved"),
        "max_risk": privacy.get("max_risk"),
        "avg_risk": privacy.get("average_risk"),
        "before_alone": privacy.get("before", {}).get("records_alone"),
        "after_alone": privacy.get("records_alone_in_crowd"),
        "io": d.get("io"),
    }


def crowd_dry_run(header, rows, cfg, lang="en") -> dict:
    """Dry-run measure: run the crowd engine without writing output.

    Returns the same summary dict as crowd_anonymize, including the
    before/after alone counts (before_alone / after_alone). lang (en
    or ja) picks the receipt language.
    """
    from sieve_crowd import anonymize
    return _crowd_summary(anonymize(header, rows, cfg), lang)


def crowd_anonymize(header, rows, cfg, *, io=None, output_path=None,
                    lang="en") -> dict:
    """Run the crowd engine and return a summary dict for the GUI.

    output_path, when given, is written only for status='anonymized':
    the format is chosen from the file extension and the bytes are
    written atomically. A refused run never touches the disk. io is
    the (input_format, output_format) pair recorded in the receipt.
    lang (en or ja) picks the receipt language.
    """
    from sieve_crowd import anonymize
    from sieve_crowd.tableio import detect_format, write_any
    result = anonymize(header, rows, cfg, io=io)
    if output_path is not None and result.status == "anonymized":
        fmt = detect_format(Path(output_path).suffix)
        _crowd_atomic_write(output_path, write_any(result.header, result.rows, fmt))
    return _crowd_summary(result, lang)


# ---------------------------------------------------------------------------
# v1.4.0 (design §3.1): the table observation (scan).  The Crowd tab can
# open Crowd 0.9.0's one-page HTML view of the current table in the
# system browser.  Tray never post-processes the bytes: the vendored CLI
# command writes them, so the output is byte-identical to
# `python -m sieve_crowd scan` for the same input, language and
# configuration (TR4-T01).  The HTML never enters the history; the temp
# file is user-only (0600) and swept at the next start or removed at exit.
# ---------------------------------------------------------------------------

SCAN_TEMP_PREFIX = "sieve_tray_scan_"


def _scan_namespace(input_path, *, lang, config_path, output):
    """The argparse namespace the vendored scan command reads (the CLI
    defaults: no --delimiter/--encoding/--sheet/--hint-pack, builtin
    hints on, derived + hidden chars on, --max-rows 200000)."""
    import argparse
    return argparse.Namespace(
        input=str(input_path), output=str(output) if output else None,
        config=str(config_path) if config_path else None,
        delimiter=None, in_format=None, encoding=None, sheet=None,
        hint_pack=None, no_builtin_hints=False, no_hidden_chars=False,
        subject=None, k=None, max_rows=200_000, no_derived=False,
        lang=lang)


def crowd_scan_bytes(input_path, *, lang="en", config_path=None) -> bytes:
    """Run Crowd 0.9.0's scan and return the HTML bytes.

    The input is first read through the same steps the CLI command uses
    (resolve format -> pre-refuse -> read -> read table), so a refused
    input raises InputRefused with its closed-vocabulary code before the
    command turns it into an exit code - the GUI shows the code wording
    and never a traceback or a value.  The HTML itself is written by the
    vendored ``sieve_crowd.cli._cmd_scan`` into a private user-only temp
    file and read back, which makes the bytes identical to the CLI
    output by construction (TR4-T01).  Configuration or pack errors
    raise ConfigError; I/O errors propagate as OSError.
    """
    import contextlib
    import io
    import tempfile
    from sieve_crowd import ConfigError
    from sieve_crowd.cli import (_cmd_scan, _pre_refuse, _read,
                                 _read_table, _resolve_format)
    ns = _scan_namespace(input_path, lang=lang, config_path=config_path,
                         output=None)
    in_fmt = _resolve_format(ns.input, None, dash_default="csv")
    _pre_refuse(ns, in_fmt)
    with contextlib.redirect_stderr(io.StringIO()):
        data = _read(ns.input)
        _read_table(ns, data, in_fmt, None)
    fd, tmp = tempfile.mkstemp(prefix=SCAN_TEMP_PREFIX, suffix=".html")
    os.close(fd)
    try:
        rc = _cmd_scan(_scan_namespace(input_path, lang=lang,
                                       config_path=config_path, output=tmp))
        if rc != 0:
            raise ConfigError(
                "the scan was refused (command exit code %d)" % rc)
        with open(tmp, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def new_scan_temp_file(data: bytes, directory=None) -> Path:
    """Write the scan HTML bytes to a user-only temp file; return it.

    mkstemp creates the file with mode 0600 (on Windows the profile's
    %TEMP% directory is already user-only), so only the user can read
    it.  The caller tracks the returned path: the GUI removes it at
    exit and the next start sweeps any leftover carrying the prefix.
    """
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=SCAN_TEMP_PREFIX, suffix=".html",
                               dir=str(directory) if directory else None)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return Path(tmp)


def sweep_scan_temp_files(directory=None) -> int:
    """Next-start cleanup: remove leftover scan temp files (only the
    ones carrying SCAN_TEMP_PREFIX); return the number removed."""
    import glob
    import tempfile
    base = str(directory) if directory else tempfile.gettempdir()
    removed = 0
    for path in glob.glob(os.path.join(base, SCAN_TEMP_PREFIX + "*.html")):
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            pass
    return removed


def remove_scan_temp_file(path) -> None:
    """Exit-time cleanup: best-effort removal of one tracked temp file."""
    try:
        os.unlink(str(path))
    except OSError:
        pass


def open_in_browser(path) -> None:
    """Open a local file in the system's default browser (a file: URI -
    no network).  A thin wrapper so tests can intercept the call."""
    webbrowser.open(Path(path).absolute().as_uri())


def save_scan_html(target, data: bytes) -> None:
    """Write the generated bytes unchanged to the user-chosen path."""
    Path(target).write_bytes(data)


def crowd_scan_open(input_path, *, lang="en", config_path=None,
                    directory=None) -> Path:
    """The whole scan flow: generate the bytes, write the user-only
    temp file and open it in the default browser.  Returns the temp
    file path (the caller tracks it for the exit-time removal)."""
    data = crowd_scan_bytes(input_path, lang=lang, config_path=config_path)
    p = new_scan_temp_file(data, directory=directory)
    open_in_browser(p)
    return p

def run_scan(input_dir: Path,
             progress: ProgressCallback = _silent,
             audit_modifier_vocab: Optional[str] = None,
             groups: Optional[List[Tuple[str, List[Path]]]] = None) -> ScanResult:
    """Core entry point. Scans input_dir and returns a ScanResult.

    This is the single function a GUI needs to call; it does no I/O
    other than reading the input files, and reports status purely
    through `progress` rather than printing directly, so it is safe
    to call from a background/worker thread.

    audit_modifier_vocab (v0.8.0): path to a modifier-vocab file for
    the quantifier audit lane. None = use the bundled default
    (DEFAULT_MODIFIER_VOCAB_PATH, shipped with the package). An empty
    string disables the override and falls back to the bundled default
    as well. A non-empty path is read line-by-line (see _load_modifier_vocab).

    groups (v0.9.0): optional explicit list of (group_name, files) to
    scan instead of discovering groups from input_dir subdirectories.
    When provided, scan(input_dir) is skipped and the supplied groups
    are used directly - this enables file-selection mode where the GUI
    passes a single group of user-picked files (any suffix). When None
    (default), behavior is unchanged from v0.8.0 (subdirectory scan).
    """
    if groups is None:
        # v1.1.0: the walk itself is symlink-safe and reports links and
        # special files as unobserved entries (design doc §3.4).
        groups = []
        unobserved_entries: List[dict] = []
        for d in sorted(input_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            files, entries = _walk_group(d)
            if files:
                groups.append((d.name, files))
            unobserved_entries.extend(entries)
    else:
        unobserved_entries = []
    progress(f"Found {len(groups)} groups.")

    def _unobserved(f: Path, engine: str, reason: str,
                    detail: Optional[str] = None) -> None:
        unobserved_entries.append({"file": _posix(f), "engine": engine,
                                   "reason": reason, "detail": detail})

    code_map: Dict[str, str] = {}
    text_map: Dict[str, str] = {}
    all_docs: List[Path] = []
    for name, files in groups:
        code, doc = split_files(files)
        for f in code:
            key = f"{name}/{f.name}"
            # v1.1.0 (design doc §3.3/§3.4): never open links or special files;
            # cap Tray's own reads; keep unparseable and empty sources
            # visible instead of silently dropping them.
            if f.is_symlink():
                _unobserved(f, "tray", "symlink_skipped")
                continue
            if not f.is_file():
                _unobserved(f, "tray", "unreadable")
                continue
            try:
                text, err = _read_limited(f)
            except OSError:
                _unobserved(f, "scope", "unreadable")
                continue
            if err == "too_large":
                _unobserved(f, "scope", "too_large")
                continue
            if err == "unsupported_encoding":
                # v1.3.0 (design doc §3.5): the file is neither UTF-8
                # (BOM included) nor CP932 - nothing was read into the
                # results, no replacement characters were produced.
                _unobserved(f, "scope", "refused",
                            detail="unsupported_encoding")
                continue
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError):
                _unobserved(f, "scope", "parse_failed")
                continue
            if len(tree.body) == 0:
                # Empty or comment/whitespace-only source: comparing it
                # would fabricate a fake "similar" pair (design doc §3.3).
                _unobserved(f, "scope", "not_applicable")
                continue
            code_map[key] = text
        for f in doc:
            if f.suffix.lower() in TEXT_EXTS:
                key = f"{name}/{f.name}"
                if f.is_symlink():
                    _unobserved(f, "tray", "symlink_skipped")
                    continue
                if not f.is_file():
                    _unobserved(f, "tray", "unreadable")
                    continue
                try:
                    text, err = _read_limited(f)
                except OSError:
                    _unobserved(f, "referee", "unreadable")
                    continue
                if err == "too_large":
                    _unobserved(f, "referee", "too_large")
                    continue
                if err == "unsupported_encoding":
                    # v1.3.0 (design doc §3.5): see the code branch above.
                    _unobserved(f, "referee", "refused",
                                detail="unsupported_encoding")
                    continue
                if text.strip() == "":
                    _unobserved(f, "referee", "empty_input")
                    continue
                text_map[key] = text
        all_docs.extend(doc)

    progress(f"Analyzing {len(all_docs)} documents...")
    doc_results = observe_documents(all_docs, progress)

    progress(f"Comparing {len(code_map)} code files...")
    code_pairs, short_circuited_excluded, scope_skipped = (
        _compare_code_detailed(code_map, progress))

    # v1.3.0: fold the engine's own skipped entries into the unobserved
    # list - engine reasons win over Tray's pre-classification on the
    # same path, so a file is never counted twice.
    unobserved_entries = _merge_unobserved(unobserved_entries,
                                           scope_skipped)

    progress(f"Comparing {len(text_map)} text files for similarity...")
    text_pairs = compare_text(text_map, progress)

    progress(f"Auditing {len(text_map)} text files for ungrounded universalization...")
    audit_results, _ = audit_text(text_map, audit_modifier_vocab, progress)

    return ScanResult(groups=groups, doc_results=doc_results,
                       code_pairs=code_pairs, text_pairs=text_pairs,
                       audit_results=audit_results,
                       unobserved=unobserved_entries,
                       short_circuited_excluded=short_circuited_excluded)


CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       max-width: 960px; margin: 2rem auto; padding: 0 1rem;
       color: #1a1a1a; background: #fafafa; }
h1 { font-size: 1.5rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }
th, td { text-align: left; padding: .5rem .8rem;
         border-bottom: 1px solid #eee; font-size: .9rem; }
th { background: #f0f0f0; }
tr.flagged { background: #fff5f5; }
code { font-family: Menlo, monospace; font-size: .85em; }
"""

# v1.1.0: the unobserved style is appended to the CSS only when the
# report actually contains unobserved items, so a report with none of
# them stays byte-identical to the pre-v1.1.0 output (TR-T12).
# v1.4.0 (design §3.2): the single gray becomes the three-stage set; the
# zero-unobserved case still emits nothing and keeps its v1.3.0 bytes.
def _unobserved_stage_css() -> str:
    return "\n" + "\n".join(
        "tr.unobserved-%s { background: %s; }"
        % (stage, UNOBSERVED_STAGE_BG[stage])
        for stage in ("remedy", "environment", "excluded"))


def _crowd_cell(value, *, md=False, quoted=False) -> str:
    """Format one crowd-run value for the report tables.

    None renders as the bare em dash the report already uses
    for empty values (never quoted). HTML cells are escaped;
    Markdown cells (md=True) escape pipes instead and may be
    wrapped in backticks (quoted=True) the way the other
    Markdown tables quote file paths.
    """
    if value is None:
        return "—"
    text = str(value)
    if md:
        text = text.replace("|", "\\|")
    return f"`{text}`" if quoted else html.escape(text)


def render(result: ScanResult) -> str:
    groups = result.groups
    doc_results, code_pairs, text_pairs = (
        result.doc_results, result.code_pairs, result.text_pairs)
    audit_results = result.audit_results

    # v1.1.0: the third state is read through the single classifier;
    # with zero unobserved items every byte matches v1.0.0 (TR-T12).
    statuses = [classify_observation(r) for r in doc_results]
    unobserved_total = (sum(1 for s in statuses if s[0] == "unobserved")
                        + len(result.unobserved))

    parts = ["<!DOCTYPE html>",
             "<html><head><meta charset='UTF-8'>",
             "<title>Sieve Tray Report</title>",
             f"<style>{CSS}{_unobserved_stage_css() if unobserved_total else ''}</style></head><body>",
             "<h1>Sieve Tray Report</h1>",
             f"<p>{len(groups)} groups scanned."
             f"{f' Unobserved: {unobserved_total}.' if unobserved_total else ''}</p>"]

    parts.append("<h2>Documents</h2>")
    if not doc_results:
        parts.append("<p>No documents analyzed.</p>")
    else:
        parts.append("<table><tr><th>File</th><th>Mask</th>"
                     "<th>Status</th></tr>")
        for r in doc_results:
            status, reason, detail = classify_observation(r)
            if status == "unobserved":
                cls = (" class='unobserved unobserved-%s'"
                       % unobserved_stage(reason))
                label = ("unobserved (%s)" %
                         (("%s: %s" % (reason, detail)) if detail else reason))
            else:
                cls = " class='flagged'" if status == "flagged" else ""
                label = status
            parts.append(
                f"<tr{cls}><td><code>{html.escape(r['path'])}</code></td>"
                f"<td><code>{html.escape(r['mask'])}</code></td>"
                f"<td>{label}</td></tr>"
            )
        parts.append("</table>")

    parts.append("<h2>Code Pairs</h2>")
    if not code_pairs:
        parts.append("<p>No suspicious code pairs.</p>")
    else:
        parts.append("<table><tr><th>File A</th><th>File B</th>"
                     "<th>Mask</th></tr>")
        for p in code_pairs:
            parts.append(
                f"<tr class='flagged'>"
                f"<td><code>{html.escape(p['a'])}</code></td>"
                f"<td><code>{html.escape(p['b'])}</code></td>"
                f"<td><code>{html.escape(p['mask'])}</code></td>"
                f"</tr>"
            )
        parts.append("</table>")
    if result.short_circuited_excluded:
        # v1.1.0 (design doc §3.2): the exclusion must remain visible in the
        # report even though the pairs themselves stay excluded.
        parts.append(
            f"<p>{result.short_circuited_excluded} code pair(s) skipped "
            "as trivially dissimilar (short-circuited).</p>")

    parts.append("<h2>Text Pairs</h2>")
    if not text_pairs:
        parts.append("<p>No suspicious text pairs.</p>")
    else:
        parts.append("<table><tr><th>File A</th><th>File B</th>"
                     "<th>Signal</th><th>Pattern</th></tr>")
        for p in text_pairs:
            parts.append(
                f"<tr class='flagged'>"
                f"<td><code>{html.escape(p['a'])}</code></td>"
                f"<td><code>{html.escape(p['b'])}</code></td>"
                f"<td>{html.escape(p['signal'])}</td>"
                f"<td>{html.escape(p['pattern_name'])}</td>"
                f"</tr>"
            )
        parts.append("</table>")

    parts.append("<h2>Quantifier Audit</h2>")
    if not audit_results:
        parts.append("<p>No flagged universalization candidates.</p>")
    else:
        parts.append(
            "<table><tr><th>File</th><th>Sentence</th>"
            "<th>Signal</th><th>Pattern</th><th>Backing</th>"
            "<th>Scope</th><th>Certainty</th></tr>")
        for a in audit_results:
            cls = " class='flagged'" if a["signal"] == "RED" else ""
            sentence = a.get("sentence_text") or a.get("sentence_sha256", "")[:16]
            certainty = ", ".join(a.get("certainty_markers", [])) or "—"
            parts.append(
                f"<tr{cls}>"
                f"<td><code>{html.escape(a['file'])}</code></td>"
                f"<td>{html.escape(sentence)}</td>"
                f"<td>{html.escape(a['signal'])}</td>"
                f"<td>{html.escape(a['pattern_name'])}</td>"
                f"<td>{html.escape(a['backing'])}</td>"
                f"<td>{html.escape(a['scope'])}</td>"
                f"<td>{html.escape(certainty)}</td>"
                f"</tr>"
            )
        parts.append("</table>")

    if unobserved_total:
        from sieve_tray_i18n import tr
        parts.append("<h2>Unobserved</h2>")
        parts.append(f"<p>{html.escape(tr('en', 'unobserved_note'))}</p>")
        parts.append("<table><tr><th>File</th><th>Engine</th>"
                     "<th>Reason</th><th>Detail</th></tr>")
        for r, (status, reason, detail) in zip(doc_results, statuses):
            if status != "unobserved":
                continue
            parts.append(
                f"<tr class='unobserved unobserved-{unobserved_stage(reason)}'>"
                f"<td><code>{html.escape(r['path'])}</code></td>"
                f"<td>lens</td>"
                f"<td>{html.escape(reason)}</td>"
                f"<td>{html.escape(detail) if detail else '—'}</td></tr>"
            )
        for e in result.unobserved:
            detail = e.get("detail")
            stage = unobserved_stage(e.get("reason", ""))
            parts.append(
                f"<tr class='unobserved unobserved-{stage}'"
                f"><td><code>{html.escape(e.get('file', ''))}</code></td>"
                f"<td>{html.escape(e.get('engine', ''))}</td>"
                f"<td>{html.escape(e.get('reason', ''))}</td>"
                f"<td>{html.escape(detail) if detail else '—'}</td></tr>"
            )
        parts.append("</table>")

    if result.crowd_runs:
        from sieve_tray_i18n import tr
        parts.append("<h2>Crowd</h2>")
        parts.append(
            f"<p>{html.escape(tr('en', 'crowd_result_premise'))}</p>")
        parts.append(
            "<table><tr><th>Input</th><th>Output</th>"
            "<th>Records In</th><th>Records Out</th><th>Suppressed</th>"
            "<th>k Achieved</th><th>Max Risk</th><th>Avg Risk</th>"
            "<th>Status</th><th>Reason</th></tr>")
        for run in result.crowd_runs:
            parts.append(
                f"<tr><td>{_crowd_cell(run.get('input_path'))}</td>"
                f"<td>{_crowd_cell(run.get('output_path'))}</td>"
                f"<td>{_crowd_cell(run.get('records_in'))}</td>"
                f"<td>{_crowd_cell(run.get('records_out'))}</td>"
                f"<td>{_crowd_cell(run.get('suppressed'))}</td>"
                f"<td>{_crowd_cell(run.get('k_achieved'))}</td>"
                f"<td>{_crowd_cell(run.get('max_risk'))}</td>"
                f"<td>{_crowd_cell(run.get('avg_risk'))}</td>"
                f"<td>{_crowd_cell(run.get('status'))}</td>"
                f"<td>{_crowd_cell(run.get('reason'))}</td></tr>")
        parts.append("</table>")

    parts.append("<p style='margin-top:2rem;color:#666;font-size:.85rem;'>"
                 "This is an observation report, not a judgment. "
                 "Human review is required.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_text(result: ScanResult) -> str:
    """Render a ScanResult as Markdown (v0.9.0).

    Plain-text alternative to render() for users who want to read the
    report in a text editor, paste it into a code review, or version it
    in git. Markdown tables are used so the output renders on GitHub
    while remaining readable as plain text.
    """
    groups = result.groups
    doc_results, code_pairs, text_pairs = (
        result.doc_results, result.code_pairs, result.text_pairs)
    audit_results = result.audit_results

    # v1.1.0: same counts as render() - via the single classifier.
    statuses = [classify_observation(r) for r in doc_results]
    unobserved_total = (sum(1 for s in statuses if s[0] == "unobserved")
                        + len(result.unobserved))

    counts_line = f"{len(groups)} groups scanned"
    if unobserved_total:
        counts_line += f". Unobserved: {unobserved_total}"
    lines = ["# Sieve Tray Report", "", f"_{counts_line}._", ""]

    lines.append("## Documents")
    if not doc_results:
        lines.append("No documents analyzed.")
    else:
        lines.append("| File | Mask | Status |")
        lines.append("| --- | --- | --- |")
        for r in doc_results:
            status, reason, detail = classify_observation(r)
            if status == "unobserved":
                label = ("unobserved (%s)" %
                         (("%s: %s" % (reason, detail)) if detail else reason))
            else:
                label = status
            lines.append(f"| `{r['path']}` | `{r['mask']}` | {label} |")
    lines.append("")

    lines.append("## Code Pairs")
    if not code_pairs:
        lines.append("No suspicious code pairs.")
    else:
        lines.append("| File A | File B | Mask |")
        lines.append("| --- | --- | --- |")
        for p in code_pairs:
            lines.append(f"| `{p['a']}` | `{p['b']}` | `{p['mask']}` |")
    if result.short_circuited_excluded:
        lines.append("")
        lines.append(f"_{result.short_circuited_excluded} code pair(s) skipped "
                     "as trivially dissimilar (short-circuited)._")
    lines.append("")

    lines.append("## Text Pairs")
    if not text_pairs:
        lines.append("No suspicious text pairs.")
    else:
        lines.append("| File A | File B | Signal | Pattern |")
        lines.append("| --- | --- | --- | --- |")
        for p in text_pairs:
            lines.append(
                f"| `{p['a']}` | `{p['b']}` | {p['signal']} "
                f"| {p['pattern_name']} |")
    lines.append("")

    lines.append("## Quantifier Audit")
    if not audit_results:
        lines.append("No flagged universalization candidates.")
    else:
        lines.append("| File | Sentence | Signal | Pattern | Backing "
                     "| Scope | Certainty |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for a in audit_results:
            sentence = a.get("sentence_text") or a.get("sentence_sha256", "")[:16]
            # Escape pipes in cell content so the Markdown table doesn't break.
            sentence = sentence.replace("|", "\\|")
            certainty = ", ".join(a.get("certainty_markers", [])) or "—"
            lines.append(
                f"| `{a['file']}` | {sentence} | {a['signal']} "
                f"| {a['pattern_name']} | {a['backing']} | {a['scope']} "
                f"| {certainty} |")
    lines.append("")

    if unobserved_total:
        from sieve_tray_i18n import tr
        lines.append("## Unobserved")
        lines.append("")
        lines.append(tr("en", "unobserved_note"))
        lines.append("")
        lines.append("| File | Engine | Reason | Detail |")
        lines.append("| --- | --- | --- | --- |")
        for r, (status, reason, detail) in zip(doc_results, statuses):
            if status != "unobserved":
                continue
            lines.append(f"| `{r['path']}` | lens | {reason} "
                         f"| {detail if detail else '—'} |")
        for e in result.unobserved:
            detail = e.get("detail")
            lines.append(f"| `{e.get('file', '')}` | {e.get('engine', '')} "
                         f"| {e.get('reason', '')} | {detail if detail else '—'} |")
        lines.append("")

    if result.crowd_runs:
        from sieve_tray_i18n import tr
        lines.append("## Crowd")
        lines.append("")
        lines.append(tr("en", "crowd_result_premise"))
        lines.append("")
        lines.append(
            "| Input | Output | Records In | Records Out | Suppressed"
            " | k Achieved | Max Risk | Avg Risk | Status | Reason |")
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for run in result.crowd_runs:
            lines.append(
                f"| {_crowd_cell(run.get('input_path'), md=True, quoted=True)} "
                f"| {_crowd_cell(run.get('output_path'), md=True, quoted=True)} "
                f"| {_crowd_cell(run.get('records_in'), md=True)} "
                f"| {_crowd_cell(run.get('records_out'), md=True)} "
                f"| {_crowd_cell(run.get('suppressed'), md=True)} "
                f"| {_crowd_cell(run.get('k_achieved'), md=True)} "
                f"| {_crowd_cell(run.get('max_risk'), md=True)} "
                f"| {_crowd_cell(run.get('avg_risk'), md=True)} "
                f"| {_crowd_cell(run.get('status'), md=True)} "
                f"| {_crowd_cell(run.get('reason'), md=True)} |")
        lines.append("")

    lines.append("_This is an observation report, not a judgment. "
                 "Human review is required._")
    return "\n".join(lines)


# ===========================================================================
# v2.0.0 (M1 Gate): the pre-handoff quarantine, anonymization and receipt
# lane (request doc §3.1-§3.6, rev. 2026-11-08, plus the 2026-11-08
# design review ruling).
#
# Gate walks a folder and, per item: decides the lane -> observes ->
# treats -> writes.  Documents yield only their visible text (strip of
# the five invisible kinds), personal data is replaced with sequential
# labels (Redact, mode label), the hidden text is observed by Order,
# and the output is split into handoff/ (what gets passed on) and
# local/ (what stays here).  The normalized receipt is written last.
#
# Closed vocabularies (extending any of them stops the implementation):
#   - not_produced reasons (6): needs_settings / unobserved /
#     not_applicable / engine_unavailable / engine_refused / write_failed
#   - verification item reasons (7) and not_verifiable reasons (5),
#     in verify_gate below.
#
# HTML lane (§3.2 as amended, measured in the M1 gate round): core Lens does
# NOT detect <style>-rule hiding, so Gate uses the extras lane
# (sieve_lens_ext.html_css_selectors) with a charset pre-check done
# here first.  The extras lane reports a rule match as a css_hidden
# segment whose location carries "selector:" while its body emitter
# still marks the matched body visible - so Gate fails closed: any
# rule-originated css_hidden segment makes the item not_produced
# (engine_refused) and its visible text is never written to handoff/.
# Without the extras lane the HTML is not_produced (engine_unavailable).
# ===========================================================================

GATE_RECEIPT_VERSION = 1
GATE_KIND = "sieve-gate"
# The repository root (sieve_tray.py sits at the root): used for the
# vendored-module hashes and the bundled sample pack.
REPO_ROOT = Path(__file__).resolve().parent
GATE_OUTPUT_SUFFIX = ".visible.txt"
GATE_ORDER_MAX_CHARS = 10000
GATE_ORDER_MAX_SEGMENTS = 500
GATE_DEFAULT_BUILTINS = ("email", "phone-jp", "postal-jp")
GATE_REDACT_MODE = "label"
GATE_ORDER_VERSION = "1.1.0"
GATE_HTML_RULE_MARKER = "selector:"

# The five default strip kinds (request §3.2/§3.7-1), in receipt order.
GATE_STRIP_KINDS = ("zero_width_space", "word_joiner", "bom_mid_text",
                    "bidi_control", "tag_chars")

NOT_PRODUCED_REASONS = frozenset({
    "needs_settings", "unobserved", "not_applicable",
    "engine_unavailable", "engine_refused", "write_failed"})

# Fixed stage per reason; "unobserved" resolves through the item's own
# unobserved_reason via the existing 8-reason stages (§3.2: no new colors).
NOT_PRODUCED_STAGE = {
    "needs_settings": "remedy",
    "not_applicable": "excluded",
    "engine_unavailable": "environment",
    "engine_refused": "remedy",
    "write_failed": "remedy",
}

# Gate lane suffixes (request §3.2).  .pdf rides the document lane only
# when the Lens extras carry it; without extras nothing observes it.
GATE_DOC_EXTS = {".docx", ".html", ".htm", ".md", ".txt", ".pdf"}
GATE_TABLE_EXTS = {".csv", ".xlsx"}
GATE_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp",
                   ".tif", ".tiff", ".webp"}


def not_produced_stage(reason: str, unobserved_reason=None) -> str:
    """One stage per not_produced reason (request §3.2).

    "unobserved" takes the stage of the item's own unobserved_reason
    (the existing three-stage mapping of the 8-reason vocabulary).
    Unknown values raise ValueError - a new reason has to join the
    closed tables first.
    """
    if reason == "unobserved":
        if unobserved_reason is None:
            raise ValueError("unobserved needs unobserved_reason")
        return unobserved_stage(unobserved_reason)
    if reason in NOT_PRODUCED_STAGE:
        return NOT_PRODUCED_STAGE[reason]
    raise ValueError("unknown not_produced reason: %r" % (reason,))


def _gate_hidden():
    return {"count": 0, "order_observed": 0, "order_axes": {},
            "truncated": 0, "skipped": 0}


def _gate_removed_zero():
    return {k: 0 for k in GATE_STRIP_KINDS}


def _gate_norm_json(obj) -> str:
    """The normalized JSON of one receipt (request §3.4): UTF-8, keys
    sorted, no spaces, ensure_ascii=False, no floats, one trailing LF."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n"


def _gate_digest(receipt: dict) -> str:
    """sha256 over the normalized body without the digest key."""
    body = {k: v for k, v in receipt.items() if k != "digest"}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _gate_write_atomic(path: Path, data: bytes) -> None:
    """Write via a temp file, then rename (request §3.1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp-gate")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(path))


def _gate_rel_sort_key(rel: str) -> bytes:
    return rel.encode("utf-8")


def _gate_walk(input_dir: Path):
    """Relative (POSIX, as the OS returns it) paths of every regular
    file under input_dir, sorted by their UTF-8 bytes.  Symlinks stay
    in the list as items (they are never followed); directories and
    special files do not."""
    items = []
    for root, dirs, names in os.walk(input_dir, followlinks=False):
        dirs.sort()
        for name in names:
            p = Path(root) / name
            rel = p.relative_to(input_dir)
            items.append(rel.as_posix() if rel.as_posix() != str(rel)
                         else str(rel).replace(os.sep, "/"))
    items.sort(key=_gate_rel_sort_key)
    return items


# ------------------------------------------------------------------------
# Seal 2.2 shared parts: the hash tree (the whole-folder checksum) and
# the check_code section.  The byte-level spec is docs/manifest-format.md;
# SL-T01 reads the two known values back from that document, so the
# document and this implementation cannot drift apart.

def _seal_tree_rows(folder: Path):
    """One row per child that is a regular file or a directory, mixed
    into ONE list sorted by (UTF-8 name bytes, kind byte d < f):

        kind NUL name NUL child-checksum LF

    kind is b"f" for a file (child checksum = SHA-256 of the bytes) and
    b"d" for a directory (child checksum = the same calculation applied
    recursively; an empty directory hashes to SHA-256(b"")).  Names are
    used as-is - NFC is never applied - and carried as UTF-8 bytes
    (surrogateescape gives back the raw bytes of a non-UTF-8 name).
    Symlinks and special files carry no row; a file that cannot be read
    and a directory that cannot be listed carry no row either (the
    manifest lane records them in skipped).
    """
    rows = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None  # unlistable: no row for this directory
    entries = []
    for name in names:
        p = folder / name
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat_module.S_ISDIR(st.st_mode):
            entries.append((name.encode("utf-8", "surrogateescape"),
                            b"d", p))
        elif stat_module.S_ISREG(st.st_mode):
            entries.append((name.encode("utf-8", "surrogateescape"),
                            b"f", p))
        # symlinks and special files carry no row
    entries.sort(key=lambda t: (t[0], t[1]))
    for name_bytes, kind, p in entries:
        if kind == b"d":
            sub = _seal_tree_rows(p)
            if sub is None:
                continue  # unlistable directory: no row
            child = hashlib.sha256(b"".join(sub)).hexdigest()
        else:
            try:
                digest = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        digest.update(chunk)
                child = digest.hexdigest()
            except OSError:
                continue  # unreadable: no row here; skipped records why
        rows.append(kind + b"\x00" + name_bytes + b"\x00"
                    + child.encode("ascii") + b"\n")
    return rows


def _seal_overall_sha256(folder: Path) -> str:
    """The whole-folder checksum: SHA-256 over the concatenated rows of
    the folder (docs/manifest-format.md section 1).  An empty folder is
    SHA-256(b"")."""
    rows = _seal_tree_rows(folder)
    if rows is None:
        rows = []  # an unlistable root hashes like an empty one
    return hashlib.sha256(b"".join(rows)).hexdigest()


_SEAL_CHECK_KEY_ID_LABEL = b"sieve-check-key-id"


def _seal_check_key_id(key: bytes) -> str:
    """The key identifier: HMAC-SHA256(key, "sieve-check-key-id"),
    first 8 bytes, 16 lowercase hex characters."""
    return hmac.new(key, _SEAL_CHECK_KEY_ID_LABEL,
                    hashlib.sha256).hexdigest()[:16]


def _seal_check_code(key: bytes, overall_sha256: str, receipt: dict) -> str:
    """The check code: HMAC-SHA256 over

        overall_sha256 ASCII (64 bytes) + b":" + canonical JSON of the
        receipt minus the check_code section and the digest

    The canonical JSON is the same byte string the digest recomputation
    uses (sorted keys, no spaces, ensure_ascii=False, NO trailing LF -
    the written file has one, the message does not).  Adding the
    check_code section therefore keeps the digest of a pre-existing
    receipt stable: _gate_digest hashes every key except digest.
    """
    body = {k: v for k, v in receipt.items()
            if k not in ("check_code", "digest")}
    blob = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    msg = overall_sha256.encode("ascii") + b":" + blob
    return "hmac-sha256:" + hmac.new(key, msg,
                                     hashlib.sha256).hexdigest()


# ------------------------------------------------------------------------
# Seal 2.2 / S2: the manifest command (request 3.1 M1-M11).  The file
# list of a folder, its duplicates, and the diff against a second
# folder.  Spec: docs/manifest-format.md (sections 1, 2 and 5).

def _seal_rel_of(root: Path, full: Path) -> str:
    """The relative POSIX form of a walked path (request 3.1 M1)."""
    return full.relative_to(root).as_posix()


def _seal_path_json(rel: str, extra: Optional[dict] = None) -> dict:
    """One path field for the receipt JSON.  Paths are used as-is (NFC
    is never applied); a path that is not valid UTF-8 cannot ride in a
    JSON string, so it is recorded as path: null plus path_hex (the
    raw bytes in hex) - the same treatment audit-names uses."""
    entry = {} if extra is None else dict(extra)
    try:
        rel.encode("utf-8")
        entry["path"] = rel
    except UnicodeEncodeError:
        entry["path"] = None
        entry["path_hex"] = rel.encode("utf-8",
                                       "surrogateescape").hex()
    return entry


def _seal_path_sort_key(rel: str) -> bytes:
    return rel.encode("utf-8", "surrogateescape")


def _seal_manifest_scan(root: Path):
    """One walk over the tree: (items, skipped).  Items are the regular
    files ({path / path_hex, bytes, sha256} + the private _abs path);
    skipped carries every symlink (symlink_skipped), every non-regular
    special file (not_applicable) and every file or directory that
    cannot be read (unreadable) - closed vocabulary only, one walk."""
    items, skipped = [], []

    def _unlistable(err):
        rel = err.filename
        try:
            rel = _seal_rel_of(root, Path(err.filename))
        except Exception:
            rel = str(err.filename)
        skipped.append(_seal_path_json(rel, {"reason": "unreadable"}))

    for dirpath, dirs, names in os.walk(root, topdown=True,
                                        followlinks=False, onerror=_unlistable):
        dirs.sort()
        names.sort()
        keep = []
        for name in dirs:
            full = Path(dirpath) / name
            rel = _seal_rel_of(root, full)
            if os.path.islink(full):
                skipped.append(_seal_path_json(
                    rel, {"reason": "symlink_skipped"}))
            else:
                keep.append(name)
        dirs[:] = keep
        for name in names:
            full = Path(dirpath) / name
            rel = _seal_rel_of(root, full)
            if os.path.islink(full):
                skipped.append(_seal_path_json(
                    rel, {"reason": "symlink_skipped"}))
                continue
            try:
                st = os.lstat(full)
                if not stat_module.S_ISREG(st.st_mode):
                    skipped.append(_seal_path_json(
                        rel, {"reason": "not_applicable"}))
                    continue
                digest = hashlib.sha256()
                size = 0
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        digest.update(chunk)
                        size += len(chunk)
            except OSError:
                skipped.append(_seal_path_json(
                    rel, {"reason": "unreadable"}))
                continue
            item = _seal_path_json(rel, {"bytes": size,
                                         "sha256": digest.hexdigest()})
            item["_abs"] = full
            items.append(item)
    items.sort(key=lambda it: _seal_path_sort_key(it["path"]
                                                  if it["path"] is not None
                                                  else it["path_hex"]))
    skipped.sort(key=lambda s: _seal_path_sort_key(s["path"]
                                                   if s["path"] is not None
                                                   else s["path_hex"]))
    return items, skipped


def _seal_bytes_equal(f1: Path, f2: Path) -> bool:
    """The byte comparison that confirms a duplicate group (M6): true
    only when both files carry the very same bytes."""
    try:
        with open(f1, "rb") as a, open(f2, "rb") as b:
            while True:
                ca = a.read(1 << 20)
                cb = b.read(1 << 20)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def _seal_duplicate_groups(items):
    """Complete duplicates: group the items by sha256, confirm every
    group by byte comparison (M6), and report the surviving groups with
    their ascending paths."""
    by_sha = {}
    for it in items:
        by_sha.setdefault(it["sha256"], []).append(it)
    groups = []
    for sha, cands in sorted(by_sha.items()):
        if len(cands) < 2:
            continue
        remaining = sorted(cands, key=lambda it: _seal_path_sort_key(
            it["path"] if it["path"] is not None else it["path_hex"]))
        while len(remaining) >= 2:
            ref = remaining[0]
            group = [ref]
            rest = []
            for c in remaining[1:]:
                if _seal_bytes_equal(ref["_abs"], c["_abs"]):
                    group.append(c)
                else:
                    rest.append(c)  # sha collision paranoia: re-group
            if len(group) >= 2:
                groups.append({
                    "sha256": sha,
                    "bytes": ref["bytes"],
                    "paths": [(it["path"] if it["path"] is not None else
                               {"path": None, "path_hex": it["path_hex"]})
                              for it in group],
                })
            remaining = rest
    return groups


_SEAL_DIFF_STATES = ("same", "changed", "removed", "added", "moved")


def run_manifest(input_dir, output_dir, against=None, key_file=None,
                 progress: Optional[Callable[[str], None]] = None) -> dict:
    """The `manifest` command (M10/M11): the file list of a folder
    (`items` + `skipped` + `duplicates` + the whole-folder checksum) or,
    with `against`, the diff receipt (the closed 5 states, moved pairs
    bound by the sha group, first pair in path order only).  The
    receipt is written LAST into handoff/; a manifest has no local
    tree.  --key-file adds the optional check_code section; the
    receipt_version stays 1."""
    tell = progress or (lambda _m: None)
    root = Path(input_dir)
    if not root.is_dir():
        raise ValueError("manifest: %s is not a directory" % root)
    out = Path(output_dir)
    key = None
    if key_file is not None:
        key = Path(key_file).read_bytes()

    if against is None:
        tell("Manifest: scanning %s" % root)
        items, skipped = _seal_manifest_scan(root)
        groups = _seal_duplicate_groups(items)
        overall = _seal_overall_sha256(root)
        receipt = {
            "receipt_version": 1,
            "kind": "sieve-manifest",
            "tool": {"name": "sieve-tray", "version": __version__},
            "engines": {},
            "settings": {"against": None},
            "items": [{k: v for k, v in it.items() if k != "_abs"}
                      for it in items],
            "skipped": skipped,
            "duplicates": groups,
            "summary": {
                "items": len(items),
                "skipped": len(skipped),
                "duplicate_groups": len(groups),
                "duplicate_files": sum(len(g["paths"]) for g in groups),
                "duplicate_bytes": sum(g["bytes"] * len(g["paths"])
                                       for g in groups),
                "overall_sha256": overall,
            },
        }
    else:
        root_b = Path(against)
        if not root_b.is_dir():
            raise ValueError("manifest: %s is not a directory" % root_b)
        tell("Manifest: diffing %s against %s" % (root, root_b))
        items_a, _skipped_a = _seal_manifest_scan(root)
        items_b, _skipped_b = _seal_manifest_scan(root_b)
        map_a = {(_seal_path_sort_key(it["path"]
                                       if it["path"] is not None
                                       else it["path_hex"])): it
                 for it in items_a}
        map_b = {(_seal_path_sort_key(it["path"]
                                       if it["path"] is not None
                                       else it["path_hex"])): it
                 for it in items_b}
        differences = []

        def _entry(state, it, extra=None):
            e = {"state": state}
            e.update({k: v for k, v in it.items() if k != "_abs"})
            if extra:
                e.update(extra)
            return e

        # 1) the moved pairs first: per sha group of removed-vs-added,
        #    only the FIRST pair in path ascending order; the leftovers
        #    keep their original state and a multi-candidate group
        #    adds one ambiguous_move
        rem_by_sha, add_by_sha = {}, {}
        for pb, it in map_a.items():
            if pb not in map_b:
                rem_by_sha.setdefault(it["sha256"], []).append(pb)
        for pb, it in map_b.items():
            if pb not in map_a:
                add_by_sha.setdefault(it["sha256"], []).append(pb)
        paired_a, paired_b = set(), set()
        ambiguous = 0
        for sha in sorted(set(rem_by_sha) & set(add_by_sha)):
            rem = sorted(rem_by_sha[sha])
            add = sorted(add_by_sha[sha])
            paired_a.add(rem[0])
            paired_b.add(add[0])
            entry = _entry("moved", map_a[rem[0]], {})
            it_b = map_b[add[0]]
            if it_b["path"] is None:
                entry["path_b"] = None
                entry["path_b_hex"] = it_b["path_hex"]
            else:
                entry["path_b"] = it_b["path"]
            differences.append((0, rem[0], entry))
            if len(rem) >= 2 or len(add) >= 2:
                ambiguous += 1
        # 2) the A-side states (a path already moved does not reappear)
        for pb, it in map_a.items():
            if pb in paired_a:
                continue
            if pb not in map_b:
                differences.append((0, pb, _entry("removed", it)))
            elif map_b[pb]["sha256"] == it["sha256"]:
                differences.append((0, pb, _entry("same", it)))
            else:
                differences.append((0, pb, _entry("changed", it, {
                    "sha256_a": it["sha256"],
                    "sha256_b": map_b[pb]["sha256"]})))
        # 3) the added paths that no moved pair consumed
        for pb, it in map_b.items():
            if pb not in map_a and pb not in paired_b:
                differences.append((1, pb, _entry("added", it)))
        # order: A-side entries by their A path bytes; added entries by
        # their B path bytes after them (both deterministic)
        differences.sort(key=lambda t: (t[0], t[1]))
        counts = {s: 0 for s in _SEAL_DIFF_STATES}
        for _side, _pb, e in differences:
            counts[e["state"]] += 1
        receipt = {
            "receipt_version": 1,
            "kind": "sieve-manifest-diff",
            "tool": {"name": "sieve-tray", "version": __version__},
            "engines": {},
            "settings": {"against": str(root_b),
                         "overall_b": _seal_overall_sha256(root_b)},
            "items": [],
            "skipped": [],
            "duplicates": [],
            "differences": [e for _s, _p, e in differences],
            "summary": {
                "items": len(differences),
                "same": counts["same"],
                "changed": counts["changed"],
                "removed": counts["removed"],
                "added": counts["added"],
                "moved": counts["moved"],
                "ambiguous_move": ambiguous,
                "overall_sha256": _seal_overall_sha256(root),
            },
        }

    if key is not None:
        receipt["check_code"] = {
            "key_id": _seal_check_key_id(key),
            "value": _seal_check_code(
                key, receipt["summary"]["overall_sha256"], receipt),
        }
    receipt["digest"] = _gate_digest(receipt)
    _gate_write_atomic(out / "handoff" / "manifest-receipt.json",
                       _gate_norm_json(receipt).encode("utf-8"))
    tell("Manifest: receipt %s"
         % (out / "handoff" / "manifest-receipt.json"))
    return receipt


def _gate_charset_check(data: bytes):
    """The series policy (request §3.2, measured against Crowd 0.9.0):
    UTF-8 BOM -> strict UTF-8 -> strict CP932; UTF-16/32 BOMs are
    refused; no errors="replace".  Returns (text, encoding_name) or
    (None, None) when refused."""
    if data.startswith(b"\x00\x00\xfe\xff") or \
            data.startswith(b"\xff\xfe\x00\x00") or \
            data.startswith(b"\xfe\xff") or data.startswith(b"\xff\xfe"):
        return None, None
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig"), "utf-8-sig"
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp932"), "cp932"
    except UnicodeDecodeError:
        return None, None


def _gate_html_lane_ready() -> bool:
    """The extras lane is usable only when html_css_selectors AND
    cssselect2 import (measured: without cssselect2 the extractor
    degrades silently to no rule detection)."""
    try:
        import sieve_lens_ext.html_css_selectors as _sel  # noqa: F401
    except ImportError:
        return False
    import sys as _sys
    mod = _sys.modules.get("sieve_lens_ext.html_css_selectors")
    if mod is None or not getattr(mod, "CSSSELECT2_AVAILABLE", False):
        return False
    return True


def _gate_build_engine():
    """A Lens engine with every available extras installed (same order
    contract as observe_documents)."""
    from sieve_lens import SieveLensEngine
    import importlib
    engine = SieveLensEngine()
    for spec in ("sieve_lens_ext.pdf:install",
                 "sieve_lens_ext.ocr:install",
                 "sieve_lens_ext.image_layers:install",
                 "sieve_lens_ext.html_css:install",
                 "sieve_lens_ext.html_css_selectors:install",
                 "sieve_lens_ext.pdf_images:install"):
        mod_name, _, fn_name = spec.partition(":")
        try:
            getattr(importlib.import_module(mod_name), fn_name)(engine)
        except Exception:
            pass
    return engine


def _gate_engine_table() -> list:
    """The engines block of the receipt: name, version, source,
    file_sha256 (request §3.4)."""
    engines = []
    try:
        import sieve_lens as _lens
        v = _lens.__version__
        sha = hashlib.sha256(
            Path(_lens.__file__).read_bytes()).hexdigest()
        engines.append({"name": "sieve-lens", "version": v,
                        "source": "pip", "file_sha256": sha})
    except Exception:
        engines.append({"name": "sieve-lens", "version": None,
                        "source": "pip", "file_sha256": None})
    for name, module_name, version, rel in (
            ("sieve-redact", "sieve_redact", None, "sieve_redact.py"),
            ("sieve-crowd", "sieve_crowd", None, None)):
        try:
            mod = __import__(module_name)
            if version is None:
                version = getattr(mod, "VERSION", None) or \
                    getattr(mod, "__version__", None)
            if rel is not None:
                sha = hashlib.sha256(
                    (REPO_ROOT / rel).read_bytes()).hexdigest()
            else:
                sha = hashlib.sha256(
                    Path(mod.__file__).read_bytes()).hexdigest()
            engines.append({"name": name, "version": version,
                            "source": "vendored", "file_sha256": sha})
        except Exception:
            engines.append({"name": name, "version": None,
                            "source": "vendored", "file_sha256": None})
    try:
        import sieve_order as _order  # vendored package
        sha = hashlib.sha256(
            Path(_order.observer.__file__).read_bytes()).hexdigest()
        engines.append({"name": "sieve-order", "version": GATE_ORDER_VERSION,
                        "source": "vendored", "file_sha256": sha})
    except Exception:
        engines.append({"name": "sieve-order", "version": GATE_ORDER_VERSION,
                        "source": "vendored", "file_sha256": None})
    # v2.1.0 (M2 Cohort): the Cohort receipt's engines resolve against
    # this table (the verification's drift check), so the comparison
    # engines join it here.
    for name in ("sieve-referee", "sieve-scope"):
        try:
            mod = __import__(name.replace("-", "_"))
            engines.append({"name": name,
                            "version": getattr(mod, "__version__", None),
                            "source": "pip", "file_sha256": None})
        except Exception:
            engines.append({"name": name, "version": None,
                            "source": "pip", "file_sha256": None})
    return engines


def _gate_engines_version() -> str:
    return "; ".join("%s %s" % (e["name"], e["version"])
                     for e in _gate_engine_table())


def _gate_order_observe(text: str) -> dict:
    """Order on one hidden segment, capped at the §3.3 limits.
    Returns {"observed": bool, "axes": {...}, "truncated": bool}."""
    truncated = len(text) > GATE_ORDER_MAX_CHARS
    slice_ = text[:GATE_ORDER_MAX_CHARS]
    import sieve_order
    obs = sieve_order.observe(slice_, rules=None)
    axes: Dict[str, int] = {}
    for e in obs.evidence:
        axes[e.axis] = axes.get(e.axis, 0) + 1
    return {"observed": True, "axes": axes, "truncated": truncated}


def _gate_classify_hidden(segments) -> Tuple[list, list]:
    """Split not-visible segments into (orderable, rule_hidden).

    orderable  - hidden text segments the Order lane may read (bodies
                 whose hiding was decided per element: inline style,
                 hidden attribute, docx concealment, comments, ...).
    rule_hidden - css_hidden segments whose location carries the
                 "selector:" marker: a <style>-rule matched something,
                 but the extras body emitter still marks that body
                 visible -> the item must fail closed (measured).
    """
    orderable, rule_hidden = [], []
    for s in segments:
        if s.visible:
            continue
        if (s.kind == "css_hidden"
                and GATE_HTML_RULE_MARKER in (s.location or "")):
            rule_hidden.append(s)
        else:
            orderable.append(s)
    return orderable, rule_hidden


def _gate_order_on_hidden(orderable) -> dict:
    """Observe up to GATE_ORDER_MAX_SEGMENTS hidden segments with
    Order; record truncations and skips (request §3.3)."""
    hidden = _gate_hidden()
    hidden["count"] = len(orderable)  # caller may extend by rule_hidden
    observed = 0
    axes: Dict[str, int] = {}
    for seg in orderable:
        if observed >= GATE_ORDER_MAX_SEGMENTS:
            hidden["skipped"] += 1
            continue
        try:
            res = _gate_order_observe(seg.text)
        except Exception:
            # §3.3: an Order exception leaves the Order observation of
            # this document unobserved (engine_unavailable) and the run
            # continues.
            hidden["order_observed"] = 0
            hidden["order_axes"] = {}
            return hidden
        observed += 1
        if res["truncated"]:
            hidden["truncated"] += 1
        for axis, n in res["axes"].items():
            axes[axis] = axes.get(axis, 0) + n
    hidden["order_observed"] = observed
    hidden["order_axes"] = dict(sorted(axes.items()))
    return hidden


def _gate_redact_apply(text: str, *, builtins, mode, config_path,
                       receipts_dir: Optional[Path], seq: int):
    """Apply Redact through the same call path the Sanitize tab uses
    (sieve_redact.main with SystemExit captured).  Returns
    (out_text, receipt, redactions) or (None, None, engine_detail)
    when the engine refuses.  The machine receipt (with content_sha256)
    is stored under local/ only."""
    try:
        import sieve_redact
    except ImportError:
        return None, None, "sieve-redact missing"
    import contextlib
    import io as _io
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.txt"
        src.write_text(text, encoding="utf-8")
        out = Path(td) / "out.txt"
        rec = Path(td) / "receipt.json"
        argv = [str(src), "-o", str(out)]
        if config_path is not None:
            argv += ["--config", str(config_path)]
        else:
            for name in builtins:
                argv += ["--builtin", f"{name}:{mode}"]
        argv += ["--receipt", str(rec)]
        out_buf, err_buf = _io.StringIO(), _io.StringIO()
        rc = None
        try:
            with contextlib.redirect_stdout(out_buf), \
                    contextlib.redirect_stderr(err_buf):
                rc = sieve_redact.main(argv)
        except SystemExit as exc:
            code = exc.code
            if code is None:
                rc = 0
            elif isinstance(code, int):
                rc = code
            else:
                rc = 1
        if rc is None:
            rc = 0
        if rc != 0:
            return None, None, f"redact rc={rc}"
        out_text = out.read_text(encoding="utf-8")
        receipt = json.loads(rec.read_text(encoding="utf-8"))
    if receipts_dir is not None:
        receipts_dir.mkdir(parents=True, exist_ok=True)
        _gate_write_atomic(receipts_dir / f"redact-{seq:04d}.json",
                           json.dumps(receipt, ensure_ascii=False,
                                      sort_keys=True,
                                      indent=1).encode("utf-8"))
    by_mode: Dict[str, int] = {}
    for r in receipt.get("redactions", []):
        m = r.get("mode") or "unknown"
        by_mode[m] = by_mode.get(m, 0) + 1
    return out_text, receipt, dict(sorted(by_mode.items()))


def _gate_output_name(rel: str, index: int, include_paths: bool) -> str:
    if include_paths:
        return "handoff/" + rel + GATE_OUTPUT_SUFFIX
    return "handoff/%04d%s" % (index, GATE_OUTPUT_SUFFIX)


def _gate_item_shell(rel: Optional[str], index: int, kind: str,
                     input_bytes: int, input_sha: Optional[str],
                     include_paths: bool, include_input_hashes: bool) -> dict:
    item = {
        "kind": kind,
        "input": {"bytes": input_bytes},
        "status": None,
        "unobserved_reason": None,
        "unobserved_detail": None,
        "lens": {"mask": None},
        "hidden_segments": _gate_hidden(),
        "removed_invisible": _gate_removed_zero(),
        "redact": {"spans": 0, "by_mode": {}},
        "treatment": "not_produced",
        "not_produced_reason": None,
        "engine_detail": None,
        "output": None,
    }
    if include_paths:
        item["path"] = rel
    else:
        item["index"] = index
    if include_input_hashes and input_sha is not None:
        item["input"]["sha256"] = input_sha
    return item


def _gate_finish_item(item: dict, treatment: str, reason=None,
                      engine_detail=None, out_blob: Optional[bytes] = None,
                      out_path: Optional[str] = None):
    if treatment == "produced":
        item["treatment"] = "produced"
        item["output"] = {
            "path": out_path,
            "bytes": len(out_blob),
            "sha256": hashlib.sha256(out_blob).hexdigest(),
        }
    else:
        item["treatment"] = "not_produced"
        item["not_produced_reason"] = reason
        item["engine_detail"] = engine_detail


def run_gate(input_dir: Path, output_dir: Path, *,
             progress: ProgressCallback = _silent,
             redact_builtins=GATE_DEFAULT_BUILTINS,
             redact_mode: str = GATE_REDACT_MODE,
             redact_config=None, no_redact: bool = False,
             crowd_config=None, include_paths: bool = True,
             include_input_hashes: bool = True,
             storage_path=None) -> dict:
    """The M1 Gate (request §3.1): one pass over a folder, producing
    handoff/ + local/ + the normalized receipt.  Returns the receipt
    dict (with its digest).

    Fails closed before any work when the output directory exists and
    is not empty, or when it sits inside the input folder or contains
    it (ValueError)."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if progress is None:
        progress = _silent
    if not input_dir.is_dir():
        raise ValueError("input folder does not exist: %s" % input_dir)
    out_abs = output_dir.absolute()
    in_abs = input_dir.absolute()
    if out_abs == in_abs or in_abs in out_abs.parents or \
            out_abs in in_abs.parents:
        raise ValueError(
            "output folder must not contain or sit inside the input "
            "folder")
    if out_abs.exists():
        if not out_abs.is_dir():
            raise ValueError("output path exists and is not a folder")
        if any(out_abs.iterdir()):
            raise ValueError(
                "output folder exists and is not empty")
    redact_builtins = tuple(redact_builtins or ())
    if redact_config is not None:
        redact_config = Path(redact_config)
        if not redact_config.is_file():
            raise ValueError("redact config file not found")

    handoff = out_abs / "handoff"
    local = out_abs / "local"
    receipts_dir = local / "engine-receipts"
    handoff.mkdir(parents=True, exist_ok=False)
    local.mkdir(parents=True, exist_ok=False)

    config_sha = None
    if redact_config is not None:
        config_sha = "sha256:" + hashlib.sha256(
            redact_config.read_bytes()).hexdigest()
    crowd_sha = None
    if crowd_config is not None:
        crowd_path = Path(crowd_config)
        crowd_sha = "sha256:" + hashlib.sha256(
            crowd_path.read_bytes()).hexdigest()

    items: List[dict] = []
    fragments: List[dict] = []
    engine = _gate_build_engine()
    rels = _gate_walk(input_dir)
    progress("Gate: %d items" % len(rels))
    for seq, rel in enumerate(rels, start=1):
        src = input_dir / rel
        item = _gate_item_shell(rel, seq, "other", 0, None,
                                include_paths, include_input_hashes)
        # every item below overwrites the shell fields as its lane decides
        items.append(item)
        try:
            if src.is_symlink():
                item["kind"] = _gate_kind_of(rel)
                item["status"] = "unobserved"
                item["unobserved_reason"] = "symlink_skipped"
                item["lens"] = {"mask": "0000-000"}
                _gate_finish_item(item, "not_produced", "unobserved")
                continue
            if not src.is_file():
                item["kind"] = _gate_kind_of(rel)
                item["status"] = "unobserved"
                item["unobserved_reason"] = "unreadable"
                item["lens"] = {"mask": "0000-000"}
                _gate_finish_item(item, "not_produced", "unobserved")
                continue
            data = src.read_bytes()
            item["input"] = {"bytes": len(data)}
            if include_input_hashes:
                item["input"]["sha256"] = hashlib.sha256(data).hexdigest()
            suffix = src.suffix.lower()
            kind = _gate_kind_of(rel)
            item["kind"] = kind
            if kind == "document":
                _gate_item_document(engine, src, data, suffix, item,
                                    handoff, receipts_dir, seq,
                                    (() if no_redact else redact_builtins),
                                    redact_mode,
                                    (None if no_redact else redact_config),
                                    include_paths, fragments)
            elif kind == "table":
                _gate_item_table(src, item, seq, handoff, crowd_config)
            elif kind == "image":
                _gate_item_image(engine, src, item)
            else:
                _gate_finish_item(item, "not_produced", "not_applicable")
        except OSError as exc:
            item["status"] = "unobserved"
            item["unobserved_reason"] = "unreadable"
            item["unobserved_detail"] = type(exc).__name__
            _gate_finish_item(item, "not_produced", "unobserved")
        progress("Gate: %s" % rel)

    # --- summary
    status_counts = {"flagged": 0, "clean": 0, "unobserved": 0}
    np_reasons = {r: 0 for r in sorted(NOT_PRODUCED_REASONS)}
    produced_n = 0
    for it in items:
        if it["treatment"] == "produced":
            produced_n += 1
        else:
            np_reasons[it["not_produced_reason"]] += 1
        st = it["status"]
        if st in status_counts:
            status_counts[st] += 1
    receipt = {
        "receipt_version": GATE_RECEIPT_VERSION,
        "kind": GATE_KIND,
        "tool": {"name": "sieve-tray", "version": __version__},
        "engines": _gate_engine_table(),
        "settings": {
            "redact": {
                "builtins": (list(redact_builtins)
                             if not no_redact else []),
                "mode": (redact_mode if not no_redact else None),
                "config_sha256": config_sha},
            "strip_invisible": list(GATE_STRIP_KINDS),
            "crowd_config_sha256": crowd_sha,
            "include_paths": include_paths,
            "include_input_hashes": include_input_hashes,
        },
        "items": items,
        "summary": {
            "items": len(items),
            "produced": produced_n,
            "not_produced": len(items) - produced_n,
            "not_produced_by_reason": np_reasons,
            "status": status_counts,
        },
    }
    receipt["digest"] = _gate_digest(receipt)

    # --- the receipt is written last (request §3.1)
    _gate_write_atomic(handoff / "gate-receipt.json",
                       _gate_norm_json(receipt).encode("utf-8"))

    # --- the local report (fragments stay here, never in handoff/)
    report = _render_gate_report(receipt, fragments)
    _gate_write_atomic(local / "gate-report.html",
                       report.encode("utf-8"))

    # --- history (allowlisted counts only; no paths, no bodies)
    if storage_path is not None:
        try:
            from sieve_tray_storage import Storage
            storage = Storage(str(storage_path))
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            storage.record_gate_run(
                run_id="gate-" + now.replace(":", "").replace("-", ""),
                created_at=now, items_total=len(items),
                produced=produced_n,
                np_needs_settings=np_reasons["needs_settings"],
                np_unobserved=np_reasons["unobserved"],
                np_not_applicable=np_reasons["not_applicable"],
                np_engine_unavailable=np_reasons["engine_unavailable"],
                np_engine_refused=np_reasons["engine_refused"],
                np_write_failed=np_reasons["write_failed"],
                status_flagged=status_counts["flagged"],
                status_clean=status_counts["clean"],
                status_unobserved=status_counts["unobserved"],
                receipt_digest=receipt["digest"],
                engines_version=_gate_engines_version())
        except Exception:
            progress("Gate: history record skipped")

    return receipt


def _gate_kind_of(rel: str) -> str:
    suffix = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    if suffix in GATE_DOC_EXTS:
        return "document"
    if suffix in GATE_TABLE_EXTS:
        return "table"
    if suffix in GATE_IMAGE_EXTS:
        return "image"
    return "other"


def _gate_item_document(engine, src: Path, data: bytes, suffix: str,
                        item: dict, handoff: Path, receipts_dir: Path,
                        seq: int, builtins, mode, redact_config_path,
                        include_paths: bool, fragments: List[dict]) -> None:
    """The document lane: Lens observation -> visible text (strip) ->
    Redact (label) -> handoff.  HTML rides the extras lane with a
    charset pre-check done here first; a rule-originated css_hidden
    segment fails the item closed (measured)."""
    # --- PDF short-circuit (Seal 2.2 ruling (2) of 2026-11-14) --------
    # Gate treats a PDF as unobserved with the reason engine_unavailable
    # regardless of whether pypdf is installed.  pypdf's visible-text
    # extraction does not interpret the rendering mode "3 Tr", so
    # observing a PDF starts a leak (measured: the invisible text rode
    # into handoff/*.pdf.visible.txt).  Until the engine understands
    # render modes, the safe side is to not observe and record why -
    # closed vocabulary only, with a detail.  This is also the standing
    # behaviour for frozen apps that bundle pypdf transitively.
    if suffix == ".pdf":
        item["status"] = "unobserved"
        item["unobserved_reason"] = "engine_unavailable"
        item["unobserved_detail"] = "pdf_visible_extraction_disabled"
        item["lens"] = {"mask": "0000-000"}
        _gate_finish_item(item, "not_produced", "engine_unavailable")
        return
    # --- observation
    try:
        if suffix in (".html", ".htm"):
            text_dec, enc = _gate_charset_check(data)
            if text_dec is None:
                item["status"] = "unobserved"
                item["unobserved_reason"] = "refused"
                item["unobserved_detail"] = "unsupported_encoding"
                item["lens"] = {"mask": "0000-000"}
                _gate_finish_item(item, "not_produced", "unobserved")
                return
            if not _gate_html_lane_ready():
                item["status"] = "unobserved"
                item["unobserved_reason"] = "engine_unavailable"
                item["lens"] = {"mask": "0000-000"}
                _gate_finish_item(item, "not_produced",
                                  "engine_unavailable")
                return
            if enc == "cp932":
                # observe a user-only UTF-8 temp copy, removed afterwards
                with tempfile.TemporaryDirectory() as td:
                    tmp = Path(td) / "cp932-copy.html"
                    tmp.write_text(text_dec, encoding="utf-8")
                    os.chmod(str(tmp), 0o600)
                    obs = engine.observe(str(tmp))
            else:
                obs = engine.observe(str(src))
        else:
            obs = engine.observe(str(src))
        mask = obs.mask
        entry = {"path": str(src), "mask": mask,
                 "flagged": (mask != "1000-000"
                             and not mask.startswith("0")),
                 "h_states": dict(obs.h_states),
                 "evidence": dict(obs.evidence)}
    except Exception as e:  # noqa: BLE001
        entry = {"path": str(src), "mask": "0000-000", "flagged": False,
                 "h_states": {}, "evidence": {},
                 "error": type(e).__name__}
        mask = entry["mask"]
    status, reason, detail = classify_observation(entry)
    item["lens"] = {"mask": mask}
    if status == "unobserved":
        item["status"] = status
        item["unobserved_reason"] = reason
        item["unobserved_detail"] = detail
        _gate_finish_item(item, "not_produced", "unobserved")
        return
    item["status"] = status
    # --- hidden segments (Lens x Order, request §3.3)
    orderable, rule_hidden = _gate_classify_hidden(
        getattr(obs, "segments", []))
    if rule_hidden:
        # fail closed: the <style>-rule matched a body the extras
        # emitter still marks visible - the visible text is never
        # handed off; the withheld bodies stay in the local report only
        hidden = _gate_hidden()
        hidden["count"] = len(orderable) + len(rule_hidden)
        item["hidden_segments"] = hidden
        for seg in getattr(obs, "segments", []):
            if seg.visible and seg.text and seg.text.strip():
                fragments.append({"item": seq, "text": seg.text,
                                  "kind": "withheld"})
        _gate_finish_item(item, "not_produced", "engine_refused",
                          engine_detail="css_rule_hidden")
        return
    for seg in orderable:
        if seg.text and seg.text.strip():
            fragments.append({"item": seq, "text": seg.text,
                              "kind": "hidden"})
    item["hidden_segments"] = _gate_order_on_hidden(orderable)
    # --- visible text
    try:
        from sieve_lens import visible_text
    except ImportError:
        _gate_finish_item(item, "not_produced", "engine_unavailable",
                          engine_detail="visible_text missing")
        return
    vt = visible_text(obs, strip=set(GATE_STRIP_KINDS))
    out_text = vt.text
    if out_text and not out_text.endswith("\n"):
        out_text += "\n"
    removed = _gate_removed_zero()
    for k, v in vt.removed.items():
        if k in removed:
            removed[k] = v
    item["removed_invisible"] = removed
    # --- redact (label, by_mode - the 2026-11-08 ruling)
    if redact_config_path is not None or builtins:
        res = _gate_redact_apply(out_text, builtins=builtins, mode=mode,
                                 config_path=redact_config_path,
                                 receipts_dir=receipts_dir, seq=seq)
        out_text, _redact_receipt, by_mode = res
        if out_text is None:
            _gate_finish_item(item, "not_produced", "engine_refused",
                              engine_detail=by_mode)
            return
        item["redact"] = {"spans": sum(by_mode.values()),
                          "by_mode": by_mode}
    out_blob = out_text.encode("utf-8")
    out_path = _gate_output_name(
        _gate_item_rel(item), seq, include_paths)
    _gate_write_atomic(handoff / out_path[len("handoff/"):], out_blob)
    _gate_finish_item(item, "produced", out_blob=out_blob,
                      out_path=out_path)


def _gate_item_rel(item: dict) -> str:
    return item.get("path") or ("%04d" % item.get("index", 0))


def _gate_item_table(src: Path, item: dict, seq: int, handoff: Path,
                     crowd_config) -> None:
    """The table lane: anonymized through Crowd only when a Crowd
    config file is supplied; otherwise unprocessed (needs_settings)."""
    if crowd_config is None:
        _gate_finish_item(item, "not_produced", "needs_settings")
        return
    try:
        import sieve_crowd
        cfg = json.loads(Path(crowd_config).read_text(encoding="utf-8"))
        config = sieve_crowd.parse_config(cfg)
        result = sieve_crowd.anonymize(src, config)
        out_blob = result.output_bytes
    except Exception as e:  # noqa: BLE001
        _gate_finish_item(item, "not_produced", "engine_refused",
                          engine_detail=f"crowd {type(e).__name__}")
        return
    out_path = _gate_output_name(_gate_item_rel(item), seq, "path" in item)
    _gate_write_atomic(handoff / out_path[len("handoff/"):], out_blob)
    _gate_finish_item(item, "produced", out_blob=out_blob,
                      out_path=out_path)


def _gate_item_image(engine, src: Path, item: dict) -> None:
    """The image lane: observed by Lens (existing routing), never
    produced - region selection is required (§3.2)."""
    try:
        obs = engine.observe(str(src))
        mask = obs.mask
        entry = {"path": str(src), "mask": mask,
                 "flagged": (mask != "1000-000"
                             and not mask.startswith("0")),
                 "h_states": dict(obs.h_states),
                 "evidence": dict(obs.evidence)}
    except Exception as e:  # noqa: BLE001
        entry = {"path": str(src), "mask": "0000-000", "flagged": False,
                 "h_states": {}, "evidence": {},
                 "error": type(e).__name__}
    status, reason, detail = classify_observation(entry)
    item["lens"] = {"mask": entry["mask"]}
    if status == "unobserved":
        item["status"] = status
        item["unobserved_reason"] = reason
        item["unobserved_detail"] = detail
        _gate_finish_item(item, "not_produced", "unobserved")
    else:
        item["status"] = status
        _gate_finish_item(item, "not_produced", "needs_settings")


GATE_REPORT_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       max-width: 960px; margin: 2rem auto; padding: 0 1rem;
       color: #1a1a1a; background: #fafafa; }
h1 { font-size: 1.4rem; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border: 1px solid #ddd; }
th, td { text-align: left; padding: .4rem .6rem; font-size: .85rem;
         border-bottom: 1px solid #eee; }
th { background: #f0f0f0; }
pre { background: #fff; border: 1px solid #ddd; padding: .6rem;
      font-size: .8rem; white-space: pre-wrap; word-break: break-all; }
"""


def _render_gate_report(receipt: dict, fragments: List[dict]) -> str:
    """The local operator report (request §3.1): counts, the item table
    with the §3.2 stage colors, and the hidden/withheld fragments -
    escaped and length-capped.  No external requests; handoff/ never
    receives this."""
    parts = ["<!DOCTYPE html><html><head><meta charset=\"utf-8\">",
             "<title>Sieve Gate report</title>",
             "<style>%s</style></head><body>" % GATE_REPORT_CSS,
             "<h1>Sieve Gate report</h1>",
             "<p>tool sieve-tray %s</p>" % html.escape(
                 receipt["tool"]["version"]),
             "<p>items %d (produced %d / not produced %d) "
             "- status flagged %d, clean %d, unobserved %d</p>" % (
                 receipt["summary"]["items"],
                 receipt["summary"]["produced"],
                 receipt["summary"]["not_produced"],
                 receipt["summary"]["status"]["flagged"],
                 receipt["summary"]["status"]["clean"],
                 receipt["summary"]["status"]["unobserved"]),
             "<table><tr><th>Item</th><th>Kind</th><th>Status</th>"
             "<th>Treatment</th><th>Reason</th><th>Hidden</th>"
             "<th>Redact</th></tr>"]
    for it in receipt["items"]:
        ident = _gate_item_rel(it)
        reason = it.get("not_produced_reason") or ""
        style = ""
        if it["treatment"] == "not_produced" and reason:
            try:
                stage = not_produced_stage(reason,
                                           it.get("unobserved_reason"))
                style = ' style="background: %s"' % UNOBSERVED_STAGE_BG[
                    stage]
            except ValueError:
                style = ""
        hidden = it.get("hidden_segments") or {}
        parts.append(
            "<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%d</td><td>%d</td></tr>" % (
                style, html.escape(str(ident)), html.escape(it["kind"]),
                html.escape(str(it["status"])),
                html.escape(it["treatment"]), html.escape(reason),
                hidden.get("count", 0), it["redact"]["spans"]))
    parts.append("</table>")
    if fragments:
        parts.append("<h2>Hidden text observed by Order (local only)</h2>")
        for fr in fragments:
            snippet = fr["text"][:200]
            parts.append("<pre>%s</pre>" % html.escape(snippet))
    parts.append("<p>This is an observation report, not a judgment. "
                 "Human review is required.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def open_report_gate(path) -> None:
    """Open the Gate report in the system browser (a file: URI - the
    same thin wrapper the scan report uses)."""
    open_in_browser(path)


# The closed verification vocabularies (request §3.4).
VERIFY_REASONS = frozenset({
    "input_changed", "input_missing", "item_added", "output_changed",
    "output_missing", "replay_differs", "engine_version_differs"})
VERIFY_NOT_VERIFIABLE_REASONS = frozenset({
    "receipt_unreadable", "receipt_version_unsupported",
    "receipt_digest_mismatch", "settings_unavailable",
    "handoff_incomplete"})


def _gate_verify_item_ident(it: dict) -> dict:
    ident = {}
    if "path" in it:
        ident["path"] = it["path"]
    else:
        ident["index"] = it["index"]
    return ident


# ===========================================================================
# v2.1.0 (M2 Cohort): the Cohort lane (request §3.1 the flow, §3.6 the
# report and the graph, §3.7 the receipt / the verification / the
# history, §3.8 the samples and the self-check).
#
# Cohort compares the submissions of a folder side by side:
#   documents (GATE_DOC_EXTS)  -> Lens visible text -> Referee
#   .py                        -> Scope analyze_corpus
#   generic source (10 exts)   -> Scope language_agnostic_pair
# everything else is not_applicable.  The output splits like Gate:
# handoff/ carries the receipt only, local/ the full report.  The
# receipt lists the flagged pairs only (GREEN lives in the summary).
# ===========================================================================

COHORT_KIND = "sieve-cohort"
# request §3.1: the generic lane covers the remaining source languages
# (the enumerated 10 extensions resolve the request's list).
COHORT_GENERIC_EXTENSIONS = (".js", ".ts", ".java", ".c", ".cpp", ".cs",
                             ".go", ".rb", ".php", ".sh")
# the 2026-11-09 ruling: the generic threshold is a provisional 700 ‰
# (a clear near-identity in per-mille terms); the 2026-11-10 ruling
# fixes the SIDE rule: either side at/over the threshold flags the pair.
COHORT_GENERIC_FLAG_PER_MILLE = 700
# request §3.6: the report caps each document at 20,000 characters and
# the side-by-side section at 50 pairs; overflows show counts.
COHORT_REPORT_MARK_CAP_CHARS = 20000
COHORT_REPORT_PAIR_CAP = 50


def _cohort_explanation_settings() -> dict:
    """The explanation-layer constants, read from the engine modules
    (request §3.7: the settings record the explanation layer)."""
    from sieve_referee.fingerprint import (FINGERPRINT_K as rk,
                                           FINGERPRINT_W as rw,
                                           MIN_FINGERPRINT_SPAN as rmin)
    import sieve_scope
    return {"referee": {"k": int(rk), "w": int(rw), "min": int(rmin)},
            "scope": {"k": int(sieve_scope.FINGERPRINT_K),
                      "w": int(sieve_scope.FINGERPRINT_W),
                      "min": int(sieve_scope.MIN_FINGERPRINT_SPAN)}}


def _cohort_engine_table() -> list:
    """The Cohort receipt's engines (the 2026-11-09 design note: the four
    guards lens/order/referee/scope - Order is the hidden-text
    observer).  The names are the gate table's, so the verification's
    drift check resolves them."""
    engines = []
    gate = {e["name"]: e for e in _gate_engine_table()}
    for name in ("sieve-lens", "sieve-order", "sieve-referee",
                 "sieve-scope"):
        entry = gate.get(name)
        if entry is None:
            try:
                import importlib
                mod = importlib.import_module(
                    name.replace("-", "_"))
                entry = {"name": name,
                         "version": getattr(mod, "__version__", None),
                         "source": "pip", "file_sha256": None}
            except Exception:
                entry = {"name": name, "version": None,
                         "source": "pip", "file_sha256": None}
        engines.append(dict(entry))
    return engines


def _cohort_removed_zero() -> dict:
    """The per-selection removal report (request §3.3/§3.4): counts and
    lengths only - never a position, never a body."""
    return {"bibliography": {"length": 0},
            "quotes": {"length": 0},
            "base": {"length": 0}}


def _cohort_measure_exclusions(text: str, *, exclude_quotes: bool,
                               exclude_bibliography: bool,
                               base_texts: Optional[List[str]]) -> Tuple[str, dict]:
    """Measure the exclusions with the engine's own strip functions in
    the engine's declared order (bibliography -> quotes -> base), so
    the measured bytes equal what the judgment strips internally.
    Returns (text for the comparison, removal report)."""
    from sieve_referee.citations import strip_bibliography, strip_quotes
    from sieve_referee.base_strip import strip_base_segments
    removed = _cohort_removed_zero()
    work = text
    if exclude_bibliography:
        stripped = strip_bibliography(work)
        removed["bibliography"]["length"] = len(work) - len(stripped)
        work = stripped
    if exclude_quotes:
        stripped = strip_quotes(work)
        removed["quotes"]["length"] = len(work) - len(stripped)
        work = stripped
    if base_texts:
        stripped, _spans = strip_base_segments(work, base_texts)
        removed["base"]["length"] = len(work) - len(stripped)
        work = stripped
    return work, removed


def _cohort_base_texts(base_paths) -> List[str]:
    """Read the base files (request §3.3): missing, empty or undecodable
    base files fail closed with ValueError - a base the run cannot read
    must never silently turn into 'no base'."""
    texts = []
    for raw in (base_paths or ()):
        p = Path(raw)
        if not p.is_file():
            raise ValueError("base file not found: %s" % p)
        data = p.read_bytes()
        if not data:
            raise ValueError("base file is empty: %s" % p)
        text, err = _read_limited(p)
        if text is None:
            raise ValueError("base file unreadable (%s): %s"
                             % (err, p))
        texts.append(text)
    return texts


def _cohort_generic_pairs(generic_map: Dict[str, str],
                          base_texts: Optional[List[str]],
                          progress) -> Tuple[list, list, dict, list]:
    """The generic lane (request §3.5): every pair goes through the
    Scope's language-agnostic comparison.  The base removal strips the
    base-matched token spans BEFORE the comparison (the 2026-11-09
    ruling: the starter-code base must not make every submission look
    alike), and a submission emptied by the removal leaves the
    comparison as empty_input.  A pair is flagged when EITHER side
    reaches COHORT_GENERIC_FLAG_PER_MILLE (the 2026-11-10 ruling: a
    small file contained in a larger one must not be missed); the
    recorded match_per_mille is the triggering (higher) side.
    Returns (flagged pairs, all pairs for the report listing, per-item
    base removal report, emptied names)."""
    try:
        import sieve_scope
    except ImportError:
        return [], [], {}, []
    compare_map: Dict[str, str] = {}
    removal_report: dict = {}
    emptied: list = []
    if base_texts:
        for name, text in generic_map.items():
            stripped, report = sieve_scope.strip_base_sources(
                text, base_texts)
            removal_report[name] = {
                "total_tokens": report.get("total_tokens", 0),
                "removed_tokens": report.get("removed_tokens", 0),
                "removed_ratio": report.get("removed_ratio", 0.0)}
            if not stripped.strip():
                emptied.append(name)
                continue
            compare_map[name] = stripped
    else:
        compare_map = dict(generic_map)
    flagged_pairs: list = []
    all_pairs: list = []
    names = sorted(compare_map)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            res = sieve_scope.language_agnostic_pair(
                compare_map[a], compare_map[b])
            pm = res.get("match_per_mille") or {}
            # the either-side rule (2026-11-10 ruling): the flagged
            # value is the triggering (higher) side, so the receipt and
            # the report show the number that justified the flag
            pmv = int(max(pm.get("a", 0), pm.get("b", 0)))
            flagged = pmv >= COHORT_GENERIC_FLAG_PER_MILLE
            all_pairs.append({"a": a, "b": b, "lane": "generic",
                              "label": pmv, "flagged": flagged})
            if flagged:
                spans = res.get("spans") or []
                flagged_pairs.append({
                    "a": a, "b": b,
                    "generic": {"match_per_mille": pmv},
                    "spans": {
                        "count": len(spans),
                        "total_length": sum(
                            max(0, int(s.get("a_end", 0))
                                - int(s.get("a_start", 0)))
                            for s in spans)}})
    return flagged_pairs, all_pairs, removal_report, emptied


def _cohort_scope_pairs(code_map: Dict[str, str],
                        base_texts: Optional[List[str]],
                        progress) -> Tuple[list, list, dict, list]:
    """The .py lane (request §3.1): the Scope corpus analysis on the
    (optionally base-stripped) code map.  Returns (flagged pairs, all
    pairs, per-item base removal report, emptied names)."""
    import sieve_scope
    from sieve_scope import (SieveScopeEngineV1_3,
                             SieveClusterAnalyzerV1_3)
    compare_map: Dict[str, str] = {}
    removal_report: dict = {}
    emptied: list = []
    if base_texts:
        for name, text in code_map.items():
            stripped, report = sieve_scope.strip_base_sources(
                text, base_texts)
            removal_report[name] = {
                "total_tokens": report.get("total_tokens", 0),
                "removed_tokens": report.get("removed_tokens", 0),
                "removed_ratio": report.get("removed_ratio", 0.0)}
            if not stripped.strip():
                emptied.append(name)
                continue
            compare_map[name] = stripped
    else:
        compare_map = dict(code_map)
    if not compare_map:
        return [], [], removal_report, emptied
    engine = SieveScopeEngineV1_3()
    analyzer = SieveClusterAnalyzerV1_3(engine, min_cluster_size=2)
    analysis = analyzer.analyze_corpus(compare_map)
    flagged_pairs: list = []
    all_pairs: list = []
    for (a, b), pr in sorted(
            (analysis.get("pair_results") or {}).items()):
        if pr.get("short_circuited"):
            # the M1 reading: a short-circuited pair is excluded from
            # the listing entirely (the summary counts it)
            continue
        mask = pr.get("mask") or pr.get("v0_mask") or ""
        flagged = _scope_pair_flagged(mask)
        all_pairs.append({"a": a, "b": b, "lane": "scope",
                          "label": mask, "flagged": flagged})
        if flagged:
            spans = []
            try:
                explained = sieve_scope.explain_pair(
                    compare_map[a], compare_map[b])
                spans = explained.get("spans") or []
            except Exception:  # noqa: BLE001 - explanation is additive
                spans = []
            flagged_pairs.append({
                "a": a, "b": b, "scope": {"mask": mask},
                "spans": {
                    "count": len(spans),
                    "total_length": sum(
                        max(0, int(s.get("a_end", 0))
                            - int(s.get("a_start", 0)))
                        for s in spans)}})
    return flagged_pairs, all_pairs, removal_report, emptied


def _scope_pair_flagged(mask: str) -> bool:
    """The .py lane's flag rule (request §3.1): a similarity bit in the
    H4..H7 positions (the content/coverage dimensions) - a structural
    presence alone (1000-000) is not a flagged pair."""
    bits = (mask or "").replace("-", "")
    if len(bits) < 7:
        bits = (bits + "0000000")[:7]
    return any(b == "1" for b in bits[3:])


COHORT_REPORT_TEXTS = {
    "en": {
        "title": "Cohort report",
        "leading_line": "The flagged pairs below are an observation "
                        "worth checking by a person; they are not a "
                        "conclusion.",
        "counts_heading": "Counts",
        "items_label": "Submissions",
        "compared_label": "compared",
        "not_compared_label": "not compared",
        "excluded_label": "Excluded",
        "excluded_total": "total excluded length: {n}",
        "base_lanes_label": "the base exclusion applied to the lanes: "
                            "{lanes}",
        "too_large_label": "files over {n} bytes are not read "
                           "(too large)",
        "not_compared_reasons": "not compared by reason",
        "items_heading": "Submissions",
        "pairs_heading": "Pairs",
        "generic_rule": "The generic lane flags a pair when either "
                        "side reaches {per_mille} ‰ (either side, so "
                        "that a small file contained in a larger one "
                        "is not missed).  The recorded match_per_mille "
                        "is the higher of the two sides.",
        "spans_heading": "Matched spans",
        "graph_heading": "Flagged pairs graph",
        "graph_note": "The regions are the connected components of "
                      "the flagged pairs plus the isolated submissions "
                      "(Referee publishes no cluster API, so the "
                      "engine's clusters are not used here).",
        "hidden_heading": "Hidden text observed by Order (local only)",
        "omitted": "{n} characters omitted",
        "pairs_shown": "{shown} of {total} pairs shown",
        "pair_of": "pair",
        "lane": "lane",
        "observation": "observation",
        "status": "status",
        "reason": "reason",
        "file": "file",
        "kind": "kind",
        "hidden": "hidden",
        "flagged_word": "check",
        "clean_word": "-",
        "mask": "mask",
        "per_mille": "per mille",
        "spans_label": "spans",
        "no_pairs": "no flagged pairs",
    },
    "ja": {
        "title": "Cohort 報告",
        "leading_line": "要確認の組は、人が確かめる価値があることを示した"
                        "ものであり、結論ではない。",
        "counts_heading": "件数",
        "items_label": "提出物",
        "compared_label": "比較に入れた",
        "not_compared_label": "比較に入れなかった",
        "excluded_label": "除外",
        "excluded_total": "除外した合計長: {n}",
        "base_lanes_label": "基準の除外を適用したレーン: {lanes}",
        "too_large_label": "{n} バイトを超えるファイルは読まない"
                           "（大きすぎる）",
        "not_compared_reasons": "比較に入らなかった理由別の件数",
        "items_heading": "提出物",
        "pairs_heading": "組の一覧",
        "generic_rule": "汎用レーンは、いずれか一方の側でも {per_mille} ‰ "
                        "に達した組を要確認にします（小さなファイルが大きな"
                        "ファイルにそのまま含まれる場合を見落とさないため）。"
                        "記録される一致率は、高い側の値です。",
        "spans_heading": "一致箇所",
        "graph_heading": "要確認の組の図",
        "graph_note": "図の領域は、要確認の組の連結成分と孤立した提出物 "
                      "です（Referee には公開のクラスタ API がないため、"
                      "エンジンのクラスタはここでは使いません）。",
        "hidden_heading": "Order が観測した隠れた文章（手元用）",
        "omitted": "残り {n} 文字を省略",
        "pairs_shown": "{total} 組のうち {shown} 組を表示",
        "pair_of": "組",
        "lane": "レーン",
        "observation": "観測",
        "status": "状態",
        "reason": "理由",
        "file": "ファイル",
        "kind": "種類",
        "hidden": "隠れた文章",
        "flagged_word": "要確認",
        "clean_word": "-",
        "mask": "マスク",
        "per_mille": "千分率",
        "spans_label": "区間",
        "no_pairs": "要確認の組なし",
    },
}


def _cohort_tr(lang: str, key: str, **kw) -> str:
    """The report wording (request §3.6, the 2026-11-09 ruling ⑤: ja/en
    both, en the default).  Unknown languages fall back to English."""
    table = COHORT_REPORT_TEXTS.get(lang) or COHORT_REPORT_TEXTS["en"]
    text = table.get(key) or COHORT_REPORT_TEXTS["en"].get(key, key)
    if kw:
        try:
            text = text.format(**kw)
        except (KeyError, IndexError):
            pass
    return text


def _cohort_merge_spans(spans: list) -> list:
    """Merge overlapping spans on one side (the Scope spans can contain
    each other - the receipt keeps every span, the display merges)."""
    ordered = sorted(((int(s.get("a_start", 0)), int(s.get("a_end", 0)))
                      for s in spans if int(s.get("a_end", 0))
                      > int(s.get("a_start", 0))))
    merged: list = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _cohort_marked_text(text: str, spans: list, side: str) -> Tuple[str, int]:
    """Escape the text with the matched spans wrapped in <mark>; the
    display is capped at COHORT_REPORT_MARK_CAP_CHARS with the omitted
    count (request §3.6: 超過は件数)."""
    merged = _cohort_merge_spans(spans)
    marks = []
    cursor = 0
    out = []
    cap = COHORT_REPORT_MARK_CAP_CHARS
    for start, end in merged:
        start = min(start, cap)
        end = min(end, cap)
        if end <= cursor:
            continue
        out.append(html.escape(text[cursor:start]))
        out.append("<mark>%s</mark>" % html.escape(text[start:end]))
        cursor = end
        if cursor >= cap:
            break
    out.append(html.escape(text[cursor:cap]))
    omitted = max(0, len(text) - cap)
    return "".join(out), omitted


def _cohort_render_fragment(a_text: str, b_text: str,
                            spans: list) -> str:
    """One side-by-side fragment: both documents escaped with their
    matched spans in <mark>, each capped at 20,000 characters with the
    omitted count shown."""
    a_disp, a_omit = _cohort_marked_text(a_text, spans, "a")
    b_disp, b_omit = _cohort_marked_text(b_text, spans, "b")
    parts = ['<div class="fragment">',
             "<pre>%s</pre>" % a_disp,
             "<pre>%s</pre>" % b_disp]
    if a_omit or b_omit:
        parts.append("<p>%s</p>" % html.escape(
            _cohort_tr("en", "omitted", n=max(a_omit, b_omit))))
    parts.append("</div>")
    return "\n".join(parts)


def _cohort_svg_graph(all_pairs: list, node_names: List[str]) -> str:
    """The deterministic SVG (request §3.6): no JavaScript, no xmlns
    (HTML5 inline SVG), the flagged pairs' connected components plus
    the isolated submissions as regions, the nodes of each region on
    the circumference in name order, RED edges heavy (2.5) and the
    others light (1.5) dashed, coordinates at 1 decimal."""
    names = sorted(node_names)
    idx = {n: i for i, n in enumerate(names)}
    flagged = [p for p in all_pairs if p.get("flagged")]

    # connected components over the flagged pairs (union-find)
    parent = {n: n for n in names}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for p in flagged:
        ra, rb = find(p["a"]), find(p["b"])
        if ra != rb:
            parent[ra] = rb
    regions: Dict[str, List[str]] = {}
    for n in names:
        regions.setdefault(find(n), []).append(n)
    ordered = sorted(regions.values(),
                     key=lambda members: min(members))

    import math
    width, height = 640.0, 320.0
    parts = ['<svg width="%s" height="%s" viewBox="0 0 %s %s">'
             % (_fmt1(width), _fmt1(height), _fmt1(width), _fmt1(height))]
    colors = ["#f2f7ff", "#fff7f2", "#f7fff2", "#fff2fb", "#f2fffb"]
    x0, y0, w_box, h_box = 10.0, 10.0, width - 20.0, height - 20.0
    cols = max(1, int(len(ordered) ** 0.5 + 0.999))
    rows = max(1, (len(ordered) + cols - 1) // cols)
    cell_w, cell_h = w_box / cols, h_box / rows
    pos: Dict[str, tuple] = {}
    for r_i, members in enumerate(ordered):
        r, c = divmod(r_i, cols)
        rx, ry = x0 + c * cell_w, y0 + r * cell_h
        rw, rh = cell_w, cell_h
        parts.append('<rect x="%s" y="%s" width="%s" height="%s" '
                     'fill="%s" stroke="#8899aa"/>'
                     % (_fmt1(rx), _fmt1(ry), _fmt1(rw), _fmt1(rh),
                        colors[r_i % len(colors)]))
        n = len(members)
        cx, cy = rx + rw / 2, ry + rh / 2
        rad = min(rw, rh) * 0.36
        for k, name in enumerate(sorted(members)):
            ang = 2 * 3.141592653589793 * k / max(1, n) - 1.5707963267948966
            px, py = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
            pos[name] = (px, py)
            parts.append('<circle cx="%s" cy="%s" r="4" fill="#334455"/>'
                         % (_fmt1(px), _fmt1(py)))
            parts.append('<text x="%s" y="%s" font-size="9">%s</text>'
                         % (_fmt1(px + 6), _fmt1(py + 3),
                            html.escape(name)))
    for p in flagged:
        pa = pos.get(p["a"])
        pb = pos.get(p["b"])
        if pa is None or pb is None:
            continue
        heavy = p.get("lane") == "referee" and \
            p.get("label") in ("RED", "red")
        if heavy:
            parts.append('<line x1="%s" y1="%s" x2="%s" y2="%s" '
                         'stroke="#aa3344" stroke-width="2.5"/>'
                         % (_fmt1(pa[0]), _fmt1(pa[1]),
                            _fmt1(pb[0]), _fmt1(pb[1])))
        else:
            parts.append('<line x1="%s" y1="%s" x2="%s" y2="%s" '
                         'stroke="#aa8833" stroke-width="1.5" '
                         'stroke-dasharray="4 3"/>'
                         % (_fmt1(pa[0]), _fmt1(pa[1]),
                            _fmt1(pb[0]), _fmt1(pb[1])))
    parts.append("</svg>")
    return "".join(parts)


def _fmt1(value: float) -> str:
    """One decimal place, deterministically (request §3.6)."""
    return "%0.1f" % (value + 0.0)


def run_cohort(input_dir: Path, output_dir: Path, *,
               base_paths=None, exclude_quotes: bool = False,
               exclude_bibliography: bool = False,
               include_paths: bool = True,
               include_input_hashes: bool = True,
               storage_path=None, lang: str = "en",
               progress=None) -> dict:
    """The M2 Cohort (request §3.1): compare the submissions of a
    folder side by side and write handoff/ (the receipt only) +
    local/ (the report).  Returns the receipt dict (with its digest).

    Fails closed before any work when the output directory exists and
    is not empty, or when it sits inside the input folder or contains
    it (ValueError); a base file that is missing, empty or undecodable
    is also a ValueError.

    storage_path is accepted for the §3.7 history: when given, one
    allowlisted cohort_runs record (counts, the receipt digest, the
    engine versions - no paths, no bodies) is appended; a broken
    storage never fails the run itself."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if progress is None:
        progress = _silent
    if not input_dir.is_dir():
        raise ValueError("input folder does not exist: %s" % input_dir)
    out_abs = output_dir.absolute()
    in_abs = input_dir.absolute()
    if out_abs == in_abs or in_abs in out_abs.parents or \
            out_abs in in_abs.parents:
        raise ValueError(
            "output folder must not contain or sit inside the input "
            "folder")
    if out_abs.exists():
        if not out_abs.is_dir():
            raise ValueError("output path exists and is not a folder")
        if any(out_abs.iterdir()):
            raise ValueError(
                "output folder exists and is not empty")
    if lang not in COHORT_REPORT_TEXTS:
        lang = "en"

    handoff = out_abs / "handoff"
    local = out_abs / "local"
    handoff.mkdir(parents=True, exist_ok=False)
    local.mkdir(parents=True, exist_ok=False)

    base_texts = _cohort_base_texts(base_paths)

    rels = _gate_walk(input_dir)
    progress("Cohort: %d items" % len(rels))

    doc_engine = _gate_build_engine()
    doc_texts: Dict[str, str] = {}
    code_texts: Dict[str, str] = {}
    generic_texts: Dict[str, str] = {}
    span_data: Dict[tuple, list] = {}
    items: List[dict] = []
    item_by_rel: Dict[str, dict] = {}
    fragments: List[dict] = []
    too_large_note = False

    for seq, rel in enumerate(rels, start=1):
        src = input_dir / rel
        suffix = src.suffix.lower()
        try:
            data = src.read_bytes()
        except OSError:
            data = b""
        if include_paths:
            item = {"kind": None, "input": {"bytes": len(data)},
                    "status": None, "unobserved_reason": None,
                    "path": rel}
        else:
            item = {"kind": None, "input": {"bytes": len(data)},
                    "status": None, "unobserved_reason": None,
                    "index": seq}
        if include_input_hashes:
            item["input"]["sha256"] = "sha256:" + hashlib.sha256(
                data).hexdigest()
        item_by_rel[rel] = item
        hidden = _gate_hidden()
        items.append(item)

        if len(data) > TRAY_READ_LIMIT_BYTES:
            too_large_note = True
            item["kind"] = ("document" if suffix in GATE_DOC_EXTS
                            else "code" if (suffix == ".py" or suffix
                                            in COHORT_GENERIC_EXTENSIONS)
                            else "other")
            item["status"] = "not_compared"
            item["unobserved_reason"] = "too_large"
            continue

        if suffix in GATE_DOC_EXTS:
            item["kind"] = "document"
            doc_item = _cohort_document_item(
                doc_engine, src, data, suffix, item, hidden, fragments,
                seq)
            if doc_item is not None:
                doc_texts[rel] = doc_item
        elif suffix == ".py" or suffix in COHORT_GENERIC_EXTENSIONS:
            item["kind"] = "code"
            text, err = _read_limited(src)
            if text is None:
                item["status"] = "not_compared"
                item["unobserved_reason"] = (
                    "too_large" if err == "too_large" else "unreadable")
                too_large_note = too_large_note or err == "too_large"
                continue
            if not text.strip():
                item["status"] = "not_compared"
                item["unobserved_reason"] = "not_applicable"
                continue
            if suffix == ".py":
                code_texts[rel] = text
            else:
                generic_texts[rel] = text
            item["status"] = "compared"
        else:
            item["kind"] = "other"
            item["status"] = "not_compared"
            item["unobserved_reason"] = "not_applicable"

    # --- lanes ----------------------------------------------------------
    referee_flagged: list = []
    referee_all: list = []
    referee_summary = {}
    if doc_texts:
        try:
            import sieve_referee
            compare_docs: Dict[str, str] = {}
            for rel, text in doc_texts.items():
                stripped, removed = _cohort_measure_exclusions(
                    text, exclude_quotes=exclude_quotes,
                    exclude_bibliography=exclude_bibliography,
                    base_texts=base_texts or None)
                if any(int(v.get("length", 0))
                       for v in removed.values()):
                    item_by_rel[rel]["removed"] = {
                        k: {"length": int(v.get("length", 0))}
                        for k, v in removed.items()}
                if stripped.strip():
                    compare_docs[rel] = stripped
                else:
                    item_by_rel[rel]["status"] = "not_compared"
                    item_by_rel[rel]["unobserved_reason"] = "empty_input"
            results = sieve_referee.batch_evaluate(
                compare_docs, base_documents=None,
                exclude_quotes=exclude_quotes,
                exclude_bibliography=exclude_bibliography)
            counts = {"RED": 0, "YELLOW": 0, "GREEN": 0, "total": 0}
            spans_map = {}
            try:
                from sieve_referee.explain import explain_results
                spans_map = explain_results(compare_docs, results)
            except Exception:  # noqa: BLE001 - explanation is additive
                spans_map = {}
            for res in results:
                cls = getattr(res.evaluation_signal, "name", str(
                    res.evaluation_signal))
                counts[cls] = counts.get(cls, 0) + 1
                counts["total"] += 1
                a, b = res.item_id, res.matched_peer_id
                if a is None or b is None:
                    continue
                mask = res.mask
                flagged = cls in ("RED", "YELLOW")
                spans = spans_map.get("%s_vs_%s" % (a, b)) or []
                referee_all.append({"a": a, "b": b,
                                    "lane": "referee", "label": cls,
                                    "flagged": flagged})
                if flagged:
                    referee_flagged.append({
                        "a": a, "b": b,
                        "referee": {"class": cls, "mask": mask},
                        "spans": {
                            "count": len(spans),
                            "total_length": sum(
                                max(0, int(s.get("a_end", 0))
                                    - int(s.get("a_start", 0)))
                                for s in spans)}})
                    span_data.setdefault((a, b), []).extend(spans)
            referee_summary = counts
        except ImportError:
            referee_summary = {}
            progress("Cohort: referee unavailable")

    scope_flagged, scope_all, scope_removal, scope_emptied = \
        _cohort_scope_pairs(code_texts, base_texts or None, progress)
    generic_flagged, generic_all, generic_removal, generic_emptied = \
        _cohort_generic_pairs(generic_texts, base_texts or None, progress)
    for rel in scope_emptied + generic_emptied:
        it = item_by_rel.get(rel)
        if it is not None:
            it["status"] = "not_compared"
            it["unobserved_reason"] = "empty_input"
    for rel, report in {**scope_removal, **generic_removal}.items():
        it = item_by_rel.get(rel)
        if it is not None and int(report.get("removed_tokens", 0)) > 0:
            it["removed"] = {"base": {"length":
                                      int(report.get("removed_tokens",
                                                     0))}}

    # --- receipt --------------------------------------------------------
    compared_n = sum(1 for it in items if it["status"] == "compared")
    not_compared_n = sum(1 for it in items
                         if it["status"] == "not_compared")
    reasons: Dict[str, int] = {}
    for it in items:
        if it["status"] == "not_compared" and it.get(
                "unobserved_reason"):
            reasons[it["unobserved_reason"]] = \
                reasons.get(it["unobserved_reason"], 0) + 1

    receipt = {
        "receipt_version": 1,
        "kind": COHORT_KIND,
        "tool": {"name": "sieve-tray", "version": __version__},
        "engines": _cohort_engine_table(),
        "settings": {
            "exclude_quotes": bool(exclude_quotes),
            "exclude_bibliography": bool(exclude_bibliography),
            "include_paths": bool(include_paths),
            "include_input_hashes": bool(include_input_hashes),
            "explanation": _cohort_explanation_settings(),
        },
        "items": items,
        "pairs": sorted(
            referee_flagged + scope_flagged + generic_flagged,
            key=lambda p: (p["a"], p["b"])),
        "summary": {
            "items": len(items),
            "compared": compared_n,
            "not_compared": not_compared_n,
            "not_compared_by_reason": reasons,
            "referee": referee_summary,
            "scope": {"pairs": len(scope_all),
                      "short_circuited": 0},
            "generic": {"pairs": len(generic_all)},
            "flagged": len(referee_flagged) + len(scope_flagged)
                       + len(generic_flagged),
        },
    }
    if base_texts:
        receipt["settings"]["base"] = {
            "sha256": ["sha256:" + hashlib.sha256(
                Path(p).read_bytes()).hexdigest()
                for p in (base_paths or ())]}
    # the base exclusion applies to the lanes whose engines received it
    receipt["settings"]["base_lanes"] = [
        lane for lane, present in
        (("referee", bool(doc_texts)), ("scope", bool(code_texts)),
         ("generic", bool(generic_texts))) if present and base_texts]
    # the too_large threshold is Gate's own read limit (the ruling:
    # reuse it and write it into the report)
    receipt["settings"]["too_large_bytes"] = TRAY_READ_LIMIT_BYTES
    # the generic flag rule is written into the settings and the
    # report (the 2026-11-10 ruling: either side at/over the
    # threshold, so an inclusion is not missed)
    receipt["settings"]["generic_flag_per_mille"] = \
        COHORT_GENERIC_FLAG_PER_MILLE
    receipt["settings"]["generic_flag_side"] = "either"

    # the report goes first, the receipt is written last (CH-T01)
    report_texts = dict(doc_texts)
    html_doc = _render_cohort_report(
        receipt, fragments, doc_texts=report_texts,
        span_data=span_data,
        all_pairs=referee_all + scope_all + generic_all,
        excluded_total=sum(
            (it.get("removed") or {}).get(k, {}).get("length", 0)
            for it in items for k in ("bibliography", "quotes", "base")),
        too_large_note=too_large_note, lang=lang)
    _gate_write_atomic(local / "cohort-report.html",
                       html_doc.encode("utf-8"))
    if not include_paths:
        # the 2026-11-10 receipt ruling (request §2-5): a record
        # without paths identifies items by sequence number - the
        # flagged pairs carry the submission file names, which is
        # where the personal names live, so the pairs take the same
        # numbers.  The report above has already rendered with the
        # names (it is local-only and never leaves this machine).
        seq_of = {rel: seq for seq, rel in enumerate(rels, start=1)}
        try:
            for p in receipt["pairs"]:
                p["a"] = seq_of[p["a"]]
                p["b"] = seq_of[p["b"]]
        except KeyError as exc:
            raise ValueError(
                "pair references an unknown item: %s" % (exc,))
        receipt["pairs"] = sorted(
            receipt["pairs"], key=lambda p: (p["a"], p["b"]))
    receipt["digest"] = _gate_digest(receipt)
    pairs = receipt["pairs"]
    blob = _gate_norm_json(receipt)
    _gate_write_atomic(handoff / "cohort-receipt.json",
                       blob.encode("utf-8"))

    # --- history (§3.7): allowlisted counts only, no paths, no bodies;
    # a broken storage never fails the run itself (the gate rule)
    if storage_path is not None:
        try:
            from sieve_tray_storage import Storage
            storage = Storage(str(storage_path))
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            removed_total = 0
            for it in items:
                for rep in (it.get("removed") or {}).values():
                    removed_total += int(rep.get("length", 0))
            storage.record_cohort_run({
                "run_id": "cohort-" + now.replace(":", "")
                                       .replace("-", ""),
                "ts_utc": now,
                "items": len(items),
                "compared": compared_n,
                "not_compared": not_compared_n,
                "pairs_flagged": len(pairs),
                "removed_total": removed_total,
                "receipt_digest": receipt["digest"],
                "engines": _gate_engines_version(),
            })
        except Exception:
            progress("Cohort: history record skipped")
    return receipt


def _cohort_document_item(engine, src: Path, data: bytes, suffix: str,
                          item: dict, hidden: dict,
                          fragments: List[dict], seq: int
                          ) -> Optional[str]:
    """The document lane (request §3.1): Lens observation -> visible
    text for the referee map.  A rule-originated css_hidden segment
    fails the item closed (the gate ruling - its visible text is never
    compared).  Returns the visible text or None (the item stays
    not_compared)."""
    try:
        obs = engine.observe(str(src))
        mask = obs.mask
        entry = {"path": str(src), "mask": mask,
                 "flagged": (mask != "1000-000"
                             and not mask.startswith("0")),
                 "h_states": dict(obs.h_states),
                 "evidence": dict(obs.evidence)}
    except Exception as e:  # noqa: BLE001
        entry = {"path": str(src), "mask": "0000-000", "flagged": False,
                 "h_states": {}, "evidence": {},
                 "error": type(e).__name__}
    status, reason, detail = classify_observation(entry)
    item["lens"] = {"mask": entry["mask"]}
    if status == "unobserved":
        item["status"] = "not_compared"
        item["unobserved_reason"] = reason
        return None
    orderable, rule_hidden = _gate_classify_hidden(
        getattr(obs, "segments", []))
    if rule_hidden:
        hidden["count"] = len(orderable) + len(rule_hidden)
        item["hidden_segments"] = hidden
        for seg in getattr(obs, "segments", []):
            if seg.visible and seg.text and seg.text.strip():
                fragments.append({"item": seq, "text": seg.text,
                                  "kind": "withheld"})
        item["status"] = "not_compared"
        item["unobserved_reason"] = "refused"
        item["unobserved_detail"] = "css_rule_hidden"
        return None
    for seg in orderable:
        if seg.text and seg.text.strip():
            fragments.append({"item": seq, "text": seg.text,
                              "kind": "hidden"})
    item["hidden_segments"] = _gate_order_on_hidden(orderable)
    try:
        from sieve_lens import visible_text
    except ImportError:
        item["status"] = "not_compared"
        item["unobserved_reason"] = "engine_unavailable"
        return None
    vt = visible_text(obs, strip=set(GATE_STRIP_KINDS))
    out_text = vt.text
    if out_text and not out_text.endswith("\n"):
        out_text += "\n"
    if not out_text.strip():
        item["status"] = "not_compared"
        item["unobserved_reason"] = "empty_input"
        return None
    item["status"] = "compared"
    return out_text


def _cohort_pair_label(p: dict) -> str:
    lane = p.get("lane")
    if lane == "referee":
        return str(p.get("label"))
    if lane == "scope":
        return "mask %s" % p.get("label")
    return "%s ‰" % p.get("label")


def _render_cohort_report(receipt: dict, fragments: List[dict], *,
                          doc_texts=None, span_data=None, all_pairs=None,
                          excluded_total: int = 0,
                          too_large_note: bool = False,
                          lang: str = "en") -> str:
    """The report (request §3.6): the leading line first, the counts,
    the pairs (flagged first, then by name), the matched spans side by
    side with the spans wrapped in <mark> (each document capped at
    20,000 characters with the omitted count, 50 pairs maximum with
    the shown/total line), the deterministic SVG - no JavaScript, no
    external requests.  ja/en both (the 2026-11-09 ruling ⑤)."""
    parts = ["<!doctype html><html><head><meta charset=\"utf-8\">",
             "<title>%s</title></head><body>" % html.escape(
                 _cohort_tr(lang, "title"))]
    # the leading line (request §3.6): an observation, not a conclusion
    parts.append("<p>%s</p>" % html.escape(
        _cohort_tr(lang, "leading_line")))
    summary = receipt.get("summary") or {}
    parts.append("<h2>%s</h2>" % html.escape(
        _cohort_tr(lang, "counts_heading")))
    parts.append("<p>%s: %d / %s: %d</p>" % (
        html.escape(_cohort_tr(lang, "items_label")),
        summary.get("items", 0),
        html.escape(_cohort_tr(lang, "compared_label")),
        summary.get("compared", 0)))
    parts.append("<p>%s: %d</p>" % (
        html.escape(_cohort_tr(lang, "not_compared_label")),
        summary.get("not_compared", 0)))
    reasons = summary.get("not_compared_by_reason") or {}
    if reasons:
        parts.append("<p>%s: %s</p>" % (
            html.escape(_cohort_tr(lang, "not_compared_reasons")),
            html.escape(", ".join(
                "%s=%d" % (k, v) for k, v in sorted(reasons.items())))))
    parts.append("<p>%s</p>" % html.escape(
        _cohort_tr(lang, "excluded_total", n=excluded_total)))
    removed_detail = {}
    for it in receipt.get("items", []):
        for k, v in (it.get("removed") or {}).items():
            removed_detail[k] = removed_detail.get(k, 0) + \
                int(v.get("length", 0))
    if removed_detail:
        parts.append("<p>%s</p>" % html.escape(
            "Excluded: " + ", ".join(
                "%s %d" % (k, v) for k, v in sorted(removed_detail.items()))))
    lanes = (receipt.get("settings") or {}).get("base_lanes") or []
    if lanes:
        parts.append("<p>%s</p>" % html.escape(
            _cohort_tr(lang, "base_lanes_label",
                       lanes=", ".join(lanes))))
    if too_large_note:
        parts.append("<p>%s</p>" % html.escape(
            _cohort_tr(lang, "too_large_label",
                       n=TRAY_READ_LIMIT_BYTES)))
    # --- the pair listing (all pairs, existing vocabulary and colors)
    parts.append("<h2>%s</h2>" % html.escape(
        _cohort_tr(lang, "pairs_heading")))
    # the generic flag rule stated in the report (2026-11-10 ruling)
    parts.append("<p>%s</p>" % html.escape(_cohort_tr(
        lang, "generic_rule",
        per_mille=COHORT_GENERIC_FLAG_PER_MILLE)))
    parts.append("<table><tr><th>%s</th><th>%s</th><th>%s</th></tr>"
                 % (html.escape(_cohort_tr(lang, "pair_of")),
                    html.escape(_cohort_tr(lang, "lane")),
                    html.escape(_cohort_tr(lang, "observation"))))
    pairs = list(all_pairs or [])
    flagged_first = sorted(
        pairs, key=lambda p: (0 if p.get("flagged") else 1,
                              str(p.get("a")), str(p.get("b"))))
    for p in flagged_first:
        obs = _cohort_pair_label(p)
        cls = "signal-red" if p.get("label") in ("RED", "red") else ""
        parts.append("<tr><td>%s vs %s</td><td>%s</td>"
                     "<td class=\"%s\">%s</td></tr>"
                     % (html.escape(str(p.get("a"))),
                        html.escape(str(p.get("b"))),
                        html.escape(str(p.get("lane"))),
                        cls, html.escape(obs)))
    parts.append("</table>")
    # --- the matched spans of the flagged pairs, side by side
    parts.append("<h2>%s</h2>" % html.escape(
        _cohort_tr(lang, "spans_heading")))
    shown = 0
    span_data = span_data or {}
    receipt_pairs = {(p.get("a"), p.get("b")): p
                     for p in receipt.get("pairs", [])}
    for (a, b), p in list(receipt_pairs.items())[
            :COHORT_REPORT_PAIR_CAP]:
        a_text = (doc_texts or {}).get(a)
        b_text = (doc_texts or {}).get(b)
        if a_text is None or b_text is None:
            continue
        parts.append("<h3>%s vs %s</h3>" % (html.escape(a),
                                            html.escape(b)))
        parts.append(_cohort_render_fragment(
            a_text, b_text, span_data.get((a, b)) or []))
        shown += 1
    if len(receipt_pairs) > COHORT_REPORT_PAIR_CAP:
        parts.append("<p>%s</p>" % html.escape(_cohort_tr(
            lang, "pairs_shown", shown=shown,
            total=len(receipt_pairs))))
    # --- the graph
    all_names = set(doc_texts)
    for p in (all_pairs or []):
        all_names.add(p.get("a"))
        all_names.add(p.get("b"))
    for it in receipt.get("items", []):
        if it.get("path"):
            all_names.add(it["path"])
    all_names.discard(None)
    node_names = sorted(all_names)
    svg = _cohort_svg_graph(all_pairs, node_names)
    parts.append("<h2>%s</h2>" % html.escape(
        _cohort_tr(lang, "graph_heading")))
    # the change from the design plan is stated in the report (the
    # 2026-11-10 ruling)
    parts.append("<p>%s</p>" % html.escape(_cohort_tr(lang, "graph_note")))
    parts.append(svg)
    if fragments:
        parts.append("<h2>%s</h2>" % html.escape(
            _cohort_tr(lang, "hidden_heading")))
        for f in fragments[:50]:
            parts.append("<p>%s</p>" % html.escape(
                "[item %s] %s" % (f.get("item"), f.get("text", ""))))
        if len(fragments) > 50:
            parts.append("<p>%s</p>" % html.escape(
                "... %d" % (len(fragments) - 50)))
    parts.append("</body></html>")
    return "\n".join(parts)


def _cohort_summary_consistent(obj: dict) -> bool:
    """The GREEN 照合 (the 2026-11-10 ruling): the receipt lists the
    flagged pairs only, so the summary counts are cross-checked against
    the pairs list and against each other - GREEN has no individual
    entries and lives in the summary alone, so the arithmetic must hold
    for the record to be verifiable."""
    summary = obj.get("summary") or {}
    pairs = obj.get("pairs") or []
    if summary.get("flagged") != len(pairs):
        return False
    n_ref = n_scope = n_gen = 0
    for p in pairs:
        lanes = sum(1 for k in ("referee", "scope", "generic") if k in p)
        if lanes != 1:
            return False
        if "referee" in p:
            n_ref += 1
        elif "scope" in p:
            n_scope += 1
        else:
            n_gen += 1
    ref = summary.get("referee") or {}
    if ref:
        if ref.get("RED", 0) + ref.get("YELLOW", 0) != n_ref:
            return False
        if ref.get("GREEN", 0) != (ref.get("total", 0)
                                   - ref.get("RED", 0)
                                   - ref.get("YELLOW", 0)):
            return False
    sc = summary.get("scope") or {}
    if sc and sc.get("pairs", 0) != n_scope:
        return False
    gen = summary.get("generic") or {}
    if gen and gen.get("pairs", 0) != n_gen:
        return False
    return True


def verify_gate(receipt_path, input_dir=None, output_dir=None, *,
                scope=None, redact_config=None, base_paths=None) -> dict:
    """Re-check a run (request §3.4).  scope is always reported:
    outputs_only / inputs_and_outputs / replay.  overall is
    match / differs / not_verifiable; the CLI maps it to exit codes
    0 / 1 / 2.  The words of judgment ("pass" etc.) are never used.

    A Cohort receipt (kind sieve-cohort, request §3.7) is verified in
    the same vocabulary: handoff/ carries the receipt only, so with no
    folders given the scope defaults to outputs_only; the summary
    arithmetic (the GREEN 照合) is cross-checked in every scope - a
    record whose numbers do not hold together is reported with the
    existing receipt_unreadable word (the 2026-11-10 ruling: the
    verify vocabulary is the published M1 contract and stays closed,
    request §2-7; the distinction is carried by the human-readable
    wording, not by a new vocabulary word); the base files given via
    base_paths are hashed against the recorded settings (a mismatch is
    settings_unavailable); the replay re-runs run_cohort with the
    recorded settings and compares the digests."""
    receipt_path = Path(receipt_path)
    result = {"scope": None, "overall": None, "items": [],
              "not_verifiable_reason": None}
    if not receipt_path.is_file():
        result["scope"] = scope or "outputs_only"
        result["overall"] = "not_verifiable"
        result["not_verifiable_reason"] = "handoff_incomplete"
        return result
    try:
        obj = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result["scope"] = scope or "outputs_only"
        result["overall"] = "not_verifiable"
        result["not_verifiable_reason"] = "receipt_unreadable"
        return result
    result["scope"] = scope
    is_cohort = obj.get("kind") == COHORT_KIND
    if obj.get("receipt_version") != GATE_RECEIPT_VERSION:
        result["overall"] = "not_verifiable"
        result["not_verifiable_reason"] = "receipt_version_unsupported"
        return result
    if obj.get("digest") != _gate_digest(obj):
        result["overall"] = "not_verifiable"
        result["not_verifiable_reason"] = "receipt_digest_mismatch"
        return result
    if scope is None:
        if output_dir is not None and input_dir is not None:
            scope = "inputs_and_outputs"
        elif output_dir is not None:
            scope = "outputs_only"
        elif input_dir is not None:
            scope = "replay"
        elif is_cohort:
            # the Cohort handoff carries the receipt only (§3.1), so
            # with nothing else given the outputs scope is the receipt
            # itself
            scope = "outputs_only"
        else:
            # the 2026-11-10 ruling: the error wording is for the user
            raise ValueError(
                "verify cannot tell what to check: pass the run's "
                "output folder (--output), the original input folder, "
                "or an explicit --scope (outputs_only / "
                "inputs_and_outputs / replay)")
        result["scope"] = scope
    elif scope not in ("outputs_only", "inputs_and_outputs", "replay"):
        raise ValueError(
            "unknown scope: %r (the scopes are outputs_only, "
            "inputs_and_outputs, replay)" % (scope,))

    # the Cohort pre-checks (§3.7): the summary arithmetic and the base
    # files.  Both run in every scope - they are properties of the
    # record itself, not of the folders.
    bases: List[Path] = []
    recorded_bases: list = []
    if is_cohort:
        if not _cohort_summary_consistent(obj):
            # the 2026-11-10 ruling: the verify vocabulary is the M1
            # published contract and stays closed (request §2-7), so a
            # record whose summary arithmetic does not hold together is
            # reported with the existing word receipt_unreadable - the
            # distinction is carried by the human-readable wording
            # (README / report), not by a new vocabulary word
            result["overall"] = "not_verifiable"
            result["not_verifiable_reason"] = "receipt_unreadable"
            return result
        base_settings = (obj.get("settings") or {}).get("base") or {}
        recorded_bases = list(base_settings.get("sha256") or [])
        for raw in (base_paths or ()):  # missing base is fail-closed
            p = Path(raw)
            if not p.is_file():
                result["overall"] = "not_verifiable"
                result["not_verifiable_reason"] = "settings_unavailable"
                return result
            bases.append(p)
        if recorded_bases and bases:
            got = ["sha256:" + hashlib.sha256(b.read_bytes()).hexdigest()
                   for b in bases]
            if got != recorded_bases:
                result["overall"] = "not_verifiable"
                result["not_verifiable_reason"] = "settings_unavailable"
                return result

    # engine version drift is reported but never stops the comparison
    current = {e["name"]: e["version"] for e in _gate_engine_table()}
    version_drift = []
    for e in obj.get("engines", []):
        if current.get(e["name"]) != e["version"]:
            version_drift.append(e["name"])

    reasons: List[dict] = []

    if scope in ("outputs_only", "inputs_and_outputs"):
        base = Path(output_dir) if output_dir else receipt_path.parent
        for it in obj.get("items", []):
            out_info = it.get("output")
            if out_info is None:
                continue
            rel = out_info["path"][len("handoff/"):]
            p = base / rel
            if not p.is_file():
                entry = _gate_verify_item_ident(it)
                entry["reason"] = "output_missing"
                reasons.append(entry)
                continue
            blob = p.read_bytes()
            if hashlib.sha256(blob).hexdigest() != out_info["sha256"]:
                entry = _gate_verify_item_ident(it)
                entry["reason"] = "output_changed"
                reasons.append(entry)

    if scope == "inputs_and_outputs":
        in_dir = Path(input_dir)
        present = {}
        for root, _dirs, names in os.walk(in_dir, followlinks=False):
            for name in names:
                rel = (Path(root) / name).relative_to(in_dir)
                present[rel.as_posix()] = (Path(root) / name)
        seen = set()
        for it in obj.get("items", []):
            path = it.get("path")
            if path is None:
                continue
            seen.add(path)
            p = in_dir / path
            if not p.is_file() or p.is_symlink():
                entry = _gate_verify_item_ident(it)
                entry["reason"] = "input_missing"
                reasons.append(entry)
                continue
            want = it.get("input", {}).get("sha256")
            got = hashlib.sha256(p.read_bytes()).hexdigest()
            if want and got != want:
                entry = _gate_verify_item_ident(it)
                entry["reason"] = "input_changed"
                reasons.append(entry)
        for rel in present:
            if rel not in seen:
                reasons.append({"path": rel, "reason": "item_added"})

    if scope == "replay" and is_cohort:
        # the Cohort replay (§3.7): re-run the comparison with the
        # recorded settings; the reproduced receipt must be
        # byte-identical, which also covers the summary counts the
        # receipt does not list individually (the GREEN 照合)
        if recorded_bases and not bases:
            # the exclusion cannot be reproduced without the base files
            result["overall"] = "not_verifiable"
            result["not_verifiable_reason"] = "settings_unavailable"
            return result
        csettings = obj.get("settings") or {}
        with tempfile.TemporaryDirectory() as td:
            receipt2 = run_cohort(
                Path(input_dir), Path(td) / "out",
                base_paths=bases or None,
                exclude_quotes=bool(csettings.get("exclude_quotes")),
                exclude_bibliography=bool(
                    csettings.get("exclude_bibliography")),
                include_paths=bool(csettings.get("include_paths", True)),
                include_input_hashes=bool(
                    csettings.get("include_input_hashes", True)))
        if receipt2["digest"] != obj.get("digest"):
            for it2 in receipt2["items"]:
                ident = _gate_verify_item_ident(it2)
                ident["reason"] = "replay_differs"
                reasons.append(ident)
    elif scope == "replay":
        settings = obj.get("settings", {})
        config_sha = settings.get("redact", {}).get("config_sha256")
        if config_sha is not None:
            if redact_config is None:
                result["overall"] = "not_verifiable"
                result["not_verifiable_reason"] = "settings_unavailable"
                return result
            got = "sha256:" + hashlib.sha256(
                Path(redact_config).read_bytes()).hexdigest()
            if got != config_sha:
                result["overall"] = "not_verifiable"
                result["not_verifiable_reason"] = "settings_unavailable"
                return result
        with tempfile.TemporaryDirectory() as td:
            replay_out = Path(td) / "out"
            red = settings.get("redact", {})
            receipt2 = run_gate(
                Path(input_dir), replay_out,
                redact_builtins=tuple(red.get("builtins")
                                      or GATE_DEFAULT_BUILTINS),
                redact_mode=red.get("mode") or GATE_REDACT_MODE,
                redact_config=redact_config,
                no_redact=not red.get("builtins") and
                red.get("config_sha256") is None,
                include_paths=settings.get("include_paths", True),
                include_input_hashes=settings.get(
                    "include_input_hashes", True))
        if receipt2["digest"] != obj.get("digest"):
            for it2 in receipt2["items"]:
                ident = _gate_verify_item_ident(it2)
                ident["reason"] = "replay_differs"
                reasons.append(ident)
        else:
            old_out = {(_gate_verify_item_ident(i2))["path"]
                       if "path" in i2 else ("index", i2["index"]): i2
                       for i2 in obj.get("items", [])}

    if version_drift:
        for it in obj.get("items", []):
            entry = _gate_verify_item_ident(it)
            entry["reason"] = "engine_version_differs"
            reasons.append(entry)

    # deduplicate: an item keeps at most one reason, replay_differs and
    # engine_version_differs included (the comparison never stops)
    dedup = {}
    for entry in reasons:
        key = (entry.get("path"), entry.get("index"))
        if key not in dedup:
            dedup[key] = entry
    result["items"] = list(dedup.values())
    result["overall"] = "differs" if result["items"] else "match"
    result["not_verifiable_reason"] = None
    return result


def gate_self_check(progress: ProgressCallback = _silent) -> dict:
    """The self-check (request §3.5): run the sample pack through Gate
    in a temp folder and compare the expected observations (never a
    digest).  Returns {"expected": n, "matching": n, "differences":
    [...]}."""
    manifest_path = REPO_ROOT / "samples" / "gate" / "MANIFEST.json"
    if not manifest_path.is_file():
        # The sample pack is a repository resource (the audit's reference
        # vocab follows the same pattern): installed wheels and frozen
        # bundles do not carry it.  Report a structured error instead of
        # crashing with a FileNotFoundError.
        return {"error": "sample_pack_not_available",
                "detail": str(REPO_ROOT / "samples" / "gate")}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    import shutil as _shutil
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in"
        inp.mkdir()
        out = Path(td) / "out"
        for entry in manifest["items"]:
            _shutil.copyfile(REPO_ROOT / "samples" / "gate" / entry["file"],
                             inp / entry["file"])
        receipt = run_gate(inp, out, progress=progress)
    by_name = {it["path"]: it for it in receipt["items"]}
    fields = ("kind", "status", "hidden_count", "order_observed",
              "order_axes", "redact_spans", "treatment",
              "not_produced_reason")
    diffs = []
    for entry in manifest["items"]:
        it = by_name.get(entry["file"])
        if it is None:
            diffs.append({"file": entry["file"], "field": "presence",
                          "expected": True, "actual": None})
            continue
        expect = entry["expect"]
        actual = {
            "kind": it["kind"],
            "status": it["status"],
            "hidden_count": it["hidden_segments"]["count"],
            "order_observed": it["hidden_segments"]["order_observed"],
            "order_axes": it["hidden_segments"]["order_axes"],
            "redact_spans": it["redact"]["spans"],
            "treatment": it["treatment"],
            "not_produced_reason": it["not_produced_reason"],
        }
        for field in fields:
            if actual[field] != expect.get(field):
                diffs.append({"file": entry["file"], "field": field,
                              "expected": expect.get(field),
                              "actual": actual[field]})
    return {"expected": len(manifest["items"]),
            "matching": len(manifest["items"]) - len(diffs),
            "differences": diffs}


def cohort_self_check(progress: ProgressCallback = _silent) -> dict:
    """The self-check (request §3.8): run the sample pack through the
    Cohort in a temp folder and compare the expected observations -
    the pair colors, the excluded-length ranges, the span presence,
    the hidden-text presence - never a digest.  Returns {"expected":
    n, "matching": n, "differences": [...]}.

    The manifest's role "base" entries are passed via --base, never
    copied into the comparison folder; the run config (the exclusions)
    comes from the manifest's "run" block, so the pack exercises the
    same configuration its expectations were measured with."""
    manifest_path = REPO_ROOT / "samples" / "cohort" / "MANIFEST.json"
    if not manifest_path.is_file():
        # the pack is a repository resource (see gate_self_check):
        # installed wheels and frozen bundles do not carry it
        return {"error": "sample_pack_not_available",
                "detail": str(REPO_ROOT / "samples" / "cohort")}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    import shutil as _shutil
    run_cfg = manifest.get("run") or {}
    subs, bases = [], []
    for entry in manifest["items"]:
        (bases if entry.get("role") == "base" else subs).append(entry)
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in"
        inp.mkdir()
        out = Path(td) / "out"
        for entry in subs:
            _shutil.copyfile(
                REPO_ROOT / "samples" / "cohort" / entry["file"],
                inp / entry["file"])
        receipt = run_cohort(
            inp, out, progress=progress,
            base_paths=[REPO_ROOT / "samples" / "cohort" / b["file"]
                        for b in bases] or None,
            exclude_quotes=bool(run_cfg.get("exclude_quotes")),
            exclude_bibliography=bool(run_cfg.get("exclude_bibliography")))
    by_name = {it.get("path", str(it.get("index"))): it
               for it in receipt["items"]}
    diffs = []
    for entry in subs:
        it = by_name.get(entry["file"])
        if it is None:
            diffs.append({"file": entry["file"], "field": "presence",
                          "expected": True, "actual": None})
            continue
        expect = entry.get("expect") or {}
        for field in ("kind", "status"):
            if field in expect and it[field] != expect[field]:
                diffs.append({"file": entry["file"], "field": field,
                              "expected": expect[field],
                              "actual": it[field]})
        hm = expect.get("hidden_count_min")
        if hm is not None and it["hidden_segments"]["count"] < hm:
            diffs.append({"file": entry["file"], "field": "hidden_count",
                          "expected": ">= %d" % hm,
                          "actual": it["hidden_segments"]["count"]})
        for key, rng in (expect.get("removed") or {}).items():
            val = ((it.get("removed") or {}).get(key)
                   or {}).get("length", 0)
            if val < rng.get("min", 0) or val > rng.get("max", val):
                diffs.append({"file": entry["file"],
                              "field": "removed.%s" % key,
                              "expected": rng, "actual": val})
    pair_index = {}
    for p in receipt["pairs"]:
        pair_index[(p["a"], p["b"])] = p
        pair_index[(p["b"], p["a"])] = p
    n_expect = len(subs) + len(manifest.get("pairs") or [])
    for entry in manifest.get("pairs") or []:
        key = (entry["a"], entry["b"])
        expect = entry.get("expect") or {}
        p = pair_index.get(key)
        if expect.get("flagged"):
            if p is None:
                diffs.append({"pair": "%s vs %s" % key,
                              "field": "flagged",
                              "expected": True, "actual": False})
                continue
            lane = expect.get("lane")
            if lane and lane not in p:
                diffs.append({"pair": "%s vs %s" % key, "field": "lane",
                              "expected": lane, "actual": None})
            cls = expect.get("class")
            if cls and (p.get("referee") or {}).get("class") != cls:
                diffs.append({"pair": "%s vs %s" % key, "field": "class",
                              "expected": cls,
                              "actual": (p.get("referee") or {})
                              .get("class")})
            pm = expect.get("per_mille_min")
            if pm is not None:
                got = (p.get("generic") or {}).get("match_per_mille", 0)
                if got < pm:
                    diffs.append({"pair": "%s vs %s" % key,
                                  "field": "match_per_mille",
                                  "expected": ">= %d" % pm, "actual": got})
            sm = expect.get("spans_min")
            if sm is not None:
                got = (p.get("spans") or {}).get("count", 0)
                if got < sm:
                    diffs.append({"pair": "%s vs %s" % key,
                                  "field": "spans",
                                  "expected": ">= %d" % sm, "actual": got})
            sl = expect.get("spans_length_min")
            if sl is not None:
                got = (p.get("spans") or {}).get("total_length", 0)
                if got < sl:
                    diffs.append({"pair": "%s vs %s" % key,
                                  "field": "spans_total_length",
                                  "expected": ">= %d" % sl,
                                  "actual": got})
        elif p is not None:
            diffs.append({"pair": "%s vs %s" % key, "field": "flagged",
                          "expected": False, "actual": True})
    return {"expected": n_expect,
            "matching": n_expect - len(diffs),
            "differences": diffs}


def _gate_main(argv: List[str]) -> int:
    """The `gate` / `verify` shapes (request §3.6).  Only entered when
    sys.argv[1] is exactly one of those words, so the legacy
    `<input folder> -o report.html` shape keeps working."""
    parser = argparse.ArgumentParser(prog="sieve-tray")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="run the Gate over a folder")
    g.add_argument("input_dir", type=Path, nargs="?", default=None)
    g.add_argument("-o", "--output", type=Path, default=None)
    g.add_argument("--redact-builtin", action="append", default=None,
                   metavar="NAME")
    g.add_argument("--redact-config", type=Path, default=None)
    g.add_argument("--no-redact", action="store_true")
    g.add_argument("--crowd-config", type=Path, default=None)
    g.add_argument("--no-paths", action="store_true")
    g.add_argument("--no-input-hashes", action="store_true")
    g.add_argument("--self-check", action="store_true")
    v = sub.add_parser("verify", help="verify a Gate/Cohort receipt")
    v.add_argument("receipt", type=Path)
    v.add_argument("input_dir", nargs="?", type=Path, default=None)
    v.add_argument("--output", "-o", type=Path, default=None)
    v.add_argument("--scope", default=None)
    v.add_argument("--redact-config", type=Path, default=None)
    # §3.7: the Cohort base files for the settings check and the replay
    v.add_argument("--base", action="append", default=None,
                   metavar="PATH")
    # v2.1.0 (M2 Cohort): the cohort subcommand joins gate and verify;
    # the legacy shape and the M1 shapes stay byte-identical.
    c = sub.add_parser("cohort", help="compare the submissions of a "
                                      "folder")
    c.add_argument("input_dir", type=Path, nargs="?", default=None)
    c.add_argument("-o", "--output", type=Path, default=None)
    c.add_argument("--base", action="append", default=None,
                   metavar="PATH")
    c.add_argument("--exclude-quotes", action="store_true")
    c.add_argument("--exclude-bibliography", action="store_true")
    c.add_argument("--no-paths", action="store_true")
    c.add_argument("--no-input-hashes", action="store_true")
    # §3.8: run the sample pack and compare the expected observations
    c.add_argument("--self-check", action="store_true")
    c.add_argument("--lang", default="en", choices=("en", "ja"),
                   help="the report language (default: en)")
    # Seal 2.2 (S2): the manifest subcommand joins gate/verify/cohort;
    # the output placement rules are the gate ones (an -o folder with a
    # handoff/ inside), except a manifest keeps no local/ tree.
    m = sub.add_parser("manifest", help="list a folder (Seal 2.2)")
    m.add_argument("input_dir", type=Path, nargs="?", default=None)
    m.add_argument("-o", "--output", type=Path, default=None)
    m.add_argument("--against", type=Path, default=None)
    m.add_argument("--key-file", type=Path, default=None,
                   metavar="PATH")
    args = parser.parse_args(argv)

    if args.cmd == "manifest":
        if args.input_dir is None or args.output is None:
            parser.error("manifest needs an input folder and -o/--output")
        if not args.input_dir.is_dir():
            parser.error("manifest: %s is not a directory" % args.input_dir)
        if args.against is not None and not args.against.is_dir():
            parser.error("manifest: %s is not a directory" % args.against)
        receipt = run_manifest(
            args.input_dir, args.output, against=args.against,
            key_file=args.key_file, progress=print)
        print("Receipt digest: %s" % receipt["digest"])
        print("Handoff: %s" % (args.output / "handoff"))
        if args.against is None:
            return 0
        # a diff with no change is a clean exit; a changed / removed /
        # added / moved entry (same does not count) is 1 (the verify
        # family semantics)
        s = receipt["summary"]
        dirty = s["changed"] + s["removed"] + s["added"] + s["moved"]
        return 0 if dirty == 0 else 1
    if args.cmd == "cohort":
        if args.self_check:
            # the exit codes (the 2026-11-10 ruling): 0 = the expected
            # observations matched, 1 = a difference, 2 = the self-check
            # could not run; the machine-readable result carries
            # expected / matching either way
            result = cohort_self_check(progress=print)
            print(json.dumps(result, ensure_ascii=False, indent=1))
            if "error" in result:
                return 2
            return 0 if result["matching"] == result["expected"] else 1
        if args.input_dir is None or args.output is None:
            parser.error("cohort needs an input folder and -o/--output")
        receipt = run_cohort(
            args.input_dir, args.output, progress=print,
            base_paths=[Path(p) for p in args.base]
            if args.base else None,
            exclude_quotes=args.exclude_quotes,
            exclude_bibliography=args.exclude_bibliography,
            include_paths=not args.no_paths,
            include_input_hashes=not args.no_input_hashes,
            lang=args.lang)
        print("Receipt digest: %s" % receipt["digest"])
        print("Handoff: %s" % (args.output / "handoff"))
        print("Report:  %s" % (args.output / "local"
                               / "cohort-report.html"))
        return 0
    if args.cmd == "gate":
        if args.self_check:
            # the exit codes (the 2026-11-10 ruling): 0 = the expected
            # observations matched, 1 = a difference, 2 = the self-check
            # could not run; the machine-readable result carries
            # expected / matching either way (the same shape as cohort)
            result = gate_self_check(progress=print)
            print(json.dumps(result, ensure_ascii=False, indent=1))
            if "error" in result:
                return 2
            return 0 if result["matching"] == result["expected"] else 1
        if args.input_dir is None or args.output is None:
            parser.error("gate needs an input folder and -o/--output "
                         "(or --self-check)")
        receipt = run_gate(
            args.input_dir, args.output, progress=print,
            redact_builtins=(tuple(args.redact_builtin)
                             if args.redact_builtin
                             else GATE_DEFAULT_BUILTINS),
            redact_config=args.redact_config, no_redact=args.no_redact,
            crowd_config=args.crowd_config,
            include_paths=not args.no_paths,
            include_input_hashes=not args.no_input_hashes)
        print("Receipt digest: %s" % receipt["digest"])
        print("Handoff: %s" % (args.output / "handoff"))
        print("Report:  %s" % (args.output / "local" / "gate-report.html"))
        return 0
    result = verify_gate(
        args.receipt, input_dir=args.input_dir, output_dir=args.output,
        scope=args.scope, redact_config=args.redact_config,
        base_paths=args.base)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return {"match": 0, "differs": 1,
            "not_verifiable": 2}[result["overall"]]


def main():
    # v1.1.0 (design doc §3.8-E): the engines may use ProcessPoolExecutor, so a
    # frozen (PyInstaller) CLI must call freeze_support() before any child
    # process can re-execute this entry point. It is a no-op outside
    # frozen runs.
    import multiprocessing
    multiprocessing.freeze_support()
    # v2.0.0 (M1 Gate): the new shapes start only when the first
    # argument is exactly `gate` or `verify`; the legacy
    # `<input folder> -o report.html` shape keeps working unchanged
    # (a folder literally named `gate` is passed as `./gate`).
    if len(sys.argv) > 1 and sys.argv[1] in ("gate", "verify",
                                             "cohort", "manifest"):
        sys.exit(_gate_main(sys.argv[1:]))
    parser = argparse.ArgumentParser(prog="sieve-tray")
    parser.add_argument("input_dir", type=Path,
                        help="Directory containing subdirectories to scan")
    parser.add_argument("--output", "-o", type=Path,
                        default=Path("report.html"))
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: {args.input_dir} is not a directory.",
              file=sys.stderr)
        sys.exit(1)

    result = run_scan(args.input_dir, progress=print)

    args.output.write_text(render(result), encoding="utf-8")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
