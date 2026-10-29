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
import html
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# Single source of truth for the package version. pyproject.toml reads
# this dynamically (see [tool.setuptools.dynamic]) instead of duplicating
# the number, since keeping two copies in sync has already caused drift
# more than once during development.
__version__ = "0.10.1"


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

# A progress callback takes a single human-readable status string.
# The CLI passes `print`; a GUI can pass e.g. a Qt signal emitter or
# a log-widget's append method. Defaults to doing nothing, so library
# callers never have to supply one.
ProgressCallback = Callable[[str], None]


def _silent(_msg: str) -> None:
    pass


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

    def to_dict(self) -> dict:
        """JSON-serializable form, used by sieve_tray_storage for history."""
        return {
            "groups": [[name, [str(p) for p in files]] for name, files in self.groups],
            "doc_results": self.doc_results,
            "code_pairs": self.code_pairs,
            "text_pairs": self.text_pairs,
            "audit_results": self.audit_results,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScanResult":
        groups = [(name, [Path(p) for p in files]) for name, files in d["groups"]]
        return cls(groups=groups, doc_results=d["doc_results"],
                    code_pairs=d["code_pairs"],
                    text_pairs=d.get("text_pairs", []),
                    audit_results=d.get("audit_results", []))


def scan(input_dir: Path) -> List[Tuple[str, List[Path]]]:
    groups = []
    for d in sorted(input_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = [f for f in sorted(d.rglob("*")) if f.is_file()]
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
        progress("Note: sieve-lens not installed; skipping document analysis.")
        return []

    # v0.11.0 integration fix: install every available Lens extension so
    # PDF/image observation actually works through Tray (same order
    # contract as the dashboard's _build_engine: image_layers chains onto
    # ocr, html_css_selectors supersedes html_css, pdf_images supersedes pdf).
    import importlib
    engine = SieveLensEngine()
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
            continue

    results = []
    for f in doc_paths:
        try:
            obs = engine.observe(str(f))
            results.append({
                "path": str(f),
                "mask": obs.mask,
                "flagged": (obs.mask != "1000-000"
                            and not obs.mask.startswith("0")),
                "h_states": dict(obs.h_states),
                "evidence": dict(obs.evidence),
            })
        except Exception as e:
            results.append({
                "path": str(f),
                "mask": "0000-000",
                "flagged": False,
                "h_states": {},
                "evidence": {},
                "error": type(e).__name__,
            })
    return results


def compare_code(code_map: Dict[str, str],
                  progress: ProgressCallback = _silent) -> List[dict]:
    if len(code_map) < 2:
        return []
    try:
        from sieve_scope import SieveScopeEngineV1_3, SieveClusterAnalyzerV1_3
    except ImportError:
        progress("Note: sieve-scope not installed; skipping code analysis.")
        return []

    engine = SieveScopeEngineV1_3()
    analyzer = SieveClusterAnalyzerV1_3(engine, min_cluster_size=2)
    analysis = analyzer.analyze_corpus(code_map)

    pairs = []
    for (k1, k2), res in analysis["pair_results"].items():
        if res.get("short_circuited"):
            continue
        pairs.append({
            "a": k1,
            "b": k2,
            "mask": res["mask"],
            "h_states": dict(res.get("h_states", {})),
            "scores": dict(res.get("scores", {})),
        })
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
        groups = scan(input_dir)
    progress(f"Found {len(groups)} groups.")

    code_map: Dict[str, str] = {}
    text_map: Dict[str, str] = {}
    all_docs: List[Path] = []
    for name, files in groups:
        code, doc = split_files(files)
        for f in code:
            key = f"{name}/{f.name}"
            try:
                code_map[key] = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        for f in doc:
            if f.suffix.lower() in TEXT_EXTS:
                key = f"{name}/{f.name}"
                try:
                    text_map[key] = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
        all_docs.extend(doc)

    progress(f"Analyzing {len(all_docs)} documents...")
    doc_results = observe_documents(all_docs, progress)

    progress(f"Comparing {len(code_map)} code files...")
    code_pairs = compare_code(code_map, progress)

    progress(f"Comparing {len(text_map)} text files for similarity...")
    text_pairs = compare_text(text_map, progress)

    progress(f"Auditing {len(text_map)} text files for ungrounded universalization...")
    audit_results, _ = audit_text(text_map, audit_modifier_vocab, progress)

    return ScanResult(groups=groups, doc_results=doc_results,
                       code_pairs=code_pairs, text_pairs=text_pairs,
                       audit_results=audit_results)


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

    parts = ["<!DOCTYPE html>",
             "<html><head><meta charset='UTF-8'>",
             "<title>Sieve Tray Report</title>",
             f"<style>{CSS}</style></head><body>",
             "<h1>Sieve Tray Report</h1>",
             f"<p>{len(groups)} groups scanned.</p>"]

    parts.append("<h2>Documents</h2>")
    if not doc_results:
        parts.append("<p>No documents analyzed.</p>")
    else:
        parts.append("<table><tr><th>File</th><th>Mask</th>"
                     "<th>Status</th></tr>")
        for r in doc_results:
            cls = " class='flagged'" if r["flagged"] else ""
            status = "flagged" if r["flagged"] else "clean"
            parts.append(
                f"<tr{cls}><td><code>{html.escape(r['path'])}</code></td>"
                f"<td><code>{html.escape(r['mask'])}</code></td>"
                f"<td>{status}</td></tr>"
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

    lines = ["# Sieve Tray Report", "",
             f"_{len(groups)} groups scanned._", ""]

    lines.append("## Documents")
    if not doc_results:
        lines.append("No documents analyzed.")
    else:
        lines.append("| File | Mask | Status |")
        lines.append("| --- | --- | --- |")
        for r in doc_results:
            status = "flagged" if r["flagged"] else "clean"
            lines.append(f"| `{r['path']}` | `{r['mask']}` | {status} |")
    lines.append("")

    lines.append("## Code Pairs")
    if not code_pairs:
        lines.append("No suspicious code pairs.")
    else:
        lines.append("| File A | File B | Mask |")
        lines.append("| --- | --- | --- |")
        for p in code_pairs:
            lines.append(f"| `{p['a']}` | `{p['b']}` | `{p['mask']}` |")
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


def main():
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
