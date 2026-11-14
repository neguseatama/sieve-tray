# 受領書と語彙の参照（receipt-reference）

README の「🚪 Gate」「👥 Cohort」の 2 節は、Seal 2.2（§3.8-1）で別添の文に差し替えました。
この文書は、差し替えのときに README から外した技術的な説明を、**原文のまま**移したものです。
文の内容は 2.1.1 の README に載っていたときのまま変更していません（旧文は当時の語彙で書かれており、「処理記録」を当時は「受領書」と呼んでいます。英語の `receipt` はそのままです）。

`verify` の語彙の現在の一覧と照合コードの確認の規則は、[manifest-format.md](manifest-format.md) の §6 にあります。

## 1. Cohort の重なりの数え方（日本語原文）

汎用レーンは、いずれか一方の側でも 700 ‰ に達した組を要確認にします（小さな
ファイルが大きなファイルにそのまま含まれる場合を見落とさないため）。記録される
`match_per_mille` は、高い側の値です。要確認の組は観測であり、結論ではありません。
`verify` の語彙は M1 のままで変更しません。要約の件数の辻褄が合わない Cohort の
受領書は、記録として読み取れない受領書と同じ `receipt_unreadable` で報告されます。

報告の中で一致箇所は文字の位置で示されます（トークンではなく文字）。トークンを
数えるのは基準文書の除去比率（各提出物のトークンのうち、基準文書の除去で
取り除かれた量）だけです。

## 2. The same paragraphs in English (moved verbatim)

The generic lane flags a pair when either side reaches 700 ‰ (either
side, so that a small file contained in a larger one is not missed);
the recorded `match_per_mille` is the higher of the two sides. The
flagged pairs are an observation, not a judgment. `verify` keeps the
M1 vocabulary unchanged: a Cohort receipt whose summary counts do not
hold together is reported with the existing `receipt_unreadable` word,
like any receipt that cannot be read as a record.

In the report, matched spans are located by character offsets
(characters, not tokens); the only token counts are the base-removal
ratios - how many of each submission's tokens the base stripping
removed.
