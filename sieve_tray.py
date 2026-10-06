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
from typing import Callable, Dict, List, Tuple

# Single source of truth for the package version. pyproject.toml reads
# this dynamically (see [tool.setuptools.dynamic]) instead of duplicating
# the number, since keeping two copies in sync has already caused drift
# more than once during development.
__version__ = "0.3.5"


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

    def to_dict(self) -> dict:
        """JSON-serializable form, used by sieve_tray_storage for history."""
        return {
            "groups": [[name, [str(p) for p in files]] for name, files in self.groups],
            "doc_results": self.doc_results,
            "code_pairs": self.code_pairs,
            "text_pairs": self.text_pairs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScanResult":
        groups = [(name, [Path(p) for p in files]) for name, files in d["groups"]]
        return cls(groups=groups, doc_results=d["doc_results"],
                    code_pairs=d["code_pairs"], text_pairs=d.get("text_pairs", []))


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


def run_scan(input_dir: Path, progress: ProgressCallback = _silent) -> ScanResult:
    """Core entry point. Scans input_dir and returns a ScanResult.

    This is the single function a GUI needs to call; it does no I/O
    other than reading the input files, and reports status purely
    through `progress` rather than printing directly, so it is safe
    to call from a background/worker thread.
    """
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

    return ScanResult(groups=groups, doc_results=doc_results,
                       code_pairs=code_pairs, text_pairs=text_pairs)


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


def render(result: ScanResult) -> str:
    groups = result.groups
    doc_results, code_pairs, text_pairs = (
        result.doc_results, result.code_pairs, result.text_pairs)

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

    parts.append("<p style='margin-top:2rem;color:#666;font-size:.85rem;'>"
                 "This is an observation report, not a judgment. "
                 "Human review is required.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


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
