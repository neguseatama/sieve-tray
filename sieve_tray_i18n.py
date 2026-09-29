"""
sieve_tray_i18n.py - minimal i18n layer for the Sieve Tray GUI.

English is the default language; Japanese is selectable from Settings.
This is a deliberately simple flat-dict approach rather than Qt's
.ts/.qm translation-file workflow: the string set is small and fixed,
and avoiding a Qt Linguist build step keeps the PyInstaller packaging
pipeline (already the most fragile part of this project) unchanged.

Usage:
    from sieve_tray_i18n import tr
    tr("en", "run_scan")          -> "Run Scan"
    tr("ja", "run_scan")          -> "スキャン実行"
    tr("en", "doc_tab", n=3)      -> "Documents (3)"
"""

from typing import Dict

SUPPORTED_LANGUAGES = ["en", "ja"]
DEFAULT_LANGUAGE = "en"

LANGUAGE_NAMES = {
    "en": "English",
    "ja": "日本語",
}

STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "window_title": "Sieve Tray",
        "select_folder_placeholder": "Select a folder to scan",
        "browse_folder": "Select Folder...",
        "run_scan": "Run Scan",
        "settings_button": "Settings...",
        "doc_tab": "Documents ({n})",
        "code_tab": "Code Pairs ({n})",
        "text_tab": "Text Similarity ({n})",
        "history_tab": "History ({n})",
        "doc_header_file": "File",
        "doc_header_mask": "Mask",
        "doc_header_status": "Status",
        "code_header_a": "File A",
        "code_header_b": "File B",
        "code_header_mask": "Mask",
        "text_header_a": "File A",
        "text_header_b": "File B",
        "text_header_signal": "Signal",
        "text_header_pattern": "Pattern",
        "history_header_timestamp": "Timestamp (UTC)",
        "history_header_folder": "Folder",
        "history_header_groups": "Groups",
        "history_header_docs": "Documents (flagged)",
        "history_header_code_pairs": "Code Pairs",
        "history_header_text_pairs": "Text Pairs",
        "filter_by_filename": "Filter by filename",
        "flagged_only": "Flagged only",
        "log_label": "Log",
        "export_html": "Export HTML Report",
        "status_flagged": "flagged",
        "status_clean": "clean",
        "scanning": "Scanning...",
        "summary_done": (
            "Done: {groups} groups / Documents {docs} ({flagged} flagged) / "
            "Code Pairs {pairs} / Text Pairs {tpairs}"
        ),
        "summary_history": (
            "Viewing history #{run_id}: {groups} groups / Documents {docs} "
            "({flagged} flagged) / Code Pairs {pairs} / Text Pairs {tpairs}"
        ),
        "summary_error": "An error occurred",
        "error_title": "Error",
        "error_select_valid_folder": "Please select a valid folder.",
        "scan_error_title": "Scan Error",
        "history_load_error": "This history entry could not be loaded.",
        "save_complete_title": "Save Complete",
        "save_complete_message": "Saved to {path}",
        "settings_title": "Settings",
        "settings_export_dir": "Default export folder:",
        "settings_browse": "Browse...",
        "settings_retention": "History retention (0 = unlimited):",
        "settings_retention_unlimited": "Unlimited",
        "settings_language": "Language:",
        "settings_language_note": "(takes effect after restart)",
        "settings_browse_dialog_title": "Select export folder",
        "ok_button": "OK",
        "cancel_button": "Cancel",
        "close_button": "Close",
        "detail_axis_header": "Observation Axis",
        "detail_result_header": "Result",
        "detail_detected": "Detected",
        "detail_not_detected": "Not detected",
        "detail_section_label": "Details",
        "detail_no_extra_info": "No additional details.",
        "detail_scores_label": "Scores:",
        "detail_reason_label": "Reason (from the engine, Japanese only):",
        "detail_doc_title": "Document Detail: {name}",
        "detail_code_title": "Code Pair Detail: {a} / {b}",
        "detail_text_title": "Text Pair Detail: {a} / {b}",
        "choose_folder_dialog_title": "Select a folder to scan",
        "save_report_dialog_title": "Save Report",
    },
    "ja": {
        "window_title": "Sieve Tray",
        "select_folder_placeholder": "スキャンするフォルダを選択してください",
        "browse_folder": "フォルダを選択...",
        "run_scan": "スキャン実行",
        "settings_button": "設定...",
        "doc_tab": "ドキュメント ({n})",
        "code_tab": "コードペア ({n})",
        "text_tab": "テキスト類似度 ({n})",
        "history_tab": "履歴 ({n})",
        "doc_header_file": "ファイル",
        "doc_header_mask": "マスク",
        "doc_header_status": "ステータス",
        "code_header_a": "ファイルA",
        "code_header_b": "ファイルB",
        "code_header_mask": "マスク",
        "text_header_a": "ファイルA",
        "text_header_b": "ファイルB",
        "text_header_signal": "シグナル",
        "text_header_pattern": "パターン",
        "history_header_timestamp": "日時 (UTC)",
        "history_header_folder": "フォルダ",
        "history_header_groups": "グループ",
        "history_header_docs": "文書(フラグ)",
        "history_header_code_pairs": "コードペア",
        "history_header_text_pairs": "テキストペア",
        "filter_by_filename": "ファイル名で絞り込み",
        "flagged_only": "フラグのみ表示",
        "log_label": "ログ",
        "export_html": "HTMLレポートを書き出す",
        "status_flagged": "フラグ",
        "status_clean": "クリーン",
        "scanning": "スキャン中...",
        "summary_done": (
            "完了: {groups}グループ / 文書 {docs}件（うちフラグ {flagged}件） / "
            "コードペア {pairs}件 / テキストペア {tpairs}件"
        ),
        "summary_history": (
            "履歴 #{run_id} を表示中: {groups}グループ / 文書 {docs}件"
            "（うちフラグ {flagged}件） / コードペア {pairs}件 / "
            "テキストペア {tpairs}件"
        ),
        "summary_error": "エラーが発生しました",
        "error_title": "エラー",
        "error_select_valid_folder": "有効なフォルダを選択してください。",
        "scan_error_title": "スキャンエラー",
        "history_load_error": "この履歴は読み込めませんでした。",
        "save_complete_title": "保存完了",
        "save_complete_message": "{path} に書き出しました。",
        "settings_title": "設定",
        "settings_export_dir": "レポートの保存先フォルダ:",
        "settings_browse": "参照...",
        "settings_retention": "履歴の保持件数（0で無制限）:",
        "settings_retention_unlimited": "無制限",
        "settings_language": "言語:",
        "settings_language_note": "（再起動後に反映されます）",
        "settings_browse_dialog_title": "保存先フォルダを選択",
        "ok_button": "OK",
        "cancel_button": "キャンセル",
        "close_button": "閉じる",
        "detail_axis_header": "観測軸",
        "detail_result_header": "結果",
        "detail_detected": "検出",
        "detail_not_detected": "検出なし",
        "detail_section_label": "詳細",
        "detail_no_extra_info": "追加の詳細情報はありません。",
        "detail_scores_label": "スコア:",
        "detail_reason_label": "理由（エンジンからの出力、日本語のみ）:",
        "detail_doc_title": "ドキュメントの詳細: {name}",
        "detail_code_title": "コードペアの詳細: {a} / {b}",
        "detail_text_title": "テキストペアの詳細: {a} / {b}",
        "choose_folder_dialog_title": "スキャンするフォルダを選択",
        "save_report_dialog_title": "レポートを保存",
    },
}

# Human-readable labels for the H1-H7 (or H1-H4) observation axes.
# Different engines use different axis counts/meanings, so each gets
# its own label set, per language.

DOC_AXIS_LABELS = {
    "en": {
        "H1": "Parseability",
        "H2": "Zero-Width Density",
        "H3": "Bidi Controls",
        "H4": "Format Concealment",
        "H5": "Out-of-Band Channel",
        "H6": "Script Mixing",
        "H7": "Contiguous Payload",
    },
    "ja": {
        "H1": "Parseability（解析可能性）",
        "H2": "Zero-Width Density（ゼロ幅文字の密度）",
        "H3": "Bidi Controls（双方向制御文字）",
        "H4": "Format Concealment（書式による隠蔽）",
        "H5": "Out-of-Band Channel（帯域外チャンネル）",
        "H6": "Script Mixing（文字体系の混在）",
        "H7": "Contiguous Payload（連続するペイロード）",
    },
}

CODE_AXIS_LABELS = {
    "en": {
        "H1": "Parseability",
        "H2": "AST Skeleton Match",
        "H3": "Identifier Similarity",
        "H4": "Cluster Safety",
        "H5": "g_POS (Structural Order Hash)",
        "H6": "g_CONST (Constant Set Match)",
        "H7": "g_FREQ (Bi-gram Frequency)",
    },
    "ja": {
        "H1": "Parseability（構文解析可能性）",
        "H2": "AST Skeleton（AST構造の完全一致）",
        "H3": "Identifier Similarity（識別子の類似度）",
        "H4": "Cluster Safety（クラスタ内での昇格）",
        "H5": "g_POS（順序構造ハッシュの一致）",
        "H6": "g_CONST（定数集合の一致）",
        "H7": "g_FREQ（Bi-gram頻度の類似度）",
    },
}

TEXT_AXIS_LABELS = {
    "en": {
        "H1": "Structural Density (character-composition uniqueness)",
        "H2": "Structure Similarity (shared structural template)",
        "H3": "Content Similarity (paraphrase / content overlap)",
        "H4": "Cluster Membership (group of 3+ similar documents)",
    },
    "ja": {
        "H1": "Structural Density（文字構成の独自性）",
        "H2": "Structure Similarity（構造テンプレートの一致）",
        "H3": "Content Similarity（内容・パラフレーズの重複）",
        "H4": "Cluster Membership（3件以上のクラスタ所属）",
    },
}


def normalize_language(lang: str) -> str:
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def tr(lang: str, key: str, **kwargs) -> str:
    lang = normalize_language(lang)
    template = STRINGS[lang].get(key) or STRINGS[DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs) if kwargs else template
