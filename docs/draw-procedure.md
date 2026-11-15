# 抽選（draw）の手順 — 誰でも再現できる形

`draw` は、名簿と公開する seed から、班分け（または並び順）を決める。
誰でも、表計算ソフトや別の実装でも、同じ結果を再現できるように、
手順をバイト単位でここに書く。

**注意（1 文）**: seed は、結果を見る前に公開してください。

**主張の範囲**: draw が示すのは「**この seed と名簿から、この結果になる**」
ことだけである。それ以上のことは（誰が選んだか、なぜそれが良い区分か、
結果を動かせないか）は、何も示さない。

## 1. 入力の正規化

- 名簿は 1 行 1 項目のテキスト。行の終端は LF。CRLF のファイルは
  CR を終端の一部として扱い、項目には入れない。
- **正規化後の名簿** = 行を LF で連結し、末尾に LF を 1 つ足したバイト列。
- **名簿のハッシュ** = SHA-256(正規化後の名簿)。
- 空の名簿・空行・UTF-8 として読めない名簿は、受け付けない
  （終了符号 2）。

## 2. 順序の決め方

1. 各項目 x について、`key(x) = SHA-256( UTF-8(seed) || 0x00 || x )`
   （seed は文字列として UTF-8 にする。0x00 は 1 バイトの NUL。
   x は名簿の行のバイト列。16 進小文字 64 桁が key）。
2. 項目を、**key のバイト列の昇順**に並べる。同じ key は、**x の
   バイト列の昇順**（同じ行が 2 回ある名簿でも、同じ並びになる）。
3. 班の数 k: `--groups N` なら k = N。`--size N` なら
   k = ceil(項目数 ÷ N)（端数は切り上げ）。
4. 並んだ項目を、先頭から k 個の班に**順番に配る**（ラウンドロビン）。
   p 番目（0 から数える）の項目は、班 (p % k) に入る。最後の班は
   少なくなることがある。
5. 席順・並び順だけが要るときは、2. で並べた順（`ordered`）をそのまま
   使う。

## 3. 出力

- `local/draw-result.json` — 結果（氏名を含む。手元に残す）。
  形: `{"groups": [[...], ...], "ordered": [...]}`。UTF-8・キーの
  整列・空白なし・末尾 LF 1 個（処理記録と同じ正準形）。
- `handoff/draw-receipt.json` — 処理記録。載るのは**名簿のハッシュ・
  seed・groups・size・結果のハッシュ・digest** のみ。
  **名簿の中身と氏名は、載らない。**
- `result_sha256` = 書いた `local/draw-result.json` のバイト列そのものの
  SHA-256（受け取る側や後日の自分が、ファイルのバイトで直接検算できる）。

## 4. 既知の例（他実装での検算用）

### KV-D1: 3 項目を 2 班に

名簿（3 行・LF 終端）と seed とパラメータ:

```
roster = "alice\nbob\ncarol\n"
seed = "2026-08-demo"
groups = 2
```

計算（key = SHA-256( UTF-8(seed) || NUL || x )）:

```
key(alice) = 1fddd17383b1b6e676482d09781a4391c11c5ae33ee3bdbf5a2d78f868ef8306
key(bob)   = ed136e519e73e3964b96bf10ebd451debb0f7498d575c1559debbbc7dca82392
key(carol) = 518f771f26d52f3e968fb182a0644820bc7fb52c1db5b21c25f94816ecff9d93
```

key 昇順 → `alice` < `carol` < `bob`。p 番目を班 p % 2 へ:

```
ordered = ["alice", "carol", "bob"]
groups = [["alice", "bob"], ["carol"]]
```

書いたファイルのバイト列（1 行・末尾 LF）:

```
{"groups":[["alice","bob"],["carol"]],"ordered":["alice","carol","bob"]}
```

名簿のハッシュと結果のハッシュ:

```
KV-D1-roster = 54e7fd617a3c08ae396cadd191b9e16db655b8c9e0832d35902f7d351b8cd191
KV-D1-result = dae02d918072cb8f225273064beaf5fd284781ebb9ca96d79b3e86520b783413
```

### KV-D2: 5 項目を --size 2 で（k = 3・最後の班は 1 人）

名簿（5 行・LF 終端）と seed とパラメータ:

```
roster = "alice\nbob\ncarol\ndave\nerin\n"
seed = "2026-winter-demo"
size = 2
```

計算:

```
key(alice) = 751d811c349aeeac8a1cc2bbd81f0277cfb3f69b77cb15d032966ef51e28d0a1
key(bob)   = d4a5cc32ac42643588a1e7499165a0457b0eef8bd510ac1442b9a7a20ab94efc
key(carol) = f64e5f09de4889731030f88e603dfcf077696afa638d5e45e92ce4db0258928e
key(dave)  = 4a208d95ddaf6e2f4d8f4e544cc813363757126219cf0a407e38229658133159
key(erin)  = 3aab22130140e78f68b9d31b004ea35bf29ae05c4db8502d56113753f8d6873d
```

key 昇順 → `erin` < `dave` < `alice` < `bob` < `carol`。k = ceil(5 ÷ 2) = 3:

```
ordered = ["erin", "dave", "alice", "bob", "carol"]
groups = [["erin", "bob"], ["dave", "carol"], ["alice"]]
```

名簿のハッシュと結果のハッシュ:

```
KV-D2-roster = 772e62f2c1ae2609e508d7168a41ad1398189960ebee4991b9443f15fd4fda22
KV-D2-result = 49ee187e2cc397886382a4d22c5bfce70a50ace4f4ff5201fbcfc79f014b4ac5
```

## 5. シェルだけで検算する（KV-D1 の key(alice)）

NUL は `\x00` で書く（`\0` にすると printf が後続の数字を 8 進数として
読むので誤る）。末尾に改行を付けない:

```sh
printf '%s\x00%s' '2026-08-demo' 'alice' | sha256sum
# -> 1fddd17383b1b6e676482d09781a4391c11c5ae33ee3bdbf5a2d78f868ef8306
```

名簿のハッシュは、行を LF でつないで `sha256sum` に渡す:

```sh
printf 'alice\nbob\ncarol\n' | sha256sum
# -> 54e7fd617a3c08ae396cadd191b9e16db655b8c9e0832d35902f7d351b8cd191
```

結果のハッシュは、上の 1 行（`{"groups":...` のバイト列・末尾 LF 含む）を
ファイルに保存して `sha256sum` に渡す。

## 6. CLI

```
python3 sieve_tray.py draw <名簿> --seed <文字列> --groups N -o <出力先>
python3 sieve_tray.py draw <名簿> --seed <文字列> --size N -o <出力先>
```

`--groups` と `--size` はどちらか 1 つ（両方・どちらも無しは不可）。
`-o` の下に `local/draw-result.json` と `handoff/draw-receipt.json` が
できる（処理記録は最後に書かれる）。
