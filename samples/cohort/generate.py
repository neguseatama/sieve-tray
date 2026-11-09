#!/usr/bin/env python3
"""The Cohort sample pack generator (request §3.8).

Deterministic: the same script run twice produces byte-identical files
(the .docx blobs are zip archives with a fixed timestamp stamp; every
other file is written as fixed UTF-8 bytes).  Running

    python3 generate.py [target]

writes the sample files and MANIFEST.json into the target folder
(default: this folder).  The pack is entirely fictional: the essays,
the quotes, the assignment and the code below are invented for the
self-check and never reference real people or real submissions.

The seven §3.8 shapes and their purpose:

1. essay_a.docx / essay_b.docx        - a paraphrased pair, flagged by
                                        Referee (the 要確認 document pair)
2. quote_a.docx / quote_b.docx        - shared long quotes + a
                                        bibliography; confirmed by the
                                        excluded lengths (the run uses
                                        both exclusions on)
3. assignment_user.docx + the base    - a submission that contains the
   file (assignment-base.txt)           assignment text verbatim; the
                                        base file is passed via --base,
                                        never copied into the input
4. hidden_note.docx                   - a .docx with hidden (vanish)
                                        text, observed by Order
5. unrelated.js                       - an unrelated submission (it
                                        also keeps the generic lane's
                                        not-flagged pairs observable)
6. calc_v1.py / calc_v2.py            - a renamed-identifier .py pair
7. report_app.js / report_widget.js   - a .js pair where the small
                                        file holds one of the large
                                        one's functions verbatim (the
                                        2026-11-10 either-side ruling:
                                        the large side stays around
                                        290 ‰, the excerpt side reaches
                                        937 ‰ - the pair is flagged by
                                        the higher side alone)

The MANIFEST expectations are observations, never digests: statuses,
colors, length ranges, span presence, hidden-text presence.
"""

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

TARGET = Path(__file__).resolve().parent

# the fixed zip stamp (every .docx part carries the same one)
ZIP_STAMP = (2020, 1, 1, 0, 0, 0)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def _zip_parts(parts):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=ZIP_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


def _docx(paragraphs):
    """A minimal .docx: paragraphs are (text, vanish) pairs."""
    body = []
    for text, vanish in paragraphs:
        rpr = "<w:rPr><w:vanish/></w:rPr>" if vanish else ""
        body.append("<w:p><w:r>%s<w:t xml:space=\"preserve\">%s"
                    "</w:t></w:r></w:p>" % (rpr, text))
    return _zip_parts([
        ("[Content_Types].xml",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Types xmlns="%s">'
         '<Default Extension="rels" ContentType="application/vnd.'
         'openxmlformats-package.relationships+xml"/>'
         '<Default Extension="xml" ContentType="application/xml"/>'
         '<Override PartName="/word/document.xml" ContentType="application/'
         'vnd.openxmlformats-officedocument.wordprocessingml.document.main'
         '+xml"/></Types>' % CT),
        ("_rels/.rels",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="%s">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
         'officeDocument/2006/relationships/officeDocument" '
         'Target="word/document.xml"/></Relationships>' % PR),
        ("word/document.xml",
         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<w:document xmlns:w="%s"><w:body>%s'
         '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body>'
         '</w:document>' % (W, "".join(body))),
    ])


# ---------------------------------------------------------------------------
# shape 1: the paraphrased essay pair (都市の緑化 - urban greening)
# ---------------------------------------------------------------------------

ESSAY_A = """都市の緑化について考える

都市の緑化は、暮らしの質を高める重要な施策です。木々が増えると、夏の街の気温が下がり、
歩く人の疲れも軽くなります。また、緑のある風景は、住まう人の心を落ち着かせる働きが
あります。

緑化を進めるには、まず公共の空間に植栽を増やすことが有効です。公園や通りの両側に木を
植えて、季節の変化を感じられる街並みを作ります。次に、民間の敷地にも緑を求める規定が
役立ちます。駐車場の一部を緑地に替える取り組みも、近年の街で見られるようになりました。

このように、都市の緑化は、計画的な植栽と制度の両輪で進めるべきだと言えます。
"""

ESSAY_B = """都市の緑化について考える

都市の緑化は、暮らしの質を高める重要な施策です。木々が増えると、夏の街の気温が下がり、
歩く人の疲れも軽くなります。さらに、緑に囲まれた風景は、住まう人の心を落ち着かせる
効果があります。

緑化を進めるには、まず公共の空間に植栽を増やすことが有効です。公園や通りの両側に木を
植えて、季節の変化を感じられる街並みを作ります。次に、民間の敷地にも緑を求める規定が
役立ちます。駐車場の空きスペースを緑地へ変える取り組みも、近年の市街で広がって
きました。

このように、都市の緑化は、計画的な植栽と制度の両輪で進めるべきだと言えます。
"""

# ---------------------------------------------------------------------------
# shape 2: the quotes + bibliography pair (梅の栽培 - growing ume plums)
# (the two documents share the quoted passages and the bibliography; the
# own sentences around them differ)
# ---------------------------------------------------------------------------

QUOTE_INNER_1 = ("一年を通じて梅の実を安定して収穫するには、品種の開花期と受粉樹の"
                 "組み合わせを事前に確認しておくことが重要である。剪定の時期を誤ると"
                 "樹勢が乱れ、翌年の開花が落ちる。")
QUOTE_INNER_2 = ("若木のうちに主干を低く切り返すと、手の届く高さで作業ができる。"
                 "摘果は満開後ひと月ほど経ってから行い、隔年結果を防ぐ。")

QUOTE_A = """梅の栽培を調べた範囲

果樹の中では梅は育てやすく、庭一本でも収穫が楽しめます。資料で確認した要点を
書き留めます。
「%s」
植える前に受粉の相手となる品種を決めておくべきだ、というのが第一の結論でした。
「%s」
手の届く高さに保つ剪定と、隔年結果を防ぐ摘果は、手順の順番を守ることが重要だと
読み取りました。北向きの庭でも耐える品種を選べば失敗が減る、という指摘も
参考になりました。

参考文献
中島実『梅の育て方』青果出版 二〇二二年
全国果樹同好会『庭の果樹の手引き』若木社 二〇二三年
""" % (QUOTE_INNER_1, QUOTE_INNER_2)

QUOTE_B = """家の庭に梅を植える計画

春の香りと実の収穫を目当てに、庭に梅を一本植えることにしました。本で調べた
内容を整理しておきます。
「%s」
同じ品種だけでは実がつかない場合があるため、隣の家に植わっている別の品種と
上手く対になるかを確認する予定です。
「%s」
切り戻しの高さと実の間引きのタイミングは、資料ごとに書き方が違うので、実際に
栽培している人の記録を読み比べて判断します。日陰でも耐える品種を選べば、
失敗は少なくなるはずです。

参考文献
中島実『梅の育て方』青果出版 二〇二二年
全国果樹同好会『庭の果樹の手引き』若木社 二〇二三年
""" % (QUOTE_INNER_1, QUOTE_INNER_2)

# ---------------------------------------------------------------------------
# shape 3: the base file and the submission that contains it verbatim
# (地域の昔話の調査 - a local folktale study assignment)
# ---------------------------------------------------------------------------

ASSIGNMENT_BASE = """課題：地域に伝わる昔話を一つ選び、語り継がれてきた経緯を調べよ。
語り手と聴衆の関係、村や町の生活の変化と物語の内容の関わりを整理して述べること。
調査の記録として、聞き取りの日付と話してくれた方の年代を必ず書き留めること。
提出は原稿用紙八枚以内とする。"""

ASSIGNMENT_USER = """%s

自分の計画では、川沿いの集落に伝わる蛇と池の話を選ぶ。祖母から聞いた筋と、
町の資料室にある古い記録を比べて、語り手の年代ごとの違いを書き留めるつもりです。
聞き取りは二月の上旬に二回行う予定です。
""" % ASSIGNMENT_BASE

# ---------------------------------------------------------------------------
# shape 4: the hidden-text submission (a photo memo with a vanish run)
# ---------------------------------------------------------------------------

HIDDEN_NOTE_PARAS = [
    ("観測のメモです。花壇の写真を撮っておくこと。", False),
    ("この文章は画面には現れませんが、観測の対象として記録されます。", True),
]

# ---------------------------------------------------------------------------
# shape 5: the unrelated submission (it also keeps the generic lane's
# not-flagged pairs observable)
# ---------------------------------------------------------------------------

UNRELATED_JS = """// 日付の表示を整えるための小さな道具集です。
function padTwo(n) {
  return (n < 10 ? "0" : "") + n;
}

function formatStamp(d) {
  const y = d.getFullYear();
  const mo = padTwo(d.getMonth() + 1);
  const da = padTwo(d.getDate());
  const hh = padTwo(d.getHours());
  const mi = padTwo(d.getMinutes());
  return y + "-" + mo + "-" + da + " " + hh + ":" + mi;
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function isLeapYear(year) {
  if (year % 400 === 0) return true;
  if (year % 100 === 0) return false;
  return year % 4 === 0;
}
"""

# ---------------------------------------------------------------------------
# shape 6: the renamed-identifier .py pair (a small shopping-total calc)
# ---------------------------------------------------------------------------

CALC_V1 = '''# 買い物の合計を出す小さな計算機です。
def total_price(items):
    """商品ごとの小計を足して、税込みの合計を返します。"""
    total = 0
    for it in items:
        price = it["price"]
        count = it["count"]
        total += price * count
    tax = total * 10 // 100
    return total + tax


def cheapest(items):
    """いちばん安い商品の名前を返します。"""
    best = None
    for it in items:
        if best is None or it["price"] < best["price"]:
            best = it
    return best["name"]
'''

CALC_V2 = '''# 買い物の合計を出す小さな計算機です。
def total_price(goods):
    """商品ごとの小計を足して、税込みの合計を返します。"""
    sum_all = 0
    for entry in goods:
        unit = entry["price"]
        qty = entry["count"]
        sum_all += unit * qty
    charge = sum_all * 10 // 100
    return sum_all + charge


def cheapest(goods):
    """いちばん安い商品の名前を返します。"""
    low = None
    for entry in goods:
        if low is None or entry["price"] < low["price"]:
            low = entry
    return low["name"]
'''

# ---------------------------------------------------------------------------
# shape 7: the .js pair (a submission-status table app, and a widget file
# that holds one of its functions verbatim)
# ---------------------------------------------------------------------------

REPORT_APP_JS = """// 提出物の集計表を作る小さなアプリです。
function makeHeader(title) {
  const bar = document.createElement("div");
  bar.className = "bar";
  const label = document.createElement("span");
  label.textContent = title;
  bar.appendChild(label);
  return bar;
}

function countByStatus(rows) {
  const out = { done: 0, open: 0, held: 0 };
  for (const r of rows) {
    if (r.status === "done") out.done += 1;
    else if (r.status === "open") out.open += 1;
    else out.held += 1;
  }
  return out;
}

function buildRow(name, n) {
  const tr = document.createElement("tr");
  const tdName = document.createElement("td");
  const tdN = document.createElement("td");
  tdName.textContent = name;
  tdN.textContent = String(n);
  tr.appendChild(tdName);
  tr.appendChild(tdN);
  return tr;
}

function renderTable(rows) {
  const table = document.createElement("table");
  for (const r of rows) {
    table.appendChild(buildRow(r.name, r.score));
  }
  return table;
}

function mountAll(root, rows) {
  root.appendChild(makeHeader("提出物の集計"));
  const counts = countByStatus(rows);
  root.appendChild(buildRow("done", counts.done));
  root.appendChild(buildRow("open", counts.open));
  root.appendChild(buildRow("held", counts.held));
  root.appendChild(renderTable(rows));
}
"""

REPORT_WIDGET_JS = """// 集計表の部品（本体のアプリから一つの関数だけを取り出したものです）。
function countByStatus(rows) {
  const out = { done: 0, open: 0, held: 0 };
  for (const r of rows) {
    if (r.status === "done") out.done += 1;
    else if (r.status === "open") out.open += 1;
    else out.held += 1;
  }
  return out;
}
"""

# ---------------------------------------------------------------------------
# the pack table: (filename, bytes, role) - role "base" is passed via
# --base, never copied into the comparison folder
# ---------------------------------------------------------------------------

PACK = [
    ("essay_a.docx", _docx([(p, False) for p in ESSAY_A.split("\n")]),
     "submission",
     {"kind": "document", "status": "compared"}),
    ("essay_b.docx", _docx([(p, False) for p in ESSAY_B.split("\n")]),
     "submission",
     {"kind": "document", "status": "compared"}),
    ("quote_a.docx", _docx([(p, False) for p in QUOTE_A.split("\n")]),
     "submission",
     {"kind": "document", "status": "compared",
      "removed": {"bibliography": {"min": 30, "max": 80},
                  "quotes": {"min": 100, "max": 190}}}),
    ("quote_b.docx", _docx([(p, False) for p in QUOTE_B.split("\n")]),
     "submission",
     {"kind": "document", "status": "compared",
      "removed": {"bibliography": {"min": 30, "max": 80},
                  "quotes": {"min": 100, "max": 190}}}),
    ("assignment-base.txt", ASSIGNMENT_BASE.encode("utf-8"), "base", {}),
    ("assignment_user.docx",
     _docx([(p, False) for p in ASSIGNMENT_USER.split("\n")]),
     "submission",
     {"kind": "document", "status": "compared",
      "removed": {"base": {"min": 90, "max": 170}}}),
    ("hidden_note.docx", _docx(HIDDEN_NOTE_PARAS), "submission",
     {"kind": "document", "status": "compared", "hidden_count_min": 1}),
    ("unrelated.js", UNRELATED_JS.encode("utf-8"), "submission",
     {"kind": "code", "status": "compared"}),
    ("calc_v1.py", CALC_V1.encode("utf-8"), "submission",
     {"kind": "code", "status": "compared"}),
    ("calc_v2.py", CALC_V2.encode("utf-8"), "submission",
     {"kind": "code", "status": "compared"}),
    ("report_app.js", REPORT_APP_JS.encode("utf-8"), "submission",
     {"kind": "code", "status": "compared"}),
    ("report_widget.js", REPORT_WIDGET_JS.encode("utf-8"), "submission",
     {"kind": "code", "status": "compared"}),
]

# the pair expectations (colors, spans, thresholds - never digests).
# The flagged values were measured with the current engines: the essay
# pair is Referee RED with four matched spans (234 characters), the
# js pair is flagged by the higher side alone (937 per mille against a
# 292 per mille large side - the 2026-11-10 either-side ruling), and
# the quote pair stays below the flag after both exclusions.
PAIRS = [
    {"a": "essay_a.docx", "b": "essay_b.docx",
     "expect": {"flagged": True, "lane": "referee", "class": "RED",
                "spans_min": 1, "spans_length_min": 100}},
    {"a": "quote_a.docx", "b": "quote_b.docx",
     "expect": {"flagged": False}},
    {"a": "assignment_user.docx", "b": "essay_a.docx",
     "expect": {"flagged": False}},
    {"a": "hidden_note.docx", "b": "essay_a.docx",
     "expect": {"flagged": False}},
    {"a": "calc_v1.py", "b": "calc_v2.py",
     "expect": {"flagged": True, "lane": "scope"}},
    {"a": "report_app.js", "b": "report_widget.js",
     "expect": {"flagged": True, "lane": "generic",
                "per_mille_min": 700}},
    {"a": "report_app.js", "b": "unrelated.js",
     "expect": {"flagged": False}},
    {"a": "report_widget.js", "b": "unrelated.js",
     "expect": {"flagged": False}},
]


def build(target: Path) -> None:
    """Write the sample files and MANIFEST.json into target."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    items = []
    for name, data, role, expect in PACK:
        (target / name).write_bytes(data)
        items.append({
            "file": name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "role": role,
            "expect": expect,
        })
    manifest = {
        "run": {
            "exclude_quotes": True,
            "exclude_bibliography": True,
            "base": ["assignment-base.txt"],
        },
        "items": items,
        "pairs": PAIRS,
    }
    (target / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
        + "\n", encoding="utf-8")


def main(argv) -> int:
    target = Path(argv[1]) if len(argv) > 1 else TARGET
    build(target)
    print("wrote %d files into %s" % (len(PACK), target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
