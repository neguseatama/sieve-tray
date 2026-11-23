"""NV (迷わない画面) 2.5.0 - the red tests (NV-T01, T03, T05, T10 of the
first wave; NV-T02, T04, T06-T09, T11, T12 of the second wave).

The second wave landed after the implementation (b55ae6b), so its red
is proven retro-verified against the 2.4.0 tree (ef533c3): the tests
fail there too, with two recorded exceptions - NV-T08 (the scan-row
scoping was already complete on 2.4.0 and start does not exist there,
so its new half cannot fail on that tree) and NV-T11's golden halves
(an invariance pin cannot fail on its own reference tree; the red half
of NV-T11 is the changed header value).  Each test says so in its own
comment.

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

NV-T13 (2.5.1) lands red-first on the 2.5.0 tree (7321041): the 21 row
names must be unique per language - the 2.5.0 grp_history heading rode
the same string (履歴 / History) the kept history page already carried.
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


# ===========================================================================
# The second wave (NV-T02, T04, T06-T09, T11, T12).  The implementation
# was already in (b55ae6b) when these landed, so the red is proven
# retro-verified: each test also runs against the 2.4.0 tree (ef533c3)
# and must fail there.  The reasons are recorded in the delivery note.
# ===========================================================================

# ---------------------------------------------------------------------------
# NV-T02 (§3.2): the arrow keys skip the headings and Ctrl/Cmd+1..9
# count the PAGES only (start=1 .. table_diff=9).  Retro-verified red on
# 2.4.0: _select_page_at(1) selects _page_keys[1] there (the old
# row-counting without start), i.e. Ctrl+1 lands on code - the mapping
# this test refuses.
# ---------------------------------------------------------------------------

def test_nv_t02_keyboard_skips_headings_and_ctrl_digits(tmp_path):
    _require_qt()
    from PySide6.QtCore import Qt as QtCore
    from PySide6.QtGui import QShortcut
    from PySide6.QtTest import QTest
    win = _make_window(tmp_path)
    try:
        win.show()
        # Ctrl+1..9: the first nine PAGES, the headings never counted
        win._select_page_at(1)
        assert win._page_keys[win.pages.currentIndex()] == "start", \
            win._page_keys[win.pages.currentIndex()]
        win._select_page_at(2)
        assert win._page_keys[win.pages.currentIndex()] == "gate"
        win._select_page_at(5)
        assert win._page_keys[win.pages.currentIndex()] == "cohort"
        win._select_page_at(9)
        assert win._page_keys[win.pages.currentIndex()] == "table_diff"
        # outside 1..9 the selection does not move
        win._select_page_at(0)
        assert win._page_keys[win.pages.currentIndex()] == "table_diff"
        win._select_page_at(10)
        assert win._page_keys[win.pages.currentIndex()] == "table_diff"
        # the shortcuts are registered (Ctrl+1 .. Ctrl+9)
        seqs = [sc.key().toString().lower()
                for sc in win.findChildren(QShortcut)]
        for pos in range(1, 10):
            assert ("ctrl+%d" % pos) in seqs, seqs
        # the arrows skip the non-selectable headings: a Down from
        # start lands on gate (row 2), never on the heading (row 1)
        win.sidebar.setCurrentRow(0)
        QTest.keyClick(win.sidebar, QtCore.Key_Down)
        assert win.sidebar.currentRow() == 2, win.sidebar.currentRow()
        assert win._page_keys[win.pages.currentIndex()] == "gate"
        QTest.keyClick(win.sidebar, QtCore.Key_Down)
        assert win.sidebar.currentRow() == 3, win.sidebar.currentRow()
        # Up from gate skips the heading back to start
        win.sidebar.setCurrentRow(win._sidebar_row_of("gate"))
        QTest.keyClick(win.sidebar, QtCore.Key_Up)
        assert win.sidebar.currentRow() == 0, win.sidebar.currentRow()
        # Down from doc skips grp_compare and lands on cohort
        win.sidebar.setCurrentRow(win._sidebar_row_of("doc"))
        QTest.keyClick(win.sidebar, QtCore.Key_Down)
        assert win._page_keys[win.pages.currentIndex()] == "cohort"
        # the top edge stays put
        win.sidebar.setCurrentRow(0)
        QTest.keyClick(win.sidebar, QtCore.Key_Up)
        assert win.sidebar.currentRow() == 0, win.sidebar.currentRow()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T04 (§3.3): the はじめに page - four cards, the card titles ride
# the i18n card keys, the links move to their pages, the link text is
# built from the registration table's names and tooltip sentences.
# Retro-verified red on 2.4.0: the Start page does not exist there
# (AttributeError: 'MainWindow' object has no attribute 'start_page').
# ---------------------------------------------------------------------------

def test_nv_t04_start_page_cards_built_from_defs(tmp_path):
    _require_qt()
    import sieve_tray_gui as gui
    from sieve_tray_i18n import tr
    from PySide6.QtWidgets import QGroupBox, QLabel
    win = _make_window(tmp_path)
    try:
        win.show()
        start = win.start_page
        win._select_page("start")
        assert win.pages.currentWidget() is start
        # the intro line
        intro = start.layout().itemAt(0).widget()
        assert intro.text() == tr(win.lang, "start_intro"), intro.text()
        # four cards, in the START_CARDS order, no history card
        cards = start.findChildren(QGroupBox)
        assert [c.title() for c in cards] == \
            [tr(win.lang, key) for key, _keys in gui.START_CARDS], \
            [c.title() for c in cards]
        assert tuple(win._page_keys[:1]) == ("start",)
        for card, (title_key, keys) in zip(cards, gui.START_CARDS):
            rows = card.findChildren(QLabel)
            assert len(rows) == len(keys), (title_key, len(rows))
            for row, key in zip(rows, keys):
                # the link targets the page; the text is the page's
                # display name plus its one-sentence tooltip
                m = re.search(r'<a href="([^"]+)">', row.text())
                assert m is not None and m.group(1) == key, \
                    (title_key, row.text())
                d = next(d for d in gui.PAGE_DEFS if d["key"] == key)
                name = tr(win.lang, d["name_key"], n=0) \
                    if key in COUNTED_KEYS else tr(win.lang, d["name_key"])
                assert name in row.text(), (title_key, key, row.text())
                tip = tr(win.lang, d["tip_key"])
                assert row.toolTip() == tip, (title_key, key, row.toolTip())
        # the records never ride a card (history pages stay out)
        joined = "".join(r.text() for c in cards
                         for r in c.findChildren(QLabel))
        for key in ("history", "sanitize_history", "start"):
            assert ('href="%s"' % key) not in joined, key
        # the card links move the page (the real signal path)
        first_row = cards[0].findChildren(QLabel)[0]
        first_row.linkActivated.emit(
            re.search(r'<a href="([^"]+)">', first_row.text()).group(1))
        assert win._page_keys[win.pages.currentIndex()] == "gate"
        # and the start-page helper navigates alike
        win._select_page("start")
        start._open_page("clean")
        assert win._page_keys[win.pages.currentIndex()] == "clean"
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T06 (§3.3): an input candidate moves the page AND fills its input
# (clean file-or-folder, crowd file, the six folder walks); the output
# fields stay untouched; an open candidate only opens.
# Retro-verified red on 2.4.0: open_drop_candidate does not exist there.
# ---------------------------------------------------------------------------

def test_nv_t06_input_candidates_fill_the_input(tmp_path):
    _require_qt()
    win = _make_window(tmp_path)
    try:
        win.show()
        _root, folder, paths = _drop_fixtures(tmp_path)

        def _current():
            return win._page_keys[win.pages.currentIndex()]

        # clean: a file and a folder both land in the input
        win.open_drop_candidate("clean", "input", [paths[".pdf"]])
        assert _current() == "clean"
        assert win.clean_page.clean_input_edit.text() == str(paths[".pdf"])
        assert win.clean_page.clean_output_edit.text() == "", "output moved"
        win.open_drop_candidate("clean", "input", [folder])
        assert win.clean_page.clean_input_edit.text() == str(folder)
        # crowd: the first dropped file the page handles, in drop order
        loaded = []
        win.crowd_load_file = loaded.append
        win.open_drop_candidate("crowd", "input",
                                [paths[".py"], paths[".csv"]])
        assert loaded == [paths[".csv"]], loaded
        # the folder walks take the dropped folder (the input edits
        # live on the page widgets: win.gate_page.gate_input_edit, ...)
        pages = {"gate": win.gate_page, "cohort": win.cohort_page,
                 "rename": win.rename_page,
                 "normalize": win.normalize_page,
                 "manifest": win.manifest_page,
                 "clean": win.clean_page}
        for key, attr in (("gate", "gate_input_edit"),
                          ("cohort", "cohort_input_edit"),
                          ("rename", "rename_input_edit"),
                          ("normalize", "normalize_input_edit"),
                          ("manifest", "manifest_input_edit")):
            win.open_drop_candidate(key, "input", [folder])
            assert _current() == key, (key, _current())
            assert getattr(pages[key], attr).text() == str(folder), key
        # the outputs never moved (the §2-5 ruling's 出力欄は常に触らない)
        assert win.gate_page.gate_output_edit.text() == ""
        assert win.cohort_page.cohort_output_edit.text() == ""
        assert win.clean_page.clean_output_edit.text() == ""
        # an open candidate only opens: a file on gate (mode open)
        # never writes the input field (the folder the earlier input
        # step filled stays exactly as it was)
        before = win.gate_page.gate_input_edit.text()
        win.open_drop_candidate("gate", "open", [paths[".pdf"]])
        assert _current() == "gate"
        assert win.gate_page.gate_input_edit.text() == before
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T07 (§3.1): the registered types reference the ENGINE constants -
# no copies.  The straight lanes are the same objects; the derived ones
# equal them; rename and manifest carry no extension constant (the
# 2026-11-23 ruling: folder drops only); table_diff carries the one
# type the engine import accepts; clean's .pdf rides CN_CLEAN_EXTS.
# Retro-verified red on 2.4.0: PAGE_DEFS does not exist there.
# ---------------------------------------------------------------------------

def test_nv_t07_registered_types_reference_engine_constants():
    import sieve_canon
    import sieve_tray
    import sieve_tray_gui as gui
    from sieve_crowd import tableio
    defs = {d["key"]: d for d in gui.PAGE_DEFS}
    # the straight lanes are the SAME objects (a copy would break `is`)
    assert defs["gate"]["file_exts"] is sieve_tray.GATE_DOC_EXTS
    assert defs["doc"]["file_exts"] is sieve_tray.DOC_EXTS
    assert defs["text"]["file_exts"] is sieve_tray.TEXT_EXTS
    assert defs["code"]["file_exts"] is sieve_tray.CODE_EXTS
    assert defs["audit"]["file_exts"] is sieve_tray.TEXT_EXTS
    assert defs["normalize"]["file_exts"] is sieve_canon.CN_TEXT_EXTS
    # the derived lanes equal the engine constants
    assert set(defs["crowd"]["file_exts"]) == set(tableio._EXTENSIONS)
    assert set(defs["clean"]["file_exts"]) == set(sieve_canon.CN_CLEAN_EXTS)
    # clean's PDF lane (the 2.4.0 widening) rides the engine constant
    assert ".pdf" in defs["clean"]["file_exts"]
    assert ".pdf" in sieve_canon.CN_CLEAN_EXTS
    # cohort: the three-lane composition of the real engine constants
    assert defs["cohort"]["file_exts"] == (
        frozenset(sieve_tray.GATE_DOC_EXTS)
        | frozenset(sieve_tray.CODE_EXTS)
        | frozenset(sieve_tray.COHORT_GENERIC_EXTENSIONS))
    # table_diff: the one type the engine import actually accepts
    # (sieve_canon.run_table_diff has no extension constant; it reads
    # comma-CSV)
    assert defs["table_diff"]["file_exts"] == {".csv"}
    assert callable(sieve_canon.run_table_diff)
    # rename and manifest walk every file: no extension constant, so
    # the folder drop is their only candidate lane (2026-11-23)
    for key in ("rename", "manifest"):
        assert defs[key].get("file_exts") is None, key
        assert defs[key]["folder_input"] is True, key
    # draw is a helper field (the roster): no drop lane at all (§2-5)
    assert defs["draw"].get("file_exts") is None
    assert defs["draw"].get("folder_input") is None
    # start / history / sanitize_history carry no lanes
    for key in ("start", "history", "sanitize_history"):
        assert not defs[key].get("file_exts"), key
        assert not defs[key].get("folder_input"), key
    # the folder walks deliver the folder (input) or open only
    assert defs["gate"]["folder_delivers"] is True
    assert defs["cohort"]["folder_delivers"] is True
    assert defs["doc"]["folder_delivers"] is False


# ---------------------------------------------------------------------------
# NV-T08 (§3.2): the scan operation row shows on the scan pages only
# (doc / code / text / audit) and stays hidden on every other page -
# on Start too.  NOT retro-verified red (and why): the scan row's
# four-page scoping was already complete on 2.4.0 (the v2.2.0 plan B),
# and the Start page does not exist there, so the one new half - the
# row stays hidden on start - cannot fail on that tree.  What this
# test pins: the scoping carries over to the 2.5.0 page set unchanged
# (16 pages, start included, hidden) while the pages grow around it.
# ---------------------------------------------------------------------------

def test_nv_t08_scan_row_rides_the_four_scan_pages_only(tmp_path):
    _require_qt()
    from PySide6.QtWidgets import QApplication
    scan_pages = frozenset({"doc", "code", "text", "audit"})
    win = _make_window(tmp_path)
    try:
        win.show()
        for key in win._page_keys:
            win._select_page(key)
            win.repaint()
            QApplication.processEvents()
            visible = win.scan_row_widget.isVisible()
            assert visible == (key in scan_pages), (key, visible)
        # the Start page never carries the scan row
        assert "start" not in scan_pages
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T09 (§3.2 + §2-7): the three points of 「切れない」 at 880x560,
# ja/en and light/dark - (1) every page body and the Start content
# reach (scroll included), (2) all 21 sidebar rows are reachable by
# scroll, (3) the selected row enters the viewport (the last_page
# restore and Ctrl/Cmd+digit alike).  The width stays 160..240px.
# Retro-verified red on 2.4.0: the sidebar there counts 15 rows, not 21.
# ---------------------------------------------------------------------------

def test_nv_t09_min_size_renders_every_row_and_page(tmp_path):
    _require_qt()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                               QScrollArea)
    app = QApplication.instance()

    def _check(win, lang, label):
        win.resize(880, 560)
        win.show()
        win.repaint()
        QApplication.processEvents()
        sb = win.sidebar
        # the width rule (§2-7: the clamp stays)
        assert 160 <= sb.width() <= 240, (label, sb.width())
        # (2) all 21 rows are reachable by scroll
        assert sb.count() == 21, (label, sb.count())
        vh = sb.viewport().height()
        assert vh > 0, (label, vh)
        for row in range(sb.count()):
            sb.scrollToItem(sb.item(row),
                            QAbstractItemView.ScrollHint.EnsureVisible)
            win.repaint()
            QApplication.processEvents()
            r = sb.visualItemRect(sb.item(row))
            assert r.top() < vh and r.bottom() > 0, \
                (label, row, r.top(), r.bottom(), vh)
        # (3) the selected row enters the viewport: the tail page via
        # the Ctrl/Cmd+digit path (the restore path rides its own test
        # below - the restore and the digit share _ensure_row_visible)
        win._select_page_at(9)
        win.repaint()
        QApplication.processEvents()
        r = sb.visualItemRect(sb.item(sb.currentRow()))
        assert r.top() >= 0 and r.bottom() <= vh - 1, \
            (label, "selected", r.top(), r.bottom(), vh)
        # (1) every page body renders uncut inside the window; the
        # scroll pages' full content stays reachable (scroll included)
        for key in win._page_keys:
            win._select_page(key)
            win.repaint()
            QApplication.processEvents()
            page = win.pages.currentWidget()
            top = page.mapTo(win, QPoint(0, 0))
            assert top.x() >= 0, (label, key, top)
            assert top.x() + page.width() <= win.width() + 1, \
                (label, key, top, page.width())
            assert page.width() >= 600, (label, key, page.width())
            rendered = page.grab()
            assert not rendered.isNull(), (label, key)
            assert rendered.width() >= 600, (label, key, rendered.width())
            if isinstance(page, QScrollArea):
                w = page.widget()
                if w is not None and w.height() > page.viewport().height():
                    smax = page.verticalScrollBar().maximum()
                    reach = smax + page.viewport().height()
                    assert reach >= w.height() - 2, \
                        (label, key, reach, w.height())
        # the Start content reaches too (the cards and the drop area)
        win._select_page("start")
        win.repaint()
        QApplication.processEvents()
        start = win.start_page
        bottom = start.drop_area.mapTo(win, QPoint(0, 0)).y() \
            + start.drop_area.height()
        assert bottom <= win.height() + 1, (label, bottom, win.height())

    # the light palette, both languages
    for lang in ("en", "ja"):
        win = _make_window(tmp_path, lang=lang)
        try:
            _check(win, lang, ("light", lang))
        finally:
            win.close()
    # the dark palette, both languages (the same three points)
    saved = app.palette()
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(221, 221, 221))
    dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    dark.setColor(QPalette.ColorRole.Text, QColor(221, 221, 221))
    dark.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark.setColor(QPalette.ColorRole.ButtonText, QColor(221, 221, 221))
    dark.setColor(QPalette.ColorRole.PlaceholderText,
                  QColor(138, 138, 138))
    try:
        app.setPalette(dark)
        for lang in ("en", "ja"):
            win = _make_window(tmp_path, lang=lang)
            try:
                _check(win, lang, ("dark", lang))
            finally:
                win.close()
    finally:
        app.setPalette(saved)


def test_nv_t09_last_page_restore_enters_the_viewport(tmp_path):
    _require_qt()
    from PySide6.QtWidgets import QApplication
    from sieve_tray_storage import Storage
    # the restore path of the third point: the saved identifier is the
    # LAST row of the 21 - after the window shows, the row is in view
    Storage(tmp_path / "history.db").set_setting(
        "last_page", "sanitize_history")
    win = _make_window(tmp_path)
    try:
        win.resize(880, 560)
        win.show()
        win.repaint()
        QApplication.processEvents()
        sb = win.sidebar
        row = sb.currentRow()
        assert win._sidebar_rows[row] == ("page", "sanitize_history"), \
            win._sidebar_rows[row]
        vh = sb.viewport().height()
        r = sb.visualItemRect(sb.item(row))
        assert r.top() >= 0 and r.bottom() <= vh - 1, \
            ("restore", r.top(), r.bottom(), vh)
    finally:
        win.close()


# ---------------------------------------------------------------------------
# NV-T11 (§3.5 + §3.6): the UI-wording change stayed OUT of the
# outputs.  The changed keys ride the GUI module only; the report
# renderer's two i18n keys keep their 2.4.0 values; the HTML and the
# Markdown reports render byte-identical to the 2.4.0 tree (the
# goldens below are the ef533c3 bytes, measured 2026-11-23 by running
# the same corpus through both trees - tools/nv_golden_experiment.py;
# report.html and report.md diffed EMPTY); the history allowlists, the
# receipt schema and the self-check counts (gate 15 / clean 6) keep
# their 2.4.0 shape, with tool.version the one documented exception.
# NOT retro-verified red (and why): the golden halves pass on 2.4.0 by
# construction - the reference IS the 2.4.0 output, so an invariance
# pin cannot fail on its own reference tree.  The red half of this
# test is (a): the changed header value, which 2.4.0 still words the
# old way ('Code Pairs' / 'コードペア' != 'Compare Code' / 'コードの比較').
# ---------------------------------------------------------------------------

GOLDEN_UNOBSERVED_NOTE_EN = (
    "Unobserved reports that the observation did not establish; "
    "it does not mean the file is problem-free.")
GOLDEN_CROWD_PREMISE_EN = (
    "Protection holds only against an outsider who knows the columns "
    "you declared as qi.")

# the keys the 2.5.0 wording change moved (the i18n VALUES only)
CHANGED_UI_KEYS = (
    "doc_tab", "text_tab", "code_tab", "audit_tab", "crowd_tab",
    "sanitize_history_tab", "sanitize_history_title",
    "history_header_code_pairs")

# the manifest receipt's top-level keys (the 2.4.0 schema)
RECEIPT_KEYS_240 = frozenset({
    "receipt_version", "kind", "tool", "engines", "settings",
    "items", "skipped", "duplicates", "summary", "digest"})

# the report corpus (tools/nv_golden_experiment.py builds the same
# ScanResult on both trees; the goldens are the 2.4.0 bytes)
GOLDEN_REPORT_HTML = """<!DOCTYPE html>
<html><head><meta charset='UTF-8'>
<title>Sieve Tray Report</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
       max-width: 960px; margin: 2rem auto; padding: 0 1rem;
       color: #1a1a1a; background: #fafafa; }
h1 { font-size: 1.5rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }
th, td { text-align: left; padding: .5rem .8rem;
         border-bottom: 1px solid #eee; font-size: .9rem; }
th { background: #f0f0f0; }
tr.flagged { background: #fff5f5; }
code { font-family: Menlo, monospace; font-size: .85em; }

tr.unobserved-remedy { background: #fff4d6; }
tr.unobserved-environment { background: #f0f0f0; }
tr.unobserved-excluded { background: #f8f8f8; }</style></head><body>
<h1>Sieve Tray Report</h1>
<p>1 groups scanned. Unobserved: 2.</p>
<h2>Documents</h2>
<table><tr><th>File</th><th>Mask</th><th>Status</th></tr>
<tr><td><code>/in/essay_a.txt</code></td><td><code>1000-000</code></td><td>clean</td></tr>
<tr class='flagged'><td><code>/in/essay_b.txt</code></td><td><code>1100-000</code></td><td>flagged</td></tr>
<tr class='unobserved unobserved-remedy'><td><code>/in/broken.docx</code></td><td><code>0000-000</code></td><td>unobserved (unreadable)</td></tr>
</table>
<h2>Code Pairs</h2>
<table><tr><th>File A</th><th>File B</th><th>Mask</th></tr>
<tr class='flagged'><td><code>/in/calc_v1.py</code></td><td><code>/in/calc_v2.py</code></td><td><code>1111-111</code></td></tr>
</table>
<p>3 code pair(s) skipped as trivially dissimilar (short-circuited).</p>
<h2>Text Pairs</h2>
<table><tr><th>File A</th><th>File B</th><th>Signal</th><th>Pattern</th></tr>
<tr class='flagged'><td><code>/in/essay_a.txt</code></td><td><code>/in/essay_b.txt</code></td><td>RED</td><td>shared_rare_trigram</td></tr>
</table>
<h2>Quantifier Audit</h2>
<table><tr><th>File</th><th>Sentence</th><th>Signal</th><th>Pattern</th><th>Backing</th><th>Scope</th><th>Certainty</th></tr>
<tr class='flagged'><td><code>/in/essay_a.txt</code></td><td>All students must submit the report.</td><td>RED</td><td>universal_necessity</td><td>must</td><td>sentence</td><td>must</td></tr>
</table>
<h2>Unobserved</h2>
<p>Unobserved reports that the observation did not establish; it does not mean the file is problem-free.</p>
<table><tr><th>File</th><th>Engine</th><th>Reason</th><th>Detail</th></tr>
<tr class='unobserved unobserved-remedy'><td><code>/in/broken.docx</code></td><td>lens</td><td>unreadable</td><td>\u2014</td></tr>
<tr class='unobserved unobserved-remedy'><td><code>/in/huge.bin</code></td><td>lens</td><td>too_large</td><td>42 MB</td></tr>
</table>
<h2>Crowd</h2>
<p>Protection holds only against an outsider who knows the columns you declared as qi.</p>
<table><tr><th>Input</th><th>Output</th><th>Records In</th><th>Records Out</th><th>Suppressed</th><th>k Achieved</th><th>Max Risk</th><th>Avg Risk</th><th>Status</th><th>Reason</th></tr>
<tr><td>/in/roster.csv</td><td>/out/roster.csv</td><td>10</td><td>9</td><td>1</td><td>2</td><td>0.5</td><td>0.25</td><td>ok</td><td>\u2014</td></tr>
</table>
<p style='margin-top:2rem;color:#666;font-size:.85rem;'>This is an observation report, not a judgment. Human review is required.</p>
</body></html>"""

GOLDEN_REPORT_MD = """# Sieve Tray Report

_1 groups scanned. Unobserved: 2._

## Documents
| File | Mask | Status |
| --- | --- | --- |
| `/in/essay_a.txt` | `1000-000` | clean |
| `/in/essay_b.txt` | `1100-000` | flagged |
| `/in/broken.docx` | `0000-000` | unobserved (unreadable) |

## Code Pairs
| File A | File B | Mask |
| --- | --- | --- |
| `/in/calc_v1.py` | `/in/calc_v2.py` | `1111-111` |

_3 code pair(s) skipped as trivially dissimilar (short-circuited)._

## Text Pairs
| File A | File B | Signal | Pattern |
| --- | --- | --- | --- |
| `/in/essay_a.txt` | `/in/essay_b.txt` | RED | shared_rare_trigram |

## Quantifier Audit
| File | Sentence | Signal | Pattern | Backing | Scope | Certainty |
| --- | --- | --- | --- | --- | --- | --- |
| `/in/essay_a.txt` | All students must submit the report. | RED | universal_necessity | must | sentence | must |

## Unobserved

Unobserved reports that the observation did not establish; it does not mean the file is problem-free.

| File | Engine | Reason | Detail |
| --- | --- | --- | --- |
| `/in/broken.docx` | lens | unreadable | \u2014 |
| `/in/huge.bin` | lens | too_large | 42 MB |

## Crowd

Protection holds only against an outsider who knows the columns you declared as qi.

| Input | Output | Records In | Records Out | Suppressed | k Achieved | Max Risk | Avg Risk | Status | Reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/in/roster.csv` | `/out/roster.csv` | 10 | 9 | 1 | 2 | 0.5 | 0.25 | ok | \u2014 |

_This is an observation report, not a judgment. Human review is required._"""


def _golden_result():
    """The representative ScanResult (every section, including the two
    i18n-referencing ones - Unobserved and Crowd)."""
    from sieve_tray import ScanResult
    return ScanResult(
        groups=[("group_a", [Path("/in/essay_a.txt"),
                             Path("/in/essay_b.txt")])],
        doc_results=[
            {"path": "/in/essay_a.txt", "mask": "1000-000",
             "flagged": False, "h_states": {}, "evidence": {}},
            {"path": "/in/essay_b.txt", "mask": "1100-000",
             "flagged": True, "h_states": {"h1": "hidden"},
             "evidence": {"h1": ["U+200B ZERO WIDTH SPACE"]}},
            {"path": "/in/broken.docx", "mask": "0000-000",
             "flagged": False, "h_states": {}, "evidence": {},
             "error": "FileNotFoundError"},
        ],
        code_pairs=[
            {"a": "/in/calc_v1.py", "b": "/in/calc_v2.py",
             "mask": "1111-111"},
        ],
        text_pairs=[
            {"a": "/in/essay_a.txt", "b": "/in/essay_b.txt",
             "signal": "RED", "pattern_name": "shared_rare_trigram"},
        ],
        audit_results=[
            {"file": "/in/essay_a.txt",
             "sentence_text": "All students must submit the report.",
             "signal": "RED", "pattern_name": "universal_necessity",
             "backing": "must", "scope": "sentence",
             "certainty_markers": ["must"]},
        ],
        crowd_runs=[{
            "input_path": "/in/roster.csv",
            "output_path": "/out/roster.csv",
            "records_in": 10, "records_out": 9, "suppressed": 1,
            "k_achieved": 2, "max_risk": 0.5, "avg_risk": 0.25,
            "status": "ok", "reason": None,
        }],
        unobserved=[{"file": "/in/huge.bin", "engine": "lens",
                     "reason": "too_large", "detail": "42 MB"}],
        short_circuited_excluded=3,
    )


def test_nv_t11_records_reports_and_cli_stay_2_4_0(tmp_path):
    import sieve_tray
    from sieve_tray import render, render_text, run_manifest
    from sieve_tray_i18n import tr
    import sieve_tray_storage
    # (a) the wording change happened in the UI keys (red on 2.4.0:
    # the history column header still reads Code Pairs / コードペア there)
    assert tr("ja", "history_header_code_pairs") == "コードの比較", \
        tr("ja", "history_header_code_pairs")
    assert tr("en", "history_header_code_pairs") == "Compare Code", \
        tr("en", "history_header_code_pairs")
    # (b) the changed keys ride the GUI module only - the record / JSON
    # / CLI / report layer (sieve_tray.py, sieve_tray_storage.py) never
    # names them
    for src in ("sieve_tray.py", "sieve_tray_storage.py"):
        text = (REPO / src).read_text(encoding="utf-8")
        for key in CHANGED_UI_KEYS:
            assert ("'%s'" % key) not in text and ('"%s"' % key) \
                not in text, (src, key)
    # and the report renderer's two i18n keys keep the 2.4.0 values
    assert tr("en", "unobserved_note") == GOLDEN_UNOBSERVED_NOTE_EN
    assert tr("en", "crowd_result_premise") == GOLDEN_CROWD_PREMISE_EN
    # (c) the reports render byte-identical to the 2.4.0 tree
    result = _golden_result()
    html = render(result)
    md = render_text(result)
    assert html == GOLDEN_REPORT_HTML, \
        "\n".join(l for l in html.splitlines()
                  if l not in GOLDEN_REPORT_HTML.splitlines())
    assert md == GOLDEN_REPORT_MD, \
        "\n".join(l for l in md.splitlines()
                  if l not in GOLDEN_REPORT_MD.splitlines())
    # (d) the history allowlists keep their 2.4.0 members
    assert sieve_tray_storage.CROWD_PAYLOAD_ALLOWLIST == frozenset({
        "input_path", "output_path",
        "records_in", "records_out", "suppressed",
        "k_achieved", "max_risk", "avg_risk",
        "status", "reason", "report_text",
    })
    assert sieve_tray_storage.COHORT_RUN_ALLOWLIST == frozenset({
        "run_id", "ts_utc", "items", "compared", "not_compared",
        "pairs_flagged", "removed_total", "receipt_digest", "engines",
    })
    # (e) the receipt schema: the 2.4.0 keys; tool.version is the one
    # documented exception (the release item)
    in_dir = tmp_path / "receipt_input"
    in_dir.mkdir()
    (in_dir / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (in_dir / "beta.txt").write_text("beta\n", encoding="utf-8")
    receipt = run_manifest(in_dir, tmp_path / "receipt_out")
    assert set(receipt) == RECEIPT_KEYS_240, sorted(receipt)
    assert receipt["receipt_version"] == 1
    assert receipt["kind"] == "sieve-manifest"
    assert receipt["tool"] == {"name": "sieve-tray",
                               "version": sieve_tray.__version__}
    # (f) the self-checks keep the 2.4.0 counts (gate 15 / clean 6)
    from sieve_canon import clean_self_check
    from sieve_tray import gate_self_check
    g = gate_self_check(progress=None)
    assert (g["expected"], g["matching"], g["differences"]) == \
        (15, 15, []), (g["expected"], g["matching"], g["differences"])
    c = clean_self_check(progress=None)
    assert (c["expected"], c["matching"], c["differences"]) == \
        (6, 6, []), (c["expected"], c["matching"], c["differences"])


# ---------------------------------------------------------------------------
# NV-T12 (§3.6): the release pack - the version, the README (title,
# the Start/drop sentence), docs/page-registry.md, the CHANGELOG
# [2.5.1] entry (2.5.1: the pin rides the current release; the [2.5.0]
# entry stays in the file), the re-shot screenshots (the 2.4.0 bytes
# are gone; the sidebar text change re-shot the pair again) and the
# forbidden words: no old display name occupies a NAME position (an
# image alt text or a heading) in the READMEs or the docs.
# Retro-verified red on 2.4.0: the version reads 2.4.0 there, the
# [2.5.0] CHANGELOG entry and docs/page-registry.md do not exist.
# ---------------------------------------------------------------------------

README_240_SCREENSHOT_SHA = {
    "ja": "89e3acd304d7c2bb5368dd90fe99eabaf97d26d97d9e8bc689a027587e5d17a4",
    "en": "d411e51cc7c54c5779593625f420d52d101991e7a36f7cf4d80c0a032c08112a",
}


def test_nv_t12_release_pack_2_5_1(tmp_path):
    import hashlib
    import sieve_tray
    # the version
    assert sieve_tray.__version__ == "2.5.1", sieve_tray.__version__
    # the READMEs: the title, the Start/drop sentence
    readme_ja = (REPO / "README.ja.md").read_text(encoding="utf-8")
    readme_en = (REPO / "README.md").read_text(encoding="utf-8")
    for text in (readme_ja, readme_en):
        assert "# Sieve Tray v2.5.1" in text
    assert "はじめに" in readme_ja and "ドロップすると" in readme_ja
    assert "**Start**" in readme_en \
        and "dropping a file or a folder on it lists the pages" in readme_en
    # docs/page-registry.md: the registration table's home and the
    # add-a-page steps
    registry = REPO / "docs" / "page-registry.md"
    assert registry.exists(), "docs/page-registry.md is missing"
    registry_text = registry.read_text(encoding="utf-8")
    assert "PAGE_DEFS" in registry_text
    assert "sieve_tray_gui.py" in registry_text
    # the CHANGELOG entry
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [2.5.1]" in changelog
    assert "### Added" in changelog and "### Changed" in changelog
    for name in ("Check Documents", "Compare Texts", "Compare Code",
                 "Anonymize Tables", "Detect Universal Statements",
                 "Masking History", "文書の確認", "文章の比較", "コードの比較",
                 "表の匿名化", "全称表現の検出", "マスキング履歴"):
        assert name in changelog, name
    # the screenshots were re-shot for 2.5.0 and again for 2.5.1 - the
    # en pair is byte-different (the sidebar width rides the widened
    # View History row); the ja pair re-saves byte-identical because the
    # changed rows 18-20 sit below the 960x640 fold and the ja width is
    # set by other rows, so no visible pixel changes (measured: the item
    # carries the new 履歴を見る text, visualItemRect(18) is outside the
    # viewport in both languages)
    for lang, fname in (("ja", "main-window-ja.png"),
                        ("en", "main-window-en.png")):
        p = REPO / "docs" / "screenshots" / fname
        assert p.exists(), fname
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest != README_240_SCREENSHOT_SHA[lang], \
            (fname, "still the 2.4.0 bytes")
    # the forbidden words: no old display name occupies a NAME position
    # (an image alt text or a heading) in the READMEs or the docs
    # (the whole-name discipline: the old name as THE name, not as a
    # word inside a sentence or an engine-lane description)
    old_names = {"ja": ("ドキュメント", "テキスト類似度", "コードペア",
                        "匿名化", "量化子監査", "サニタイズ履歴"),
                 "en": ("Documents", "Code Pairs", "Text Similarity",
                        "Anonymize", "Quantifier Audit",
                        "Sanitize History")}
    name_positions = [re.compile(r"!\[([^\]]*)\]"),
                      re.compile(r"^#+\s*(.+?)\s*$", re.M)]
    files = [REPO / "README.md", REPO / "README.ja.md"]
    files += sorted((REPO / "docs").glob("*.md"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        for pat in name_positions:
            for m in pat.finditer(text):
                segment = m.group(1).strip()
                for lang, olds in old_names.items():
                    assert segment not in olds, \
                        (f.name, lang, segment)


# ---------------------------------------------------------------------------
# NV-T13 (2.5.1): the 21 sidebar row names are unique per language -
# the counted suffix stripped, no heading lands on a page name.  Red on
# the 2.5.0 tree (7321041): the grp_history heading (履歴 / History)
# collides with the adjacent history page (履歴 (0) / History (0)) in
# both languages - the user's Mac acceptance counted the 21 rows and
# saw 履歴 twice.  NV-T01 could not see it: it reads each row's expected
# name from the same dictionary it asserts against, so a
# dictionary-internal collision passes the structure pin.
# ---------------------------------------------------------------------------

def test_nv_t13_sidebar_row_names_unique(tmp_path):
    _require_qt()
    from PySide6.QtCore import Qt
    win = _make_window(tmp_path)
    try:
        for lang in ("en", "ja"):
            w = _make_window(tmp_path, lang=lang)
            try:
                seen = {}
                for pos in range(w.sidebar.count()):
                    item = w.sidebar.item(pos)
                    # the rendered counted suffix (the (0) form) must not
                    # mask a collision - compare the base names
                    base = re.sub(r"\s*\(\d+\)\s*$", "", item.text())
                    kind = ("page"
                            if item.flags() & Qt.ItemIsSelectable
                            else "head")
                    seen.setdefault(base, []).append(
                        (kind, pos, item.text()))
                dups = {k: v for k, v in seen.items() if len(v) > 1}
                assert not dups, (lang, dups)
            finally:
                if w is not win:
                    w.close()
    finally:
        win.close()
