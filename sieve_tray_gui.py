"""
Sieve Tray GUI - Desktop front-end for sieve_tray.

Phase 1: pick a folder, run the scan in the background, show results
in tables.
Phase 2 (this revision): every completed scan is saved to local
history (sqlite3, via sieve_tray_storage.Storage) so past results can
be revisited without re-scanning, and a Settings dialog lets the user
configure the default export folder and how many past runs to keep.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QPlainTextEdit, QFileDialog, QMessageBox, QHeaderView,
    QDialog, QFormLayout, QSpinBox, QDialogButtonBox,
)
from PySide6.QtGui import QColor

from sieve_tray import run_scan, render, ScanResult
from sieve_tray_storage import Storage, RunSummary


FLAGGED_BG = QColor("#fff5f5")


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


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage | None = None):
        super().__init__()
        self.setWindowTitle("Sieve Tray")
        self.resize(960, 680)

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
        self.code_table = self._make_table(["ファイルA", "ファイルB", "マスク"])
        self.history_table = self._make_table(
            ["日時 (UTC)", "フォルダ", "グループ", "文書(フラグ)", "コードペア"])
        self.history_table.cellDoubleClicked.connect(self._on_history_row_activated)
        self.tabs.addTab(self.doc_table, "ドキュメント (0)")
        self.tabs.addTab(self.code_table, "コードペア (0)")
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
        return table

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
        self.doc_table.setRowCount(len(result.doc_results))
        for row, r in enumerate(result.doc_results):
            self.doc_table.setItem(row, 0, QTableWidgetItem(r["path"]))
            self.doc_table.setItem(row, 1, QTableWidgetItem(r["mask"]))
            status = "flagged" if r.get("flagged") else "clean"
            self.doc_table.setItem(row, 2, QTableWidgetItem(status))
            if r.get("flagged"):
                for col in range(3):
                    self.doc_table.item(row, col).setBackground(FLAGGED_BG)
        self.tabs.setTabText(0, f"ドキュメント ({len(result.doc_results)})")

        self.code_table.setRowCount(len(result.code_pairs))
        for row, p in enumerate(result.code_pairs):
            self.code_table.setItem(row, 0, QTableWidgetItem(p["a"]))
            self.code_table.setItem(row, 1, QTableWidgetItem(p["b"]))
            self.code_table.setItem(row, 2, QTableWidgetItem(p["mask"]))
            for col in range(3):
                self.code_table.item(row, col).setBackground(FLAGGED_BG)
        self.tabs.setTabText(1, f"コードペア ({len(result.code_pairs)})")

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
    # history
    # ------------------------------------------------------------------

    def _refresh_history_table(self):
        runs = self.storage.list_runs()
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
