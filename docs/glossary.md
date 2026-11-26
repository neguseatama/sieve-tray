# 用語の対応表（`docs/glossary.md`）

Sieve Tray は、画面・README・docs で、一般に通じる言葉を使う。設計側の
呼び名（部品の名前）と、利用者に見せる言葉の対応を、この表に集める。
Seal 2.2.0 の対応表を引き継ぎ、Canon 2.3.0 の分を追記した。

## 製品の部品

| 設計側の呼び名 | 画面・README・docs で使う言葉 | 備考 |
| --- | --- | --- |
| manifest | ファイル一覧 | `manifest` コマンド |
| checksum（ハッシュ値） | チェックサム（ハッシュ値） | SHA-256 の値 |
| whole-folder checksum（ハッシュツリー） | フォルダ全体のチェックサム | `docs/manifest-format.md` |
| check code（HMAC） | 照合コード | `--key-file` で結ぶ |
| key file | キーファイル | 中身がそのままキーのバイト列 |
| receipt | 処理記録 | 英語は receipt のまま。ファイル名（`*-receipt.json`）・JSON のキー・`kind`・コード内の名前は変えない |
| verify | 確認（`verify` コマンド） | コマンド名はそのまま |
| handoff | `handoff/` | 渡してよいファイル |
| local | `local/` | 手元に残すファイル（詳しい報告） |

## Canon 2.3.0 で加わった言葉

| 設計側の呼び名 | 画面・README・docs で使う言葉 | 備考 |
| --- | --- | --- |
| clean | メタデータの除去 | `clean` コマンド（`docs/clean-metadata.md`） |
| metadata | メタデータ | 画像・Office 文書の付随情報 |
| normalize | テキストと JSON / CSV の整理 | `normalize` コマンド（`docs/normalize-format.md`） |
| character encoding | 文字コード | 自動判定しない（`--from-encoding` で指定） |
| line endings | 改行コード | LF / CRLF / CR |
| normalization | 正規化 | 文字コード・改行・JSON / CSV の書き方を揃えること |
| NFC / JCS | （RFC の名前のまま） | NFC = Unicode の合成。JCS = RFC 8785 の正準形 |
| table diff | 表の比較 | `table-diff` コマンド（`docs/table-diff.md`） |
| mojibake signs | 文字化けの兆候 | 閉じた 5 種（replacement_char・c1_controls・nul_bytes・utf8_invalid・mixed_newlines） |
| in_content | 本文の中にあるもの | コメント・変更履歴・非表示のシート / スライド（観測のみ） |

## 使わない言葉

設計側の古い呼び名（帳簿を指す語・閉じることを指す語・キーを指す
古い一文字の語・構造を指す一文字の語）と、主張の強い言葉は使わない。
照合コードは「このキーを持つ者が、この内容に、このコードを付けた」こと
しか示さない（証明書のように振る舞う言い方・不可侵を述べる言い方・
公式に証する言い方は、その範囲を超える）。抽選は「この seed と名簿から、
この結果になる」ことしか示さない（くじの偶然を保証する言い方は、その
範囲を超える）。`clean` は「観測されない」ことしか示さない。
対応の全文は、各文書（manifest-format.md・clean-metadata.md・
normalize-format.md・table-diff.md・draw-procedure.md）と、
`tests/test_seal_s9_readme_docs.py` の語彙一覧に従う。
