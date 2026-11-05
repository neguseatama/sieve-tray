"""scan: one static HTML page — how the table looks right now (v0.8.0).

``scan`` assembles what the other read-only commands already measure into a
single reading document.  It creates **no new measurement**: the provisional
roles come from the hint-pack candidates (the ``inspect`` mechanism, the
v0.5.2 candidate order), the group sizes and per-column observations from
:mod:`sieve_crowd.audit`, the derived keep-vs-qi relations from
:mod:`sieve_crowd.derived`, the invisible-character counts from
:mod:`sieve_crowd.hidden_chars`, and the visible-notation character set from
the shared chartable.  This module is pure assembly and rendering: the CLI
handler reads the table, calls those functions and writes the page — nothing
here touches the file system, the clock or the environment, so the same input
yields byte-identical output.

Report contract (aggregates only): column names, counts, floored per-mille
shares, rule ids, file base names and the input SHA-256 — **never a cell
value**.  The wording follows the release's style: an observation, not a
verdict (no "safe", "unsafe", "pass" or "fail" in any message), positive
first, neutral colors, and every share computed in integer arithmetic
(``1000 * count // n`` rendered with one decimal).

Findings are listed in a fixed order (code ascending, then column name in
codepoint order, then the source order), so the page does not depend on load
order.  User-derived strings (column names, base names, pack ids and
versions, rule ids, the draft JSON) are HTML-escaped and their invisible and
control characters (the chartable's invisible categories plus C0 — tab and
newline excepted — C1 and DEL) are shown as ``<U+XXXX>``; column names
truncate at 120 code points for display, the draft keeps the full names so it
stays copy-pasteable.
"""
from __future__ import annotations

import json
import os
import re
from typing import Mapping, Optional, Sequence

from . import __version__
from .audit import SIZE_BUCKETS, SUBJECT_BUCKETS
from .derived import RELATIONS

FIXED_ORDER = ("hidden_chars", "japanese_era", "leak", "mixed_form",
               "role_mismatch")      # findings order: code ascending
MAX_NAME_DISPLAY = 120              # code points (display only)

# --------------------------------------------------------------------------- #
# text plumbing: visible notation, escaping, truncation, shares
# --------------------------------------------------------------------------- #
_NOTATION: Optional[frozenset] = None


def _notation_set() -> frozenset:
    """The characters shown as ``<U+XXXX>``: the chartable's invisible
    categories, C0 (tab and newline excepted), C1 and DEL."""
    global _NOTATION
    if _NOTATION is None:
        from .chartable import invisible_categories   # lazy, as everywhere
        cps = set().union(*invisible_categories().values())
        cps |= set(range(0x00, 0x20)) - {0x09, 0x0A}
        cps |= {0x7F}
        cps |= set(range(0x80, 0xA0))
        _NOTATION = frozenset(cps)
    return _NOTATION


def _visible(text: str) -> str:
    """Invisible and control characters become a visible ``<U+XXXX>`` form."""
    s = _notation_set()
    if not any(ord(c) in s for c in text):
        return text
    return "".join(f"<U+{ord(c):04X}>" if ord(c) in s else c for c in text)


def _esc(text: str) -> str:
    """Text-node escape for user-derived strings.  Beyond the HTML five it
    also encodes ``= ( ) @``, so a hostile name can never assemble ``src=``,
    ``href=``, ``url(``, ``@import`` or an ``on*=`` attribute anywhere in the
    page."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&#39;")
                .replace("=", "&#61;").replace("(", "&#40;")
                .replace(")", "&#41;").replace("@", "&#64;"))


def _esc_lit(text: str) -> str:
    """Escape for the report's own literals (no user data in them)."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _shorten(name: str) -> str:
    """Column names display at most 120 code points (display only)."""
    return name if len(name) <= MAX_NAME_DISPLAY else name[:MAX_NAME_DISPLAY] + "…"


def _col(name: str) -> str:
    """The display form of a column name: truncated, visible, escaped."""
    return _esc(_visible(_shorten(name)))


def _pct(permille: int) -> str:
    """A floored per-mille as a one-decimal percent (integer math only)."""
    return f"{permille // 10}.{permille % 10}"


# --------------------------------------------------------------------------- #
# wording (en / ja)
# --------------------------------------------------------------------------- #
_W = {
    "en": {
        "title": "scan",
        "h1": "How the table looks right now — {name}",
        "stdin": "(standard input)",
        "meta_size": "{rows} rows × {cols} columns",
        "meta_sha": "input SHA-256: {sha}",
        "meta_version": "Sieve Crowd {version}",
        "meta_packs": "hint packs: {packs}",
        "meta_no_packs": "no hint pack",
        "pack_item": "{id} {version} ({source})",
        "pack_item_nover": "{id} ({source})",
        "src_builtin": "builtin",
        "src_file": "file",
        "meta_k": "k = {k}",
        "h2_summary": "Summary",
        "h2_columns": "Columns",
        "h2_groups": "Group sizes",
        "h2_percolumn": "Per-column observations",
        "h2_derived": "Derived relations",
        "h2_subject": "Repeated subjects",
        "h2_next": "Next steps",
        "h2_about": "About this report",
        "howto": "How to read this section: {text}",
        "s1_size": "The table holds {rows} rows × {cols} columns.",
        "s2_prov": "The roles are provisional: {parts} column(s).",
        "s2_cfg": "The configuration treats {parts} column(s).",
        "part_sep": ", ",
        "part_unit": " column(s)",
        "part_unassigned": "{label} {count}{unit}",
        "s3_groups": ("Rows sharing the same quasi-identifier values form {count} "
                      "group(s); the smallest holds {min} row(s). {pct}% of the rows "
                      "sit in groups smaller than k = {k}."),
        "s4_findings": ("The packs and the observations recorded {w} finding(s) in "
                        "the column list."),
        "s4_findings_subject": ("The packs and the observations recorded {w} finding(s) "
                                "in the column list ({s} was used to count the people "
                                "behind the rows)."),
        "s5_next": "The next-step section holds a configuration draft and example commands.",
        "guidance": ("No quasi-identifier candidates were found, so the group-size, "
                     "per-column and derived sections are left out. Decide which "
                     "columns are the quasi-identifiers, write the configuration, "
                     "and plan/run are ready to use."),
        "howto_summary": "the shape of the whole table, in a few sentences and integers only.",
        "howto_columns_prov": ("the roles are provisional. The evidence says whether the "
                               "pack's top candidate judged the column by its name, its "
                               "values, or both. Findings are counts per kind; a kind "
                               "that is not listed is 0."),
        "howto_columns_cfg": ("the roles are the ones declared in the configuration. "
                              "Evidence and findings are the pack's observations; "
                              "findings are counts per kind, and a kind that is not "
                              "listed is 0."),
        "cap_columns": "role, evidence, candidates and finding counts per column",
        "th_col": "column",
        "th_role": "role",
        "th_evidence": "evidence",
        "th_rules": "candidate rules",
        "th_findings": "findings (counts)",
        "role_id_prov": "id (provisional, excluded from the output by default)",
        "role_unassigned": "unassigned (provisionally keep)",
        "dash": "—",
        "hidden_summary_line": ("the invisible-character observation checked {checked} "
                                "column(s); {flagged} carry a finding."),
        "howto_groups": ("rows sharing the same quasi-identifier values are counted by "
                         "group size. The bar shows the share (integer percent, "
                         "floored); the number is the exact value."),
        "intro_groups": ("There are {count} group(s), the smallest holds {min} row(s); "
                         "{up}% of the rows are alone in their group, {bp}% sit in "
                         "groups smaller than k = {k}."),
        "over_limit": ("the table holds {rows} rows, above the {max_rows} limit; the "
                       "observation read every row."),
        "cap_groups": "rows by group size",
        "th_bucket": "size",
        "th_share": "share",
        "th_rows": "rows",
        "unit_rows": "{n} row(s)",
        "howto_percolumn": ("per quasi-identifier column: how varied the values are, "
                            "and whether the column is what separates the groups."),
        "cap_percolumn": "observations per quasi-identifier column",
        "th_distinct": "distinct values",
        "th_unique": "unique rows",
        "th_without": "rows below k without it",
        "howto_derived": ("keep columns (kept verbatim in the output) are cross-checked "
                          "against the quasi-identifier columns in both directions. "
                          "support counts the rows the check rests on, violations the "
                          "rows it fails to pin down."),
        "intro_pairs": ("{pairs} keep × qi pair(s) were checked in both directions; "
                        "{flagged} of them came out as one column nearly determining "
                        "the other."),
        "intro_classes": ("directions: unchecked {u}, trivial {t}, flagged {f}, "
                          "clear {c}."),
        "skipped_note": "({skipped} pair(s) above the cap were not checked)",
        "no_keep_note": "no keep columns, so no pair was checked.",
        "zero_flagged": "no pair came out flagged.",
        "cap_derived": "pairs where one column nearly determines the other",
        "th_keep": "keep column",
        "th_qi": "qi column",
        "th_dir": "direction",
        "th_support": "support (rows)",
        "th_viol": "violations (rows)",
        "dir_reveals": "the keep column nearly determines the qi column",
        "dir_implied": "the qi column nearly determines the keep column",
        "howto_subject_with": ("the people are counted by the value of the --subject "
                               "column; each empty value counts as one person of its own."),
        "howto_subject_without": ("give --subject a column to count the people behind "
                                  "the rows."),
        "subject_examples": "in this table {names} could serve as the subject column.",
        "subj_line": ("column {name} holds {subjects} subject(s) ({with_} row(s) with a "
                      "value, {missing} empty); {repeated} appear on 2 or more rows, "
                      "{in_rep} rows in all, and one subject appears on at most "
                      "{max_rows} rows."),
        "subj_class_line": ("distinct subjects per group: at least {min}; {below} row(s) "
                            "sit in groups holding fewer than k = {k} distinct "
                            "subjects, {over} of them in groups of size >= k."),
        "cap_subj_buckets": "rows per subject (subjects per bucket)",
        "th_subjects": "subjects",
        "unit_subjects": "{n} subject(s)",
        "next_draft_label": "configuration draft",
        "next_commands_label": "commands to try next",
        "howto_next": ("the draft is meant to be edited; replace the example file "
                       "names."),
        "next_q_note": "columns with role ? need a decided role before plan/run.",
        "about_items": [
            "this is an observation, not a judgment of safety. The numbers are the "
            "values of this table under the roles as they are placed now.",
            "the table is assumed to have one row per person. If the same person "
            "appears in more than one row, observe the repetition with --subject.",
            "k-anonymity does not prevent matching against other information, or "
            "guessing an attribute from the values inside a group.",
            "this report was produced by reading the table once; it changes nothing and "
            "writes only this page.",
            "no cell value appears anywhere. The page carries column names, counts, "
            "shares, rule ids, file names and the input SHA-256 — nothing else.",
            "the same input produces the same bytes every time (no clock, no "
            "environment values).",
            "findings are listed in a fixed order: kind (code ascending), then column "
            "name (codepoint order), then the source order.",
            "shares are computed in integer arithmetic (floored per-mille) and shown "
            "with one decimal.",
            "column names longer than 120 code points are shortened for display (the "
            "draft below keeps the full names).",
            "{roles_note}",
            "color carries no information (neutral colors only).",
            f"produced by sieve-crowd scan, Sieve Crowd {__version__}.",
        ],
        "roles_note_prov": ("the roles are provisional — placed from the hint-pack "
                            "candidates, not decided."),
        "roles_note_cfg": "the roles are the ones the configuration declares.",
    },
    "ja": {
        "title": "scan",
        "h1": "いまどう見えているか — {name}",
        "stdin": "（標準入力）",
        "meta_size": "{rows} 行 × {cols} 列",
        "meta_sha": "入力 SHA-256: {sha}",
        "meta_version": "Sieve Crowd {version}",
        "meta_packs": "ヒントパック: {packs}",
        "meta_no_packs": "ヒントパックなし",
        "pack_item": "{id} {version}（{source}）",
        "pack_item_nover": "{id}（{source}）",
        "src_builtin": "内蔵",
        "src_file": "ファイル",
        "meta_k": "k = {k}",
        "h2_summary": "要点",
        "h2_columns": "列の一覧",
        "h2_groups": "グループの大きさ",
        "h2_percolumn": "列ごとの観測",
        "h2_derived": "導出関係",
        "h2_subject": "同一対象の繰り返し",
        "h2_next": "次の一手",
        "h2_about": "この報告について",
        "howto": "この節の読み方: {text}",
        "s1_size": "この表は {rows} 行 × {cols} 列です。",
        "s2_prov": "列の役割は仮の割り当てで、{parts}です。",
        "s2_cfg": "設定では{parts}として扱います。",
        "part_sep": "・",
        "part_unit": " 列",
        "part_unassigned": "{label}{count}{unit}",
        "s3_groups": ("同じ準識別子の値の組を持つ行の集まり（グループ）は {count} 個で、"
                      "最小 {min} 行です。k = {k} 未満のグループに属する行は {pct}% です。"),
        "s4_findings": "パックと観測の所見は計 {w} 件で、列の一覧に件数を記録しました。",
        "s4_findings_subject": ("パックと観測の所見は計 {w} 件で、列の一覧に件数を記録しました"
                                "（対象の列 {s} では人の繰り返しも数えています）。"),
        "s5_next": "次の一手に設定の下書きとコマンドの例を用意しました。",
        "guidance": ("準識別子の候補が見つからなかったため、グループの大きさ・列ごとの観測・"
                     "導出関係の各節は省きました。どの列を準識別子として扱うかを決めて設定に"
                     "書けば、plan と run が使えます。"),
        "howto_summary": "表全体のあらましを、短い文と整数だけで書いています。",
        "howto_columns_prov": ("役割は現時点の仮の割り当てです。根拠は、いちばん上の候補をパックが"
                               "列の名前と値のどちらから判断したかを示します。所見は種類ごとの"
                               "件数で、何も書かれていない種別は 0 件です。"),
        "howto_columns_cfg": ("役割は設定で宣言されたものです。根拠と所見はパックの観察です。"
                              "所見は種類ごとの件数で、何も書かれていない種別は 0 件です。"),
        "cap_columns": "列ごとの役割・根拠・候補と所見の件数",
        "th_col": "列",
        "th_role": "役割",
        "th_evidence": "根拠",
        "th_rules": "候補ルール",
        "th_findings": "所見（件数）",
        "role_id_prov": "id（仮・出力から除く前提）",
        "role_unassigned": "未割当（仮に keep）",
        "dash": "—",
        "hidden_summary_line": "不可視文字の観察は {checked} 列を調べ、{flagged} 列に所見がありました。",
        "howto_groups": ("同じ準識別子の値の組を持つ行の集まり（グループ）を、大きさごとに"
                         "数えています。棒の長さは全体の中の割合（整数パーセント、切り捨て）の"
                         "目安で、数値が正確な値です。"),
        "intro_groups": ("グループは {count} 個で、最小のグループは {min} 行です。"
                         "1 行だけのグループに属する行は {up}%、"
                         "k = {k} 未満のグループに属する行は {bp}% です。"),
        "over_limit": "行数 {rows} は上限 {max_rows} を超えています。観測はすべての行を読みました。",
        "cap_groups": "グループのサイズ別の行数",
        "th_bucket": "サイズ",
        "th_share": "割合",
        "th_rows": "行数",
        "unit_rows": "{n} 行",
        "howto_percolumn": ("準識別子として扱った列ごとに、値のばらつきと、その列がグループの"
                            "分かれ方に効いているかを数えています。"),
        "cap_percolumn": "準識別子の列ごとの観測",
        "th_distinct": "異なる値",
        "th_unique": "1 行だけのグループに属する行",
        "th_without": "この列を外すと k 未満になる行",
        "howto_derived": ("keep（出力にそのまま残す）として扱った列と準識別子の列の組み合わせを、"
                          "両方向で調べています。支持は根拠となる行数、違反は値を言い当てられなかった"
                          "行数です。"),
        "intro_pairs": ("keep の列と準識別子の列の組み合わせは {pairs} 組で、うち {flagged} 組が"
                        "「一方の列からもう一方の列の値がほぼ推定できる」状態でした。"),
        "intro_classes": ("方向の内訳: 未判定（unchecked）{u}・情報なし（trivial）{t}・"
                          "該当（flagged）{f}・それ以外（clear）{c}。"),
        "skipped_note": "（上限を超えた {skipped} 組は調べていません）",
        "no_keep_note": "keep として扱った列がないため、調べた組み合わせは 0 でした。",
        "zero_flagged": "該当する組み合わせは 0 件でした。",
        "cap_derived": "一方からもう一方がほぼ推定できる組み合わせ",
        "th_keep": "keep の列",
        "th_qi": "準識別子の列",
        "th_dir": "向き",
        "th_support": "支持（行）",
        "th_viol": "違反（行）",
        "dir_reveals": "keep 列から準識別子がほぼ推定できる",
        "dir_implied": "準識別子から keep 列がほぼ推定できる",
        "howto_subject_with": ("--subject で指定した列の値で人を数えています。空の値は"
                               "それぞれ別のひとりとして数えます。"),
        "howto_subject_without": "--subject に列を指定すると、同じ人が複数の行に現れていないかを数えられます。",
        "subject_examples": "この表では {names} が対象の列に使えます。",
        "subj_line": ("列 {name} の値で対象を数えると {subjects} 人でした（値のある行 {with_} 行、"
                      "空の行 {missing} 行）。{repeated} 人が 2 行以上に現れ、その行は {in_rep} 行です。"
                      "もっとも多く現れる対象は {max_rows} 行です。"),
        "subj_class_line": ("グループごとに異なる対象を数えると、最小 {min} 人です。k = {k} 人に"
                            "届かないグループに属する行は {below} 行で、このうち行数では k 以上の"
                            "グループに属する行は {over} 行です。"),
        "cap_subj_buckets": "対象ごとの行数（バケットごとの対象数）",
        "th_subjects": "対象数",
        "unit_subjects": "{n} 人",
        "next_draft_label": "設定の下書き",
        "next_commands_label": "次に試すコマンドの例",
        "howto_next": "下書きは編集して使うためのものです。コマンド例のファイル名は読み替えてください。",
        "next_q_note": "role が ? の列は、役割を決めてから plan / run してください。",
        "about_items": [
            "これは観測であって、安全かどうかの判定ではありません。数値は、この表の、いまの役割の置き方での値です。",
            "1 人が 1 行の表であることを前提にしています。同じ人が複数の行にいる場合は、--subject を指定して観測してください。",
            "k-匿名性は、別の情報との照合や、同じグループ内の値からの属性の推測を防ぐものではありません。",
            "この報告は、表を 1 回読んで作った静的なページです。表も設定も書き換えません。",
            "セルの値はどこにも載っていません。載っているのは列名・件数・割合・ルール id・"
            "ファイル名・入力の SHA-256 だけです。",
            "同じ入力からは、いつでも同じバイト列ができます（日時や環境の情報は載せていません）。",
            "所見の並び順は固定です: 種類（code の昇順）→ 列名（コードポイント順）→ 既定の順。",
            "割合は千分率を切り捨てる整数の演算で作り、小数 1 桁の百分率で表示しています。",
            "表の中の列名は、120 コードポイントを超えると省いて表示します（次の一手の下書きには"
            "全文が入ります）。",
            "{roles_note}",
            "色は情報を運びません（中性の色だけを使っています）。",
            f"sieve-crowd scan（Sieve Crowd {__version__}）が作成しました。",
        ],
        "roles_note_prov": "仮の役割はヒントパックの候補から仮に置いたもので、決定ではありません。",
        "roles_note_cfg": "役割は設定で宣言されたものをそのまま使っています。",
    },
}

_CSS = """:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0 auto; padding: 1rem 1.25rem 3rem; max-width: 64rem; line-height: 1.6; }
h1 { font-size: 1.35rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
.meta, .howto, caption { color: #555; font-size: 0.9rem; margin: 0.2rem 0; }
.howto { margin-bottom: 0.6rem; }
table { border-collapse: collapse; margin: 0.5rem 0; width: 100%; }
caption { caption-side: top; text-align: left; padding: 0.2rem 0; }
th, td { border: 1px solid #aaa; padding: 0.2rem 0.5rem; text-align: left; vertical-align: top; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.bar { min-width: 8rem; width: 40%; }
.fill { background: #808080; height: 0.75rem; }
pre { border: 1px solid #aaa; padding: 0.5rem; overflow-x: auto; font-size: 0.85rem; }
ul { padding-left: 1.25rem; }
@media (max-width: 40rem) { body { padding: 0.75rem; } .bar { min-width: 4rem; } }
@media print { body { max-width: none; } h2 { break-after: avoid; } }
@media (prefers-color-scheme: dark) {
  body { background: #141414; color: #e8e8e8; }
  .meta, .howto, caption { color: #b0b0b0; }
  th, td, pre { border-color: #555; }
  .fill { background: #909090; }
}
"""

_FORBIDDEN = ("<script", "<link", "src=", "href=", "url(", "@import")
_FORBIDDEN_RE = re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE)


def _guard(html: str) -> str:
    """The page must not carry executable markup — the report's own literals
    never do, and user strings are escaped, so this never fires; it stands as
    the last line of defence (a RuntimeError beats a silent break)."""
    low = html.lower()
    for token in _FORBIDDEN:
        if token in low:
            raise RuntimeError(f"scan: forbidden token in the report: {token!r}")
    if _FORBIDDEN_RE.search(low):
        raise RuntimeError("scan: forbidden on*= attribute in the report")
    return html


# --------------------------------------------------------------------------- #
# small render helpers
# --------------------------------------------------------------------------- #
def _bar(width: int) -> str:
    return f'<td class="bar"><div class="fill" style="width:{width}%"></div></td>'


def _table(caption: str, head: Sequence[str], body: Sequence[str]) -> str:
    cols = "".join(f'<th scope="col">{h}</th>' for h in head)
    return ("<table>\n<caption>" + _esc_lit(caption) + "</caption>\n<thead><tr>"
            + cols + "</tr></thead>\n<tbody>\n" + "\n".join(body)
            + "\n</tbody>\n</table>")


def _row(cells: str) -> str:
    return f"<tr>{cells}</tr>"


def _num(v: int) -> str:
    return f'<td class="n">{v}</td>'


# --------------------------------------------------------------------------- #
# the page
# --------------------------------------------------------------------------- #
def page(header: Sequence[str], rows: Sequence[Sequence[str]], *, cfg,
         k: int, roles: Mapping[str, str], provisional: bool,
         unassigned: frozenset, findings, derived, hidden, audit,
         subject: Optional[str], lang: str, input_name: Optional[str],
         input_sha256: str, config_name: Optional[str]) -> str:
    """Assemble the observation into the static HTML page (pure; no I/O)."""
    m = _W[lang]
    n = len(rows)
    dash = m["dash"]
    name_disp = _esc_lit(m["stdin"]) if input_name is None else _esc(_visible(input_name))
    pack_info = findings.pack_info if findings is not None else []
    if pack_info:
        items = []
        for p in pack_info:
            src = m["src_builtin"] if p["source"] == "builtin" else m["src_file"]
            body = (m["pack_item"] if p.get("version") else m["pack_item_nover"])
            items.append(_esc(body).format(id=_esc(_visible(p["id"])),
                                           version=_esc(_visible(p["version"] or "")),
                                           source=_esc_lit(src)))
        packs_disp = _esc_lit(m["meta_packs"]).format(packs=", ".join(items))
    else:
        packs_disp = _esc_lit(m["meta_no_packs"])

    # --- per-column data (codepoint order; fixed finding order) ----------------
    def finding_counts(name: str) -> dict:
        counts: dict = {}
        if findings is not None:
            cf = findings.columns.get(name)
            if cf is not None:
                for e in cf.leaks:
                    if e["count"]:
                        counts["leak"] = counts.get("leak", 0) + e["count"]
            for w in findings.warnings:
                if w.get("column") == name:
                    code = w["code"]
                    if code == "mixed_form":
                        counts["mixed_form"] = w["mixed_values"]
                    elif code == "japanese_era":
                        counts["japanese_era"] = w["count"]
                    elif code == "role_mismatch":
                        counts["role_mismatch"] = 1
        if hidden is not None:
            for w in hidden[0]:
                if w["column"] == name:
                    counts["hidden_chars"] = w["rows"]
        return counts

    def role_disp(name: str) -> str:
        if not provisional:
            return _esc_lit(roles[name])
        if name in unassigned:
            return _esc_lit(m["role_unassigned"])
        r = roles[name]
        return _esc_lit(m["role_id_prov"]) if r == "id" else _esc_lit(r)

    col_rows = []
    for name in sorted(header):
        cf = findings.columns.get(name) if findings is not None else None
        cands = cf.candidates if cf is not None else []
        counts = finding_counts(name)
        parts = [f"{code} {counts[code]}" for code in FIXED_ORDER if counts.get(code)]
        cells = (f'<th scope="row">{_col(name)}</th>'
                 f"<td>{role_disp(name)}</td>"
                 f"<td>{_esc_lit(cands[0]['evidence']) if cands else dash}</td>"
                 f"<td>{_esc(_visible(', '.join(c['rule'] for c in cands))) if cands else dash}</td>"
                 f"<td>{_esc_lit(', '.join(parts)) if parts else dash}</td>")
        col_rows.append(_row(cells))
    columns_html = _table(m["cap_columns"],
                          [m["th_col"], m["th_role"], m["th_evidence"],
                           m["th_rules"], m["th_findings"]], col_rows)
    hidden_line = ""
    if hidden is not None:
        hidden_line = ("<p>" + _esc_lit(m["hidden_summary_line"]).format(
            checked=hidden[1]["columns_checked"],
            flagged=hidden[1]["columns_flagged"]) + "</p>")

    # --- summary sentences -----------------------------------------------------
    w = ((len(findings.warnings) if findings is not None else 0)
         + (len(derived[0]) if derived is not None else 0)
         + (len(hidden[0]) if hidden is not None else 0))
    unit_col = "" if lang == "en" else " 列"
    role_parts = []
    if provisional:
        # the summary counts every column once: the provisional keeps (the
        # unassigned columns) form one bucket, never a second "keep" bucket
        for role in ("qi", "id", "sensitive"):
            c = sum(1 for h in header if roles[h] == role)
            if c:
                role_parts.append(f"{role} {c}{unit_col}")
        c = sum(1 for h in header if roles[h] == "keep")
        if c:
            role_parts.append(m["part_unassigned"].format(
                label=m["role_unassigned"], count=c, unit=unit_col))
    else:
        for role in ("qi", "id", "sensitive", "keep", "drop"):
            c = sum(1 for h in header if roles[h] == role)
            if c:
                role_parts.append(f"{role} {c}{unit_col}")
    joined = m["part_sep"].join(role_parts)
    s2 = _esc_lit(m["s2_prov"] if provisional else m["s2_cfg"]).format(parts=joined)
    sentences = [_esc_lit(m["s1_size"]).format(rows=n, cols=len(header)), s2]
    audit_subject = audit["subject"] if audit is not None else None
    if audit is not None:
        c = audit["classes"]
        sentences.append(_esc_lit(m["s3_groups"]).format(
            count=c["count"], min=c["min_size"], k=k, pct=_pct(c["below_k_permille"])))
    if w or audit_subject is not None:
        key = "s4_findings_subject" if audit_subject is not None else "s4_findings"
        sentences.append(_esc_lit(m[key]).format(w=w, s=_col(subject or "")))
    if audit is not None:
        sentences.append(_esc_lit(m["s5_next"]))
    else:
        sentences.append(_esc_lit(m["guidance"]))

    # --- draft (display only; full column names) --------------------------------
    draft_cols: dict = {}
    if provisional:
        for h in header:
            if h in unassigned:
                draft_cols[h] = {"role": "?"}
                continue
            r = roles[h]
            if r == "qi":
                sug = (findings.template_extras.get(h, {}).get("_suggest")
                       if findings is not None else None)
                d = dict(sug) if sug and sug.get("role") == "qi" else {"role": "qi"}
                d["role"] = "qi"
                d.setdefault("type", "exact")
                draft_cols[h] = d
            else:
                draft_cols[h] = {"role": r}
        draft = {"k": k, "columns": draft_cols}
    else:
        for h in header:
            spec = cfg.columns[h]
            d = {"role": spec.role.value}
            if spec.role.value == "id" and spec.action == "pseudonymize":
                d["action"] = "pseudonymize"
            if spec.role.value == "qi" and spec.gen:
                d.update(spec.gen)
            draft_cols[h] = d
        draft = {"k": k, "l": cfg.l, "max_suppression": cfg.max_suppression,
                 "missing_value_policy": cfg.missing_value_policy,
                 "columns": draft_cols}
    draft_text = _esc(_visible(json.dumps(draft, ensure_ascii=False, indent=2,
                                          sort_keys=True)))
    has_q_mark = any(c.get("role") == "?" for c in draft_cols.values())

    if input_name is None:
        cmd_in, cmd_out = "input.csv", "output.csv"
        cmd_cfg = "config.json"
    else:
        cmd_in = input_name
        cmd_out = os.path.splitext(input_name)[0] + ".output.csv"
        cmd_cfg = os.path.basename(config_name) if config_name else "config.json"
    commands = (f"sieve-crowd plan {cmd_in} -c {cmd_cfg}\n"
                f"sieve-crowd run {cmd_in} -c {cmd_cfg} -o {cmd_out}")
    commands_text = _esc(_visible(commands))

    about_items = []
    for item in m["about_items"]:
        note = m["roles_note_prov"] if provisional else m["roles_note_cfg"]
        about_items.append("<li>" + _esc_lit(item).format(roles_note=note) + "</li>")

    out = ['<!DOCTYPE html>',
           f'<html lang="{lang}">',
           '<head>',
           '<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<meta http-equiv="Content-Security-Policy" '
           "content=\"default-src 'none'; style-src 'unsafe-inline'\">",
           f"<title>{_esc_lit(m['title'])} — {name_disp}</title>",
           "<style>", _CSS, "</style>",
           "</head>",
           "<body>",
           "<header>",
           f"<h1>{_esc_lit(m['h1']).format(name=name_disp)}</h1>",
           f'<p class="meta">{_esc_lit(m["meta_size"]).format(rows=n, cols=len(header))}</p>',
           f'<p class="meta">{_esc_lit(m["meta_sha"]).format(sha=input_sha256)}</p>',
           f'<p class="meta">{_esc_lit(m["meta_version"]).format(version=__version__)}</p>',
           f'<p class="meta">{packs_disp}</p>',
           f'<p class="meta">{_esc_lit(m["meta_k"]).format(k=k)}</p>',
           "</header>",
           "<main>",
           '<section id="summary">',
           f"<h2>{_esc_lit(m['h2_summary'])}</h2>",
           f'<p class="howto">{_esc_lit(m["howto"]).format(text=m["howto_summary"])}</p>',
           ]
    out.extend(f"<p>{s}</p>" for s in sentences)
    out.append("</section>")

    out.extend(['<section id="columns">',
                f"<h2>{_esc_lit(m['h2_columns'])}</h2>",
                '<p class="howto">' + _esc_lit(m["howto"]).format(
                    text=m["howto_columns_prov"] if provisional
                    else m["howto_columns_cfg"]) + "</p>",
                columns_html,
                hidden_line,
                "</section>"])

    if audit is not None:
        c = audit["classes"]
        total = n if n else 1
        body = []
        for b in SIZE_BUCKETS:
            r = c["size_buckets"][b]
            body.append(_row(f'<th scope="row">{_esc_lit(b)}</th>'
                             + _bar(r * 100 // total) + _num(r)))
        groups_html = _table(m["cap_groups"],
                             [m["th_bucket"], m["th_share"], m["th_rows"]], body)
        note = ""
        if cfg is not None and n > cfg.max_rows:
            note = ("<p>" + _esc_lit(m["over_limit"]).format(rows=n,
                                                             max_rows=cfg.max_rows) + "</p>")
        out.extend(['<section id="groups">',
                    f"<h2>{_esc_lit(m['h2_groups'])}</h2>",
                    '<p class="howto">' + _esc_lit(m["howto"]).format(
                        text=m["howto_groups"]) + "</p>",
                    "<p>" + _esc_lit(m["intro_groups"]).format(
                        count=c["count"], min=c["min_size"],
                        up=_pct(c["unique_permille"]), bp=_pct(c["below_k_permille"]),
                        k=k) + "</p>",
                    note,
                    groups_html,
                    "</section>"])

        body = []
        for col in audit["qi_columns"]:
            body.append(_row(f'<th scope="row">{_col(col["column"])}</th>'
                             + _num(col["distinct"]) + _num(col["unique_rows"])
                             + _num(col["rows_below_k_without"])))
        percolumn_html = _table(m["cap_percolumn"],
                                [m["th_col"], m["th_distinct"], m["th_unique"],
                                 m["th_without"]], body)
        out.extend(['<section id="percolumn">',
                    f"<h2>{_esc_lit(m['h2_percolumn'])}</h2>",
                    '<p class="howto">' + _esc_lit(m["howto"]).format(
                        text=m["howto_percolumn"]) + "</p>",
                    percolumn_html,
                    "</section>"])

    if derived is not None:
        dsum = derived[1]
        flagged = sorted((w for w in derived[0] if w["code"] == "derived"),
                         key=lambda w: (w["column"], w["qi_column"],
                                        RELATIONS.index(w["relation"])))
        skipped = ("" if not dsum["skipped_pairs"]
                   else _esc_lit(m["skipped_note"]).format(skipped=dsum["skipped_pairs"]))
        intro = _esc_lit(m["intro_pairs"]).format(pairs=dsum["pairs"],
                                                  flagged=dsum["flagged"]) + skipped
        classes_line = _esc_lit(m["intro_classes"]).format(
            u=dsum["unchecked"], t=dsum["trivial"], f=dsum["flagged"],
            c=dsum["clear"])
        if not dsum["pairs"]:
            tail = f"<p>{_esc_lit(m['no_keep_note'])}</p>"
        elif not flagged:
            tail = f"<p>{_esc_lit(m['zero_flagged'])}</p>"
        else:
            body = []
            for fw in flagged:
                dir_text = (m["dir_reveals"] if fw["relation"] == "reveals_qi"
                            else m["dir_implied"])
                body.append(_row(f'<th scope="row">{_col(fw["column"])}</th>'
                                 f'<td>{_col(fw["qi_column"])}</td>'
                                 f"<td>{_esc_lit(fw['relation'])} — {_esc_lit(dir_text)}</td>"
                                 + _num(fw["support"]) + _num(fw["violations"])))
            table = _table(m["cap_derived"],
                           [m["th_keep"], m["th_qi"], m["th_dir"], m["th_support"],
                            m["th_viol"]], body)
            tail = f"<p>{intro}</p><p>{classes_line}</p>{table}"
        out.extend(['<section id="derived">',
                    f"<h2>{_esc_lit(m['h2_derived'])}</h2>",
                    '<p class="howto">' + _esc_lit(m["howto"]).format(
                        text=m["howto_derived"]) + "</p>",
                    tail,
                    "</section>"])

    if audit is not None and audit_subject is not None:
        s = audit_subject
        total_s = sum(s["rows_per_subject_buckets"].values())
        body = []
        for b in SUBJECT_BUCKETS:
            c = s["rows_per_subject_buckets"][b]
            body.append(_row(f'<th scope="row">{_esc_lit(b)}</th>'
                             + _bar(c * 100 // total_s if total_s else 0)
                             + _num(c)))
        buckets_html = _table(m["cap_subj_buckets"],
                              [m["th_bucket"], m["th_share"], m["th_subjects"]], body)
        cs = s["class_subjects"]
        subject_html = (
            "<p>" + _esc_lit(m["subj_line"]).format(
                name=_col(s["column"]), subjects=s["subjects"],
                with_=s["rows_with_subject"], missing=s["rows_missing_subject"],
                repeated=s["repeated_subjects"],
                in_rep=s["rows_in_repeated_subjects"],
                max_rows=s["max_rows_per_subject"]) + "</p>"
            + buckets_html
            + "<p>" + _esc_lit(m["subj_class_line"]).format(
                min=cs["min_distinct"], below=cs["rows_below_k"], over=cs["rows_overstated"],
                k=k) + "</p>")
        howto = m["howto_subject_with"]
    else:
        examples = [h for h in sorted(header) if roles[h] in ("id", "keep")][:3]
        names = ", ".join(_col(h) for h in examples)
        tail = ""
        if examples:
            tail = "<p>" + _esc_lit(m["subject_examples"]).format(names=names) + "</p>"
        subject_html = tail
        howto = m["howto_subject_without"]
    if audit is not None:
        out.extend(['<section id="subject">',
                    f"<h2>{_esc_lit(m['h2_subject'])}</h2>",
                    '<p class="howto">' + _esc_lit(m["howto"]).format(text=howto) + "</p>",
                    subject_html,
                    "</section>"])

    q_note = f"<p>{_esc_lit(m['next_q_note'])}</p>" if has_q_mark else ""
    out.extend(['<section id="next">',
                f"<h2>{_esc_lit(m['h2_next'])}</h2>",
                '<p class="howto">' + _esc_lit(m["howto"]).format(
                    text=m["howto_next"]) + "</p>",
                f"<p>{_esc_lit(m['next_draft_label'])}</p>",
                f"<pre>{draft_text}</pre>",
                f"<p>{_esc_lit(m['next_commands_label'])}</p>",
                f"<pre>{commands_text}</pre>",
                q_note,
                "</section>"])
    out.extend(["</main>",
                "<footer>",
                '<section id="about">',
                f"<h2>{_esc_lit(m['h2_about'])}</h2>",
                '<p class="howto">' + _esc_lit(m["howto"]).format(
                    text=_ABOUT_HOWTO[lang]) + "</p>",
                "<ul>", *about_items, "</ul>",
                "</section>",
                "</footer>",
                "</body>",
                "</html>"])
    return _guard("\n".join(part for part in out if part != "") + "\n")


_ABOUT_HOWTO = {"en": "this section describes the report itself.",
                "ja": "この節は報告自体の説明です。"}
