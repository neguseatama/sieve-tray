"""
Sieve Tray GUI - Desktop front-end for sieve_tray.

Phase 1: pick a folder, run the scan in the background, show results
in tables.
Phase 2: local history (sqlite3) + Settings dialog (export folder,
history retention).
Phase 3: sortable/filterable result tables + a detail dialog showing
the per-axis (H1-H7) observation states and evidence/scores behind a
flag.
Phase 4: a third result category - Text Similarity, powered by
Sieve-Referee's pairwise paraphrase/plagiarism screening for plain-text
documents (.txt/.md) - plus a full English/Japanese UI switch (English
by default) via sieve_tray_i18n.
Phase 5 (this revision): an app icon (window/taskbar/dock icon, plus
the .ico/.icns used when packaging with PyInstaller) and a Help > About
dialog with version info and links to the other Sieve engines.
"""

import sys
from pathlib import Path
from multiprocessing import freeze_support

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QTabWidget, QPlainTextEdit, QFileDialog, QMessageBox, QHeaderView,
    QDialog, QFormLayout, QSpinBox, QDialogButtonBox, QCheckBox,
    QComboBox, QListWidget, QScrollArea,
)
from PySide6.QtGui import QColor, QIcon, QAction, QPainter, QPixmap

from sieve_tray import (
    run_scan,
    render,
    sanitize_file,
    sanitize_tree,
    ScanResult,
    TEXT_EXTS,
    __version__,
    make_region_spec,
    validate_region_spec,
    build_region_config,
    validate_rect,
)
from sieve_tray_storage import Storage, RunSummary
from sieve_tray_i18n import (
    tr, normalize_language, SUPPORTED_LANGUAGES, LANGUAGE_NAMES,
    DOC_AXIS_LABELS, CODE_AXIS_LABELS, TEXT_AXIS_LABELS,
)


def resource_path(relative: str) -> Path:
    """Resolve a bundled resource (e.g. an icon) both when running from
    source and when frozen into a PyInstaller executable, where files
    added via --add-data are extracted under sys._MEIPASS at runtime."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return base / relative


FLAGGED_BG = QColor("#fff5f5")
SIGNAL_BG = {
    "RED": QColor("#fff5f5"),
    "YELLOW": QColor("#fffbea"),
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


class SanitizeWorker(QObject):
    """Runs sanitize_tree() on a background thread (same pattern as
    ScanWorker) so the UI stays responsive on large folders."""

    progress = Signal(str)
    finished = Signal(object)   # sanitize_tree summary dict
    failed = Signal(str)

    def __init__(self, input_dir: Path, config_path: Path, out_root: Path):
        super().__init__()
        self.input_dir = input_dir
        self.config_path = config_path
        self.out_root = out_root

    def run(self):
        try:
            summary = sanitize_tree(self.input_dir, self.config_path,
                                    self.out_root, progress=self.progress.emit)
            self.finished.emit(summary)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")

def normalize_rect(x1, y1, x2, y2):
    """Normalize two drag endpoints into an x/y/w/h dict (direction-
    agnostic)."""
    return {"x": min(x1, x2), "y": min(y1, y2),
            "w": abs(x2 - x1), "h": abs(y2 - y1)}


def clamp_point(x, y, img_w, img_h):
    """Clamp a pixel coordinate into the 0..img_w-1 / 0..img_h-1 bounds."""
    return (max(0, min(x, img_w - 1)), max(0, min(y, img_h - 1)))


def image_output_paths(image_path, export_dir):
    """Build the auto config and output paths for one PNG sanitize run."""
    src = Path(image_path)
    return (Path(export_dir) / (src.stem + "_regions.txt"),
            Path(export_dir) / (src.stem + "_sanitized.png"))


class ImageCanvas(QLabel):
    """1:1 image view with translucent region overlays and drag-to-select.

    Canvas coordinates are pixel coordinates (the 1:1 display removes
    coordinate mapping from the risk surface). A completed drag emits
    region_selected(x, y, w, h); zero-area drags are ignored because the
    engine rejects zero-area regions (exit code 2). Overlay geometry is
    clamped to the image bounds.
    """

    OVERLAY_FILL = QColor(255, 0, 0, 128)

    region_selected = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._regions = []
        self._drag_origin = None
        self._drag_current = None

    def set_image(self, pixmap):
        self._pixmap = pixmap
        self.setPixmap(pixmap)
        self._regions = []
        self._drag_origin = None
        self._drag_current = None
        self.setFixedSize(pixmap.size())
        self.update()

    def set_regions(self, regions):
        self._regions = list(regions)
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and self._pixmap:
            pos = ev.position().toPoint()
            self._drag_origin = clamp_point(pos.x(), pos.y(),
                                            self._pixmap.width(),
                                            self._pixmap.height())
            self._drag_current = self._drag_origin
            self.update()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_origin is not None and self._pixmap:
            pos = ev.position().toPoint()
            self._drag_current = clamp_point(pos.x(), pos.y(),
                                             self._pixmap.width(),
                                             self._pixmap.height())
            self.update()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if (ev.button() == Qt.MouseButton.LeftButton
                and self._drag_origin is not None and self._pixmap):
            pos = ev.position().toPoint()
            cur = clamp_point(pos.x(), pos.y(), self._pixmap.width(),
                              self._pixmap.height())
            rect = normalize_rect(self._drag_origin[0], self._drag_origin[1],
                                  cur[0], cur[1])
            self._drag_origin = None
            self._drag_current = None
            self.update()
            if rect["w"] > 0 and rect["h"] > 0:
                self.region_selected.emit(rect["x"], rect["y"],
                                          rect["w"], rect["h"])
        super().mouseReleaseEvent(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self._pixmap:
            return
        p = QPainter(self)
        for r in self._regions:
            p.fillRect(r["x"], r["y"], r["w"], r["h"], self.OVERLAY_FILL)
        if self._drag_origin is not None and self._drag_current is not None:
            rect = normalize_rect(self._drag_origin[0], self._drag_origin[1],
                                  self._drag_current[0],
                                  self._drag_current[1])
            if rect["w"] > 0 and rect["h"] > 0:
                p.fillRect(rect["x"], rect["y"], rect["w"], rect["h"],
                           self.OVERLAY_FILL)
        p.end()

class ImageRegionEditorDialog(QDialog):
    """Drag regions on the source PNG, list them, and export a config.

    Region addition validates through the tray core helpers (engine
    grammar via validate_region_spec, bounds via validate_rect), so
    invalid regions are rejected before any engine run. The preview is
    a synchronous real engine run into a temp output (no hand-drawn
    imitation) and reports the receipt verdict honestly: pixel
    integrity is the measured value; byte integrity is not applicable
    to PNG re-encoding.
    """

    def __init__(self, image_path, lang, parent=None):
        super().__init__(parent)
        self._ = lambda key, **kw: tr(lang, key, **kw)
        self._input_path = Path(image_path)
        from PIL import Image as PILImage

        with PILImage.open(self._input_path) as im:
            self._img_w, self._img_h = im.size
        self._specs = []
        self._rects = []
        self._preview_result = None
        self._saved_config_path = None

        self.setWindowTitle(self._("image_editor_title"))

        self.canvas = ImageCanvas()
        self.canvas.set_image(QPixmap(str(self._input_path)))
        self.canvas.region_selected.connect(self._on_region_selected)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)

        import sieve_redact

        self.mode_combo = QComboBox()
        for mode in sieve_redact.REGION_MODES:
            self.mode_combo.addItem(mode)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

        self.arg_edit = QLineEdit()
        self.arg_edit.setEnabled(False)

        self.spec_list = QListWidget()

        delete_btn = QPushButton(self._("image_delete_button"))
        delete_btn.clicked.connect(self.delete_selected_region)
        save_btn = QPushButton(self._("image_save_config_button"))
        save_btn.clicked.connect(self.save_config)
        preview_btn = QPushButton(self._("image_preview_button"))
        preview_btn.clicked.connect(self.run_preview)

        self.integrity_label = QLabel("")
        self.preview_label = QLabel()

        form = QFormLayout()
        form.addRow(self._("image_mode_label"), self.mode_combo)
        form.addRow(self._("image_arg_label"), self.arg_edit)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(self.spec_list)
        right.addWidget(delete_btn)
        right.addWidget(save_btn)
        right.addWidget(preview_btn)
        right.addWidget(self.integrity_label)
        right.addWidget(self.preview_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self._("ok_button"))
        buttons.button(QDialogButtonBox.Cancel).setText(
            self._("cancel_button"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        cols = QHBoxLayout()
        cols.addWidget(scroll, stretch=3)
        cols.addLayout(right, stretch=2)
        outer = QVBoxLayout(self)
        outer.addLayout(cols)
        outer.addWidget(buttons)

    def _on_mode_changed(self, mode):
        self.arg_edit.setEnabled(mode not in ("delete", "noise"))

    def _on_region_selected(self, x, y, w, h):
        mode = self.mode_combo.currentText()
        arg = self.arg_edit.text().strip()
        try:
            self.add_region(x, y, w, h, mode, arg or None)
        except ValueError as exc:
            QMessageBox.warning(self, self._("image_invalid_arg"), str(exc))

    def add_region(self, x, y, w, h, mode, arg=None):
        spec = make_region_spec(x, y, w, h, mode, arg)
        rect = validate_region_spec(spec)
        if not validate_rect(rect, self._img_w, self._img_h):
            raise ValueError("region outside the image bounds: %s" % spec)
        self._specs.append(spec)
        self._rects.append(rect)
        self._refresh()
        return spec

    def regions(self):
        return list(self._specs)

    def config_text(self):
        return build_region_config(self._specs)

    def delete_selected_region(self):
        row = self.spec_list.currentRow()
        if 0 <= row < len(self._specs):
            del self._specs[row]
            del self._rects[row]
            self._refresh()

    def save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._("image_save_config_button"), "",
            "Redact config (*.txt)")
        if not path:
            return
        Path(path).write_text(self.config_text(), encoding="utf-8")
        self._saved_config_path = Path(path)

    def run_preview(self):
        import tempfile

        import sieve_tray as core

        if not self._specs:
            self._preview_result = None
            self.preview_label.setPixmap(QPixmap())
            self.integrity_label.setText("")
            return
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "regions.txt"
            cfg_path.write_text(self.config_text(), encoding="utf-8")
            out_path = Path(td) / "preview.png"
            result = core.sanitize_file(self._input_path, cfg_path,
                                        out_path)
            preview_pm = QPixmap(str(out_path)) if result["ok"] else None
        self._preview_result = result
        if result["ok"] and result["integrity_verified"] and preview_pm:
            self.preview_label.setPixmap(preview_pm)
            self.integrity_label.setText(
                self._("image_integrity_measured") + " / "
                + self._("image_byte_not_applicable"))
        else:
            self.preview_label.setPixmap(QPixmap())
            self.integrity_label.setText(
                self._("image_preview_failed", rc=result["rc"]))

    def preview_result(self):
        return self._preview_result

    def saved_config_path(self):
        return self._saved_config_path

    def _refresh(self):
        self.spec_list.clear()
        self.spec_list.addItems(self._specs)
        self.canvas.set_regions(self._rects)


class SettingsDialog(QDialog):
    """Default export folder, history retention, and UI language."""

    def __init__(self, storage: Storage, lang: str, parent=None):
        super().__init__(parent)
        self.storage = storage
        self._ = lambda key, **kw: tr(lang, key, **kw)
        self.setWindowTitle(self._("settings_title"))

        self.export_dir_edit = QLineEdit(storage.get_setting("export_dir"))
        browse_btn = QPushButton(self._("settings_browse"))
        browse_btn.clicked.connect(self._browse_export_dir)
        export_row = QHBoxLayout()
        export_row.addWidget(self.export_dir_edit, stretch=1)
        export_row.addWidget(browse_btn)

        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(0, 10000)
        self.retention_spin.setSpecialValueText(
            self._("settings_retention_unlimited"))
        try:
            current = int(storage.get_setting("history_retention"))
        except ValueError:
            current = 50
        self.retention_spin.setValue(current)

        self.language_combo = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self.language_combo.addItem(LANGUAGE_NAMES[code], userData=code)
        current_lang = normalize_language(storage.get_setting("language"))
        self.language_combo.setCurrentIndex(SUPPORTED_LANGUAGES.index(current_lang))

        form = QFormLayout()
        form.addRow(self._("settings_export_dir"), export_row)
        form.addRow(self._("settings_retention"), self.retention_spin)
        form.addRow(
            f"{self._('settings_language')} {self._('settings_language_note')}",
            self.language_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self._("ok_button"))
        buttons.button(QDialogButtonBox.Cancel).setText(self._("cancel_button"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_export_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, self._("settings_browse_dialog_title"),
            self.export_dir_edit.text())
        if path:
            self.export_dir_edit.setText(path)

    def selected_language(self) -> str:
        return self.language_combo.currentData()

    def save(self):
        self.storage.set_setting("export_dir", self.export_dir_edit.text())
        self.storage.set_setting(
            "history_retention", str(self.retention_spin.value()))
        self.storage.set_setting("language", self.selected_language())
        self.storage.prune_history()


class DetailDialog(QDialog):
    """Shows why a document, code pair, or text pair was flagged: the
    H1-H7 (or H1-H4) states plus whatever evidence/scores/reason the
    engine recorded for them.

    This is deliberately just a reader (no interpretation added on
    top) - it surfaces exactly what the underlying Sieve engine
    observed, consistent with those engines' own "observation, not
    judgment" stance.
    """

    def __init__(self, title: str, h_states: dict, labels: dict, lang: str,
                 evidence: dict | None = None, scores: dict | None = None,
                 reason: str | None = None, parent=None):
        super().__init__(parent)
        self._ = lambda key, **kw: tr(lang, key, **kw)
        self.setWindowTitle(title)
        self.resize(560, 480)

        layout = QVBoxLayout(self)

        axis_table = QTableWidget(len(labels), 2)
        axis_table.setHorizontalHeaderLabels(
            [self._("detail_axis_header"), self._("detail_result_header")])
        axis_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        axis_table.setEditTriggers(QTableWidget.NoEditTriggers)
        for row, key in enumerate(labels):
            axis_table.setItem(row, 0, QTableWidgetItem(f"{key}: {labels[key]}"))
            state = h_states.get(key, 0)
            result_item = QTableWidgetItem(
                self._("detail_detected") if state
                else self._("detail_not_detected"))
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
        if reason:
            lines.append(self._("detail_reason_label"))
            lines.append(f"  {reason}")
        if scores:
            lines.append(self._("detail_scores_label"))
            for k, v in scores.items():
                lines.append(
                    f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")

        detail_view = QPlainTextEdit()
        detail_view.setReadOnly(True)
        detail_view.setPlainText(
            "\n".join(lines) if lines else self._("detail_no_extra_info"))
        layout.addWidget(QLabel(self._("detail_section_label")))
        layout.addWidget(detail_view)

        close_btn = QPushButton(self._("close_button"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class AboutDialog(QDialog):
    """Version, engine credits, and license - opened from Help > About."""

    ENGINE_LINKS = [
        ("Sieve Lens", "https://github.com/neguseatama/sieve-lens"),
        ("Sieve Scope", "https://github.com/neguseatama/sieve-scope"),
        ("Sieve Referee", "https://github.com/neguseatama/sieve-referee"),
    ]

    def __init__(self, lang: str, parent=None):
        super().__init__(parent)
        self._ = lambda key, **kw: tr(lang, key, **kw)
        self.setWindowTitle(self._("about_title"))
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_path = resource_path("assets/icon.png")
        if icon_path.exists():
            icon_label.setPixmap(QIcon(str(icon_path)).pixmap(64, 64))
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel(f"<b>Sieve Tray</b>")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        version_label = QLabel(self._("about_version", version=__version__))
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        tagline_label = QLabel(self._("about_tagline"))
        tagline_label.setAlignment(Qt.AlignCenter)
        tagline_label.setWordWrap(True)
        layout.addWidget(tagline_label)

        layout.addWidget(QLabel(self._("about_engines_label")))
        links_html = "<br>".join(
            f'<a href="{url}">{name}</a>' for name, url in self.ENGINE_LINKS)
        links_label = QLabel(links_html)
        links_label.setOpenExternalLinks(True)
        layout.addWidget(links_label)

        license_label = QLabel(self._("about_license"))
        license_label.setAlignment(Qt.AlignCenter)
        license_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(license_label)

        close_btn = QPushButton(self._("close_button"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage | None = None):
        super().__init__()
        self.storage = storage if storage is not None else Storage()
        self.lang = normalize_language(self.storage.get_setting("language"))
        self._ = lambda key, **kw: tr(self.lang, key, **kw)

        self.setWindowTitle(self._("window_title"))
        self.resize(1050, 720)

        icon_path = resource_path("assets/icon.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        help_menu = self.menuBar().addMenu(self._("help_menu"))
        about_action = QAction(self._("about_action"), self)
        about_action.setMenuRole(QAction.AboutRole)
        about_action.triggered.connect(self.open_about)
        help_menu.addAction(about_action)

        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._last_result: ScanResult | None = None
        self._scan_running = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- folder picker row ---
        picker_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText(self._("select_folder_placeholder"))
        browse_btn = QPushButton(self._("browse_folder"))
        browse_btn.clicked.connect(self.choose_folder)
        self.run_btn = QPushButton(self._("run_scan"))
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self.start_scan)
        settings_btn = QPushButton(self._("settings_button"))
        settings_btn.clicked.connect(self.open_settings)
        self.sanitize_btn = QPushButton(self._("sanitize_button"))
        self.sanitize_btn.setEnabled(False)
        self.sanitize_btn.clicked.connect(self.sanitize_folder)
        self.sanitize_image_btn = QPushButton(
            self._("sanitize_image_button"))
        self.sanitize_image_btn.setEnabled(True)
        self.sanitize_image_btn.clicked.connect(self.sanitize_image)
        picker_row.addWidget(self.path_edit, stretch=1)
        picker_row.addWidget(browse_btn)
        picker_row.addWidget(self.run_btn)
        picker_row.addWidget(self.sanitize_btn)
        picker_row.addWidget(self.sanitize_image_btn)
        picker_row.addWidget(settings_btn)
        layout.addLayout(picker_row)

        # --- results / history tabs ---
        self.tabs = QTabWidget()

        self.doc_table = self._make_table(
            [self._("doc_header_file"), self._("doc_header_mask"),
             self._("doc_header_status")])
        self.doc_table.cellDoubleClicked.connect(self._on_doc_row_activated)
        self.doc_filter_edit = QLineEdit()
        self.doc_filter_edit.setPlaceholderText(self._("filter_by_filename"))
        self.doc_filter_edit.textChanged.connect(self._apply_doc_filter)
        self.doc_flagged_only_cb = QCheckBox(self._("flagged_only"))
        self.doc_flagged_only_cb.stateChanged.connect(self._apply_doc_filter)
        self._doc_tab_index = self.tabs.addTab(
            self._make_filterable_tab(
                self.doc_table, self.doc_filter_edit, self.doc_flagged_only_cb),
            self._("doc_tab", n=0))

        self.code_table = self._make_table(
            [self._("code_header_a"), self._("code_header_b"),
             self._("code_header_mask")])
        self.code_table.cellDoubleClicked.connect(self._on_code_row_activated)
        self.code_filter_edit = QLineEdit()
        self.code_filter_edit.setPlaceholderText(self._("filter_by_filename"))
        self.code_filter_edit.textChanged.connect(self._apply_code_filter)
        self._code_tab_index = self.tabs.addTab(
            self._make_filterable_tab(self.code_table, self.code_filter_edit),
            self._("code_tab", n=0))

        self.text_table = self._make_table(
            [self._("text_header_a"), self._("text_header_b"),
             self._("text_header_signal"), self._("text_header_pattern")])
        self.text_table.cellDoubleClicked.connect(self._on_text_row_activated)
        self.text_filter_edit = QLineEdit()
        self.text_filter_edit.setPlaceholderText(self._("filter_by_filename"))
        self.text_filter_edit.textChanged.connect(self._apply_text_filter)
        self._text_tab_index = self.tabs.addTab(
            self._make_filterable_tab(self.text_table, self.text_filter_edit),
            self._("text_tab", n=0))

        self.history_table = self._make_table([
            self._("history_header_timestamp"), self._("history_header_folder"),
            self._("history_header_groups"), self._("history_header_docs"),
            self._("history_header_code_pairs"), self._("history_header_text_pairs"),
        ])
        self.history_table.cellDoubleClicked.connect(self._on_history_row_activated)
        self._history_tab_index = self.tabs.addTab(
            self.history_table, self._("history_tab", n=0))

        layout.addWidget(self.tabs, stretch=3)

        # --- log ---
        layout.addWidget(QLabel(self._("log_label")))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        layout.addWidget(self.log_view, stretch=1)

        # --- export row ---
        export_row = QHBoxLayout()
        self.summary_label = QLabel("")
        self.export_btn = QPushButton(self._("export_html"))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_html)
        export_row.addWidget(self.summary_label, stretch=1)
        export_row.addWidget(self.export_btn)
        layout.addLayout(export_row)

        self._refresh_history_table()

    def closeEvent(self, event):
        # Defensive: if a scan is still running in the background when the
        # window is closed, make sure the thread fully winds down before
        # this window (and its thread reference) is torn down. Destroying
        # a QThread object while it is still marked as running is
        # undefined behavior in Qt/PySide and can crash the app. We track
        # this with a plain Python flag rather than re-querying the
        # QThread object here, since by this point Qt may already have
        # deleted it via deleteLater (finished -> deleteLater, wired in
        # start_scan()) if the scan finished normally long ago.
        if self._scan_running and self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
        if getattr(self, "_sanitize_thread", None) is not None:
            self._sanitize_thread.quit()
            self._sanitize_thread.wait(5000)
        super().closeEvent(event)

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

    def sanitize_folder(self):
        input_dir = Path(self.path_edit.text())
        if not input_dir.is_dir():
            QMessageBox.warning(
                self, self._("error_title"), self._("error_select_valid_folder"))
            return
        config_path, _ = QFileDialog.getOpenFileName(
            self, self._("sanitize_config_title"), "",
            "Text Files (*.txt);;All Files (*)")
        if not config_path:
            return
        export_dir = Path(self.storage.get_setting("export_dir"))
        out_root = export_dir / (input_dir.name + "_sanitized")

        self.run_btn.setEnabled(False)
        self.sanitize_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.summary_label.setText(self._("sanitize_running"))
        self._sanitize_input_dir = input_dir
        self._sanitize_config_path = Path(config_path)
        self._sanitize_out_root = out_root
        self._sanitize_thread = QThread(self)
        self._sanitize_worker = SanitizeWorker(
            input_dir, Path(config_path), out_root)
        self._sanitize_worker.moveToThread(self._sanitize_thread)
        self._sanitize_thread.started.connect(self._sanitize_worker.run)
        self._sanitize_worker.progress.connect(self.log_view.appendPlainText)
        self._sanitize_worker.finished.connect(
            lambda summary: self._on_sanitize_finished(summary))
        self._sanitize_worker.failed.connect(self._on_sanitize_failed)
        self._sanitize_worker.finished.connect(self._sanitize_thread.quit)
        self._sanitize_worker.failed.connect(self._sanitize_thread.quit)
        self._sanitize_thread.finished.connect(self._sanitize_thread.deleteLater)
        self._sanitize_thread.start()

    def _on_sanitize_finished(self, summary):
        if summary["skipped"]:
            self.summary_label.setText(self._("sanitize_skipped"))
            message = self._("sanitize_skipped")
        else:
            masked = summary["masked_total"]
            integrity_bad = summary["integrity_bad_count"]
            if integrity_bad:
                integrity = self._("sanitize_integrity_fail", k=integrity_bad)
            else:
                integrity = self._("sanitize_integrity_ok")
            message = self._("sanitize_done_label", n=summary["n_files"],
                             ok=summary["ok_count"], masked=masked,
                             integrity=integrity)
            if summary["failed"]:
                listing = "\n".join(str(rel) for rel, _ in summary["failed"])
                message += self._("sanitize_failed_files", files=listing)
            self.summary_label.setText(message)
        self.run_btn.setEnabled(True)
        self.sanitize_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        if not summary["skipped"]:
            self.storage.save_sanitization(
                summary, self._sanitize_input_dir,
                self._sanitize_config_path, self._sanitize_out_root)
        QMessageBox.information(self, self._("sanitize_done_title"), message)

    def _on_sanitize_failed(self, message: str):
        self.summary_label.setText(message)
        self.run_btn.setEnabled(True)
        self.sanitize_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        QMessageBox.critical(self, self._("error_title"), message)

    def sanitize_image(self):
        image_path, _ = QFileDialog.getOpenFileName(
            self, self._("sanitize_image_button"), "",
            "PNG Images (*.png)")
        if not image_path:
            return
        editor = ImageRegionEditorDialog(image_path, self.lang, parent=self)
        if editor.exec() != QDialog.Accepted:
            return
        export_dir = Path(self.storage.get_setting("export_dir"))
        cfg_path, out_path = image_output_paths(image_path, export_dir)
        saved = editor.saved_config_path()
        if saved is None:
            cfg_path.write_text(editor.config_text(), encoding="utf-8")
        else:
            cfg_path = saved
        result = self.run_image_sanitize(image_path, cfg_path, out_path)
        if result["ok"]:
            message = (
                self._("sanitize_done_label", n=1, ok=1,
                       masked=result["masked_count"],
                       integrity=self._("image_integrity_measured"))
                + "\n" + self._("image_byte_not_applicable"))
        else:
            message = self._("sanitize_image_failed", rc=result["rc"])
        self.summary_label.setText(message)
        QMessageBox.information(self, self._("sanitize_done_title"), message)

    def run_image_sanitize(self, image_path, config_path, output_path):
        """Run one PNG through the engine synchronously and record history.

        The receipt lands next to the output (sanitize_tree convention);
        the history row is saved unless the engine is unavailable
        (folder-flow convention: failures are recorded too).
        """
        receipt_path = output_path.with_name(
            output_path.name + ".receipt.json")
        result = sanitize_file(Path(image_path), Path(config_path),
                               output_path, receipt_path=receipt_path)
        summary = {
            "n_files": 1,
            "ok_count": 1 if result["ok"] else 0,
            "masked_total": result["masked_count"],
            "integrity_bad_count": 0 if result["integrity_verified"] else 1,
            "failed": [] if result["ok"] else [(str(image_path),
                                                result["rc"])],
            "skipped": bool(result["skipped"]),
        }
        if not summary["skipped"]:
            self.storage.save_sanitization(
                summary, Path(image_path).parent, Path(config_path),
                Path(output_path).parent)
        return result

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, self._("choose_folder_dialog_title"))
        if path:
            self.path_edit.setText(path)
            self.run_btn.setEnabled(True)
            self.sanitize_btn.setEnabled(True)

    def open_settings(self):
        dialog = SettingsDialog(self.storage, self.lang, self)
        if dialog.exec() == QDialog.Accepted:
            dialog.save()
            self._refresh_history_table()

    def open_about(self):
        AboutDialog(self.lang, self).exec()

    def start_scan(self):
        input_dir = Path(self.path_edit.text())
        if not input_dir.is_dir():
            QMessageBox.warning(
                self, self._("error_title"), self._("error_select_valid_folder"))
            return

        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.log_view.clear()
        self.doc_filter_edit.clear()
        self.doc_flagged_only_cb.setChecked(False)
        self.code_filter_edit.clear()
        self.text_filter_edit.clear()
        self._clear_result_tables()
        self.summary_label.setText(self._("scanning"))

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

        self._scan_running = True
        self._thread.start()

    def _clear_result_tables(self):
        self.doc_table.setRowCount(0)
        self.code_table.setRowCount(0)
        self.text_table.setRowCount(0)
        self.tabs.setTabText(self._doc_tab_index, self._("doc_tab", n=0))
        self.tabs.setTabText(self._code_tab_index, self._("code_tab", n=0))
        self.tabs.setTabText(self._text_tab_index, self._("text_tab", n=0))

    def _on_finished(self, input_dir: Path, result: ScanResult):
        self._scan_running = False
        self._last_result = result
        self._populate_result_tables(result)
        flagged_docs = sum(1 for r in result.doc_results if r.get("flagged"))
        self.summary_label.setText(self._(
            "summary_done", groups=len(result.groups),
            docs=len(result.doc_results), flagged=flagged_docs,
            pairs=len(result.code_pairs), tpairs=len(result.text_pairs)))
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

        # Phase 2: persist this run so it can be revisited later.
        self.storage.save_run(input_dir, result)
        self._refresh_history_table()

    def _on_failed(self, message: str):
        self._scan_running = False
        self.summary_label.setText(self._("summary_error"))
        QMessageBox.critical(self, self._("scan_error_title"), message)
        self.run_btn.setEnabled(True)

    def _populate_result_tables(self, result: ScanResult):
        status_flagged = self._("status_flagged")
        status_clean = self._("status_clean")

        self.doc_table.setSortingEnabled(False)
        self.doc_table.setRowCount(len(result.doc_results))
        for row, r in enumerate(result.doc_results):
            path_item = QTableWidgetItem(r["path"])
            path_item.setData(Qt.UserRole, r)
            self.doc_table.setItem(row, 0, path_item)
            self.doc_table.setItem(row, 1, QTableWidgetItem(r["mask"]))
            status = status_flagged if r.get("flagged") else status_clean
            self.doc_table.setItem(row, 2, QTableWidgetItem(status))
            if r.get("flagged"):
                for col in range(3):
                    self.doc_table.item(row, col).setBackground(FLAGGED_BG)
        self.tabs.setTabText(
            self._doc_tab_index, self._("doc_tab", n=len(result.doc_results)))
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
        self.tabs.setTabText(
            self._code_tab_index, self._("code_tab", n=len(result.code_pairs)))
        self.code_table.setSortingEnabled(True)
        self._apply_code_filter()

        self.text_table.setSortingEnabled(False)
        self.text_table.setRowCount(len(result.text_pairs))
        for row, p in enumerate(result.text_pairs):
            a_item = QTableWidgetItem(p["a"])
            a_item.setData(Qt.UserRole, p)
            self.text_table.setItem(row, 0, a_item)
            self.text_table.setItem(row, 1, QTableWidgetItem(p["b"]))
            self.text_table.setItem(row, 2, QTableWidgetItem(p["signal"]))
            self.text_table.setItem(row, 3, QTableWidgetItem(p["pattern_name"]))
            bg = SIGNAL_BG.get(p["signal"], FLAGGED_BG)
            for col in range(4):
                self.text_table.item(row, col).setBackground(bg)
        self.tabs.setTabText(
            self._text_tab_index, self._("text_tab", n=len(result.text_pairs)))
        self.text_table.setSortingEnabled(True)
        self._apply_text_filter()

    def export_html(self):
        if self._last_result is None:
            return
        default_dir = self.storage.get_setting("export_dir")
        default_path = str(Path(default_dir) / "report.html")
        path, _ = QFileDialog.getSaveFileName(
            self, self._("save_report_dialog_title"), default_path,
            "HTML Files (*.html)")
        if not path:
            return
        Path(path).write_text(render(self._last_result), encoding="utf-8")
        QMessageBox.information(
            self, self._("save_complete_title"),
            self._("save_complete_message", path=path))

    # ------------------------------------------------------------------
    # filtering
    # ------------------------------------------------------------------

    def _apply_doc_filter(self):
        text = self.doc_filter_edit.text().lower()
        flagged_only = self.doc_flagged_only_cb.isChecked()
        status_flagged = self._("status_flagged")
        for row in range(self.doc_table.rowCount()):
            path_item = self.doc_table.item(row, 0)
            status_item = self.doc_table.item(row, 2)
            if path_item is None:
                continue
            matches_text = text in path_item.text().lower()
            matches_flag = (not flagged_only) or (
                status_item is not None and status_item.text() == status_flagged)
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

    def _apply_text_filter(self):
        text = self.text_filter_edit.text().lower()
        for row in range(self.text_table.rowCount()):
            a_item = self.text_table.item(row, 0)
            b_item = self.text_table.item(row, 1)
            if a_item is None or b_item is None:
                continue
            combined = (a_item.text() + " " + b_item.text()).lower()
            self.text_table.setRowHidden(row, text not in combined)

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
            self._("detail_doc_title", name=Path(r["path"]).name),
            r.get("h_states", {}), DOC_AXIS_LABELS[self.lang], self.lang,
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
            self._("detail_code_title", a=p["a"], b=p["b"]),
            p.get("h_states", {}), CODE_AXIS_LABELS[self.lang], self.lang,
            scores=p.get("scores"), parent=self)
        dialog.exec()

    def _on_text_row_activated(self, row: int, _column: int):
        item = self.text_table.item(row, 0)
        if item is None:
            return
        p = item.data(Qt.UserRole)
        if not p:
            return
        dialog = DetailDialog(
            self._("detail_text_title", a=p["a"], b=p["b"]),
            p.get("h_states", {}), TEXT_AXIS_LABELS[self.lang], self.lang,
            scores=p.get("scores"), reason=p.get("reason"), parent=self)
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
            self.history_table.setItem(
                row, 5, QTableWidgetItem(str(r.text_pair_count)))
            # stash the run id on the row for double-click lookup
            self.history_table.item(row, 0).setData(Qt.UserRole, r.id)
        self.tabs.setTabText(
            self._history_tab_index, self._("history_tab", n=len(runs)))
        self.history_table.setSortingEnabled(True)

    def _on_history_row_activated(self, row: int, _column: int):
        item = self.history_table.item(row, 0)
        if item is None:
            return
        run_id = item.data(Qt.UserRole)
        result = self.storage.load_run(run_id)
        if result is None:
            QMessageBox.warning(
                self, self._("error_title"), self._("history_load_error"))
            return
        self._last_result = result
        self._populate_result_tables(result)
        flagged_docs = sum(1 for r in result.doc_results if r.get("flagged"))
        self.summary_label.setText(self._(
            "summary_history", run_id=run_id, groups=len(result.groups),
            docs=len(result.doc_results), flagged=flagged_docs,
            pairs=len(result.code_pairs), tpairs=len(result.text_pairs)))
        self.export_btn.setEnabled(True)
        self.tabs.setCurrentIndex(self._doc_tab_index)


def main():
    app = QApplication(sys.argv)
    icon_path = resource_path("assets/icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # Required on Windows for any frozen (PyInstaller) executable that
    # uses multiprocessing anywhere in its dependency tree - Sieve-Referee
    # uses ProcessPoolExecutor internally. Without this, a frozen Windows
    # .exe can re-launch itself for every spawned worker process instead
    # of running as a plain worker, leading to a runaway process storm.
    # It's a no-op on macOS/Linux and in normal (non-frozen) runs, so it's
    # safe to always call.
    freeze_support()
    main()
