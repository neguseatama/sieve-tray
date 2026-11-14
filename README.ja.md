[English](README.md) | **日本語**

# Sieve Tray v2.1.1

**汎用観測ツール — Sieveシリーズのデスクトップフロントエンド**

> [Sieve Lens](https://github.com/neguseatama/sieve-lens)の不可視コンテンツ観測、
> [Sieve Scope](https://github.com/neguseatama/sieve-scope)のコード類似度検知、
> [Sieve Referee](https://github.com/neguseatama/sieve-referee)のテキストパラフレーズ検知 —
> そしてv0.8.0で新たに追加されたSieve Refereeの量化子監査レーン — を、
> 1つのデスクトップアプリに統合しました。さらに、テキスト・画像のサニタイズ操作の
> 背後にある[Sieve Redact](https://github.com/neguseatama/sieve-redact)マスキング
> エンジンと、v0.10.0で追加された「匿名化」タブの背後にある
> [Sieve Crowd](https://github.com/neguseatama/sieve-crowd)テーブル匿名化エンジンを
> 同梱しています。匿名化タブには **表の観測（`scan`）** もあります:
> 「いまの表がどう見えているか」 — 役割・グループ・不可視文字の所見（セルの値は出ません）—
> をCrowdが1枚のHTMLにまとめ、ブラウザでそのまま開けます。
> 提出物のフォルダを指定するだけで、
> 不可視のコンテンツや隠されたプロンプトを含む文書、構造的に疑わしく似ているコードペア、
> 言い換え・流用の疑いがあるテキストペア、根拠のない全称主張（ハルシネーション候補）を
> 含む文を、一度にまとめて検出、報告します。さらに
> Cohort（提出物の比較）タブが加わりました: フォルダ内の提出物を互いに比較し、
> プライバシーを確認済みの書き出し記録（`handoff/`）を書き出します。
> 報告一式は手元に残ります。

[![Test](https://github.com/neguseatama/sieve-tray/actions/workflows/test.yml/badge.svg)](https://github.com/neguseatama/sieve-tray/actions/workflows/test.yml)
[![Release](https://github.com/neguseatama/sieve-tray/actions/workflows/release.yml/badge.svg)](https://github.com/neguseatama/sieve-tray/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)

---

## 💡 コンセプト

[Sieve Lens](https://github.com/neguseatama/sieve-lens)は「この文書には、人間には
見えないがパーサには読める何かが含まれていないか」を、
[Sieve Scope](https://github.com/neguseatama/sieve-scope)は「この2つのソースコードは、
偶然とは思えないほどロジックが似ていないか」を、
[Sieve Referee](https://github.com/neguseatama/sieve-referee)は「このテキストは、
あちらのテキストを言い換えただけではないか」を、それぞれ観測します。
[Sieve Redact](https://github.com/neguseatama/sieve-redact)は「選んだ領域だけを
確実に隠し、他は何も変わっていないことを証明する」を、
[Sieve Crowd](https://github.com/neguseatama/sieve-crowd)は「このテーブルを、
中の個人を晒さずに共有する」を、それぞれ担います。いずれも
Sieveシリーズらしい、外部依存ゼロ・決定論的なエンジンですが、提出物フォルダを
実際にチェックするには、これらを別々に走らせ、結果を自分で突き合わせる必要が
ありました。

**Sieve Tray**はその手間をなくします。1提出者につき1サブフォルダ、という構造の
フォルダを指定するだけで、ファイルごとに適切なエンジンへ自動的に振り分けます
（文書はSieve Lensへ、`.py`ファイルはSieve Scopeのペア比較へ、プレーンテキスト
（`.txt`/`.md`）はさらにSieve Refereeのペア比較**と量化子監査レーン**へ
（v0.8.0で追加・Sieve Referee >=1.3.0 が必要）。結果は1つのウィンドウに
まとまり、履歴が残るので再スキャンは不要、さらにどの観測軸が反応し、その根拠が
何だったかまで詳細表示で確認できます。単なる「白黒の判定」ではなく、エンジンが
実際に観測した事実だけを提示します。**匿名化**タブはテーブルファイルをSieve
Crowdへ、サニタイズ操作はテキスト・画像エディタを通じてSieve Redactへ、
それぞれワンクリックでつなぎます。

> 他のSieveシリーズ同様、これは**観測ツールであって、判定ツールではありません**。
> フラグが立つことは「人間が確認すべき」という意味であり、「不正が確定した」という
> 意味ではありません。

---

## 🚪 Gate（共有前の書き出し）

フォルダを選ぶだけで、AI や他の人に渡す前の処理を、まとめて行います。

- 文書から、画面に見えているテキストだけを取り出す
- 氏名・メールアドレスなどの個人情報を、`[REDACTED]1`、`[REDACTED]2` … に置き換える
- 見えない文字（背景と同じ色の文字など）に、AI へのプロンプトが隠されていないか調べる

出力は 2 つのフォルダに分かれます。

- `handoff/` … 渡してよいファイル
- `local/` … 手元に残すファイル（詳しいレポート）

`handoff/` には処理記録（`gate-receipt.json`）も入ります。載るのは件数とチェックサムだけで、本文や氏名は載りません。あとで `verify` を実行すると、渡したファイルが書き出したときのままか確認できます。

```
python3 sieve_tray.py gate <入力フォルダ> -o <出力先>
python3 sieve_tray.py verify <出力先>/handoff/gate-receipt.json
```

## 👥 Cohort（提出物の比較）

フォルダに集めた提出物を総当たりで比べて、似ているペアを見つけます。

- 文書 … 文章の重なりを調べる
- Python … 変数名を変えてあっても、同じ構造を見つける
- そのほかのプログラミング言語 … 共通の方法で調べる（小さなファイルが大きなファイルにそのまま含まれている場合も見つかる）

結果は、Gate と同じく `handoff/`（処理記録だけ）と `local/`（比較レポート）に出ます。レポートには、似ているペアと、重なっている場所（何文字目から何文字目か）が載ります。似ているペアは「確認する候補」で、不正の判定ではありません。

課題文やテンプレートなど、全員に共通する資料は「基準となる資料」に指定すると、重なりから除外されます。

```
python3 sieve_tray.py cohort <入力フォルダ> -o <出力先>
python3 sieve_tray.py verify <出力先>/handoff/cohort-receipt.json
```

ファイル名に氏名が入っているときは `--no-paths` を付けてください。処理記録では、ファイルを連番で区別します。

処理記録の語彙や重なりの数え方の詳細は、[docs/receipt-reference.md](docs/receipt-reference.md) にあります。

## 📋 ファイル一覧と照合コード

フォルダの中身を 1 つの表にまとめて書き出し、あとで確かめられるようにします。表には各ファイルのチェックサムとサイズが載り、フォルダ全体のチェックサムも付きます。`--key-file` を付けると照合コードが付き、確認には同じキーファイルが必要になります。

1. フォルダを指定して実行する（差分は `--against`、照合コードは `--key-file`）
2. `handoff/` の処理記録を渡し、`local/` は手元に残す
3. 受け取った側は `verify` で一致を確かめる

```
python3 sieve_tray.py manifest <入力フォルダ> -o <出力先>
python3 sieve_tray.py manifest <A> --against <B> -o <出力先>
python3 sieve_tray.py verify <出力先>/handoff/manifest-receipt.json
```

処理記録の形と照合コードの規則の詳細は、[docs/manifest-format.md](docs/manifest-format.md) にあります。

## 🧹 名前の整理

ファイル名を決まった規則で整える計画を作り、確認してから適用できます。元のフォルダはそのまま変えず、整えた複製を別に作ります。

1. `--pattern` で規則を指定して実行し、計画を確認する
2. 問題なければ `--apply` で複製を作る
3. 名前が氏名を含むときは `--no-paths` を付ける（処理記録は連番で識別する）

```
python3 sieve_tray.py rename <入力フォルダ> --pattern '{stem}_{seq:3}{ext}' -o <出力先>
python3 sieve_tray.py rename <入力フォルダ> --pattern '{stem}_{seq:3}{ext}' --apply -o <出力先>
```

規則に書けるフィールドは `{seq}`・`{stem}`・`{ext}`・`{hash8}`・`{parent}` の 5 種（`{seq:3}` のように桁数を指定できます）で、名前の衝突は実行の前に一覧が出ます。規則と処理記録の詳細は、[docs/rename-procedure.md](docs/rename-procedure.md) にあります。

## 🎲 抽選・班分け

名簿と公開の seed から、誰でも同じ結果を出せる抽選を行います。順番は seed から決まり、班はラウンドロビンで配られます。

1. 名簿（1 行に 1 件）を用意する
2. `--seed` に文字列を指定し、`--groups` か `--size` のどちらかで分け方を決める
3. 結果は `local/`、処理記録は `handoff/` に出る（処理記録に氏名は載らない）

```
python3 sieve_tray.py draw <名簿> --seed <文字列> --groups 3 -o <出力先>
```

手順と検算の方法の詳細は、[docs/draw-procedure.md](docs/draw-procedure.md) にあります。

---

## 🧩 Sieve シリーズ

Sieve は、決定的・ゼロ依存・完全ローカルという共通の設計原則を共有する
エンジン群です。各エンジンが 1 つのリスクの観測または処置を担い、
相互に接続します:

| パッケージ | 役割 | 接続 |
|---------|------|-------------|
| [sieve-core-engine](https://github.com/neguseatama/sieve-core) | 決定論的な構造集約・確信度評価の基盤エンジン | — |
| [sieve-lens](https://github.com/neguseatama/sieve-lens) | 文書内の不可視コンテンツ・隠しプロンプトを観測 | → `--from-lens` 経由で redact へ、→ tray へ |
| [sieve-scope](https://github.com/neguseatama/sieve-scope) | ソースコードの構造的類似性を観測 | → tray へ |
| [sieve-referee](https://github.com/neguseatama/sieve-referee) | テキストの構造・流用・言い換えを観測 | → tray へ |
| [sieve-redact](https://github.com/neguseatama/sieve-redact) | 指定領域の決定論的マスキングと完全性検証 | ← lens、→ tray |
| [sieve-order](https://github.com/neguseatama/sieve-order) | プロンプトの表層構造を6-bit観測空間で観測しレシートを発行 | — |
| [sieve-crowd](https://github.com/neguseatama/sieve-crowd) | テーブルデータを数理的変換で匿名化 | → tray へ |
| [sieve-tray](https://github.com/neguseatama/sieve-tray) | 各エンジンを統合するローカルフロントエンド | ← 全エンジン |

観測から排除まで 1 パスで: Lens が人間に見えないものを見つけ、
Redact が「他は何も変わっていない」ことを証明するレシートとともに
除去します。

## 🔥 主な特徴

- **フォルダ1つで全部チェック** — `.py`ファイルはSieve Scopeへ、プレーンテキスト
  （`.txt`、`.md`）はさらにSieve Refereeへ（ペア比較**と量化子監査レーン**の両方）、
  全ての文書（`.html`、`.docx`、`.pdf`、画像を含む）はSieve Lensへ、
  拡張子で自動的に振り分け
- **バックグラウンドスレッドで動くGUI** — 大量の提出物でもスキャン中にウィンドウが
  固まらない
- **表の観測（scan）と未観測の3段階の色分け** — CSV／Excelを1つ選ぶだけで、Crowdの
  1枚もののHTMLをブラウザで読めます。観測できなかった行は、アプリの画面とHTML報告の
  両方で3段階の色に分かれます（淡い琥珀 = ファイル側の対応で観測できる、グレー =
  エンジン側の事情、より淡いグレー = 設計上の対象外）。理由の文字は色と併せて必ず表示
- **英語・日本語UI** — 設定画面からいつでも切り替え可能（デフォルトは英語）。なお
  Sieve Refereeが生成する判定理由の説明文は、エンジンの閾値調整が日本語前提のため、
  UI言語に関わらず常に日本語で出力されます。詳細ダイアログにはその旨を明記した上で
  表示します
- **ソート・フィルタ可能な結果テーブル** — 列見出しクリックで並び替え、ファイル名や
  「フラグのみ表示」で絞り込み可能
- **第3の状態「未観測」の報告（v1.1.0新機能）** — 読めなかった・大きすぎる・
  リンクのため読まなかった・エンジンが必要とする拡張が使えなかった・解析が
  成立しなかったファイルが、これまでの「クリーン」と同じ見た目に紛れたり、
  結果から消えたりしません。理由を閉じた語彙で「未観測」として、結果表・
  件数サマリ・履歴・HTML/Markdownレポートに表示します。未観測は「観測が
  成立しなかったことの報告」であり、問題がないことを意味しません
- **詳細ダイアログ** — 行をダブルクリックすると、マスク文字列だけでなく観測軸ごとの
  結果と、エンジンが記録した根拠・スコア・理由まで確認できる
- **量化子監査レーン（v0.8.0新機能）** — スキャンした`.txt`/`.md`ファイルは、
  Sieve Refereeの量化子監査レーンにも渡されます。定理証明 (`theorem`)・
  有限全列挙 (`enumerated`)・標本 (`sample`) のいずれの裏付けもなく全称主張を
  閉じる「すべてのXはYである」型の文を検出し、ハルシネーション候補として
  フラグします。フラグされた文は専用の**量化子監査**タブに1行1文で表示され、
  シグナル (RED = 裏付けのない全称、YELLOW = 標本のみまたは裏付けのない測定値) ・
  マッチした語彙パターン・裏付け・スコープが確認できます。詳細ダイアログには
  **確信度マーカー**セクションが別途用意され、文中に共起した認識的確信度マーカー
  （例：「明白に」「例外なく」）を表示します。レーンは同梱のデフォルト語彙
  ファイルで初期状態から動作し、設定画面から語彙ファイルを上書き可能です
- **エンジンの更新（v1.3.0新機能）** — 匿名化はSieve Crowd 0.9.0、テキスト・
  画像マスキングはSieve Redact 0.10.0に更新しました。Crowd は CP932 の CSV と
  Excel（`.xlsx`）のワークブックをそのまま読み込みます（文字コードは自動判定 —
  UTF-8 を優先し、CP932 を代替として採用・どちらでもないファイルは拒否）。
  Redact は画素数上限を超える画像を処理せずに人間が読めるメッセージで拒否し、
  `090ー1234ー5678`（全角長音・半角カナ長音）の電話番号もハイフン表記と同じく
  観測してマスクします
- **エンジンの「観測できなかった」を未観測に（v1.3.0新機能）** — エンジンが
  観測できなかったファイルは、エンジン自身の理由とともに「未観測」一覧に載ります。
  解析の抜けが、問題なしとして見えることはありません
- **監査語彙17種への追従（v1.2.0新機能）** — Sieve Referee 1.5.0が追加した
  確信度マーカー7種（「必然的に」「不可避的に」「自ずと」「おのずと」
  「疑いようがない」「疑いようもない」「言うまでもなく」）でも量化子監査
  レーンが全称文を検出し、監査タブ・両レポート・履歴に漏れなく表示します
- **ローカル履歴** — スキャン・匿名化のたびにローカルのSQLiteデータベース
  （`~/.sieve_tray/history.db`）に自動保存。再スキャンせずに過去の結果を見返せる
- **設定可能** — レポートの保存先フォルダ、履歴の保持件数、UI言語、
  そして監査レーンの確信度マーカー語彙ファイル（空 = 同梱デフォルト）を、
  設定画面から変更可能
- **ファイル選択 / フォルダ選択（v0.9.0新機能）** — 従来のフォルダ選択に加え、個別ファイルを選択できる。監査レーンは 1 文書でも動くため、ファイル選択モードは気軽な単体チェックに適する。
- **HTML / Markdown レポート書き出し（v0.9.0で Markdown 追加）** — どの結果も、共有・保管しやすい単体の HTML レポート、またはプレーンテキスト / バージョン管理向きの Markdown レポートとして書き出せる。
- **履歴の消去（v0.9.0新機能）** — 「履歴」タブと「サニタイズ履歴」タブにそれぞれ「履歴を消去」ボタンを置いた。ローカル SQLite ストアをリセットできる。
- **信号色の改善（v0.9.0新機能）** — RED / YELLOW 行の背景色を強めのパステルにし、信号列を信号色の前景色で描画。キャリブレーション済みモニターでも、フラグ行が一目で分かる。
- **テキストのサニタイズ** — 選択フォルダ内の`.txt`/`.md`ファイルに対し、
  ルールファイルを指定して同梱のSieve Redactエンジンを実行。出力ごとに
  機械可読なレシートが生成され、サマリにはマスク件数とバイト完全性の
  検証結果が常に表示されます
- **画像のサニタイズ** — PNG（8bit RGB/RGBA）の上に矩形をドラッグして指定し、
  リージョンエディタで本物のエンジン出力をその場でプレビュー、設定ファイルとしても
  保存可能。出力ごとに機械可読なレシートが生成されます（画素完全性は検証・
  バイト完全性はPNG再エンコードのため測定対象外）
- **フォルダの画像サニタイズ** — 1つのリージョン設定をフォルダ内の全PNG
  （8bit RGB/RGBA）に一括適用します。設定の種類が対象を決めます（region 行
  のみの設定はPNG、rule・builtin 行のみの設定は`.txt`/`.md`）。合わない
  ファイルは「失敗」ではなく「対象外」として報告され、両方が混在する設定は
  何も処理せずにエラーを報告します。出力ごとに機械可読なレシートが生成されます
- **テーブルの匿名化（v0.10.0新機能）** — 「匿名化」タブでテーブルファイル
  （`.csv`/`.json`/`.xml`/`.xlsx`・v1.3.0 から Excel と CP932 に対応）を
  同梱のSieve Crowdエンジンへ渡します。列の調査
  （異なり数・一意率・提案役割）、測定実行による処理前後の単独レコード数比較、
  仮名化キーの生成、そして決定論的な匿名化（入力・出力レコード数・除外件数・
  達成 k 値・状態を含む機械可読なレシートつき）。保護は、qi として宣言した
  列を知る相手への k-匿名性で、要求した k が達成できない場合エンジンは
  出力ファイルを書かずに拒否します。実行はすべてローカル履歴に保存され、
  書き出したレポートにも含まれます。タブ内には 8 列の実行履歴ビュー
  （最新 20 件・起動時と実行直後に更新・v1.0.0 新機能）もあります
- **サニタイズ履歴タブ** — これまでのサニタイズ実行(フォルダ・単体画像
  ともに)を専用タブに一覧表示します(日時・フォルダ・設定・出力先・
  ファイル数と成功数・マスク件数・完全性失敗)。実行が完了すると
  即座に反映されます
- **完全ローカルで動作** — スキャンは100%お使いの端末内で完結します。提出物の中身が
  外部に送信されることはなく、クラウドへのアップロードもAPI通信も一切発生しません
- **コアはゼロ依存** — スキャンエンジン本体（`sieve_tray.py`）はPython標準ライブラリと
  Sieve Lens / Sieve Scope / Sieve Refereeのみに依存。GUIはその上に載る任意のレイヤー
  （`PySide6`）として分離してあり、Sieveシリーズ全体の「外部依存ゼロ・オフライン・
  決定論的」という設計思想をコア部分では保っています
- **クロスプラットフォーム配布** — CIがPyInstallerでWindows・macOS（Apple Silicon /
  Intel）向けの単体アプリを自動ビルド。実行にPythonのインストールは不要

---

## 📦 インストール

### 方法1: ビルド済みアプリをダウンロード（推奨）

Pythonのインストールは不要です。
[最新リリース](https://github.com/neguseatama/sieve-tray/releases/latest)から、
お使いの環境に合ったものをダウンロードしてください。ファイル名はタグから決まり、
`<version>` はリリース版です。

| プラットフォーム | ファイル |
|---|---|
| Windows | `SieveTray-<version>-windows.zip` |
| macOS（Apple Silicon / M系） | `SieveTray-<version>-macos-arm64.zip` |
| macOS（Intel） | `SieveTray-<version>-macos-intel.zip` |

展開して`SieveTray.exe` / `SieveTray.app`を起動してください。初回起動時、macOSでは
「開発元を確認できません」という警告が出ます（想定内です）。
**システム設定 → プライバシーとセキュリティ**から「このまま開く」を選んでください。
Windowsでも同様にSmartScreenの警告が出ることがあります。「詳細情報 → 実行」を
選んでください。

### 方法2: ソースからインストール

```bash
git clone https://github.com/neguseatama/sieve-tray.git
cd sieve-tray
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui]"
python3 sieve_tray_gui.py
```

Python 3.10〜3.13が必要です（PySide6はまだ3.14に対応していません）。

インストールには、HTML の見えない文字を調べるための CSS 解析（tinycss2・cssselect2）が、Sieve Lens の追加ライブラリとして一緒に入ります。

コアのみ（GUIなし、CLI利用・スクリプト用途向け）:

```bash
pip install -e .
```

---

## 💻 クイックスタート

### GUI

1. アプリを起動
2. 「フォルダを選択...」から、1提出者につき1サブフォルダという構造のフォルダを選択
3. 「Run Scan」をクリック
4. 「Documents」「Code Pairs」「Text Similarity」「量化子監査」タブで結果を確認 —
   列見出しで並び替え、ファイル名で絞り込み、行をダブルクリックで観測軸ごとの詳細を表示
   （監査行の詳細ダイアログには別途「確信度マーカー」セクションが表示されます）
5. 「Export HTML Report」で共有可能なレポートを出力。過去のスキャンは常に
   「History」タブから確認できます

（UI言語のデフォルトは英語です。設定画面から日本語に切り替えられます。切り替えは
再起動後に反映されます）

### CLI

```bash
python3 sieve_tray.py path/to/submissions -o report.html
```

1提出者につき1サブフォルダという構造のディレクトリを想定しています。

```
submissions/
    student_a/
        essay.docx
        solution.py
    student_b/
        essay.docx
        solution.py
```

### ライブラリとして

```python
from pathlib import Path
from sieve_tray import run_scan, render

result = run_scan(Path("submissions"), progress=print)
print(result.doc_results)   # path / mask / flagged / h_states / evidence
print(result.code_pairs)    # a / b / mask / h_states / scores
print(result.text_pairs)    # a / b / signal / mask / pattern_name / reason / h_states / scores
print(result.audit_results) # v0.8.0: file / sentence_sha256 / sentence_text /
                           #         patterns / backing / scope / signal /
                           #         pattern_name / reason / certainty_markers /
                           #         modifier_vocab_sha256 / modifier_vocab_count

Path("report.html").write_text(render(result))
```

---

## 🚀 初回起動

[最新リリース](https://github.com/neguseatama/sieve-tray/releases/latest) からプラットフォームに
合うzipをダウンロードして展開し、`SieveTray` を起動します。macOSは初回だけ
Gatekeeperの確認が出ます — **システム設定 → プライバシーとセキュリティ** で
**このまま開く** を押してください。Windowsは初回だけSmartScreenの確認が出ます —
**詳細情報** から **実行** を押してください。それ以降は普通に起動します。
各リリースには成果物の **`SHA256SUMS.txt`** を添えてあるので、初回起動の前に
`shasum -a 256 SieveTray-<version>-macos-arm64.zip`（macOS/Linux）や
`certutil -hashfile SieveTray-<version>-windows.zip SHA256`（Windows）で
確かめられます。

---

## 🖼️ スクリーンショット

| メインウィンドウ | 匿名化タブ |
|---|---|
| ![メインウィンドウ](docs/screenshots/main-window-ja.png) | ![匿名化タブ](docs/screenshots/anonymize-tab-ja.png) |

| ファイル一覧と照合コード | 抽選・班分け |
|---|---|
| ![ファイル一覧と照合コード](docs/screenshots/manifest-page-ja.png) | ![抽選・班分け](docs/screenshots/draw-page-ja.png) |

---

## 🔬 テスト

```bash
pip install -e . pytest
pytest -v
```

コアのスキャン/レンダリング処理（CSSレンダリングバグやSieve Refereeのパラフレーズ
検知の回帰テストを含む）、履歴・設定のストレージ層（保存・読み込み・削除・保持件数
による自動整理、Referee導入前のDBからの移行を含む）、i18n文字列テーブル（英語・
日本語のキー整合性）を合わせて132件のテストでカバーしています。加えて、同梱Sieve Redact統合（バイトpin同期と終了コードマッピング）、画像サニタイズ経路
（リージョンヘルパー・レシート処理・offscreen Qt上のエディタウィジェット）、フォルダ均一画像サニタイズ（設定種別によるルーティング・対象外ファイルの報告・設定レベルのエラー報告）、同梱Sieve Crowd統合（コアラッパー・ストレージ・UIウィジェット・レポート節・vendor pin同期・Aboutのエンジン一覧）も対象です。

CIはpushのたびにこのテストスイートを実行し（Ubuntu上でPython 3.12）、
バージョンタグをpushするたびにWindows/macOS向けデスクトップアプリをビルドします。

---

## ⚠️ 既知の制限

1. **コード比較はPythonのみ対応。** Sieve Scopeへ振り分けられるのは`.py`のみで、
   他言語は現状ただの文書として扱われる（または無視される）
2. **テキスト類似度比較はプレーンテキストのみ対応。** Sieve Refereeへ振り分けられる
   のは`.txt`/`.md`のみ。`.docx`/`.pdf`などのリッチな形式は、Sieve Lensによる個別の
   観測は行われるものの、現状このテキスト比較のためにプレーンテキスト抽出はしていない
3. **Sieve Refereeの`reason`（判定理由）はUI言語に関わらず日本語のみ。** エンジンの
   類似度閾値が日本語テキストを前提に調整されているため。詳細ダイアログにはその旨を
   明記した上で表示する
4. **配布ビルドは開発元の確認ができません。** Windows SmartScreenとmacOS Gatekeeperが初回起動時に
   警告を出す。想定内の挙動
5. **観測ツールであって、判定ツールではない**（Sieve Lens・Sieve Scope・Sieve
   Refereeから継承した姿勢）。フラグは「人間の確認が必要」という意味であり、「不正が
   確定した」という意味ではない
6. **サニタイズはプレーンテキストとPNG画像のみ対応。** フォルダのSanitizeは
   設定の種類で振り分けます（region 行のみの設定はPNGを、rule・builtin 行のみの
   設定は`.txt`/`.md`をバックグラウンドスレッドで処理）。画像エディタは単一のPNG
   （8bit RGB/RGBA・非インターレース）を扱います。いずれも出力ごとに機械可読な
   レシートを書き出します。PDF・JPEGのマスキングは同梱エンジンでは未対応です
7. **量化子監査レーンは日本語調整**（v0.8.0新機能）。監査レーンのデフォルトの
   全称スコープ語彙・確信度マーカー語彙は日本語テキストを前提に調整されています。
   他言語の文は同等の全称主張であっても反応しない場合があります。語彙のsha256・
   収録数は詳細ダイアログに表示されるため調整状況が透明で、語彙ファイルは
   設定画面から上書き可能です
8. **量化子監査レーンは候補を表示するもので、判定ではない。** REDシグナルは
   「この文はtagfileに裏付けが記録されていない全称主張を含む」という意味で、
   ハルシネーションの**候補**であって確定ではありません。tagfileが裏付けラベル
   （`theorem` / `enumerated` / `sample` / `unbacked`）の真の情報源であり、
   audit_text()はtagfileを自動で埋めません。フラグされた文が本当に裏付け不足
   なのか、単にtagfile未登録なのかは人間が確認する必要があります
9. **匿名化は宣言した準識別子のみを保護**（v0.10.0新機能）。Sieve Crowdの
   k-匿名性の保証は、qi として宣言した列を知る相手に対してのみ成立します。
   宣言し忘れた列は保護されません。宣言した qi・達成された k・処理前後の
   単独レコード数は常に表示されるため保護範囲は透明で、要求した k が
   達成できない場合エンジンは出力ファイルを書かずに拒否します

---

## 📚 関連プロジェクト

- [Sieve Core](https://github.com/neguseatama/sieve-core) — 決定論的な構造集約・
  確信度評価の基盤エンジン
- [Sieve Lens](https://github.com/neguseatama/sieve-lens) — 不可視コンテンツ観測
  エンジン（文書向け）
- [Sieve Scope](https://github.com/neguseatama/sieve-scope) — コード類似度検知
  エンジン
- [Sieve Referee](https://github.com/neguseatama/sieve-referee) — テキスト
  パラフレーズ・盗用検知エンジン
- [Sieve Redact](https://github.com/neguseatama/sieve-redact) — 指定領域の
  決定論的マスキング・完全性検証エンジン（テキスト & PNG）
- [Sieve Order](https://github.com/neguseatama/sieve-order) — プロンプト表層
  構造観測エンジン（6-bit観測空間）
- [Sieve Crowd](https://github.com/neguseatama/sieve-crowd) — テーブルデータ
  匿名化・プライバシー保護エンジン

---

## 🎨 アプリケーションアイコン

<img src="assets/icon.png" width="96" alt="アプリケーションアイコン">

デザイン：[AURA_HYSTERICA](http://www.maroon.dti.ne.jp/clover-hp/)

---

## 📄 ライセンス

MIT License. 詳細は[LICENSE](LICENSE)を参照してください。

---

## 👤 作者

* **Kai IWASAKI**
