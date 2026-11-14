# manifest の形式（`docs/manifest-format.md`）

Sieve Tray 2.2.0（Seal）。この文書は `manifest` コマンドと `pack` コマンドが
使うフォルダ全体チェックサム（ハッシュツリー）と照合コード（check_code）の
仕様をバイト単位で定める。別の実装でもこの文書どおりに計算すれば
同じ値になる。既知値は §4 の 2 つ（KV-1・KV-2）で確かめられる。

用語: この文書で「処理記録」は `receipt`（JSON ファイル）を指す。
「キー」は照合コードを計算するための秘密のバイト列（キーファイルの中身）を指す。

---

## 1. ハッシュツリー（フォルダ全体チェックサム）

フォルダ全体のチェックサム = ルート フォルダのチェックサム。
フォルダのチェックサムは、そのフォルダの**子の行を連結したバイト列**の
SHA-256 である。

### 1.1 行の形式

子 1 個につき 1 行。行はバイト列で:

```
種別 1 バイト  NUL (0x00)  名前  NUL (0x00)  子チェックサム  LF (0x0A)
```

- 種別: 通常ファイル = `f` (0x66)、ディレクトリ = `d` (0x64)。
- 名前: ファイル名（相対パスの最後の成分）の UTF-8 バイト列。
  NFC 正規化をしない（名前をそのまま使う）。UTF-8 で表せない名前は、
  OS が返した文字列を surrogateescape でバイトに戻したもの（生バイト）を使う。
- 子チェックサム: 64 文字の小文字 16 進（`0`-`9` `a`-`f`）。
  - ファイル: ファイルの中身の SHA-256。
  - ディレクトリ: そのディレクトリ自身のチェックサム（同じ規則で再帰）。

### 1.2 子の並び順

1 つのフォルダの中で、ファイルとディレクトリを**混ぜて 1 つの列**にし、
次の鍵（sort key）で昇順に並べる:

1. 名前の UTF-8 バイト列の辞書順（バイトごとの比較）
2. 同一名のときは種別バイトの昇順（`d` (0x64) < `f` (0x66)）

### 1.3 計算の規則

- 子は**通常ファイルとディレクトリのみ**。シンボリック リンク、
  読めないファイル、一覧（list）できないディレクトリ、その他の
  特殊ファイルは行に入れない（`manifest` コマンドでは別途
  `skipped` に記録される）。
- 空のディレクトリも 1 行を持つ。その子チェックサムは
  SHA-256(空のバイト列) = `e3b0c442…b855`（§4 KV-1）。
- ルートのチェックサム = ルートの子の行を（1.2 の順で）連結した
  バイト列の SHA-256。ルートが空なら SHA-256(b"")。
- ルート自身の名前は行に現れない。行に現れる名前は相対パスの最後の
  成分（各フォルダの中ではファイル名だけ）。

### 1.4 手計算での再現例

`a/` の中に `one.txt`（中身 `one\n`）と空ディレクトリ `empty/` があるとき:

```
d NUL empty NUL e3b0c44298fc1c14…b855 LF
f NUL one.txt NUL <sha256("one\n") の 64 文字> LF
```

この 2 行を連結したバイト列の SHA-256 が `a/` のチェックサムになる。

---

## 2. 照合コード（check_code）

照合コードは、キーを持つ者が同じフォルダと同じ処理記録に対して
付けたことを確かめるための値である。主張の範囲はそれだけ
（キーを持っていない者が付けた物は排除できるが、キーを持つ誰が
付けたかまでは分からない。キーの持ち主が複数なら区別しない）。

### 2.1 キー

- キー = `--key-file` で渡したファイルの中身そのもの（バイト列）。
  末尾の改行も含む。変換・ trimming をしない。
- キーは保存しない。ログに出さない。処理記録に載せない。
  例外の文言にも出ない。

### 2.2 キー識別子（key_id）

```
key_id = HMAC-SHA256(キー, b"sieve-check-key-id") の先頭 8 バイトの 16 進（16 文字・小文字）
```

処理記録には値だけでなく `key_id` を載せる。受取人はキーを 1 つ
試せば、それが計算に使われたキーと同じかどうかを先に確かめられる。

### 2.3 照合コードの値

```
メッセージ = 全体チェックサムの ASCII (64 バイト)
           + b":"
           + 処理記録から check_code 節と digest を除いた物の正準 JSON（UTF-8・
             キー順・区切りなし・ensure_ascii=False・末尾 LF を付けない。
             digest 再計算と同じバイト列）
check_code = "hmac-sha256:" + HMAC-SHA256(キー, メッセージ) の 16 進（64 文字・小文字）
```

- 全体チェックサムは §1 のフォルダ全体チェックサム（64 文字 16 進・`sha256:` 接頭辞なし）。
- 「check_code 節と digest を除いた物」とは、処理記録（`receipt`）の
  トップレベルからキー `check_code` と `digest` を取り除いた残り全部を
  正準 JSON にした物である（`summary` 節だけより強い結び付き）。
- `receipt_version` は 1 のまま（check_code は任意の節。無い処理記録は
  2.1.1 までと同じ形で検証できる）。

### 2.4 確認の規則

- キーが渡されない: ファイル一覧（パス・サイズ・SHA-256・全体チェックサム）の
  一致確認は**キーなしでも行う**。照合コードの確認だけが
  `not_verifiable`（理由 `code_key_missing`）になる。
- キー識別子が合わない: `not_verifiable`（理由 `code_key_mismatch`）。
  キーが違う物で値の一致不一致を報告しない。
- 照合コードの値が合わない: 既存の語彙 `differs` の `check_code` 項目として載せる。

---

## 3. 処理記録の共通の形

処理記録の外枠は 2.1.1 の Gate と同じ（`receipt_version` / `kind` / `tool` /
`engines` / `settings` / `items` / `summary`、最後に `digest`）。
`manifest` と `pack` は同じ外枠を使い、`--key-file` があるときは
`digest` の直前に `check_code` 節を 1 つ足す（§2.3）。

- 正準 JSON: UTF-8・キー順・`,` と `:` の後に空白を入れない・
  `ensure_ascii=False`・末尾に LF を 1 つ。
- `digest` = `sha256:` + digest キーを除いた処理記録本体の正準 JSON
  （末尾 LF なし）の SHA-256。
- 処理記録は**最後に**書く（handoff の中で最後の言葉）。

---

## 4. 既知値（他実装での検算用）

### KV-1: 空のフォルダ

```
KV-1 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

空のフォルダ（子が 1 つも無い）の全体チェックサム = SHA-256(b"")。
`sha256sum /dev/null` と同じ値。

### KV-2: 3 成分のフォルダ

次の形のフォルダ（`beta.txt` の中身は `beta\n`・`one.txt` の中身は `one\n`・
`empty` は空のディレクトリ・改行は LF 1 バイト）:

```
kv2/
  a/
    one.txt   (b"one\n")
    empty/    (空)
  beta.txt    (b"beta\n")
```

計算:

```
sha256("one\n")  = 2c8b08da5ce60398e1f19af0e5dccc744df274b826abe585eaba68c525434806
sha256("beta\n") = f2c82decdd7181cf98945929a62598db7e6b477e11f6e0eb0ae97020eff151ad
a/ のチェックサム   = SHA-256( d NUL empty NUL KV-1 LF
                               f NUL one.txt NUL sha256("one\n") LF )
                 = be759232915ae5cc26248dfcfcee7dc3a204669594ca0e4ef73fbbd72b385720
ルートのチェックサム = SHA-256( d NUL a NUL (a/ のチェックサム) LF
                                f NUL beta.txt NUL sha256("beta\n") LF )
```

```
KV-2 = 06965d1ff8239b8e9efad9c88d05e8624d92ac3dd252d047617c82c0de724a92
```

`sha256sum` コマンドだけで検算できる（NUL は `\x00` で書く。`\0` にすると
printf が後続の数字を 8 進数として読むので誤る）:

```sh
A=$(printf 'd\x00empty\x00e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\nf\x00one.txt\x002c8b08da5ce60398e1f19af0e5dccc744df274b826abe585eaba68c525434806\n' | sha256sum | cut -d' ' -f1)
# A = be759232915ae5cc26248dfcfcee7dc3a204669594ca0e4ef73fbbd72b385720
printf 'd\x00a\x00%s\nf\x00beta.txt\x00f2c82decdd7181cf98945929a62598db7e6b477e11f6e0eb0ae97020eff151ad\n' "$A" | sha256sum
# -> 06965d1ff8239b8e9efad9c88d05e8624d92ac3dd252d047617c82c0de724a92 = KV-2
```

---

## 5. `manifest` の処理記録の形

### 5.1 単独モード（`manifest <フォルダ> -o <出力先>`）

外枠は §3 のとおり。`kind` = `sieve-manifest`。節:

- `items`: 通常ファイルのみ。要素 = `{"path", "bytes", "sha256"}`。
  `path` は出力フォルダから相対の POSIX 形。UTF-8 で書けないパスは
  `path: null` + `path_hex`（生バイトの 16 進）。順序 = 相対パスの
  UTF-8 バイト昇順。NFC 正規化はしない。
- `skipped`: シンボリック リンク = `symlink_skipped`、読めない
  ファイル/ディレクトリ = `unreadable`、特殊ファイル = `not_applicable`
  （閉じた語彙のみ・ツリー走査は 1 回）。順序 = パス バイト昇順。
- `duplicates`: sha256 が同じ群を**バイト比較で確認**した物だけを載せる。
  要素 = `{"sha256", "bytes", "paths"}`（`paths` はパス昇順）。
- `summary`: `items` / `skipped` / `duplicate_groups` /
  `duplicate_files`（群に属するファイルの総数）/ `duplicate_bytes`
  （群に属するファイルの合計バイト数）/ `overall_sha256`（§1）。
- `--key-file` があるとき: `digest` の直前に `check_code` 節（§2.3）。

`local/` は作らない。処理記録（`handoff/manifest-receipt.json`）が
出力先で最後に書かれる物になる。

### 5.2 差分モード（`manifest <A> --against <B> -o <出力先>`）

`kind` = `sieve-manifest-diff`。`items` / `skipped` / `duplicates` は
空の列。代わりに:

- `differences`: 状態は閉じた 5 種
  `same / changed / removed / added / moved`。
  - `same`: `{"state", "path", "bytes", "sha256"}`
  - `changed`: `{"state", "path", "bytes", "sha256_a", "sha256_b"}`
  - `removed`: `{"state", "path", "bytes", "sha256"}`（A にのみ）
  - `added`: `{"state", "path", "bytes", "sha256"}`（B にのみ）
  - `moved`: `{"state", "path", "path_b", "bytes", "sha256"}`
- moved 対付け: removed と added を **sha256 の群**ごとに見て、
  両側に候補がある群で、**パス昇順の最初の 1 対だけ**を moved にする。
  残りの候補は元の状態（removed / added）のまま残る。
  候補が複数ある群（どちらかの側が 2 以上）は `ambiguous_move` を
  1 ずつ加算する。
- 順序: A 側のパス バイト昇順（moved は A 側パスで並ぶ）。
  `added` は B 側パス バイト昇順で A 側の列に続く。
- `settings`: `against`（B のパス）と `overall_b`（B の全体チェックサム）。
- `summary`: `items`（differences の要素数）/ 5 状態ごとの件数 /
  `ambiguous_move` / `overall_sha256`（**A 側**の全体チェックサム）。

CLI の終了符号: 単独モードと差異なしの差分 = `0`、
changed / removed / added / moved が 1 件でもある差分 = `1`、
実行不能 = `2`。

---

## 6. `verify` の拡張（§2 の確認のしかた）

`verify <処理記録> [--key-file <キー>] [--root <フォルダ>]` は、
既存の語彙（overall = `match` / `differs` / `not_verifiable`・
項目理由 7 種・終了符号 0/1/2）を保ったまま、次だけを足す:

- `not_verifiable` の理由に 2 語を追加（§2.4）:
  `code_key_missing`（処理記録が `check_code` 節を持ち、キーが渡らない。
  **ファイル一覧の一致確認は、この場合でも行われ、その結果が items に載る**）、
  `code_key_mismatch`（キー識別子が合わない。値の一致不一致は報告しない）。
- 照合コードの値が、合うキーで再計算した結果と違うとき:
  既存の `differs` に `{"path": "check_code", "reason":
  "check_code_differs"}` の 1 行として載る（C11）。
- 実差異があるときは `differs` が `not_verifiable` に勝つ
  （一覧の確認結果を隠さないため）。
- `--root` は `manifest` / `pack` の処理記録をフォルダに対して確かめる:
  項目ごとの有無・サイズ・SHA-256（既存の理由語 `input_missing` /
  `input_changed` / `item_added`）と、§1 の全体チェックサムの再計算
  （合わなければ `.` が `input_changed`）。

`gate` / `cohort` / `manifest` / `pack` は共通の `--key-file` を受ける（C5）。
キーが渡された実行だけが `summary.overall_sha256`（入力フォルダの §1
チェックサム）と `check_code` 節を持ち、`receipt_version` は 1 のまま
（キーのない処理記録は 2.1.1 までと同じ形・同じ digest）。
主張の範囲は §2 冒頭のとおり限定される（C13）。

## 7. `--verify-page` が書くページと `verify_page` 節

`manifest` と `pack` は `--verify-page` を受けます（§3.5）。

- ページは 1 つの `handoff/verify.html`。**処理記録の前に書く**
  （処理記録が最後の書き出しという規則を保つ）。外部の読み込み・
  通信・フォントの参照はなく、ファイル一覧（`path` / `bytes` /
  `sha256` と、§1 のフォルダ全体チェックサム）を
  `<script id="seal-data" type="application/json">` として埋め込む。
  埋め込む JSON は、`sort_keys` の整列・`ensure_ascii=False`・
  空白なし（§3 の正準形）に `s/</\\u003c/; s/>/\\u003e/; s/&/\\u0026/`
  を施したもの（名前が閉じタグを挟めないようにする。置換後も有効な
  JSON で、値は変わらない）。
- SHA-256 は、ページ内の純 JavaScript 実装（`<script id=
  "seal-sha256-core">`）で計算する。標準の暗号 API が使える環境でも
  こちらを使う（挙動を 1 つに固定）。既知の値 4 種（空文字列・`abc`・
  64 バイト境界・100 万個の `a`）で検算できる（SL-T12）。
- ページが確かめるのはファイル一覧の一致のみ
  （same / changed / missing / extra を画面に表示。送信はない）。
  **照合コード（HMAC）は、ページでは確かめない**（1 行でその旨を
  表示する）。
- `--verify-page` を付けた実行の処理記録は、次の任意節を 1 つ足す。

```json
"verify_page": {"name": "verify.html", "sha256": "sha256:…64 桁…"}
```

  `sha256` は、書いたページのバイト列そのものの SHA-256。節は
  digest の計算対象に入る（§3 どおり、body 全体から `digest` を除いた
  文字列の SHA-256。`check_code` と同じく、後から足す節ではないので
  順序は `check_code` → `digest` の前に確定する）。
- `--verify-page` を付けない実行は、ページを書かず、処理記録にも節を
  足さない（2.1.1 までとバイト等価）。
- 拒否（終了符号 2）: 差分（`--against`）に `--verify-page` は付けられない。
  UTF-8 として読めない名前（`path: null` + `path_hex` の項目）は、
  ブラウザが再現できないため、ページには乗せられない。
