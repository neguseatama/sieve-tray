# ページの登録（PAGE_DEFS）

Sieve Tray 2.5.0（迷わない画面 の依頼 §3.1）。サイドバーの 21 行（ページ 16 + 見出し 5）は、
`sieve_tray_gui.py` のモジュール層にある **1 か所の登録表 `PAGE_DEFS`** だけで定義される。
サイドバーの行・「はじめに」のカード・`Ctrl/Cmd+1〜9`・`last_page` の復元・
ドロップの候補（純関数 `drop_candidates`）は、すべてこの表から作られる。
画面ごとの対照表は存在しない。

## 各定義の欄

| 欄 | 意味 |
|---|---|
| `kind` | `"page"`（選べる行）または `"head"`（見出し。選べない・矢印キーで飛ばされる） |
| `key` | 安定した識別子（`last_page` の保存値・テストのキー指定） |
| `name_key` / `tip_key` | i18n の表示名（`<key>_tab`）と 1 文のツールチップ（`<key>_tip`）のキー |
| `folder_input` / `folder_delivers` | フォルダのドロップに一致するか / そのとき入力欄に入るか（スキャン系 4 ページは `delivers` が偽＝開くだけ） |
| `file_exts` | ファイルのドロップに一致する拡張子。**エンジン側の定数の参照**（複製しない）。`None` は拡張子で内容を選ばないページ（rename・manifest）＝ファイルのドロップの候補から外れる。table_diff の `{".csv"}` は、エンジンの取り込み（`sieve_canon.run_table_diff`）が拡張子の定数を持たずカンマ区切り CSV を読むことの実物の写し（2026-11-23 裁定） |
| `file_delivers` | 一致したファイルが入力欄に入るか（crowd・clean だけ真） |

`start`・`draw`（名簿は補助欄）・`history`・`sanitize_history` はドロップの欄を持たず、
候補には現れない。

## ページを足すときの手順

1. `sieve_tray_i18n.py` に `<key>_tab` と `<key>_tip`（日英）を足す。
2. ページのウィジェットを `MainWindow.__init__` で作り、
   `self._register_page(key, widget)` で登録する（作る順序は自由）。
3. `PAGE_DEFS` の目的の位置に定義を 1 行足す（順序＝サイドバーの順序）。
   ドロップを受け付けるなら `folder_input` / `file_exts` / 各 `delivers` を
   エンジンの定数への参照で埋める。
4. 「はじめに」のカードに載せるなら、`START_CARDS` の該当カードの
   タプルに `key` を加える（カードを出さないページはそのままでよい）。
5. テストは必ずキー指定で書く（行番号で指定しない。§2-6 の作法）。
