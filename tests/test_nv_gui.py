"""NV (迷わない画面) 2.5.0 - the first-wave red tests (NV-T01, T03, T05, T10).

The expectations carry the three corrections of the 2026-11-23 ruling:

1.  The file-drop candidates keep only the pages that handle the
    dropped extension's content (rename and manifest leave the file
    lanes; table_diff joins only for .csv, the type the engine import
    actually accepts); the folder drop stays the folder pages' input;
    a folder-and-file mix puts the folder-only pages in the "some"
    group; the "no page accepts this" branch is reachable with real
    file types (.zip, a video).
2.  The decided tooltip sentences of doc / crowd / clean ride this
    file (audit's sentence was decided 2026-11-22 and rides unchanged).
3.  The audit en name is Detect Universal Statements.

Every pin addresses a page by KEY (never by row number, the §2-6
ruling).  The expected sidebar is 21 rows: 5 headings + 16 pages.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))

from test_v1_4_scan import _require_qt  # noqa: E402
from test_seal_s8_gui import _make_window  # noqa: E402

# ---------------------------------------------------------------------------
# the sidebar definition of the 2.5.0 request (§3.2 of the clause table):
# 21 rows = 5 headings + 16 pages, in order.  kind: "head" is the
# non-selectable heading row, "page" the selectable page row.
# ---------------------------------------------------------------------------

SIDEBAR_ROWS = (
    ("page", "start", "start_tab"),
    ("head", "grp_before_ai", "grp_before_ai_tab"),
    ("page", "gate", "gate_tab"),
    ("page", "crowd", "crowd_tab"),
    ("page", "doc", "doc_tab"),
    ("head", "grp_compare", "grp_compare_tab"),
    ("page", "cohort", "cohort_tab"),
    ("page", "text", "text_tab"),
    ("page", "code", "code_tab"),
    ("page", "audit", "audit_tab"),
    ("page", "table_diff", "table_diff_tab"),
    ("head", "grp_tidy", "grp_tidy_tab"),
    ("page", "rename", "rename_tab"),
    ("page", "clean", "clean_tab"),
    ("page", "normalize", "normalize_tab"),
    ("head", "grp_records", "grp_records_tab"),
    ("page", "manifest", "manifest_tab"),
    ("page", "draw", "draw_tab"),
    ("head", "grp_history", "grp_history_tab"),
    ("page", "history", "history_tab"),
    ("page", "sanitize_history", "sanitize_history_tab"),
)

PAGE_KEYS_16 = tuple(k for kind, k, _n in SIDEBAR_ROWS if kind == "page")

# the counted display (the (0) suffix) rides the six measured pages
# only (the 2026-11-22 correction of the clause table §3.2).
COUNTED_KEYS = frozenset(
    {"doc", "code", "text", "audit", "history", "sanitize_history"})

# ---------------------------------------------------------------------------
# NV-T01 / NV-T10: the six renamed pairs (ja and en).  The audit en
# name is Detect Universal Statements (2026-11-23).
# ---------------------------------------------------------------------------

RENAME_EXPECT = (
    (("en", "doc"), ("Check Documents", "doc_tab")),
    (("en", "text"), ("Compare Texts", "text_tab")),
    (("en", "code"), ("Compare Code", "code_tab")),
    (("en", "crowd"), ("Anonymize Tables", "crowd_tab")),
    (("en", "audit"), ("Detect Universal Statements", "audit_tab")),
    (("en", "sanitize_history"), ("Masking History", "sanitize_history_tab")),
    (("ja", "doc"), ("文書の確認", "doc_tab")),
    (("ja", "text"), ("文章の比較", "text_tab")),
    (("ja", "code"), ("コードの比較", "code_tab")),
    (("ja", "crowd"), ("表の匿名化", "crowd_tab")),
    (("ja", "audit"), ("全称表現の検出", "audit_tab")),
    (("ja", "sanitize_history"), ("マスキング履歴", "sanitize_history_tab")),
)

# the old display names, six per language (the whole-match judgment;
# the partial match is refused because 匿名化 sits inside 表の匿名化).
OLD_NAMES = {
    "ja": ("ドキュメント", "テキスト類似度", "コードペア", "匿名化",
           "量化子監査", "サニタイズ履歴"),
    "en": ("Documents", "Code Pairs", "Text Similarity", "Anonymize",
           "Quantifier Audit", "Sanitize History"),
}

# ---------------------------------------------------------------------------
# NV-T10: the decided tooltip sentences.  audit keeps the 2026-11-22
# sentence through the rename; doc / crowd / clean are the 2026-11-23
# decisions.  One sentence per page, ja and en.
# ---------------------------------------------------------------------------

DECIDED_TIPS = (
    (("ja", "audit"),
     "『すべて』『必ず』のような言い切りの文を、一覧にして確認します。"),
    (("ja", "doc"),
     "フォルダの文書に、人には見えない文字が隠れていないか調べます。"),
    (("ja", "crowd"),
     "表の中の、個人を特定できる情報を、置き換えて分からなくします。"),
    (("ja", "clean"),
     "作成者・日時・位置情報などの付帯情報（メタデータ）を、取り除きます。"),
    (("en", "audit"),
     "Lists sentences that overstate things (all, always, never) for "
     "you to review."),
    (("en", "doc"),
     "Checks the documents in a folder for characters hidden from "
     "human eyes."),
    (("en", "crowd"),
     "Replaces the information that can identify a person in a table "
     "so it stops being readable."),
    (("en", "clean"),
     "Removes the bundled metadata (author, dates, location) that "
     "files carry."),
)

# the decided one-line strings of the drop area (§3.3).
DROP_STRINGS = {
    "en": {
        "start_drop_none": "No page accepts this kind of file.",
        "start_drop_all_label": "Pages that accept everything you dropped",
        "start_drop_some_label": "Pages that accept only some of it",
        "start_drop_hint": "You will choose the folder that contains the "
                           "files on the page itself.",
    },
    "ja": {
        "start_drop_none": "この種類のファイルを受け付ける画面はありません。",
        "start_drop_all_label": "ドロップしたすべてを受け付ける画面",
        "start_drop_some_label": "一部だけを受け付ける画面",
        "start_drop_hint": "ファイルのあるフォルダを指定して使います。",
    },
}

# ---------------------------------------------------------------------------
# NV-T05: the candidate match table (the 2026-11-23 ruling's rebuild,
# the implementation contract of the clause table §3.3).  Each drop
# shape expects the sidebar-ordered (key, mode, accepted) triples;
# mode is "input" when the page can receive the input, "open" when the
# page only opens; accepted is "all" when the page matches every
# dropped path, "some" when it matches only part of the drop.
# ---------------------------------------------------------------------------

DROP_TABLE = {
    "pdf": [("gate", "open", "all"), ("doc", "open", "all"),
            ("cohort", "open", "all"), ("clean", "input", "all")],
    "txt": [("gate", "open", "all"), ("doc", "open", "all"),
            ("cohort", "open", "all"), ("text", "open", "all"),
            ("audit", "open", "all"), ("normalize", "open", "all")],
    "py": [("cohort", "open", "all"), ("code", "open", "all")],
    "csv": [("crowd", "input", "all"), ("table_diff", "open", "all"),
            ("normalize", "open", "all")],
    "folder": [("gate", "input", "all"), ("doc", "open", "all"),
               ("cohort", "input", "all"), ("text", "open", "all"),
               ("code", "open", "all"), ("audit", "open", "all"),
               ("rename", "input", "all"), ("clean", "input", "all"),
               ("normalize", "input", "all"), ("manifest", "input", "all")],
    # the display groups すべて / 一部; the function rides the sidebar
    # order and carries the group in the accepted flag.
    "pdf+py": [("gate", "open", "some"), ("doc", "open", "some"),
               ("cohort", "open", "all"), ("code", "open", "some"),
               ("clean", "input", "some")],
    "folder+pdf": [("gate", "input", "all"), ("doc", "open", "all"),
                   ("cohort", "input", "all"), ("text", "open", "some"),
                   ("code", "open", "some"), ("audit", "open", "some"),
                   ("rename", "input", "some"), ("clean", "input", "all"),
                   ("normalize", "input", "some"),
                   ("manifest", "input", "some")],
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _drop_fixtures(tmp_path):
    """The real fixture tree for the drop shapes (the paths exist; the
    contents stay one byte - the contract forbids reading them)."""
    root = tmp_path / "drop_root"
    root.mkdir()
    folder = root / "the_folder"
    folder.mkdir()
    paths = {}
    for ext in (".pdf", ".txt", ".py", ".csv", ".zip", ".mp4"):
        p = root / ("a" + ext)
        p.write_text("x", encoding="utf-8")
        paths[ext] = p
    return root, folder, paths


def _strip_count_suffix(value):
    """The whole-name judgment: the counted suffix ({n}) rides the
    same display name, so it is stripped before the comparison."""
    return re.sub(r"\s*\(\{n\}\)\s*$", "", value)


# ---------------------------------------------------------------------------
# NV-T01 - the sidebar structure (§3.2): 21 rows, order, ja/en names,
# headings not selectable, the counted suffix on the six pages only.
# ---------------------------------------------------------------------------

def test_nv_t01_sidebar_structure(tmp_path):
    _require_qt()
    from PySide6.QtCore import Qt
    from sieve_tray_i18n import tr
    win = _make_window(tmp_path)
    try:
        # 21 rows = 5 headings + 16 pages (the §2-6 ruling's count)
        assert win.sidebar.count() == 21, win.sidebar.count()
        for lang in ("en", "ja"):
            w = _make_window(tmp_path, lang=lang)
            try:
                for pos, (kind, key, name_key) in enumerate(SIDEBAR_ROWS):
                    item = w.sidebar.item(pos)
                    if kind == "page":
                        expected = tr(lang, name_key, n=0)
                        assert item.data(Qt.ItemDataRole.UserRole) == key, \
                            (lang, pos, item.data(Qt.ItemDataRole.UserRole))
                        assert item.flags() & Qt.ItemIsSelectable, \
                            (lang, key, "page not selectable")
                    else:
                        expected = tr(lang, name_key)
                        assert not (item.flags() & Qt.ItemIsSelectable), \
                            (lang, key, "heading selectable")
                    assert item.text() == expected, (lang, key, item.text())
                # the page registry skips the headings and keeps the
                # request's order; start is the first page
                assert tuple(w._page_keys) == PAGE_KEYS_16, w._page_keys
            finally:
                if w is not win:
                    w.close()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T03 - last_page (§3.4): the three fallbacks land on start; the
# identifier restore and the closeEvent save stay (birth-green halves
# - they hold since 2.4.0).
# ---------------------------------------------------------------------------

def test_nv_t03_last_page_falls_to_start(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_storage import Storage

    def _key_of_current_row(win):
        # the sidebar row -> the page key (the headings offset the rows)
        row = max(0, win.sidebar.currentRow())
        if 0 <= row < len(win._sidebar_rows):
            kind, key = win._sidebar_rows[row]
            if kind == "page":
                return key
        return None

    # (1) no saved value -> start
    win = _make_window(tmp_path)
    try:
        assert win._page_keys[0] == "start"
        assert _key_of_current_row(win) == "start"
    finally:
        win.close()
    # (2) values that do not read as an identifier -> start (the None
    # shape has no lane of its own: the settings column is NOT NULL, so
    # a missing row already returns the None that case (1) covers)
    for saved in ("", "3", 42):
        store = Storage(tmp_path / "history.db")
        store.set_setting("last_page", saved)
        win = gui.MainWindow(storage=store)
        try:
            assert _key_of_current_row(win) == "start", (saved,)
        finally:
            win.close()
    # (3) an identifier that exists nowhere -> start
    store = Storage(tmp_path / "history.db")
    store.set_setting("last_page", "no_such_page")
    win = gui.MainWindow(storage=store)
    try:
        assert _key_of_current_row(win) == "start"
    finally:
        win.close()
    # the restore and the save keep working on identifiers
    store = Storage(tmp_path / "history.db")
    store.set_setting("last_page", "crowd")
    win = gui.MainWindow(storage=store)
    try:
        assert _key_of_current_row(win) == "crowd"
        win.sidebar.setCurrentRow(win._sidebar_row_of("doc"))
        win.close()
        assert Storage(tmp_path / "history.db").get_setting(
            "last_page") == "doc"
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T05 - the drop candidates (§3.3): the pure function, the corrected
# 2026-11-23 table, the "no page" branch on real file types, and the
# never-read-contents detection.
# ---------------------------------------------------------------------------

def test_nv_t05_drop_candidates_mechanical(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    _root, folder, paths = _drop_fixtures(tmp_path)
    cases = {
        "pdf": [paths[".pdf"]],
        "txt": [paths[".txt"]],
        "py": [paths[".py"]],
        "csv": [paths[".csv"]],
        "folder": [folder],
        "pdf+py": [paths[".pdf"], paths[".py"]],
        "folder+pdf": [folder, paths[".pdf"]],
    }
    for shape, dropped in cases.items():
        got = gui.drop_candidates(dropped)
        assert got == DROP_TABLE[shape], (shape, got)


def test_nv_t05_drop_candidates_none_and_strings(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    import sieve_tray_gui as gui
    _root, _folder, paths = _drop_fixtures(tmp_path)
    # the branch is real: .zip and a video reach it
    assert gui.drop_candidates([paths[".zip"]]) == []
    assert gui.drop_candidates([paths[".mp4"]]) == []
    assert gui.drop_candidates([paths[".zip"], paths[".mp4"]]) == []
    # the decided one-line strings of the drop area exist in both
    # languages (ja 「…」, en "…")
    for lang in ("en", "ja"):
        for key, expected in DROP_STRINGS[lang].items():
            assert tr(lang, key) == expected, (lang, key, tr(lang, key))


def test_nv_t05_drop_candidates_never_read_contents(tmp_path, monkeypatch):
    _require_qt()
    import sieve_tray_gui as gui
    _root, folder, paths = _drop_fixtures(tmp_path)

    def _boom(*_args, **_kwargs):
        raise AssertionError("drop_candidates read file contents")

    for name in ("read_bytes", "read_text", "open", "iterdir"):
        monkeypatch.setattr(Path, name, _boom, raising=False)
    # the mixed folder + pdf + py drop needs is_dir()/suffix only
    got = gui.drop_candidates([folder, paths[".pdf"], paths[".py"]])
    assert got == [
        ("gate", "input", "some"), ("doc", "open", "some"),
        ("cohort", "input", "all"), ("text", "open", "some"),
        ("code", "open", "some"), ("audit", "open", "some"),
        ("rename", "input", "some"), ("clean", "input", "some"),
        ("normalize", "input", "some"), ("manifest", "input", "some"),
    ], got


# ---------------------------------------------------------------------------
# NV-T10 - the names (§3.5): the six new pairs on the sidebar and the
# counted title, the old names absent from the UI wording (whole-name
# match), the decided tooltip sentences, the README alignment.
# ---------------------------------------------------------------------------

def test_nv_t10_renamed_pages_show_the_new_names(tmp_path):
    _require_qt()
    from sieve_tray_i18n import tr
    win = _make_window(tmp_path)
    try:
        for lang in ("en", "ja"):
            w = _make_window(tmp_path, lang=lang)
            try:
                for (lg, key), (name, _name_key) in RENAME_EXPECT:
                    if lg != lang:
                        continue
                    # the counted suffix rides the six measured pages
                    # only; the decided name itself is the expectation
                    template = name + (" ({n})" if key in COUNTED_KEYS
                                       else "")
                    expected = template.format(n=0)
                    row = w._sidebar_row_of(key)
                    item = w.sidebar.item(row)
                    assert item.text() == expected, \
                        (lang, key, item.text())
                    # the counted title rides the new name too
                    w._set_page_title(key, n=2)
                    assert w.sidebar.item(row).text() == \
                        template.format(n=2), (lang, key, "n=2")
            finally:
                if w is not win:
                    w.close()
    finally:
        win.close()


def test_nv_t10_old_names_absent_from_ui_wording():
    import sieve_tray_i18n as i18n
    leftovers = []
    for lang, olds in OLD_NAMES.items():
        old_set = set(olds)
        for key, value in i18n.STRINGS[lang].items():
            if _strip_count_suffix(value) in old_set:
                leftovers.append((lang, key, value))
    assert not leftovers, leftovers


def test_nv_t10_decided_tooltip_sentences_hold(tmp_path):
    _require_qt()
    win = _make_window(tmp_path)
    try:
        for lang in ("en", "ja"):
            w = _make_window(tmp_path, lang=lang)
            try:
                for (lg, key), sentence in DECIDED_TIPS:
                    if lg != lang:
                        continue
                    row = w._sidebar_row_of(key)
                    tip = w.sidebar.item(row).toolTip()
                    assert tip == sentence, (lang, key, tip)
            finally:
                if w is not win:
                    w.close()
    finally:
        win.close()


def test_nv_t10_readme_names_aligned():
    readme_ja = (REPO / "README.ja.md").read_text(encoding="utf-8")
    readme_en = (REPO / "README.md").read_text(encoding="utf-8")
    for name in ("文書の確認", "文章の比較", "コードの比較", "表の匿名化",
                 "全称表現の検出", "マスキング履歴"):
        assert name in readme_ja, ("ja", name)
    for name in ("Check Documents", "Compare Texts", "Compare Code",
                 "Anonymize Tables", "Detect Universal Statements",
                 "Masking History"):
        assert name in readme_en, ("en", name)
