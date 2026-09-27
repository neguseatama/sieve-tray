"""
Sieve Tray GUI - Desktop front-end for sieve_tray.

Phase 1: pick a folder, run the scan in the background, show results
in tables.
Phase 2: every completed scan is saved to local history (sqlite3, via
sieve_tray_storage.Storage) so past results can be revisited without
re-scanning, and a Settings dialog lets the user configure the
default export folder and how many past runs to keep.
Phase 3 (this revision): result tables are sortable (click a column
header) and filterable (text + "flagged only" for documents), and
double-clicking a row opens a detail dialog showing the per-axis
(H1-H7) observation states plus the underlying evidence/scores, so
"why was this flagged" is one click away instead of just a mask
string.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QPlainTextEdit, QFileDialog, QMessageBox, QHeaderView,
    QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QCheckBox,
)
from PySide6.QtGui import QColor

from sieve_tray import run_scan, render, ScanResult
from sieve_tray_storage import Storage, RunSummary


FLAGGED_BG = QColor("#fff5f5")

# Human-readable labels for the H1-H7 observation axes. sieve_lens and
# sieve_scope both use the "H1..H7" naming, but the axes mean
# different things in each engine (documents vs. code), so they get
# separate label dictionaries.
DOC_LABELS = {
    "H1": "Parseability（解析可能性）",
    "H2": "Zero-Width Density（ゼロ幅文字の密度）",
    "H3": "Bidi Controls（双方向制御文字）",
    "H4": "Format Concealment（書式による隠蔽）",
    "H5": "Out-of-Band Channel（帯域外チャンネル）",
    "H6": "Script Mixing（文字体系の混在）",
    "H7": "Contiguous Payload（連続するペイロード）",
}

CODE_LABELS = {
    "H1": "Parseability（構文解析可能性）",
    "H2": "AST Skeleton（AST構造の完全一致）",
    "H3": "Identifier Similarity（識別子の類似度）",
    "H4": "Cluster Safety（クラスタ内での昇格）",
    "H5": "g_POS（順序構造ハッシュの一致）",
    "H6": "g_CONST（定数集合の一致）",
    "H7": "g_FREQ（Bi-gram頻度の類似度）",
}


class ScanWorker(QObject):
    """Runs run_scan() on a background thread so the UI stays responsive."""

    progress = Signal(str)
    finished = Signal(object)   # ScanResult
    failed = Signal(str)

    def __init__(self, input_dir: Path):
        super().__init__()
        self.input_dir = input_dir

    def run(self):
        try:
            result = run_scan(self.input_dir, progress=self.progress.emit)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class SettingsDialog(QDialog):
    """Default export folder + how many past runs to keep in history."""

    def __init__(self, storage: Storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle("設定")

        self.export_dir_edit = QLineEdit(storage.get_setting("export_dir"))
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._browse_export_dir)
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_dir_edit, stretch=1)
        export_row.addWidget(browse_btn)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(0, 10000)
        self.retention_spin.setSpecialValueText("無制限")
        try:
            current = int(storage.get_setting("history_retention"))
        except ValueError:
            current = 50
        self.retention_spin.setValue(current)

        form = QFormLayout()
        form.addRow("レポートの保存先フォルダ:", export_row)
        form.addRow("履歴の保持件数（0で無制限）:", self.retention_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_export_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "保存先フォルダを選択", self.export_dir_edit.text())
        if path:
            self.export_dir_edit.setText(path)

    def save(self):
        self.storage.set_setting("export_dir", self.export_dir_edit.text())
        self.storage.set_setting(
            "history_retention", str(self.retention_spin.value()))
        self.storage.prune_history()


class DetailDialog(QDialog):
    """Shows why a document or code pair was flagged: the H1-H7 states
    plus whatever evidence/scores the engine recorded for them.

    This is deliberately just a reader (no interpretation added on
    top) - it surfaces exactly what sieve_lens/sieve_scope observed,
    consistent with those engines' own "observation, not judgment"
    stance.
    """

    def __init__(self, title: str, h_states: dict, labels: dict,
                 evidence: dict | None = None, scores: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 460)

        layout = QVBoxLayout(self)

        axis_table = QTableWidget(len(labels), 2)
        axis_table.setHorizontalHeaderLabels(["観測軸", "結果"])
        axis_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        axis_table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row, key in enumerate(labels):
            axis_table.setItem(row, 0, QTableWidgetItem(f"{key}: {labels[key]}"))
            state = h_states.get(key, 0)
            result_item = QTableWidgetItem("検出" if state else "検出なし")
            if state:
                result_item.setBackground(FLAGGED_BG)
            axis_table.setItem(row, 1, result_item)
        layout.addWidget(axis_table)

        lines: list[str] = []
        if evidence:
            for key in labels:
                items = [x for x in evidence.get(key, []) if x and x != "none"]
                if items:
                    lines.append(f"[{key}] {labels[key]}")
                    for it in items:
                        lines.append(f"  - {it}")
        if scores:
            lines.append("スコア:")
            for k, v in scores.items():
                lines.append(
                    f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

        detail_view = QPlainTextEdit()
        detail_view.setReadOnly(True)
        detail_view.setPlainText(
            "\n".join(lines) if lines else "追加の詳細情報はありません。")
        layout.addWidget(QLabel("詳細"))
        layout.addWidget(detail_view)

        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage | None = None):
        super().__init__()
        self.setWindowTitle("Sieve Tray")
        self.resize(1000, 700)

        self.storage = storage if storage is not None else Storage()

        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._last_result: ScanResult | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- folder picker row ---
        picker_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("スキャンするフォルダを選択してください")
        browse_btn = QPushButton("フォルダを選択...")
        browse_btn.clicked.connect(self.choose_folder)
        self.run_btn = QPushButton("スキャン実行")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.start_scan)
        settings_btn = QPushButton("設定...")
        settings_btn.clicked.connect(self.open_settings)
        picker_row.addWidget(self.path_edit, stretch=1)
        picker_row.addWidget(browse_btn)
        picker_row.addWidget(self.run_btn)
        picker_row.addWidget(settings_btn)
        layout.addLayout(picker_row)

        # --- results / history tabs ---
        self.tabs = QTabWidget()

        self.doc_table = self._make_table(["ファイル", "マスク", "ステータス"])
        self.doc_table.cellDoubleClicked.connect(self._on_doc_row_activated)
        self.doc_filter_edit = QLineEdit()
        self.doc_filter_edit.setPlaceholderText("ファイル名で絞り込み")
        self.doc_filter_edit.textChanged.connect(self._apply_doc_filter)
        self.doc_flagged_only_cb = QCheckBox("フラグのみ表示")
        self.doc_flagged_only_cb.stateChanged.connect(self._apply_doc_filter)
        self.tabs.addTab(
            self._make_filterable_tab(
                self.doc_table, self.doc_filter_edit, self.doc_flagged_only_cb),
            "ドキュメント (0)")

        self.code_table = self._make_table(["ファイルA", "ファイルB", "マスク"])
        self.code_table.cellDoubleClicked.connect(self._on_code_row_activated)
        self.code_filter_edit = QLineEdit()
        self.code_filter_edit.setPlaceholderText("ファイル名で絞り込み")
        self.code_filter_edit.textChanged.connect(self._apply_code_filter)
        self.tabs.addTab(
            self._make_filterable_tab(self.code_table, self.code_filter_edit),
            "コードペア (0)")

        self.history_table = self._make_table(
            ["日時 (UTC)", "フォルダ", "グループ", "文書(フラグ)", "コードペア"])
        self.history_table.cellDoubleClicked.connect(self._on_history_row_activated)
        self.tabs.addTab(self.history_table, "履歴")

        layout.addWidget(self.tabs, stretch=3)

        # --- log ---
        layout.addWidget(QLabel("ログ"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        layout.addWidget(self.log_view, stretch=1)

        # --- export row ---
        export_row = QHBoxLayout()
        self.summary_label = QLabel("")
        self.export_btn = QPushButton("HTMLレポートを書き出す")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_html)
        export_row.addWidget(self.summary_label, stretch=1)
        export_row.addWidget(self.export_btn)
        layout.addLayout(export_row)

        self._refresh_history_table()

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSortingEnabled(True)
        return table

    @staticmethod
    def _make_filterable_tab(table: QTableWidget, filter_edit: QLineEdit,
                              flagged_only_cb: QCheckBox | None = None) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 4, 0, 0)
        filter_row = QHBoxLayout()
        filter_row.addWidget(filter_edit, stretch=1)
        if flagged_only_cb is not None:
            filter_row.addWidget(flagged_only_cb)
        outer.addLayout(filter_row)
        outer.addWidget(table)
        return container

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "スキャンするフォルダを選択")
        if path:
            self.path_edit.setText(path)
            self.run_btn.setEnabled(True)

    def open_settings(self):
        dialog = SettingsDialog(self.storage, self)
        if dialog.exec() == QDialog.Accepted:
            dialog.save()
            self._refresh_history_table()

    def start_scan(self):
        input_dir = Path(self.path_edit.text())
        if not input_dir.is_dir():
            QMessageBox.warning(self, "エラー", "有効なフォルダを選択してください。")
            return

        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.log_view.clear()
        self.doc_filter_edit.clear()
        self.doc_flagged_only_cb.setChecked(False)
        self.code_filter_edit.clear()
        self._clear_result_tables()
        self.summary_label.setText("スキャン中...")

        self._thread = QThread(self)
        self._worker = ScanWorker(input_dir)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.log_view.appendPlainText)
        self._worker.finished.connect(
            lambda result: self._on_finished(input_dir, result))
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _clear_result_tables(self):
        self.doc_table.setRowCount(0)
        self.code_table.setRowCount(0)
        self.tabs.setTabText(0, "ドキュメント (0)")
        self.tabs.setTabText(1, "コードペア (0)")

    def _on_finished(self, input_dir: Path, result: ScanResult):
        self._last_result = result
        self._populate_result_tables(result)
        flagged_docs = sum(1 for r in result.doc_results if r.get("flagged"))
        self.summary_label.setText(
            f"完了: {len(result.groups)}グループ / "
            f"文書 {len(result.doc_results)}件（うちフラグ {flagged_docs}件） / "
            f"コードペア {len(result.code_pairs)}件"
        )
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

        # Phase 2: persist this run so it can be revisited later.
        self.storage.save_run(input_dir, result)
        self._refresh_history_table()

    def _on_failed(self, message: str):
        self.summary_label.setText("エラーが発生しました")
        QMessageBox.critical(self, "スキャンエラー", message)
        self.run_btn.setEnabled(True)

    def _populate_result_tables(self, result: ScanResult):
        self.doc_table.setSortingEnabled(False)
        self.doc_table.setRowCount(len(result.doc_results))
        for row, r in enumerate(result.doc_results):
            path_item = QTableWidgetItem(r["path"])
            path_item.setData(Qt.UserRole, r)
            self.doc_table.setItem(row, 0, path_item)
            self.doc_table.setItem(row, 1, QTableWidgetItem(r["mask"]))
            status = "flagged" if r.get("flagged") else "clean"
            self.doc_table.setItem(row, 2, QTableWidgetItem(status))
            if r.get("flagged"):
                for col in range(3):
                    self.doc_table.item(row, col).setBackground(FLAGGED_BG)
        self.tabs.setTabText(0, f"ドキュメント ({len(result.doc_results)})")
        self.doc_table.setSortingEnabled(True)
        self._apply_doc_filter()

        self.code_table.setSortingEnabled(False)
        self.code_table.setRowCount(len(result.code_pairs))
        for row, p in enumerate(result.code_pairs):
            a_item = QTableWidgetItem(p["a"])
            a_item.setData(Qt.UserRole, p)
            self.code_table.setItem(row, 0, a_item)
            self.code_table.setItem(row, 1, QTableWidgetItem(p["b"]))
            self.code_table.setItem(row, 2, QTableWidgetItem(p["mask"]))
            for col in range(3):
                self.code_table.item(row, col).setBackground(FLAGGED_BG)
        self.tabs.setTabText(1, f"コードペア ({len(result.code_pairs)})")
        self.code_table.setSortingEnabled(True)
        self._apply_code_filter()

    def export_html(self):
        if self._last_result is None:
            return
        default_dir = self.storage.get_setting("export_dir")
        default_path = str(Path(default_dir) / "report.html")
        path, _ = QFileDialog.getSaveFileName(
            self, "レポートを保存", default_path, "HTML Files (*.html)")
        if not path:
            return
        Path(path).write_text(render(self._last_result), encoding="utf-8")
        QMessageBox.information(self, "保存完了", f"{path} に書き出しました。")

    # ------------------------------------------------------------------
    # filtering
    # ------------------------------------------------------------------

    def _apply_doc_filter(self):
        text = self.doc_filter_edit.text().lower()
        flagged_only = self.doc_flagged_only_cb.isChecked()
        for row in range(self.doc_table.rowCount()):
            path_item = self.doc_table.item(row, 0)
            status_item = self.doc_table.item(row, 2)
            if path_item is None:
                continue
            matches_text = text in path_item.text().lower()
            matches_flag = (not flagged_only) or (
                status_item is not None and status_item.text() == "flagged")
            self.doc_table.setRowHidden(row, not (matches_text and matches_flag))

    def _apply_code_filter(self):
        text = self.code_filter_edit.text().lower()
        for row in range(self.code_table.rowCount()):
            a_item = self.code_table.item(row, 0)
            b_item = self.code_table.item(row, 1)
            if a_item is None or b_item is None:
                continue
            combined = (a_item.text() + " " + b_item.text()).lower()
            self.code_table.setRowHidden(row, text not in combined)

    # ------------------------------------------------------------------
    # detail dialogs
    # ------------------------------------------------------------------

    def _on_doc_row_activated(self, row: int, _column: int):
        item = self.doc_table.item(row, 0)
        if item is None:
            return
        r = item.data(Qt.UserRole)
        if not r:
            return
        dialog = DetailDialog(
            f"ドキュメントの詳細: {Path(r['path']).name}",
            r.get("h_states", {}), DOC_LABELS,
            evidence=r.get("evidence"), parent=self)
        dialog.exec()

    def _on_code_row_activated(self, row: int, _column: int):
        item = self.code_table.item(row, 0)
        if item is None:
            return
        p = item.data(Qt.UserRole)
        if not p:
            return
        dialog = DetailDialog(
            f"コードペアの詳細: {p['a']} / {p['b']}",
            p.get("h_states", {}), CODE_LABELS,
            scores=p.get("scores"), parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------

    def _refresh_history_table(self):
        runs = self.storage.list_runs()
        self.history_table.setSortingEnabled(False)
        self.history_table.setRowCount(len(runs))
        for row, r in enumerate(runs):
            self.history_table.setItem(row, 0, QTableWidgetItem(r.timestamp))
            self.history_table.setItem(row, 1, QTableWidgetItem(r.input_dir))
            self.history_table.setItem(
                row, 2, QTableWidgetItem(str(r.groups_count)))
            self.history_table.setItem(
                row, 3,
                QTableWidgetItem(f"{r.doc_count} ({r.flagged_doc_count})"))
            self.history_table.setItem(
                row, 4, QTableWidgetItem(str(r.pair_count)))
            # stash the run id on the row for double-click lookup
            self.history_table.item(row, 0).setData(Qt.UserRole, r.id)
        self.tabs.setTabText(2, f"履歴 ({len(runs)})")
        self.history_table.setSortingEnabled(True)

    def _on_history_row_activated(self, row: int, _column: int):
        item = self.history_table.item(row, 0)
        if item is None:
            return
        run_id = item.data(Qt.UserRole)
        result = self.storage.load_run(run_id)
        if result is None:
            QMessageBox.warning(self, "エラー", "この履歴は読み込めませんでした。")
            return
        self._last_result = result
        self._populate_result_tables(result)
        flagged_docs = sum(1 for r in result.doc_results if r.get("flagged"))
        self.summary_label.setText(
            f"履歴 #{run_id} を表示中: {len(result.groups)}グループ / "
            f"文書 {len(result.doc_results)}件（うちフラグ {flagged_docs}件） / "
            f"コードペア {len(result.code_pairs)}件"
        )
        self.export_btn.setEnabled(True)
        self.tabs.setCurrentIndex(0)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
