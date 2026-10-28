"""Core crowd wrappers in sieve_tray.py: thin in-process calls into the
vendored sieve_crowd package. Each wrapper returns plain Python values
(a list of observations, a Config, or a flat summary dict) so a GUI can
surface them directly. A refused run is a normal result, not an
exception, and never writes an output file.
"""

import json
from collections import Counter

import pytest

import sieve_tray
from sieve_crowd import ConfigError

HEADER = ["name", "age", "city"]
QI_IDX = (1, 2)

COLS = {
    "name": {"role": "drop"},
    "age": {"role": "qi", "type": "numeric", "widths": [10]},
    "city": {"role": "qi", "type": "exact"},
}

ROWS_5 = [
    ["Alice", "30", "Osaka"],
    ["Bob", "30", "Osaka"],
    ["Carol", "40", "Kyoto"],
    ["Dave", "40", "Kyoto"],
    ["Eve", "25", "Nara"],
]


def _config_text(**top):
    obj = {"k": 2, "l": 1, "max_suppression": 0.2, "columns": dict(COLS)}
    obj.update(top)
    return json.dumps(obj)


def _count_alone(rows):
    groups = Counter(tuple(r[i] for i in QI_IDX) for r in rows)
    return sum(1 for r in rows if groups[tuple(r[i] for i in QI_IDX)] < 2)


def test_crowd_inspect_returns_column_observations():
    obs = sieve_tray.crowd_inspect(HEADER, ROWS_5)
    assert [o["name"] for o in obs] == HEADER
    assert all(set(o) == {"name", "distinct", "empty", "unique_ratio", "shape"}
               for o in obs)
    assert obs[1]["shape"] == "integer"
    assert obs[0]["distinct"] == 5
    assert obs[0]["empty"] == 0


def test_crowd_parse_config_builds_config_from_json_text():
    cfg = sieve_tray.crowd_parse_config(_config_text())
    assert cfg.k == 2 and cfg.l == 1 and cfg.max_suppression == 0.2
    assert set(cfg.columns) == set(HEADER)


def test_crowd_parse_config_maps_json_syntax_errors_to_config_error():
    with pytest.raises(ConfigError) as ei:
        sieve_tray.crowd_parse_config("{\n  \"k\": 5,}")
    msg = str(ei.value)
    assert "not valid JSON" in msg
    assert "line 2" in msg


def test_crowd_dry_run_reports_before_after_and_writes_nothing():
    cfg = sieve_tray.crowd_parse_config(_config_text())
    s = sieve_tray.crowd_dry_run(HEADER, ROWS_5, cfg)
    assert s["ok"] is True and s["status"] == "anonymized"
    assert s["reason"] is None
    assert s["records_in"] == 5 and s["records_out"] == 4 and s["suppressed"] == 1
    assert s["k_requested"] == 2 and s["k_achieved"] == 2
    assert s["before_alone"] == _count_alone(ROWS_5) == 1
    assert s["after_alone"] == 0
    assert s["io"] is None
    assert "Sieve Crowd" in s["report_text"]
    assert json.loads(s["report_json"])["status"] == "anonymized"
    assert s["header"] == ["age", "city"]
    assert len(s["rows"]) == 4


def test_crowd_dry_run_returns_refusal_as_a_normal_result():
    cfg = sieve_tray.crowd_parse_config(_config_text(k=5))
    s = sieve_tray.crowd_dry_run(HEADER, ROWS_5[:3], cfg)
    assert s["ok"] is False and s["status"] == "refused"
    assert s["reason"] == "infeasible"
    assert s["header"] is None and s["rows"] is None
    assert s["records_in"] == 3
    assert s["records_out"] is None and s["k_achieved"] is None
    assert s["max_risk"] is None and s["before_alone"] is None
    assert "refused" in s["report_text"]


def test_crowd_anonymize_writes_output_file_for_anonymized_status(tmp_path):
    cfg = sieve_tray.crowd_parse_config(_config_text())
    out = tmp_path / "out.csv"
    s = sieve_tray.crowd_anonymize(HEADER, ROWS_5, cfg,
                                   io=("csv", "csv"), output_path=str(out))
    assert s["ok"] is True
    assert out.exists()
    from sieve_crowd.tableio import write_any
    assert out.read_bytes() == write_any(s["header"], s["rows"], "csv")
    assert s["io"] == {"input_format": "csv", "output_format": "csv"}
    assert s["records_out"] == 4 and s["before_alone"] == 1 and s["after_alone"] == 0


def test_crowd_anonymize_refused_writes_no_file(tmp_path):
    cfg = sieve_tray.crowd_parse_config(_config_text(k=5))
    out = tmp_path / "out.csv"
    s = sieve_tray.crowd_anonymize(HEADER, ROWS_5[:3], cfg,
                                   output_path=str(out))
    assert s["ok"] is False and s["reason"] == "infeasible"
    assert not out.exists()


def test_crowd_anonymize_without_output_path_returns_japanese_receipt():
    cfg = sieve_tray.crowd_parse_config(_config_text())
    s = sieve_tray.crowd_anonymize(HEADER, ROWS_5, cfg, lang="ja")
    assert s["ok"] is True
    assert s["io"] is None
    assert "群れの大きさ" in s["report_text"]
    assert s["report_json"] != ""
