"""Seal 2.2 S9 (request §3.8): the README, the docs and the dependency.

SL-T17: the README Gate/Cohort sections are replaced with the addendum
wording (ja/en), docs/receipt-reference.md exists and is linked from
both READMEs, the old technical words (match_per_mille,
receipt_unreadable, 700 per mille) live in the doc instead of the
README, the three new-feature sections (file list and check code /
rename / draw) follow the same four manners, the icon renders at 96 px
and the screenshots show the 2.2.0 screens (the sidebar and the new
pages) in both languages.

SL-T18: the forbidden screen words (the M2 list plus the overclaim
words) stay out of the README, the docs, the GUI strings and the
verify-page template.

SL-T19: the §3.8-4 decision - the Lens html-css-full extra (tinycss2 +
cssselect2) rides the dependency list, because a bare install cannot
observe the hidden HTML text (measured 2026-11-14: the HTML item is
reported with not_produced_reason engine_unavailable while the same
input is observed, flagged, with the extra installed) - is pinned in
pyproject.toml and stated in the README install note.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

README_EN = REPO_ROOT / "README.md"
README_JA = REPO_ROOT / "README.ja.md"

# the §3.8-1 addendum words: the replaced sections are recognized by
# the exact subtitles the addendum writes (the section is swapped, not
# merely retitled, so the body wording rides along).
JA_GATE_SUBTITLE = "Gate（共有前の書き出し）"
JA_COHORT_SUBTITLE = "Cohort（提出物の比較）"
EN_GATE_SUBTITLE = "Gate (Export for Sharing)"
EN_COHORT_SUBTITLE = "Cohort (Compare Submissions)"

# the three new-feature sections join after Cohort with the same
# manners ((a) what it does in 1-2 sentences, (b) up to 3 numbered
# steps, (c) one command block, (d) one docs link line).
JA_NEW_SECTIONS = ("📋 ファイル一覧と照合コード",
                   "🧹 名前の整理",
                   "🎲 抽選・班分け")
EN_NEW_SECTIONS = ("📋 File List and Check Code",
                   "🧹 Rename",
                   "🎲 Draw")

NEW_SECTION_DOCS = {
    "ja": {"docs/manifest-format.md",
           "docs/rename-procedure.md",
           "docs/draw-procedure.md"},
    "en": {"docs/manifest-format.md",
           "docs/rename-procedure.md",
           "docs/draw-procedure.md"},
}

# the §3.8-6 screenshots: the 2.2.0 screens (the sidebar and the new
# pages) re-shot offscreen, one set per README language.
EXPECTED_SHOTS = ("main-window", "anonymize-tab", "manifest-page",
                  "draw-page")
SHOT_LANGS = ("ja", "en")

# the SL-T18 forbidden screen words: the M2 vocabulary list plus the
# overclaim words (request §4, SL-T18).
FORBIDDEN_SCREEN_WORDS = ("台帳", "封", "鍵", "木",
                          "署名", "改ざんできない", "認証", "公平",
                          "無作為", "作成者の証明")


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body between the given '## ...' heading and the next one."""
    start = text.find(heading)
    assert start != -1, heading
    body = text[start:]
    nxt = body.find("\n## ", 1)
    if nxt != -1:
        body = body[:nxt]
    return body


# ---------------------------------------------------------------------------
# SL-T17: the replaced Gate/Cohort sections, the receipt-reference doc,
# the moved technical words, the three new sections, the icon, the
# screenshots.

def test_t17_gate_cohort_sections_replaced_en_ja():
    ja = _read("README.ja.md")
    en = _read("README.md")
    assert JA_GATE_SUBTITLE in ja, "ja Gate section is not the addendum one"
    assert JA_COHORT_SUBTITLE in ja, "ja Cohort section is not the addendum"
    assert EN_GATE_SUBTITLE in en, "en Gate section is not the addendum one"
    assert EN_COHORT_SUBTITLE in en, "en Cohort section is not the addendum"
    # the addendum manners: the command block per section
    for body in (_section(ja, "🚪 Gate"), _section(ja, "👥 Cohort"),
                 _section(en, "🚪 Gate"), _section(en, "👥 Cohort")):
        assert body.count("```") >= 2, "the command block is missing"


def test_t17_receipt_reference_doc_exists_and_linked():
    doc = REPO_ROOT / "docs" / "receipt-reference.md"
    assert doc.is_file(), "docs/receipt-reference.md is missing"
    assert "docs/receipt-reference.md" in _read("README.ja.md")
    assert "docs/receipt-reference.md" in _read("README.md")


def test_t17_technical_words_moved_to_docs():
    doc = (REPO_ROOT / "docs" / "receipt-reference.md").read_text(
        encoding="utf-8")
    for name in ("README.ja.md", "README.md"):
        text = _read(name)
        for word in ("match_per_mille", "receipt_unreadable", "700"):
            assert word not in text, f"{name} still carries {word!r}"
    for word in ("match_per_mille", "receipt_unreadable", "700"):
        assert word in doc, f"docs/receipt-reference.md lost {word!r}"


def test_t17_new_feature_sections_follow_the_manners():
    for name, sections, lang in (("README.ja.md", JA_NEW_SECTIONS, "ja"),
                                 ("README.md", EN_NEW_SECTIONS, "en")):
        text = _read(name)
        for heading in sections:
            body = _section(text, heading)
            # (b) numbered steps: at least one "1. " line
            assert any(ln.startswith("1. ") for ln in body.splitlines()), \
                f"{name}: {heading} has no numbered steps"
            # (c) one command block
            assert body.count("```") >= 2, \
                f"{name}: {heading} has no command block"
            # (d) the docs link line
            linked = [d for d in NEW_SECTION_DOCS[lang] if d in body]
            assert linked, f"{name}: {heading} has no docs link"


def test_t17_icon_renders_at_96px():
    marker = '<img src="assets/icon.png" width="96"'
    assert marker in _read("README.ja.md"), "ja icon is not at 96 px"
    assert marker in _read("README.md"), "en icon is not at 96 px"


def test_t17_screenshots_show_the_2_2_0_screens():
    refs = set()
    for name in ("README.ja.md", "README.md"):
        text = _read(name)
        for line in text.splitlines():
            if "docs/screenshots/" in line:
                refs.add(line)
    seen = set()
    for ref in refs:
        for key in EXPECTED_SHOTS:
            for lang in SHOT_LANGS:
                if f"{key}-{lang}.png" in ref:
                    seen.add((key, lang))
    expected = {(key, lang) for key in EXPECTED_SHOTS
                for lang in SHOT_LANGS}
    assert seen == expected, sorted(seen ^ expected)
    # every referenced png exists, is a real PNG and is not blank
    import re
    for name in ("README.ja.md", "README.md"):
        for m in re.finditer(r"docs/screenshots/[A-Za-z0-9._-]+\.png",
                             _read(name)):
            path = REPO_ROOT / m.group(0)
            assert path.is_file(), m.group(0)
            data = path.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n", f"not a png: {path}"
            assert len(data) > 10_000, f"too small to be a screenshot: {path}"


# ---------------------------------------------------------------------------
# SL-T18: the forbidden screen words stay out of the README, the docs,
# the GUI strings and the verify-page template.

def test_t18_forbidden_screen_words_readme_docs_gui():
    targets = [README_EN, README_JA]
    targets += sorted((REPO_ROOT / "docs").glob("*.md"))
    targets += [REPO_ROOT / "sieve_tray_i18n.py",
                REPO_ROOT / "sieve_tray.py"]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for word in FORBIDDEN_SCREEN_WORDS:
            assert word not in text, f"{path.name} uses {word!r}"


# ---------------------------------------------------------------------------
# SL-T19: the dependency decision is pinned.

def test_t19_dependency_carries_the_lens_html_css_full_extra():
    pyproject = _read("pyproject.toml")
    dep_line = [ln for ln in pyproject.splitlines()
                if ln.strip().startswith("dependencies = [")]
    assert dep_line, "no dependencies list in pyproject.toml"
    assert "sieve-lens[html-css-full]>=0.22.0" in dep_line[0], dep_line[0]
    # the decision is stated in the install note of both READMEs
    assert "## 📦 インストール" in _read("README.ja.md")
    assert "## 📦 Installation" in _read("README.md")
    for name, head in (("README.ja.md", "## 📦 インストール"),
                       ("README.md", "## 📦 Installation")):
        install = _section(_read(name), head)
        assert "tinycss2" in install and "cssselect2" in install, \
            f"{name}: the install note does not name the extra packages"
