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
import json
import os
import secrets
import tempfile

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
    render_text,
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

from sieve_tray import (
    crowd_anonymize,
    crowd_dry_run,
    crowd_inspect,
    crowd_parse_config,
)
from sieve_crowd import ConfigError, InputError, Role, parse_key
from sieve_crowd.hints import hint as crowd_hint
from sieve_crowd.tableio import detect_format, read_any


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
    "RED": QColor("#ffe0e0"),
    "YELLOW": QColor("#fff4cc"),
}
# v0.9.0: signal-colored text for the Signal column so the row is
# identifiable even on a calibrated monitor where the pastel background
# alone may be too subtle. RED/YELLOW get distinct hues for foreground.
SIGNAL_FG = {
    "RED": QColor("#b00000"),
    "YELLOW": QColor("#8a5a00"),
}


class ScanWorker(QObject):
    """Runs run_scan() on a background thread so the UI stays responsive."""

    progress = Signal(str)
    finished = Signal(object)   # ScanResult
    failed = Signal(str)

    def __init__(self, input_dir: Path, audit_modifier_vocab: str = "",
                 groups=None):
        super().__init__()
        self.input_dir = input_dir
        # v0.8.0: optional override path for the audit lane's modifier
        # vocab. Empty string = use the bundled default (audit_documents
        # falls back to sieve_referee.DEFAULT_MODIFIER_VOCAB).
        self.audit_modifier_vocab = audit_modifier_vocab
        # v0.9.0: optional explicit groups list (file-selection mode).
        # When set, run_scan skips scan(input_dir) and uses these groups
        # directly. None = folder mode (unchanged from v0.8.0).
        self.groups = groups

    def run(self):
        try:
            result = run_scan(
                self.input_dir,
                progress=self.progress.emit,
                audit_modifier_vocab=self.audit_modifier_vocab or None,
                groups=self.groups,
            )
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

CROWD_OK_BG = QColor("#e2f6e2")
CROWD_OK_FG = QColor("#1a6b1a")


def crowd_default_output(input_path: Path) -> Path:
    """Default crowd output path: <stem>_anonymized.<ext> next to the
    input file. The input itself is never the default."""
    return input_path.with_name(
        input_path.stem + "_anonymized" + input_path.suffix)


class CrowdWorker(QObject):
    """Runs crowd_dry_run()/crowd_anonymize() on a background thread
    (same pattern as ScanWorker / SanitizeWorker) so the UI stays
    responsive on large tables."""

    progress = Signal(str)
    finished = Signal(object)   # crowd summary dict
    failed = Signal(str)

    def __init__(self, mode: str, header, rows, cfg, *, io=None,
                 output_path=None, lang="en"):
        super().__init__()
        self.mode = mode                # "dry_run" or "run"
        self.header = header
        self.rows = rows
        self.cfg = cfg
        self.io = io
        self.output_path = output_path
        self.lang = lang

    def run(self):
        try:
            if self.mode == "dry_run":
                summary = crowd_dry_run(self.header, self.rows, self.cfg,
                                        lang=self.lang)
            else:
                summary = crowd_anonymize(self.header, self.rows, self.cfg,
                                          io=self.io,
                                          output_path=self.output_path,
                                          lang=self.lang)
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
        scroll.setMaximumHeight(480)
        self.canvas_scroll = scroll

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
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_scroll.setMaximumHeight(240)

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
        right.addWidget(self.preview_scroll)

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

        self.resize(960, 640)
        self.setSizeGripEnabled(True)

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

        # v0.8.0: optional override path for the audit lane's modifier
        # vocab. Empty = use the bundled default
        # (sieve_tray.DEFAULT_MODIFIER_VOCAB_PATH).
        self.audit_vocab_edit = QLineEdit(
            storage.get_setting("audit_modifier_vocab_path"))
        audit_browse_btn = QPushButton(self._("settings_audit_vocab_browse"))
        audit_browse_btn.clicked.connect(self._browse_audit_vocab)
        audit_row = QHBoxLayout()
        audit_row.addWidget(self.audit_vocab_edit, stretch=1)
        audit_row.addWidget(audit_browse_btn)

        form = QFormLayout()
        form.addRow(self._("settings_export_dir"), export_row)
        form.addRow(self._("settings_retention"), self.retention_spin)
        form.addRow(
            f"{self._('settings_language')} {self._('settings_language_note')}",
            self.language_combo)
        form.addRow(self._("settings_audit_vocab"), audit_row)

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

    def _browse_audit_vocab(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._("settings_audit_vocab_dialog_title"),
            self.audit_vocab_edit.text(),
            "Text files (*.txt);;All files (*)")
        if path:
            self.audit_vocab_edit.setText(path)

    def selected_language(self) -> str:
        return self.language_combo.currentData()

    def save(self):
        self.storage.set_setting("export_dir", self.export_dir_edit.text())
        self.storage.set_setting(
            "history_retention", str(self.retention_spin.value()))
        self.storage.set_setting("language", self.selected_language())
        # v0.8.0: persist the audit-vocab override path (empty = default).
        self.storage.set_setting(
            "audit_modifier_vocab_path", self.audit_vocab_edit.text().strip())
        self.storage.prune_history()


class DetailDialog(QDialog):
    """Shows why a document, code pair, or text pair was flagged: the
    H1-H7 (or H1-H4) states plus whatever evidence/scores/reason the
    engine recorded for them.

    This is deliberately just a reader (no interpretation added on
    top) - it surfaces exactly what the underlying Sieve engine
    observed, consistent with those engines' own "observation, not
    judgment" stance.

    v0.8.0: an optional `certainty` dict adds a separate "Certainty
    Markers" section for the quantifier audit lane, surfacing the
    modifier-vocab sha256, vocab count, and the per-sentence
    certainty markers (or "no markers" when the sentence had none).
    Pass None for non-audit dialogs and the section is omitted.
    """

    def __init__(self, title: str, h_states: dict, labels: dict, lang: str,
                 evidence: dict | None = None, scores: dict | None = None,
                 reason: str | None = None, certainty: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self._ = lambda key, **kw: tr(lang, key, **kw)
        self.setWindowTitle(title)
        self.resize(560, 560)

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

        # v0.8.0: separate Certainty Markers section for audit-sentence
        # details. Omitted entirely when `certainty` is None (non-audit
        # dialogs). When present, shows the modifier-vocab provenance
        # (sha256 + count) and the per-sentence certainty markers (or
        # a "no markers" line when the sentence had none).
        if certainty is not None:
            layout.addWidget(QLabel(self._("detail_certainty_section")))
            cert_view = QPlainTextEdit()
            cert_view.setReadOnly(True)
            cert_lines: list[str] = []
            sha = certainty.get("modifier_vocab_sha256")
            count = int(certainty.get("modifier_vocab_count", 0))
            if sha:
                cert_lines.append(
                    self._("detail_certainty_vocab_label", sha=sha))
            cert_lines.append(self._("detail_certainty_count_label", n=count))
            flagged = certainty.get("certainty_flagged")
            if flagged is not None:
                cert_lines.append(
                    self._("detail_certainty_flagged_label", n=int(flagged)))
            markers = certainty.get("certainty_markers", [])
            if markers:
                cert_lines.append("")
                for m in markers:
                    cert_lines.append(f"  - {m}")
            else:
                cert_lines.append("")
                cert_lines.append(self._("detail_certainty_none"))
            cert_view.setPlainText("\n".join(cert_lines))
            layout.addWidget(cert_view)

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
        # v0.9.0: file-selection mode (audit lane works on a single
        # document, so users can pick a file without grouping).
        choose_files_btn = QPushButton(self._("choose_files_button"))
        choose_files_btn.clicked.connect(self.start_scan_files)
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
        picker_row.addWidget(choose_files_btn)
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

        # v0.8.0: Quantifier Audit tab. One row per flagged sentence
        # across all scanned .txt/.md files. Double-click opens a
        # DetailDialog with a separate Certainty Markers section.
        self.audit_table = self._make_table(
            [self._("audit_header_file"), self._("audit_header_sentence"),
             self._("audit_header_signal"), self._("audit_header_pattern"),
             self._("audit_header_backing"), self._("audit_header_scope"),
             self._("audit_header_certainty")])
        self.audit_table.cellDoubleClicked.connect(self._on_audit_row_activated)
        self.audit_filter_edit = QLineEdit()
        self.audit_filter_edit.setPlaceholderText(self._("filter_by_filename"))
        self.audit_filter_edit.textChanged.connect(self._apply_audit_filter)
        self._audit_tab_index = self.tabs.addTab(
            self._make_filterable_tab(self.audit_table, self.audit_filter_edit),
            self._("audit_tab", n=0))

        self.history_table = self._make_table([
            self._("history_header_timestamp"), self._("history_header_folder"),
            self._("history_header_groups"), self._("history_header_docs"),
            self._("history_header_code_pairs"), self._("history_header_text_pairs"),
            self._("history_header_audit"),
        ])
        self.history_table.cellDoubleClicked.connect(self._on_history_row_activated)
        # v0.9.0: wrap the history table in a container with a 'Clear'
        # button beneath it (PLAN D93 - Sanitize History also has one).
        self.history_clear_btn = QPushButton(self._("history_clear"))
        self.history_clear_btn.clicked.connect(self._on_history_clear)
        history_container = QWidget()
        history_layout = QVBoxLayout(history_container)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(self.history_table, stretch=1)
        history_layout.addWidget(self.history_clear_btn)
        self._history_tab_index = self.tabs.addTab(
            history_container, self._("history_tab", n=0))
        self.sanitize_history_table = self._make_table([
            self._("history_header_timestamp"),
            self._("history_header_folder"),
            self._("sanitize_history_header_config"),
            self._("sanitize_history_header_output"),
            self._("sanitize_history_header_files"),
            self._("sanitize_history_header_masked"),
            self._("sanitize_history_header_integrity"),
        ])
        self.sanitize_history_clear_btn = QPushButton(
            self._("sanitize_history_clear"))
        self.sanitize_history_clear_btn.clicked.connect(
            self._on_sanitize_history_clear)
        sanitize_history_container = QWidget()
        sanitize_history_layout = QVBoxLayout(sanitize_history_container)
        sanitize_history_layout.setContentsMargins(0, 0, 0, 0)
        sanitize_history_layout.addWidget(self.sanitize_history_table, stretch=1)
        sanitize_history_layout.addWidget(self.sanitize_history_clear_btn)
        self._sanitize_history_tab_index = self.tabs.addTab(
            sanitize_history_container,
            self._("sanitize_history_tab", n=0))

        # --- Crowd tab (sieve-crowd integration): select a table,
        # inspect it, edit the k-anonymity config as JSON, measure
        # (dry-run), then run in the background. Refused runs are a
        # normal result, not an error.
        self._crowd_input_path = None
        self._crowd_header = None
        self._crowd_rows = None
        self._crowd_fmt = None
        self._crowd_inspect_info = None
        self._crowd_last_dry_run = None
        self._crowd_key_path = None
        self._crowd_config_path = None
        self._crowd_thread = None
        self._crowd_worker = None

        crowd_page = QWidget()
        crowd_layout = QVBoxLayout(crowd_page)

        crowd_file_row = QHBoxLayout()
        self.crowd_file_btn = QPushButton(self._("crowd_file_select"))
        self.crowd_file_btn.clicked.connect(self.crowd_choose_file)
        self.crowd_input_label = QLabel("")
        crowd_file_row.addWidget(self.crowd_file_btn)
        crowd_file_row.addWidget(self.crowd_input_label, stretch=1)
        crowd_layout.addLayout(crowd_file_row)

        self.crowd_inspect_btn = QPushButton(self._("crowd_inspect_button"))
        self.crowd_inspect_btn.setEnabled(False)
        self.crowd_inspect_btn.clicked.connect(self.crowd_run_inspect)
        crowd_layout.addWidget(self.crowd_inspect_btn)
        self.crowd_inspect_table = self._make_table([
            self._("crowd_inspect_column_name"),
            self._("crowd_inspect_distinct"),
            self._("crowd_inspect_empty"),
            self._("crowd_inspect_unique_ratio"),
            self._("crowd_inspect_shape"),
            self._("crowd_inspect_hint"),
        ])
        crowd_layout.addWidget(self.crowd_inspect_table)

        crowd_layout.addWidget(QLabel(self._("crowd_config_label")))
        self.crowd_config_edit = QPlainTextEdit()
        crowd_layout.addWidget(self.crowd_config_edit, stretch=2)
        crowd_config_row = QHBoxLayout()
        self.crowd_config_save_btn = QPushButton(self._("crowd_config_save"))
        self.crowd_config_save_btn.clicked.connect(self.crowd_save_config)
        self.crowd_config_load_btn = QPushButton(self._("crowd_config_load"))
        self.crowd_config_load_btn.clicked.connect(self.crowd_load_config)
        crowd_config_row.addWidget(self.crowd_config_save_btn)
        crowd_config_row.addWidget(self.crowd_config_load_btn)
        crowd_config_row.addStretch(1)
        self.crowd_config_error_label = QLabel("")
        crowd_config_row.addWidget(self.crowd_config_error_label, stretch=1)
        crowd_layout.addLayout(crowd_config_row)

        crowd_dry_row = QHBoxLayout()
        self.crowd_dry_run_btn = QPushButton(self._("crowd_dry_run_button"))
        self.crowd_dry_run_btn.setEnabled(False)
        self.crowd_dry_run_btn.clicked.connect(self.crowd_start_dry_run)
        self.crowd_dry_run_label = QLabel("")
        self.crowd_dry_receipt_btn = QPushButton(
            self._("crowd_result_receipt"))
        self.crowd_dry_receipt_btn.setEnabled(False)
        self.crowd_dry_receipt_btn.clicked.connect(
            self.crowd_show_dry_run_receipt)
        crowd_dry_row.addWidget(self.crowd_dry_run_btn)
        crowd_dry_row.addWidget(self.crowd_dry_run_label, stretch=1)
        crowd_dry_row.addWidget(self.crowd_dry_receipt_btn)
        crowd_layout.addLayout(crowd_dry_row)

        crowd_key_row = QHBoxLayout()
        self.crowd_keygen_btn = QPushButton(self._("crowd_keygen_button"))
        self.crowd_keygen_btn.clicked.connect(self.crowd_keygen)
        self.crowd_key_file_label = QLabel(self._("crowd_key_file"))
        crowd_key_row.addWidget(self.crowd_keygen_btn)
        crowd_key_row.addWidget(self.crowd_key_file_label, stretch=1)
        crowd_layout.addLayout(crowd_key_row)

        crowd_out_row = QHBoxLayout()
        self.crowd_output_label = QLabel(self._("crowd_output_label"))
        self.crowd_output_edit = QLineEdit()
        self.crowd_output_edit.setPlaceholderText(
            self._("crowd_output_default"))
        self.crowd_output_browse_btn = QPushButton(
            self._("crowd_output_browse"))
        self.crowd_output_browse_btn.clicked.connect(self.crowd_choose_output)
        crowd_out_row.addWidget(self.crowd_output_label)
        crowd_out_row.addWidget(self.crowd_output_edit, stretch=1)
        crowd_out_row.addWidget(self.crowd_output_browse_btn)
        crowd_layout.addLayout(crowd_out_row)

        self.crowd_run_btn = QPushButton(self._("crowd_run_button"))
        self.crowd_run_btn.setEnabled(False)
        self.crowd_run_btn.clicked.connect(self.crowd_start_run)
        crowd_layout.addWidget(self.crowd_run_btn)

        self.crowd_result_label = QLabel("")
        self.crowd_result_label.setWordWrap(True)
        crowd_layout.addWidget(self.crowd_result_label)
        crowd_layout.addWidget(QLabel(self._("crowd_result_receipt")))
        self.crowd_receipt_view = QPlainTextEdit()
        self.crowd_receipt_view.setReadOnly(True)
        crowd_layout.addWidget(self.crowd_receipt_view, stretch=2)
        self.crowd_premise_label = QLabel(self._("crowd_result_premise"))
        self.crowd_premise_label.setWordWrap(True)
        crowd_layout.addWidget(self.crowd_premise_label)

        self._crowd_tab_index = self.tabs.addTab(crowd_page,
                                                 self._("crowd_tab"))

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
        if getattr(self, "_crowd_thread", None) is not None:
            self._crowd_thread.quit()
            self._crowd_thread.wait(5000)
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
        self._sanitize_worker.finished.connect(self._on_sanitize_finished)
        self._sanitize_worker.failed.connect(self._on_sanitize_failed)
        self._sanitize_worker.finished.connect(self._sanitize_thread.quit)
        self._sanitize_worker.failed.connect(self._sanitize_thread.quit)
        self._sanitize_thread.finished.connect(self._sanitize_thread.deleteLater)
        self._sanitize_thread.start()

    def _on_sanitize_finished(self, summary):
        if summary.get("config_error"):
            message = self._("sanitize_config_error",
                             err=summary["config_error"])
            self.summary_label.setText(message)
        elif summary["skipped"]:
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
            if summary.get("excluded"):
                listing = "\n".join("%s (%s)" % (rel, reason)
                                    for rel, reason in summary["excluded"])
                message += self._("sanitize_excluded_files", files=listing)
            self.summary_label.setText(message)
        self.run_btn.setEnabled(True)
        self.sanitize_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        if not summary["skipped"] and not summary.get("config_error"):
            self.storage.save_sanitization(
                summary, self._sanitize_input_dir,
                self._sanitize_config_path, self._sanitize_out_root)
            self._refresh_sanitize_history_table()
        if summary.get("config_error"):
            QMessageBox.warning(self, self._("error_title"), message)
        else:
            QMessageBox.information(
                self, self._("sanitize_done_title"), message)

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
            self._refresh_sanitize_history_table()
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
        self._launch_scan(input_dir, groups=None)

    def start_scan_files(self):
        """v0.9.0: file-selection mode. User picks one or more files; they
        are scanned as a single group (any suffix). code_pairs and
        text_pairs will be 0 since there is only one group; the audit
        lane still runs (Sieve-Referee §9: single document + audit
        enabled = standalone audit run)."""
        path, _ = QFileDialog.getOpenFileNames(
            self, self._("choose_files_dialog_title"), "",
            self._("choose_files_filter"))
        if not path:
            return
        files = [Path(p) for p in path]
        # Use the first file's parent as the nominal input_dir so
        # history save_run has a reasonable path to record.
        input_dir = files[0].parent
        # Single group named after the common parent (matches the
        # folder-mode key shape "{group}/{file}").
        group_name = input_dir.name or "selected"
        groups = [(group_name, files)]
        self._launch_scan(input_dir, groups=groups)

    def _launch_scan(self, input_dir: Path, groups=None):
        """Shared scan launcher for folder and file modes."""
        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.log_view.clear()
        self.doc_filter_edit.clear()
        self.doc_flagged_only_cb.setChecked(False)
        self.code_filter_edit.clear()
        self.text_filter_edit.clear()
        self.audit_filter_edit.clear()
        self._clear_result_tables()
        self.summary_label.setText(self._("scanning"))

        self._thread = QThread(self)
        # v0.8.0: pass the user's audit-vocab override (empty = bundled default).
        audit_vocab = self.storage.get_setting("audit_modifier_vocab_path") or ""
        self._worker = ScanWorker(
            input_dir, audit_modifier_vocab=audit_vocab, groups=groups)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.log_view.appendPlainText)
        self._scan_input_dir = input_dir
        self._worker.finished.connect(self._on_scan_finished)
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
        self.audit_table.setRowCount(0)
        self.tabs.setTabText(self._doc_tab_index, self._("doc_tab", n=0))
        self.tabs.setTabText(self._code_tab_index, self._("code_tab", n=0))
        self.tabs.setTabText(self._text_tab_index, self._("text_tab", n=0))
        self.tabs.setTabText(self._audit_tab_index, self._("audit_tab", n=0))

    def _on_scan_finished(self, result: ScanResult):
        """Main-thread adapter for the scan worker's finished
        signal: a bound-method connection gives Qt a receiver, so
        the call is queued to the main thread (the handler touches
        widgets and must never run on the worker thread).
        """
        self._on_finished(self._scan_input_dir, result)

    def _on_finished(self, input_dir: Path, result: ScanResult):
        self._scan_running = False
        self._last_result = result
        self._populate_result_tables(result)
        flagged_docs = sum(1 for r in result.doc_results if r.get("flagged"))
        self.summary_label.setText(self._(
            "summary_done", groups=len(result.groups),
            docs=len(result.doc_results), flagged=flagged_docs,
            pairs=len(result.code_pairs), tpairs=len(result.text_pairs),
            audit=len(result.audit_results)))
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
            fg = SIGNAL_FG.get(p["signal"])
            if fg is not None:
                self.text_table.item(row, 2).setForeground(fg)
        self.tabs.setTabText(
            self._text_tab_index, self._("text_tab", n=len(result.text_pairs)))
        self.text_table.setSortingEnabled(True)
        self._apply_text_filter()

        # v0.8.0: Quantifier Audit table - one row per flagged sentence.
        # The full audit entry is stashed on column 0's UserRole so the
        # detail dialog can rebuild the Certainty Markers section.
        self.audit_table.setSortingEnabled(False)
        self.audit_table.setRowCount(len(result.audit_results))
        for row, a in enumerate(result.audit_results):
            file_item = QTableWidgetItem(a["file"])
            file_item.setData(Qt.UserRole, a)
            self.audit_table.setItem(row, 0, file_item)
            sentence = a.get("sentence_text") or ""
            self.audit_table.setItem(row, 1, QTableWidgetItem(sentence))
            self.audit_table.setItem(row, 2, QTableWidgetItem(a["signal"]))
            self.audit_table.setItem(row, 3, QTableWidgetItem(a["pattern_name"]))
            self.audit_table.setItem(row, 4, QTableWidgetItem(a["backing"]))
            self.audit_table.setItem(row, 5, QTableWidgetItem(a["scope"]))
            certainty = ", ".join(a.get("certainty_markers", [])) or "—"
            self.audit_table.setItem(row, 6, QTableWidgetItem(certainty))
            bg = SIGNAL_BG.get(a["signal"], FLAGGED_BG)
            for col in range(7):
                self.audit_table.item(row, col).setBackground(bg)
            # Signal column gets a signal-colored foreground so the row
            # is identifiable even when the pastel background is subtle.
            fg = SIGNAL_FG.get(a["signal"])
            if fg is not None:
                self.audit_table.item(row, 2).setForeground(fg)
        self.tabs.setTabText(
            self._audit_tab_index, self._("audit_tab", n=len(result.audit_results)))
        self.audit_table.setSortingEnabled(True)
        self._apply_audit_filter()

    def export_html(self):
        if self._last_result is None:
            return
        default_dir = self.storage.get_setting("export_dir")
        default_path = str(Path(default_dir) / "report.html")
        # v0.9.0: format picker - HTML or Markdown (render_text).
        path, selected_filter = QFileDialog.getSaveFileName(
            self, self._("save_report_dialog_title"), default_path,
            self._("save_report_filter"))
        if not path:
            return
        # Decide the renderer from the selected filter; fall back to
        # extension-based detection if the platform returned no filter.
        fmt = "md" if (".md" in (selected_filter or "") or path.endswith(".md")) \
            else "html"
        # v0.10.0: attach the crowd run history (newest first) so
        # the exported report carries the crowd results section.
        # Inert for the on-screen tables; reloaded every export.
        self._last_result.crowd_runs = self.storage.load_crowd_runs()
        if fmt == "md":
            content = render_text(self._last_result)
        else:
            content = render(self._last_result)
        Path(path).write_text(content, encoding="utf-8")
        QMessageBox.information(
            self, self._("save_complete_title"),
            self._("save_complete_message", path=path))

    # ------------------------------------------------------------------
    # v0.9.0: history clear handlers (教訓 67: bound method, not lambda)
    # ------------------------------------------------------------------

    def _on_history_clear(self):
        """Bound-method handler for the History tab 'Clear' button."""
        if QMessageBox.question(
                self,
                self._("confirm_clear_title"),
                self._("confirm_clear_history"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        self.storage.clear_runs()
        self._refresh_history_table()

    def _on_sanitize_history_clear(self):
        """Bound-method handler for the Sanitize History 'Clear' button."""
        if QMessageBox.question(
                self,
                self._("confirm_clear_title"),
                self._("confirm_clear_sanitizations"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        self.storage.clear_sanitizations()
        self._refresh_sanitize_history_table()

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

    def _apply_audit_filter(self):
        text = self.audit_filter_edit.text().lower()
        for row in range(self.audit_table.rowCount()):
            file_item = self.audit_table.item(row, 0)
            sentence_item = self.audit_table.item(row, 1)
            if file_item is None or sentence_item is None:
                continue
            combined = (file_item.text() + " " + sentence_item.text()).lower()
            self.audit_table.setRowHidden(row, text not in combined)

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

    def _on_audit_row_activated(self, row: int, _column: int):
        # v0.8.0: open a DetailDialog for a quantifier-audit sentence.
        # The audit lane has no H1-H7 axes (it's a separate lane), so
        # we pass an empty h_states/labels pair and surface everything
        # through the `certainty` section + reason.
        item = self.audit_table.item(row, 0)
        if item is None:
            return
        a = item.data(Qt.UserRole)
        if not a:
            return
        # Fake a single "axis" so the axis_table isn't empty - the
        # audit lane has one verdict per sentence, surfaced as a single
        # row whose "axis" is the sentence's signal.
        audit_labels = {"S": {"en": "Signal", "ja": "シグナル"}[self.lang]}
        h_states = {"S": 1 if a["signal"] == "RED" else 0}
        certainty = {
            "modifier_vocab_sha256": a.get("modifier_vocab_sha256"),
            "modifier_vocab_count": int(a.get("modifier_vocab_count", 0)),
            "certainty_markers": list(a.get("certainty_markers", [])),
        }
        dialog = DetailDialog(
            self._("detail_audit_title", file=a["file"]),
            h_states, audit_labels, self.lang,
            reason=a.get("reason"), certainty=certainty, parent=self)
        dialog.exec()

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------

    def _refresh_sanitize_history_table(self):
        rows = self.storage.load_sanitizations()
        self.sanitize_history_table.setSortingEnabled(False)
        self.sanitize_history_table.setRowCount(len(rows))
        for row, r in enumerate(rows):
            self.sanitize_history_table.setItem(
                row, 0, QTableWidgetItem(r["timestamp"]))
            self.sanitize_history_table.setItem(
                row, 1, QTableWidgetItem(r["input_dir"]))
            self.sanitize_history_table.setItem(
                row, 2, QTableWidgetItem(r["config_path"]))
            self.sanitize_history_table.setItem(
                row, 3, QTableWidgetItem(r["out_root"]))
            self.sanitize_history_table.setItem(
                row, 4, QTableWidgetItem(
                    "%d (%d)" % (r["n_files"], r["ok_count"])))
            self.sanitize_history_table.setItem(
                row, 5, QTableWidgetItem(str(r["masked_total"])))
            self.sanitize_history_table.setItem(
                row, 6, QTableWidgetItem(
                    str(r["integrity_bad_count"])))
            self.sanitize_history_table.item(row, 0).setData(
                Qt.UserRole, r["id"])
        self.tabs.setTabText(
            self._sanitize_history_tab_index,
            self._("sanitize_history_tab", n=len(rows)))
        self.sanitize_history_table.setSortingEnabled(True)

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
            # v0.8.0: audit count column
            self.history_table.setItem(
                row, 6, QTableWidgetItem(str(r.audit_count)))
            # stash the run id on the row for double-click lookup
            self.history_table.item(row, 0).setData(Qt.UserRole, r.id)
        self.tabs.setTabText(
            self._history_tab_index, self._("history_tab", n=len(runs)))
        self.history_table.setSortingEnabled(True)
        self._refresh_sanitize_history_table()

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
            pairs=len(result.code_pairs), tpairs=len(result.text_pairs),
            audit=len(result.audit_results)))
        self.export_btn.setEnabled(True)
        self.tabs.setCurrentIndex(self._doc_tab_index)

    # ------------------------------------------------------------------
    # Crowd tab (sieve-crowd integration): select a table, inspect it,
    # edit the k-anonymity config as JSON, measure (dry-run), then run
    # in the background. Refused runs are a normal result, not an error.
    # ------------------------------------------------------------------

    def crowd_choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._("crowd_file_select"), "", self._("crowd_file_filter"))
        if path:
            self.crowd_load_file(Path(path))

    def crowd_load_file(self, path: Path):
        try:
            data = path.read_bytes()
            fmt = detect_format(path.suffix)
            header, rows = read_any(data, fmt)
        except (OSError, InputError) as exc:
            QMessageBox.critical(self, self._("error_title"),
                                 f"{type(exc).__name__}: {exc}")
            return
        self._crowd_input_path = path
        self._crowd_header = header
        self._crowd_rows = rows
        self._crowd_fmt = fmt
        self._crowd_inspect_info = None
        self._crowd_last_dry_run = None
        self.crowd_input_label.setText(str(path))
        self.crowd_output_edit.setText(str(crowd_default_output(path)))
        self.crowd_config_error_label.setText("")
        self.crowd_dry_run_label.setText("")
        self.crowd_result_label.setText("")
        self.crowd_result_label.setStyleSheet("")
        self.crowd_receipt_view.setPlainText("")
        self.crowd_inspect_btn.setEnabled(True)
        self.crowd_dry_run_btn.setEnabled(True)
        self.crowd_run_btn.setEnabled(True)
        self.crowd_run_inspect()
        self.crowd_config_edit.setPlainText(self._crowd_config_template())

    def crowd_run_inspect(self):
        if self._crowd_header is None or self._crowd_rows is None:
            return
        info = crowd_inspect(self._crowd_header, self._crowd_rows)
        self._crowd_inspect_info = info
        n = len(self._crowd_rows)
        table = self.crowd_inspect_table
        table.setSortingEnabled(False)
        table.setRowCount(len(info))
        for row, col_info in enumerate(info):
            role, text_en, text_ja = crowd_hint(col_info["name"], col_info, n)
            hint_text = ""
            if role:
                hint_text = text_en if self.lang == "en" else text_ja
            values = [
                col_info["name"],
                str(col_info["distinct"]),
                str(col_info["empty"]),
                "%.0f%%" % (col_info["unique_ratio"] * 100),
                col_info["shape"],
                role if role else "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if hint_text:
                    item.setToolTip(hint_text)
                table.setItem(row, column, item)
        table.setSortingEnabled(True)

    def _crowd_config_template(self) -> str:
        """Initial JSON config from the inspect proposal, the same
        shape the sieve-crowd CLI writes with its config template:
        every column starts as role "?" (a suggestion is never
        applied automatically); hinted columns carry an _hint note
        that parse_config ignores."""
        info = self._crowd_inspect_info or []
        n = len(self._crowd_rows or [])
        columns = {}
        for col_info in info:
            role, text_en, text_ja = crowd_hint(col_info["name"], col_info, n)
            if role:
                hint_text = text_en if self.lang == "en" else text_ja
                columns[col_info["name"]] = {"role": "?", "_hint": hint_text}
            else:
                columns[col_info["name"]] = {"role": "?"}
        template = {"k": 5, "l": 1, "max_suppression": 0.05,
                    "columns": columns}
        return json.dumps(template, ensure_ascii=False, indent=2) + "\n"

    def crowd_save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._("crowd_config_save"), "",
            self._("crowd_filter_json"))
        if not path:
            return
        Path(path).write_text(self.crowd_config_edit.toPlainText(),
                              encoding="utf-8")

    def crowd_load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._("crowd_config_load"), "",
            self._("crowd_filter_json"))
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, self._("error_title"),
                                 f"{type(exc).__name__}: {exc}")
            return
        self.crowd_config_edit.setPlainText(text)
        self._crowd_config_path = Path(path)
        self.crowd_config_error_label.setText("")

    def crowd_keygen(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._("crowd_keygen_button"), "",
            self._("crowd_filter_text"))
        if path:
            self.crowd_keygen_to(Path(path))

    def crowd_keygen_to(self, target: Path):
        """Write a fresh 64-hex-digit key file atomically with mode
        600 (the sieve-crowd keygen contract). An existing file is
        only replaced after confirmation. The key content is read
        back from the file at run time; it is never kept in the
        history, receipts or logs."""
        if target.exists():
            answer = QMessageBox.question(
                self, self._("crowd_keygen_button"),
                self._("crowd_confirm_key_replace"),
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        fd, tmp = tempfile.mkstemp(dir=str(target.parent),
                                   prefix=".sieve-tray-key-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write((secrets.token_hex(32) + "\n").encode("ascii"))
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._crowd_key_path = target
        self.crowd_key_file_label.setText(
            f"{self._('crowd_key_file')} {target}")

    def crowd_choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._("crowd_output_browse"), "", self._("crowd_file_filter"))
        if path:
            self.crowd_output_edit.setText(path)

    def _crowd_build_config(self):
        """Parse the config editor text (with the optional key file).
        Returns the Config or None; a failure never starts a worker
        and the JSON/validation message carries the offending line
        number from crowd_parse_config."""
        text = self.crowd_config_edit.toPlainText()
        overrides = {}
        if self._crowd_key_path is not None:
            try:
                overrides["key"] = parse_key(
                    self._crowd_key_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ConfigError) as exc:
                QMessageBox.critical(self, self._("error_title"),
                                     f"{type(exc).__name__}: {exc}")
                return None
        try:
            return crowd_parse_config(text, **overrides)
        except ConfigError as exc:
            self.crowd_config_error_label.setText(
                f"{self._('crowd_config_json_error')}: {exc}")
            return None

    def _crowd_identifier_conflicts(self, cfg) -> list:
        """Columns that look like direct identifiers (the sieve-crowd
        hint proposal is "id", which is driven by the hints._ID set)
        but stay in keep or sensitive."""
        if self._crowd_inspect_info is None:
            return []
        info_by_name = {c["name"]: c for c in self._crowd_inspect_info}
        conflicts = []
        for name in cfg.names(Role.KEEP) + cfg.names(Role.SENSITIVE):
            info = info_by_name.get(name)
            if info is None:
                continue
            suggested, _text_en, _text_ja = crowd_hint(
                name, info, len(self._crowd_rows or []))
            if suggested == "id":
                conflicts.append(name)
        return conflicts

    def _crowd_identifier_gate(self, cfg) -> bool:
        """Run gate: an identifier-like column left in keep/sensitive
        must be confirmed by the user before anything runs."""
        conflicts = self._crowd_identifier_conflicts(cfg)
        if not conflicts:
            return True
        names = "\n".join(conflicts)
        answer = QMessageBox.question(
            self, self._("crowd_confirm_identifier_title"),
            f"{self._('crowd_confirm_identifier_message')}\n{names}",
            QMessageBox.Yes | QMessageBox.No)
        return answer == QMessageBox.Yes

    def _crowd_ready(self) -> bool:
        if self._crowd_header is None or self._crowd_rows is None:
            QMessageBox.warning(self, self._("error_title"),
                                self._("crowd_file_select"))
            return False
        return True

    def crowd_start_dry_run(self):
        if not self._crowd_ready():
            return
        cfg = self._crowd_build_config()
        if cfg is None:
            return
        if not self._crowd_identifier_gate(cfg):
            return
        self.crowd_config_error_label.setText("")
        self._crowd_launch("dry_run", cfg)

    def crowd_start_run(self):
        if not self._crowd_ready():
            return
        output_text = self.crowd_output_edit.text().strip()
        if not output_text:
            return
        output_path = Path(output_text)
        if self._crowd_input_path is not None:
            try:
                same = (output_path.resolve()
                        == self._crowd_input_path.resolve())
            except OSError:
                same = False
            if same:
                QMessageBox.critical(self, self._("error_title"),
                                     self._("crowd_error_output_is_input"))
                return
        if output_path.exists():
            answer = QMessageBox.question(
                self, self._("crowd_output_label"),
                self._("crowd_confirm_output_replace"),
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        cfg = self._crowd_build_config()
        if cfg is None:
            return
        if not self._crowd_identifier_gate(cfg):
            return
        self.crowd_config_error_label.setText("")
        io = (self._crowd_fmt, self._crowd_fmt)
        self._crowd_launch("run", cfg, io=io, output_path=output_path)

    def _crowd_launch(self, mode, cfg, *, io=None, output_path=None):
        self._crowd_set_running(True)
        self._crowd_thread = QThread(self)
        self._crowd_worker = CrowdWorker(
            mode, self._crowd_header, self._crowd_rows, cfg,
            io=io, output_path=output_path, lang=self.lang)
        self._crowd_worker.moveToThread(self._crowd_thread)
        self._crowd_thread.started.connect(self._crowd_worker.run)
        self._crowd_worker.progress.connect(self.log_view.appendPlainText)
        if mode == "dry_run":
            self._crowd_worker.finished.connect(
                self._on_crowd_dry_run_finished)
        else:
            self._crowd_worker.finished.connect(self._on_crowd_run_finished)
        self._crowd_worker.failed.connect(self._on_crowd_failed)
        self._crowd_worker.finished.connect(self._crowd_thread.quit)
        self._crowd_worker.failed.connect(self._crowd_thread.quit)
        self._crowd_thread.finished.connect(self._crowd_thread.deleteLater)
        self._crowd_thread.start()

    def _crowd_set_running(self, running: bool):
        has_input = self._crowd_header is not None
        self.crowd_file_btn.setEnabled(not running)
        self.crowd_inspect_btn.setEnabled(has_input and not running)
        self.crowd_dry_run_btn.setEnabled(has_input and not running)
        self.crowd_run_btn.setEnabled(has_input and not running)
        self.crowd_config_save_btn.setEnabled(not running)
        self.crowd_config_load_btn.setEnabled(not running)
        self.crowd_keygen_btn.setEnabled(not running)
        self.crowd_output_browse_btn.setEnabled(not running)

    def _on_crowd_dry_run_finished(self, summary):
        self._crowd_last_dry_run = summary
        self._crowd_set_running(False)
        self.crowd_dry_receipt_btn.setEnabled(True)
        self.crowd_dry_run_label.setText(
            f"{self._('crowd_dry_run_before')} {summary.get('before_alone')}"
            f" \u2192 {self._('crowd_dry_run_after')}"
            f" {summary.get('after_alone')}")
        self.crowd_receipt_view.setPlainText(
            summary.get("report_text") or "")

    def crowd_show_dry_run_receipt(self):
        summary = self._crowd_last_dry_run
        if summary is not None:
            self.crowd_receipt_view.setPlainText(
                summary.get("report_text") or "")

    def _on_crowd_run_finished(self, summary):
        self._crowd_set_running(False)
        pairs = [
            (self._("crowd_result_status"), summary.get("status")),
            (self._("crowd_result_records_in"), summary.get("records_in")),
            (self._("crowd_result_records_out"), summary.get("records_out")),
            (self._("crowd_result_suppressed"), summary.get("suppressed")),
            (self._("crowd_result_k_achieved"), summary.get("k_achieved")),
        ]
        lines = [f"{name}: {value}" for name, value in pairs]
        if summary.get("ok"):
            background, foreground = CROWD_OK_BG, CROWD_OK_FG
        else:
            background = SIGNAL_BG["YELLOW"]
            foreground = SIGNAL_FG["YELLOW"]
            lines.append(self._("crowd_result_refused"))
            reason = summary.get("reason")
            if reason:
                lines.append(
                    f"{self._('crowd_result_refused_reason')}: {reason}")
        self.crowd_result_label.setText("\n".join(lines))
        self.crowd_result_label.setStyleSheet(
            f"background: {background.name()};"
            f" color: {foreground.name()};")
        self.crowd_receipt_view.setPlainText(
            summary.get("report_text") or "")
        record = dict(summary)
        record["input_path"] = (
            str(self._crowd_input_path)
            if self._crowd_input_path is not None else None)
        record["output_path"] = (
            str(self.crowd_output_edit.text().strip())
            if summary.get("ok") else None)
        record["config_path"] = (
            str(self._crowd_config_path)
            if self._crowd_config_path is not None else None)
        self.storage.save_crowd_run(record)

    def _on_crowd_failed(self, message):
        self._crowd_set_running(False)
        self.crowd_result_label.setText(message)
        self.crowd_result_label.setStyleSheet(
            f"background: {SIGNAL_BG['RED'].name()};"
            f" color: {SIGNAL_FG['RED'].name()};")
        QMessageBox.critical(self, self._("error_title"), message)


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
