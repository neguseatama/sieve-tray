import pytest

from sieve_tray_i18n import (
    tr, normalize_language, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE,
    STRINGS, DOC_AXIS_LABELS, CODE_AXIS_LABELS, TEXT_AXIS_LABELS,
)


def test_default_language_is_english():
    assert DEFAULT_LANGUAGE == "en"


def test_normalize_language_falls_back_to_default():
    assert normalize_language("en") == "en"
    assert normalize_language("ja") == "ja"
    assert normalize_language("fr") == DEFAULT_LANGUAGE
    assert normalize_language("") == DEFAULT_LANGUAGE


def test_tr_basic_lookup():
    assert tr("en", "run_scan") == "Run Scan"
    assert tr("ja", "run_scan") == "スキャン実行"


def test_tr_formats_with_kwargs():
    assert tr("en", "doc_tab", n=3) == "Documents (3)"
    assert tr("ja", "doc_tab", n=3) == "ドキュメント (3)"


def test_tr_unknown_language_falls_back_to_english():
    assert tr("fr", "run_scan") == tr("en", "run_scan")


def test_tr_unknown_key_returns_key_itself():
    assert tr("en", "this_key_does_not_exist") == "this_key_does_not_exist"


def test_every_key_present_in_both_languages():
    en_keys = set(STRINGS["en"])
    ja_keys = set(STRINGS["ja"])
    assert en_keys == ja_keys, (
        f"key mismatch: en-only={en_keys - ja_keys}, "
        f"ja-only={ja_keys - en_keys}"
    )


@pytest.mark.parametrize("labels,axis_count", [
    (DOC_AXIS_LABELS, 7),
    (CODE_AXIS_LABELS, 7),
    (TEXT_AXIS_LABELS, 4),
])
def test_axis_labels_cover_expected_axes_in_both_languages(labels, axis_count):
    expected_keys = {f"H{i}" for i in range(1, axis_count + 1)}
    for lang in SUPPORTED_LANGUAGES:
        assert set(labels[lang]) == expected_keys
