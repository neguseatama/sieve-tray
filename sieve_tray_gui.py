"""
Sieve Tray GUI - Minimal desktop front-end for sieve_tray.

Phase 1 prototype: pick a folder, run the scan in the background
(so the UI never freezes), and show the results in two tables.

This file only depends on sieve_tray.py (which in turn depends on
sieve_lens / sieve_scope being importable) and PySide6. It does not
yet have settings or history (that is Phase 2) - the goal here is
just to prove the GUI <-> core-engine wiring works end-to-end and
that the app can later be packaged with PyInstaller.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QPlainTextEdit, QFileDialog, QMessageBox, QHeaderView,
)
from PySide6.QtGui import QColor

from sieve_tray import run_scan, render, ScanResult


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sieve Tray")
        self.resize(900, 620)

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
        picker_row.addWidget(self.path_edit, stretch=1)
        picker_row.addWidget(browse_btn)
        picker_row.addWidget(self.run_btn)
        layout.addLayout(picker_row)

        # --- results tabs ---
        self.tabs = QTabWidget()
        self.doc_table = self._make_table(["ファイル", "マスク", "ステータス"])
        self.code_table = self._make_table(["ファイルA", "ファイルB", "マスク"])
        self.tabs.addTab(self.doc_table, "ドキュメント (0)")
        self.tabs.addTab(self.code_table, "コードペア (0)")
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

    def start_scan(self):
        input_dir = Path(self.path_edit.text())
        if not input_dir.is_dir():
            QMessageBox.warning(self, "エラー", "有効なフォルダを選択してください。")
            return

        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.log_view.clear()
        self._clear_tables()
        self.summary_label.setText("スキャン中...")

        self._thread = QThread(self)
        self._worker = ScanWorker(input_dir)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.log_view.appendPlainText)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _clear_tables(self):
        self.doc_table.setRowCount(0)
        self.code_table.setRowCount(0)
        self.tabs.setTabText(0, "ドキュメント (0)")
        self.tabs.setTabText(1, "コードペア (0)")

    def _on_finished(self, result: ScanResult):
        self._last_result = result
        self._populate_tables(result)
        flagged_docs = sum(1 for r in result.doc_results if r.get("flagged"))
        self.summary_label.setText(
            f"完了: {len(result.groups)}グループ / "
            f"文書 {len(result.doc_results)}件（うちフラグ {flagged_docs}件） / "
            f"コードペア {len(result.code_pairs)}件"
        )
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    def _on_failed(self, message: str):
        self.summary_label.setText("エラーが発生しました")
        QMessageBox.critical(self, "スキャンエラー", message)
        self.run_btn.setEnabled(True)

    def _populate_tables(self, result: ScanResult):
        self.doc_table.setRowCount(len(result.doc_results))
        for row, r in enumerate(result.doc_results):
            self.doc_table.setItem(row, 0, QTableWidgetItem(r["path"]))
            self.doc_table.setItem(row, 1, QTableWidgetItem(r["mask"]))
            status = "flagged" if r.get("flagged") else "clean"
            status_item = QTableWidgetItem(status)
            self.doc_table.setItem(row, 2, status_item)
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
        path, _ = QFileDialog.getSaveFileName(
            self, "レポートを保存", "report.html", "HTML Files (*.html)")
        if not path:
            return
        Path(path).write_text(render(self._last_result), encoding="utf-8")
        QMessageBox.information(self, "保存完了", f"{path} に書き出しました。")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
