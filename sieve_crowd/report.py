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
        "status": {"anonymized": "anonymized", "refused": "refused (no output written)"},
        "reason": {
            "no_records": "the table has no records",
            "resource_limit_rows": "the table has more records than the configured limit",
            "resource_limit_search": "the search needed more steps than the configured limit; use fewer or coarser quasi-identifiers",
            "infeasible": "k (and l) cannot be reached for this table, even with every quasi-identifier suppressed",
            "verification_failed": "the measurement on the output did not confirm the requested k / l",
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
        "verified": "Verification: measured again on the output table: passed",
        "relax": "Relaxations: {items}",
        "relax_none": "Relaxations: none",
    },
    "ja": {
        "title": "Sieve Crowd {version}",
        "status": {"anonymized": "匿名化済み", "refused": "拒否（出力は書き込まれていません）"},
        "reason": {
            "no_records": "表にレコードがありません",
            "resource_limit_rows": "表のレコード数が設定の上限を超えています",
            "resource_limit_search": "探索が設定の上限を超えました。準識別子の数を減らすか、粗くしてください",
            "infeasible": "すべての準識別子を隠しても、この表ではkまたはlを満たせません",
            "verification_failed": "出力の測定で、要求したkまたはlを確認できませんでした",
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
        "verified": "検証: 出力の表で再測定し、合格しました",
        "relax": "緩和: {items}",
        "relax_none": "緩和: なし",
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
