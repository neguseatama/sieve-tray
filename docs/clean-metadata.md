# メタデータの除去の形式（`docs/clean-metadata.md`）

Sieve Tray 2.4.0（Canon）。この文書は `clean` コマンドが扱う 4 つの形式
（PDF・JPEG・PNG・Office）について、**取り除くもの**と**残すもの**、観測の
分類、そして本文の中にあるものの扱いを定める。既知の例は「既知値」（KV-C1）で、
文書から読み戻すテスト（`tests/test_canon_docs.py`）が確かめる。

PDF は 2.4.0 から対象に加わった（依存の下限は、公開済みの
`sieve-lens[pdf,html-css-full]>=0.23.0`）。

---

## 1. 形式ごとの規則

### 1.1 JPEG

**取り除く**: EXIF と XMP（APP1）・IPTC / Photoshop（APP13）・コメント
（COM）・JFIF の埋め込みサムネイル（APP0 内）・EXIF 内のサムネイル
（IFD1）。APP3〜APP12・APP15 など、それ以外の APP 記録も付随情報として
取り除く（分類は `custom`）。

**残す**: 画像の本体（エントロピー符号化データ）・フレームとテーブルの定義
（DQT・SOF・DHT・DRI）・ICC プロファイル（APP2）・Adobe マーカー（APP14）。

**向き（Orientation）**: 1 以外のときは、向きだけを持つ最小の EXIF を残す
（見た目を変えないため）。処理記録の `orientation_kept` が立つ。最小の
EXIF は、TIFF ヘッダ（II）+ IFD0 の 1 エントリ（タグ 0x0112・型 3）だけ
で、それ以外のタグ・サブ IFD・IFD1 は持たない。

### 1.2 PNG

**取り除く**: `tEXt`・`iTXt`・`zTXt`・`eXIf`・`tIME` と、下の残すリストに
ない**補助チャンク**（先頭の文字が小文字のチャンク）。

**残す**: 必須チャンク（`IHDR`・`PLTE`・`IDAT`・`IEND`）と、表示に関わる
`tRNS`・`gAMA`・`cHRM`・`sRGB`・`iCCP`・`sBIT`・`bKGD`・`pHYs`。
先頭の文字が大文字の未知のチャンク（重要チャンク）は、デコードに必要な
可能性があるため残す。出力のチャンクの CRC は計算し直す。

### 1.3 Office（docx / xlsx / pptx）

**取り除く**: `docProps/core.xml`（作成者・最終更新者・タイトル・件名・
キーワード・説明・日時）・`docProps/app.xml`（ソフト名・版・会社・管理者）・
`docProps/custom.xml`（カスタムプロパティ）・`docProps/thumbnail.*`
（サムネイル）の中身。

**残す**: `docProps` 以外の部品（本文・書式・画像・数式・関係定義）は、
**バイト単位で同一**に保つ。メタデータの部品は**削除せず**、空の有効な形
に置き換える（部品を削除すると関連定義の編集が必要になるため）。

**出力の zip**: 決定論的な zip（`pack` と同じ規則。エントリは名前の
バイト列昇順・日時は 1980-01-01 00:00:00・`create_system = 3`・
外部属性はファイル 0o644・圧縮は ZIP_STORED）。同じ入力から、同じ
バイト列になる。

### 1.4 PDF（2.4.0 から）

**取り除く**: Info 辞書（`/Title` `/Author` `/Subject` `/Keywords`
`/Creator` `/Producer`・`/CreationDate` `/ModDate`・規格外の項目ごと全部）・
XMP（`/Metadata`。文書全体に加え、ページ、画像とフォームの XObject、
AcroForm にも付くもの）・ページのサムネイル（`/Thumb`）・`/PieceInfo`
（文書とページの両方）。追記型（`/Prev` つき）は、前半部ごと捨てて
最新版だけを書き出す。

**残す**: ページと内容ストリーム・注釈・添付ファイル・フォームの欄と
入力値・資源。内容ストリームの前後一致（`content_checksum_match`）で
確かめる。

**決定性**: 同じ pypdf の版で、同じ結果。`/ID` は内容から決めた値で
上書きする（乱数は作らない・元の `/ID` は引き継がない）。版が違うと
バイト列は変わることがある（文字列のエンコードの違い）が、論理内容
（ページ数・内容ストリーム・可視テキスト）は同じ。

**観測の分類の対応**: `/Author` → author・`/CreationDate` `/ModDate` →
time・`/Creator` `/Producer` → software・`/Title` `/Subject`
`/Keywords` → title_subject・`/Thumb` → thumbnail・XMP と `/PieceInfo`
と規格外の Info 項目 → custom。location と device は PDF 由来では 0。
再観測の分類ごとの残りはすべて 0。

**本文の中にあるもの**: 注釈（`/Annots`）→ `comment`・添付ファイル
（`/EmbeddedFiles`）→ `hidden_part`・フォームの入力値（`/AcroForm` の
`/V` つきの欄）→ `hidden_part`。いずれも**取り除かない**
（本文扱いと同じ。`tracked_change` は PDF 由来では 0）。

**読めないとき**: 暗号化は `refused`、壊れた PDF は `parse_failed`、
pypdf が無い環境では `engine_unavailable`（いずれも既存の閉じた語彙）。
大きさの上限とシンボリックリンクは既存の規則のまま。

## 2. 観測の分類（閉じた 8 種）

`author`（作成者・最終更新者・会社・管理者）／`time`（作成・更新・撮影・
印刷の日時）／`software`（作成ソフト・版）／`location`（位置情報）／
`device`（カメラ・機種・シリアル）／`title_subject`（タイトル・件名・
キーワード・説明）／`thumbnail`（サムネイル）／`custom`（そのほかの
メタデータ）。

主な対応（実装の `_CN_EXIF_TAG_CATEGORIES`・`_CN_XMP_PATTERNS`・
`_CN_IPTC_CATEGORIES`・`_CN_PNG_KEYWORD_CATEGORIES`・
`_CN_XML_COUNTS` が根拠）:

- EXIF: Artist / Copyright → author。DateTime 系 → time。Software →
  software。Make / Model / シリアル系 → device。ImageDescription・
  XPComment / XPKeywords / XPSubject / XPTitle → title_subject。
  GPS サブ IFD のタグ → location（GPSTimeStamp は time）。
  IFD1（サムネイル）→ thumbnail。
- XMP: dc:creator → author。xmp:CreateDate 系 → time。
  xmp:CreatorTool → software。photoshop:City / State / Country と
  exif:GPSLatitude → location。tiff:Make / Model → device。
  dc:title / dc:description / dc:subject → title_subject。
  対応のない XMP 要素 → custom。
- IPTC（8BIM）: By-line（1:50）と CopyrightNotice（1:116）→ author。
  ObjectName（1:5）・Keywords（1:25）・Caption（2:120）→ title_subject。
  Location（1:55）→ location。DateCreated（2:55）→ time。そのほか →
  custom。
- PNG のテキスト: Author → author。Software → software。
  Creation Time → time。Description / Comment / Title / Subject /
  Keywords → title_subject。そのほか → custom。
- Office: core.xml の dc:creator・cp:lastModifiedBy と app.xml の
  Company・Manager → author。dcterms:created / modified → time。
  Application・AppVersion → software。dc:title / dc:subject /
  cp:keywords / dc:description → title_subject。custom.xml の
  property 要素 → custom。空でない thumbnail 部品 → thumbnail。

## 3. 本文の中にあるもの（観測のみ・変更しない）

Office 文書に `comment`（コメント）・`tracked_change`（変更履歴）・
`hidden_part`（非表示のシート・スライド）があるときは、件数を処理記録の
`in_content` に記録する。**取り除かない**（本文の一部であり、勝手に変え
ない）。報告に「本文の中に残っている」と書く。

計上の範囲（実装の根拠: `sieve_canon._cn_office_observe`）:

- `comment`: docx の `word/comments.xml` の `w:comment` 要素・xlsx の
  `xl/comments*.xml` の `comment` 要素。
- `tracked_change`: docx の `word/document.xml` の `w:ins` と `w:del`
  要素。
- `hidden_part`: xlsx の `xl/workbook.xml` の `state="hidden"` のシート・
  pptx の `ppt/slides/slide*.xml` で `show="0"` のスライド。

## 4. 既知の例（KV-C1）

入力（PNG・チャンクの並び）:

```
シグネチャ 89 50 4e 47 0d 0a 1a 0a
IHDR  00 00 00 01 00 00 00 01 08 02 00 00 00   (1x1・8bit・RGB)
gAMA  00 00 b1 8f                              (0.45455)
tEXt  41 75 74 68 6f 72 00 53 61 6b 75 72 61   ("Author\0Sakura")
IDAT  00 01 02 03
IEND
```

この入力全体の SHA-256 は
`sha256:38a3ab0346a4660127dd21ac62bf03093013e2e1684a17c49244b04e7bf635f0`。
`clean` を実行すると、`tEXt` が取り除かれ（author 1 件）、出力は:

```
シグネチャ + IHDR + gAMA + IDAT + IEND
```

で、出力全体の SHA-256 は
**`sha256:f7e30406a52f23d7828345a5768997d15cfe4904ae560b1b092ccf0bd27be117`**。
再観測の分類ごとの残りはすべて 0。必須チャンク（IHDR・gAMA は表示に関わる
ので必須ではないが kept・IDAT・IEND）のチェックサムは前後で一致する
（`content_checksum_match` が真）。

## 5. 主張の範囲

`clean` は「出力に、この分類のメタデータが観測されない」ことだけを示す。
「メタデータが一切存在しない」「復元できない」とは書かない（禁止語）。
取り除いた値そのもの（人名・場所など）は、`handoff/` には出ない
（`local/` の報告にだけ出る）。
