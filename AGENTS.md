# AGENTS.md

公開面の文章: README・docs・CHANGELOG・Release 本文・パッケージの説明・コミットメッセージ・コードのコメント・テストの説明文は、利用者と開発者に向けた事実の短い文で書く。作業の経緯・内部の呼び名・日付つきの決定・開発環境の情報・絶対パス・テストの番号（README・docs・CHANGELOG）を書かない。CHANGELOG の版の節は、3〜5 項目の短文にする。`tools/check_public_text.py` が通ること。

## Build and test

- Python >= 3.9; the GUI lane needs PySide6 >= 6.5 and Pillow >= 10.0
  (`pip install "sieve-tray[gui]"`).
- The observation lane needs sieve-lens[pdf,html-css-full] >= 0.24.0
  (installed with the package) and pypdf.
- Test suite: `python -m pytest -v` (the GUI tests render offscreen:
  `QT_QPA_PLATFORM=offscreen`).
- Package build: `python -m build`.
- Public-text watch: `python tools/check_public_text.py`
  (runs in CI; one file: `--text FILE`).

## Working rules

1. **test-first**: 修正の前に、そのふるまいを固定するテストを書き、
   実装の前の赤と実装後の緑を確認する。既存のテストは、その版の変更で
   意味が変わらない限り修正しない。
2. **語彙の規律**: サブコマンド・CLI のフラグ・処理記録の鍵・終了符号・
   理由の語は、宣言済みの閉じた集合だけ。増やすときは CHANGELOG の
   最新の節で宣言してから入れる。
3. **処理記録の作法**: 処理記録は正準 JSON で、2 回の実行でバイト一致。
   入力そのものは書き換えない。出力は handoff/ と local/ だけ。
4. **版の作法**: 版は `sieve_tray.py` の `__version__` が唯一の静的な源。
   pyproject は dynamic attr で参照し、README ×2 の題字と CHANGELOG の
   最新の節と docs の登録表はそれと一致させる。版を固定するテストは
   `sieve_tray.__version__` との比較の形にする。
5. **CI**: 3 OS（ubuntu / windows / macos × 3.12、ubuntu 3.9 の下限）。
   環境に依存する失敗はテスト側を直し、製品の不具合は次の版で直す。
6. **公開の順序**: PR の merge → PyPI への公開（手動）→ tag →
   GitHub Release（`release.yml` が tag で起動し、CHANGELOG の最新の節を
   本文として点検のうえ資産を添付する）。同一版のタグ・資産の
   差し替えはしない。
7. **機械の見張り**: 公開面の点検は手作業に頼らず
   `tools/check_public_text.py` と baseline で守る。触った行の
   コメント/docstring は規則に合わせ、baseline は下げる方向で更新する。
