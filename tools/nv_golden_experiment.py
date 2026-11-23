"""NV-T11 golden experiment - generate the 2.4.0 / 2.5.0 output corpus.

Runs the SAME inputs through ONE tree (the tree root is argv[1]) and
writes the outputs to argv[2]:

- report.html / report.md   render(result) / render_text(result) for a
  representative ScanResult that exercises every section of the report,
  including the two i18n-referencing sections (Unobserved ->
  unobserved_note, Crowd -> crowd_result_premise) - the exact leak path
  the user's NV-T11 ruling warns about (the same key in the report turns
  the UI-only wording change into an output change).
- manifest-receipt.json     run_manifest()'s receipt JSON (the receipt
  schema of the processing record; tool.version is the ONE documented
  exception).
- gate-self-check.json / clean-self-check.json   the --self-check
  outputs (gate 15 / clean 6 known examples).

Usage: python nv_golden_experiment.py <tree_root> <out_dir>
"""
import json
import sys
from pathlib import Path

TREE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)

# the tree's own modules win over any installed distribution
sys.path.insert(0, str(TREE))

# --- the report corpus ----------------------------------------------------

from sieve_tray import ScanResult, render, render_text, run_manifest  # noqa: E402

result = ScanResult(
    groups=[("group_a", [Path("/in/essay_a.txt"), Path("/in/essay_b.txt")])],
    doc_results=[
        # a clean observation
        {"path": "/in/essay_a.txt", "mask": "1000-000", "flagged": False,
         "h_states": {}, "evidence": {}},
        # a flagged observation (hidden characters observed)
        {"path": "/in/essay_b.txt", "mask": "1100-000", "flagged": True,
         "h_states": {"h1": "hidden"},
         "evidence": {"h1": ["U+200B ZERO WIDTH SPACE"]}},
        # an unobserved observation (the report's i18n half rides here:
        # the Unobserved section reads tr('en', 'unobserved_note'))
        {"path": "/in/broken.docx", "mask": "0000-000", "flagged": False,
         "h_states": {}, "evidence": {},
         "error": "FileNotFoundError"},
    ],
    code_pairs=[
        {"a": "/in/calc_v1.py", "b": "/in/calc_v2.py",
         "mask": "1111-111"},
    ],
    text_pairs=[
        {"a": "/in/essay_a.txt", "b": "/in/essay_b.txt",
         "signal": "RED", "pattern_name": "shared_rare_trigram"},
    ],
    audit_results=[
        {"file": "/in/essay_a.txt",
         "sentence_text": "All students must submit the report.",
         "signal": "RED", "pattern_name": "universal_necessity",
         "backing": "must", "scope": "sentence",
         "certainty_markers": ["must"]},
    ],
    # the Crowd section (the report's other i18n half rides here:
    # crowd_result_premise)
    crowd_runs=[{
        "input_path": "/in/roster.csv", "output_path": "/out/roster.csv",
        "records_in": 10, "records_out": 9, "suppressed": 1,
        "k_achieved": 2, "max_risk": 0.5, "avg_risk": 0.25,
        "status": "ok", "reason": None,
    }],
    # file-level unobserved entries (the same Unobserved section)
    unobserved=[{"file": "/in/huge.bin", "engine": "lens",
                 "reason": "too_large", "detail": "42 MB"}],
    short_circuited_excluded=3,
)
(OUT / "report.html").write_text(render(result), encoding="utf-8")
(OUT / "report.md").write_text(render_text(result), encoding="utf-8")

# --- the manifest receipt (the processing-record JSON schema) -------------

in_dir = OUT / "manifest_input"
in_dir.mkdir(exist_ok=True)
(in_dir / "alpha.txt").write_text("alpha\n", encoding="utf-8")
(in_dir / "beta.txt").write_text("beta\n", encoding="utf-8")
sub = in_dir / "sub"
sub.mkdir(exist_ok=True)
(sub / "gamma.txt").write_text("gamma\n", encoding="utf-8")
receipt = run_manifest(in_dir, OUT / "manifest_out")
(OUT / "manifest-receipt.json").write_text(
    json.dumps(receipt, ensure_ascii=False, indent=1, sort_keys=True),
    encoding="utf-8")

# --- the self-checks -------------------------------------------------------

from sieve_tray import gate_self_check  # noqa: E402
from sieve_canon import clean_self_check  # noqa: E402

(OUT / "gate-self-check.json").write_text(
    json.dumps(gate_self_check(progress=None), ensure_ascii=False,
               indent=1, sort_keys=True), encoding="utf-8")
(OUT / "clean-self-check.json").write_text(
    json.dumps(clean_self_check(progress=None), ensure_ascii=False,
               indent=1, sort_keys=True), encoding="utf-8")

print("written:", OUT)
