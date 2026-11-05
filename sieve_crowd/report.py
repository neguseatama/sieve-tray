"""Receipt of one run. Never contains cell values; column names and aggregate numbers only."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any

from . import __version__

_MSG = {
    "en": {
        "title": "Sieve Crowd {version}",
        "status": {"anonymized": "anonymized", "refused": "refused (no output written)",
                   "plan": "plan (estimate only; nothing searched, nothing written)"},
        "reason": {
            "no_records": "the table has no records",
            "resource_limit_rows": "the table has more records than the configured limit",
            "resource_limit_search": "the search needed more steps than the configured limit; use fewer or coarser quasi-identifiers",
            "infeasible": "k (and l) cannot be reached for this table, even with every quasi-identifier suppressed",
            "verification_failed": "the measurement on the output did not confirm the requested k / l",
            "missing_exceeds_budget": ("more records have an empty quasi-identifier value than the suppression "
                                       "budget allows (policy 'suppress'); raise max_suppression or use 'star'"),
        },
        "records": "Records: {n_in} in, {n_out} out ({sup} suppressed, {pct:.1f}%)",
        "format_in": "Format: {fmt} in",
        "format_out": ", {fmt} out",
        "crowd": "Crowd size: every record is one of at least {k} look-alikes on: {cols}",
        "crowd_detail": "  smallest crowds: {sizes}; records alone in their crowd: {alone}",
        "before": "Before: {a} of {n} records ({p:.0%}) were one-of-a-kind on those columns. After: {b}.",
        "risk": "  re-identification risk (given those columns): at most {mx:.1%}, on average {av:.1%}",
        "div": "Diversity of \"{col}\": at least {l} different values in every crowd",
        "cols": "Columns:",
        "id_drop": "  {c}: removed (direct identifier)",
        "id_pseudo": "  {c}: replaced by keyed pseudonyms (same key => same pseudonym)",
        "qi": "  {c}: {how}",
        "sens": "  {c}: kept as is (sensitive)",
        "keep": "  {c}: kept as is (unique values: {u:.0%})",
        "drop": "  {c}: removed",
        "order_shuffled": "Row order: shuffled (seed {seed})",
        "order_kept": "Row order: kept as in the input",
        "loss": "Information loss: generalization {h}/{H} steps, suppression {pct:.1f}%",
        "suppression_detail": ("Suppression detail: {crowds} crowd(s), {records} record(s): "
                                "{kc} smaller than k ({kr} records), {lc} short of diversity ({lr} records)."),
        "verified": "Verification: measured again on the output table: passed",
        "relax": "Relaxations: {items}",
        "relax_none": "Relaxations: none",
        "diag_infeasible": "Diagnostics: {records} record(s) in the table; requested k = {k}",
        "diag_sens": "  \"{col}\": {v} distinct value(s) (requested l = {l})",
        "diag_limit": "Diagnostics: lattice {nodes} node(s) (levels per QI: {tops}); evaluations used {evals} of {max_evals}.",
        "diag_verification": ("Diagnostics: {crowds} crowd(s) in the output; {bc} smaller than k "
                              "({br} records); {alone} alone in their crowd."),
        "diag_l_shortfall": "  \"{col}\": {c} crowd(s) short of l-diversity ({r} records)",
        "diag_missing": "Diagnostics: {m} of {records} record(s) have an empty quasi-identifier value; the budget is {budget}.",
        "plan_records": "Records: {n} in, columns: {cols}",
        "plan_lattice": "Search space: {nodes} nodes (max height {h}) on: {cols}",
        "plan_budget": "Suppression budget: {b} of {n} records ({pct:.1f}%)",
        "plan_missing": "Missing quasi-identifier values: {m} of {n} record(s) (policy: {policy})",
        "plan_before": ("Level 0 (no generalization): {a} of {n} records ({p:.0%}) are one-of-a-kind "
                        "on those columns; {below} records are in crowds smaller than k."),
        "plan_sens": "  \"{col}\": {v} distinct value(s) (l = {l})",
        "plan_warnings": "Warnings:",
        "plan_no_warnings": "Warnings: none",
        "warn_rows_over_limit": "the table has {records} record(s) (limit {max_rows}): a run will refuse with resource_limit_rows.",
        "warn_k_unreachable": "k = {k} cannot be reached with {records} record(s).",
        "warn_l_unreachable": "\"{column}\" has only {distinct} distinct value(s), so l = {l} cannot be reached.",
        "warn_budget_zero": ("no suppression is allowed and {records} record(s) are already in crowds "
                             "smaller than k at level 0: generalization alone must fix them."),
        "warn_lattice_large": ("the lattice has {nodes} nodes (cap {cap}): the refinement phase will be "
                               "skipped and the result may not be the absolute optimum."),
        "warn_evals_tight": ("the lattice has up to {nodes} nodes but max_evals is {max_evals}: "
                             "the search may stop with resource_limit_search."),
        "warn_many_singletons": "{records} record(s) ({ratio:.0%}) are one-of-a-kind on the QI columns: expect heavy generalization.",
        "warn_missing_over_budget": ("{records} record(s) have an empty quasi-identifier value but the suppression "
                                     "budget is {budget}: a run will refuse with missing_exceeds_budget."),
        "missing_note": ("  of the {total} suppressed record(s), {m} were dropped up front: empty "
                         "quasi-identifier value (policy 'suppress')."),
    },
    "ja": {
        "title": "Sieve Crowd {version}",
        "status": {"anonymized": "匿名化済み", "refused": "拒否（出力は書き込まれていません）",
                   "plan": "計画（推定のみ。探索も書き込みもしません）"},
        "reason": {
            "no_records": "表にレコードがありません",
            "resource_limit_rows": "表のレコード数が設定の上限を超えています",
            "resource_limit_search": "探索が設定の上限を超えました。準識別子の数を減らすか、粗くしてください",
            "infeasible": "すべての準識別子を隠しても、この表ではkまたはlを満たせません",
            "verification_failed": "出力の測定で、要求したkまたはlを確認できませんでした",
            "missing_exceeds_budget": ("準識別子が空のレコードが除外予算を超えています（方針 suppress）。"
                                       "max_suppression を上げるか、方針を star にしてください"),
        },
        "records": "レコード: 入力 {n_in} 件、出力 {n_out} 件（除外 {sup} 件、{pct:.1f}%）",
        "format_in": "形式: 入力 {fmt}",
        "format_out": "、出力 {fmt}",
        "crowd": "群れの大きさ: すべてのレコードは、次の列について、少なくとも {k} 件の似た者の1つです: {cols}",
        "crowd_detail": "  小さい群れ: {sizes}、群れに1件だけのレコード: {alone}",
        "before": "処理前: それらの列で、{n} 件中 {a} 件（{p:.0%}）が、似た者のいない1件だけの存在でした。処理後: {b} 件。",
        "risk": "  再識別リスク（それらの列を知る相手に対して）: 最大 {mx:.1%}、平均 {av:.1%}",
        "div": "「{col}」の多様性: どの群れにも少なくとも {l} 種類の値があります",
        "cols": "列:",
        "id_drop": "  {c}: 削除（直接識別子）",
        "id_pseudo": "  {c}: 鍵付きの仮名に置換（同じ鍵なら同じ仮名）",
        "qi": "  {c}: {how}",
        "sens": "  {c}: そのまま（機微情報）",
        "keep": "  {c}: そのまま（値が一意な割合: {u:.0%}）",
        "drop": "  {c}: 削除",
        "order_shuffled": "行の順序: シャッフル済み（シード {seed}）",
        "order_kept": "行の順序: 入力のまま",
        "loss": "情報の損失: 一般化 {h}/{H} 段階、除外 {pct:.1f}%",
        "suppression_detail": ("除外の内訳: {crowds} 群れ・{records} 件 — k 未満 {kc} 群れ（{kr} 件）、"
                               "多様性不足 {lc} 群れ（{lr} 件）。"),
        "verified": "検証: 出力の表で再測定し、合格しました",
        "relax": "緩和: {items}",
        "relax_none": "緩和: なし",
        "diag_infeasible": "診断: 表のレコードは {records} 件、要求 k = {k}",
        "diag_sens": "  「{col}」: 異なる値 {v} 種類（要求 l = {l}）",
        "diag_limit": "診断: 格子 {nodes} ノード（QIごとの段数 {tops}）、使用した評価 {evals}（上限 {max_evals}）",
        "diag_verification": "診断: 出力に群れ {crowds} 個、k 未満の群れ {bc} 個（{br} 件）、一独りのレコード {alone} 件。",
        "diag_l_shortfall": "  「{col}」: 多様性が l 未満の群れ {c} 個（{r} 件）",
        "diag_missing": "診断: {records} 件中 {m} 件に準識別子の空値があり、除外予算は {budget} 件です。",
        "plan_records": "レコード: 入力 {n} 件、列数 {cols}",
        "plan_lattice": "探索空間: 準識別子 {cols} の格子は {nodes} ノード（最大の高さ {h}）",
        "plan_budget": "除外の上限: {n} 件中 {b} 件（{pct:.1f}%）",
        "plan_missing": "準識別子の空値: {n} 件中 {m} 件（方針: {policy}）",
        "plan_before": "段階0（そのまま）では、{n} 件中 {a} 件（{p:.0%}）が一独りで、k 未満の群れに属するレコードは {below} 件です。",
        "plan_sens": "  「{col}」: 異なる値 {v} 種類（l = {l}）",
        "plan_warnings": "警告:",
        "plan_no_warnings": "警告: なし",
        "warn_rows_over_limit": "レコード数 {records} 件が上限 {max_rows} 件を超えています。実行すると resource_limit_rows で拒否されます。",
        "warn_k_unreachable": "レコードが {records} 件しかないため、k = {k} には届きません。",
        "warn_l_unreachable": "「{column}」の異なる値は {distinct} 種類しかないため、l = {l} には届きません。",
        "warn_budget_zero": "除外は 0 件しか許されず、段階0で既に {records} 件が k 未満の群れに属します。一般化だけで満たす必要があります。",
        "warn_lattice_large": "格子は {nodes} ノードで上限 {cap} を超えるため、改善フェーズは省略され、結果が厳密な最適にならないことがあります。",
        "warn_evals_tight": "格子は最大 {nodes} ノードに対し max_evals が {max_evals} のため、探索が resource_limit_search で打ち切られる可能性があります。",
        "warn_many_singletons": "QI 列だけで一独りのレコードが {records} 件（{ratio:.0%}）です。強い一般化が必要になる見込みです。",
        "warn_missing_over_budget": "準識別子が空のレコードが {records} 件ありますが、除外予算は {budget} 件です。実行すると missing_exceeds_budget で拒否されます。",
        "missing_note": "  除外 {total} 件のうち {m} 件は、準識別子の空値として検索前に除外されました（方針 suppress）。",
    },
}


@dataclass(frozen=True)
class Report:
    data: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True)

    def text(self, lang: str = "en") -> str:
        m, d = _MSG[lang], self.data
        lines = [m["title"].format(version=d["version"]),
                 ("Status: " if lang == "en" else "状態: ") + m["status"][d["status"]]]
        if d["status"] == "refused":
            lines.append(("Reason: " if lang == "en" else "理由: ") + m["reason"][d["reason"]])
            dg = d.get("diagnostics")
            if dg:
                if d["reason"] == "infeasible":
                    lines.append(m["diag_infeasible"].format(records=dg["records"], k=dg["k_requested"]))
                    for col, v in dg.get("sensitive_distinct", {}).items():
                        lines.append(m["diag_sens"].format(col=col, v=v, l=dg["l_requested"]))
                elif d["reason"] == "resource_limit_search":
                    lines.append(m["diag_limit"].format(nodes=dg["lattice_nodes"], tops=dg["tops"],
                                                        evals=dg["evaluations"], max_evals=dg["max_evals"]))
                elif d["reason"] == "verification_failed":
                    lines.append(m["diag_verification"].format(
                        crowds=dg["crowds"],
                        bc=sum(c for _s, c in dg["crowd_sizes_below_k"]), br=dg["records_below_k"],
                        alone=dg["records_alone"]))
                    for col, e in dg.get("l_shortfalls", {}).items():
                        lines.append(m["diag_l_shortfall"].format(col=col, c=e["crowds"], r=e["records"]))
                elif d["reason"] == "missing_exceeds_budget":
                    lines.append(m["diag_missing"].format(m=dg["missing"], records=dg["records"],
                                                          budget=dg["budget"]))
            return "\n".join(lines)
        if d["status"] == "plan":
            p, b = d["lattice"], d["budget"]
            lines.append(m["plan_records"].format(n=d["input"]["records"], cols=d["input"]["columns"]))
            lines.append(m["plan_lattice"].format(nodes=p["nodes"], h=p["max_height"],
                                                  cols=", ".join(p["quasi_identifiers"])))
            lines.append(m["plan_budget"].format(b=b["records"], n=d["input"]["records"],
                                                 pct=100 * b["max_suppression"]))
            if d["missing"]["records"]:
                lines.append(m["plan_missing"].format(m=d["missing"]["records"],
                                                      n=d["input"]["records"],
                                                      policy=d["missing"]["policy"]))
            bf = d["before"]
            lines.append(m["plan_before"].format(a=bf["records_alone"], n=d["input"]["records"],
                                                 p=bf["records_alone_ratio"], below=bf["records_below_k"]))
            if d["settings"]["l"] > 1:
                for col, v in d["sensitive"]["distinct"].items():
                    lines.append(m["plan_sens"].format(col=col, v=v, l=d["settings"]["l"]))
            if d["warnings"]:
                lines.append(m["plan_warnings"])
                for w in d["warnings"]:
                    lines.append("  - " + m["warn_" + w["code"]].format(**w["params"]))
            else:
                lines.append(m["plan_no_warnings"])
            return "\n".join(lines)
        r = d["result"]
        lines.append(m["records"].format(n_in=d["input"]["records"], n_out=r["records_out"],
                                         sup=r["suppressed"], pct=100 * r["suppression_rate"]))
        if d.get("io"):
            line = m["format_in"].format(fmt=d["io"]["input_format"])
            if d["io"].get("output_format"):
                line += m["format_out"].format(fmt=d["io"]["output_format"])
            lines.append(line)
        p = d["privacy"]
        lines.append(m["crowd"].format(k=p["k_achieved"], cols=", ".join(p["quasi_identifiers"])))
        lines.append(m["crowd_detail"].format(sizes=", ".join(map(str, p["smallest_crowds"])),
                                              alone=p["records_alone_in_crowd"]))
        bf = p["before"]
        lines.append(m["before"].format(a=bf["records_alone"], n=d["input"]["records"],
                                        p=bf["records_alone_ratio"], b=p["records_alone_in_crowd"]))
        lines.append(m["risk"].format(mx=p["max_risk"], av=p["average_risk"]))
        for col, l in p["diversity"].items():
            lines.append(m["div"].format(col=col, l=l))
        lines.append(m["cols"])
        for c in d["columns"]:
            role = c["role"]
            if role == "id":
                lines.append(m["id_pseudo" if c["action"] == "pseudonymize" else "id_drop"].format(c=c["name"]))
            elif role == "qi":
                lines.append(m["qi"].format(c=c["name"], how=c["description_" + lang]))
            elif role == "sensitive":
                lines.append(m["sens"].format(c=c["name"]))
            elif role == "keep":
                lines.append(m["keep"].format(c=c["name"], u=c["unique_ratio"]))
            else:
                lines.append(m["drop"].format(c=c["name"]))
        lines.append(m["order_shuffled"].format(seed=d["order"]["seed"]) if d["order"]["shuffled"]
                     else m["order_kept"])
        loss = d["information_loss"]
        lines.append(m["loss"].format(h=loss["height"], H=loss["max_height"], pct=100 * r["suppression_rate"]))
        sup = d.get("diagnostics", {}).get("suppression")
        if sup:
            bk, bl = sup["reasons"]["below_k"], sup["reasons"]["below_l"]
            lines.append(m["suppression_detail"].format(
                crowds=sup["dropped_crowds"], records=sup["dropped_records"],
                kc=bk["crowds"], kr=bk["records"], lc=bl["crowds"], lr=bl["records"]))
        if r.get("missing_suppressed"):
            lines.append(m["missing_note"].format(total=r["suppressed"], m=r["missing_suppressed"]))
        lines.append(m["verified"])
        lines.append(m["relax"].format(items=", ".join(d["relaxations"])) if d["relaxations"]
                     else m["relax_none"])
        return "\n".join(lines)


def base(status: str, *, reason: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"tool": "sieve-crowd", "version": __version__,
                         "unicode_data_version": unicodedata.unidata_version, "status": status}
    if reason:
        d["reason"] = reason
    return d
