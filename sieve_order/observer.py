from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

AXES = ("H2", "H3", "H4", "H5", "H6", "H7")
EVIDENCE_CONTEXT_RADIUS = 12

# The supported language surfaces are deliberately limited to Japanese and English.
REQUEST_PATTERNS = (
    # Japanese
    ("request:kudasai", re.compile(r"してください")),
    ("request:kudasai_variant", re.compile(r"して下さい")),
    ("request:itadakemasu", re.compile(r"していただけますか")),
    ("request:kudasaimasenka", re.compile(r"してくださいませんか")),
    ("request:shite", re.compile(r"(?<![\u3040-\u309f])して(?=$|[。！？])")),
    ("request:onegaishimasu", re.compile(r"お願いします")),
    ("request:onegaidekimasuka", re.compile(r"お願いできますか")),
    # English. These are request surfaces, not politeness or intent judgments.
    ("request:en_please", re.compile(r"\bplease\b", re.IGNORECASE)),
    ("request:en_could_you", re.compile(r"\bcould\s+you\b", re.IGNORECASE)),
    ("request:en_would_you", re.compile(r"\bwould\s+you\b", re.IGNORECASE)),
    ("request:en_can_you", re.compile(r"\bcan\s+you\b", re.IGNORECASE)),
    ("request:en_i_would_like_you_to", re.compile(r"\bi\s+would\s+like\s+you\s+to\b", re.IGNORECASE)),
)

ACTIONS = (
    # Japanese
    "確認", "取得", "削除", "表示", "送信", "実行", "変更", "保存", "開く", "検索", "生成", "提出", "作成", "入力", "閲覧",
    # English
    "check", "get", "delete", "display", "send", "execute", "change", "save", "open", "search", "generate", "submit", "create", "enter", "view",
)
TARGETS = (
    # Japanese
    "情報", "資料", "データ", "ファイル", "URL", "内容", "結果", "設定", "文書", "回答", "コード", "認証情報",
    # English
    "information", "document", "data", "file", "URL", "content", "result", "settings", "answer", "code", "credentials",
)

# The menu is intentionally small and explicit. It is vocabulary, not semantics.
MENU = {
    "REQUEST": tuple(code for code, _ in REQUEST_PATTERNS),
    "ACTION": ACTIONS,
    "TARGET": TARGETS,
}

H4_RE = re.compile(
    r"(?:以前の指示|上の指示|これまでの指示|システム指示|優先順位|役割)(?:を|は).{0,12}?(?:無視|変更|上書き|最優先|忘れ)"
    r"|(?:ignore|disregard|override|forget|prioritize).{0,24}(?:instructions?|rules?|system\s+instructions?)"
    r"|(?:system\s+instructions?|previous\s+instructions?|above\s+instructions?|instructions?).{0,12}(?:ignore|disregard|override|forget|prioritize)",
    re.IGNORECASE,
)
H6_CONTROL_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
H6_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/])")
H7_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
H7_FILE_RE = re.compile(
    r"(?:添付|参照|読み込んで|開いて).{0,12}(?:ファイル|文書|PDF|CSV)"
    r"|(?:attached|reference|referenced|load|open).{0,12}(?:file|document|PDF|CSV)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Evidence:
    axis: str
    code: str
    matched: str
    start: int
    end: int


@dataclass(frozen=True)
class Order:
    request: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observation:
    mask: str
    evidence: tuple[Evidence, ...]
    order: Order
    metrics: Mapping[str, int]
    unobservable: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        # Canonical JSON-compatible observation form. Lists are intentional:
        # the same representation must survive the Human/Machine receipt boundary.
        return {
            "mask": self.mask,
            "evidence": [asdict(e) for e in self.evidence],
            "order": {
                "request": list(self.order.request),
                "actions": list(self.order.actions),
                "targets": list(self.order.targets),
            },
            "metrics": dict(self.metrics),
            "unobservable": list(self.unobservable),
        }


UNOBSERVABLE = (
    "intent",
    "legality",
    "morality",
    "maliciousness",
    "truth_of_external_claims",
    "model_specific_token_count",
)


def _evidence(axis: str, code: str, match: re.Match[str]) -> Evidence:
    return Evidence(axis, code, match.group(0), match.start(), match.end())


def _find_request(prompt: str) -> list[Evidence]:
    found: list[Evidence] = []
    for code, pattern in REQUEST_PATTERNS:
        for match in pattern.finditer(prompt):
            found.append(_evidence("H2", code, match))
    return found


def _word_menu_pattern(items: tuple[str, ...]) -> re.Pattern[str]:
    escaped = sorted(map(re.escape, items), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(escaped) + r")(?![A-Za-z])", re.IGNORECASE)


def _find_order(prompt: str, request_evidence: list[Evidence]) -> tuple[Order, list[Evidence]]:
    evidence: list[Evidence] = []

    # H3 is an explicitly observable local ACTION/TARGET relation.
    # Japanese surface: TARGET + particle + ACTION.
    ja_targets = tuple(item for item in TARGETS if (not re.fullmatch(r"[A-Za-z]+", item) or item == "URL"))
    ja_actions = tuple(item for item in ACTIONS if not re.fullmatch(r"[A-Za-z]+", item))
    ja_target_group = "|".join(map(re.escape, sorted(ja_targets, key=len, reverse=True)))
    ja_action_group = "|".join(map(re.escape, sorted(ja_actions, key=len, reverse=True)))
    if ja_targets and ja_actions:
        ja_pair_pattern = re.compile(
            rf"(?P<target>{ja_target_group})(?P<particle>を|は)(?P<action>{ja_action_group})"
        )
        for match in ja_pair_pattern.finditer(prompt):
            evidence.append(Evidence("H3", "action_target", match.group(0), match.start(), match.end()))

    # English surface: ACTION + TARGET. This remains local lexical adjacency;
    # no semantic expansion or cross-order pairing is performed.
    en_targets = tuple(item for item in TARGETS if re.fullmatch(r"[A-Za-z]+", item))
    en_actions = tuple(item for item in ACTIONS if re.fullmatch(r"[A-Za-z]+", item))
    en_action_group = "|".join(map(re.escape, sorted(en_actions, key=len, reverse=True)))
    en_target_group = "|".join(map(re.escape, sorted(en_targets, key=len, reverse=True)))
    en_linker = r"(?:the|a|an|this|that|my|your)"
    if en_targets and en_actions:
        en_pair_pattern = re.compile(
            rf"(?<![A-Za-z])(?P<action>{en_action_group})\s+(?:(?:{en_linker})\s+)?(?P<target>{en_target_group})(?![A-Za-z])",
            re.IGNORECASE,
        )
        for match in en_pair_pattern.finditer(prompt):
            evidence.append(Evidence("H3", "action_target", match.group(0), match.start(), match.end()))

    # ACTION and TARGET are menu items, so they can be observed independently
    # without inventing the missing counterpart. Preserve their source order.
    def find_menu_items(items: tuple[str, ...]) -> list[tuple[int, str]]:
        pattern = _word_menu_pattern(items)
        return [(match.start(), match.group(0)) for match in pattern.finditer(prompt)]

    action_matches = find_menu_items(ACTIONS)
    target_matches = find_menu_items(TARGETS)
    actions = tuple(dict.fromkeys(item for _, item in sorted(action_matches)))
    targets = tuple(dict.fromkeys(item for _, item in sorted(target_matches)))

    return Order(("REQUEST",) if request_evidence else (), actions, targets), evidence


def _find_rule_matches(prompt: str, rules: Iterable[Mapping[str, Any]] | None) -> list[Evidence]:
    found: list[Evidence] = []
    for rule in rules or ():
        rule_id = str(rule.get("id", "unnamed"))
        pattern = re.compile(str(rule["pattern"]))
        for match in pattern.finditer(prompt):
            found.append(_evidence("H5", f"rule_match:{rule_id}", match))
    return found


def _find_axis_regex(prompt: str, axis: str, code: str, pattern: re.Pattern[str]) -> list[Evidence]:
    return [_evidence(axis, code, m) for m in pattern.finditer(prompt)]


def observe(prompt: str, rules: Iterable[Mapping[str, Any]] | None = None) -> Observation:
    request_evidence = _find_request(prompt)
    order, h3 = _find_order(prompt, request_evidence)
    evidence = request_evidence + h3
    evidence += _find_axis_regex(prompt, "H4", "hierarchy_interference", H4_RE)
    evidence += _find_rule_matches(prompt, rules)
    evidence += _find_axis_regex(prompt, "H6", "invisible_control", H6_CONTROL_RE)
    evidence += _find_axis_regex(prompt, "H6", "base64_like_surface", H6_BASE64_RE)
    evidence += _find_axis_regex(prompt, "H7", "url", H7_URL_RE)
    evidence += _find_axis_regex(prompt, "H7", "file_reference", H7_FILE_RE)

    present = {axis for axis in (e.axis for e in evidence)}
    mask = "".join("1" if axis in present else "0" for axis in AXES)
    metrics = {
        "text_length": len(prompt),
        "token_units": len(re.findall(r"\S+|\s", prompt)),
    }
    return Observation(mask, tuple(evidence), order, metrics, UNOBSERVABLE)


def _evidence_context(source: str, evidence: Evidence, radius: int = EVIDENCE_CONTEXT_RADIUS) -> str:
    """Render source context around an already-observed evidence span."""
    start = max(0, evidence.start - radius)
    end = min(len(source), evidence.end + radius)
    before = source[start:evidence.start]
    matched = source[evidence.start:evidence.end]
    after = source[evidence.end:end]
    return f"{before}[{matched}]{after}"


def make_receipt(observation: Observation, source: str | None = None) -> str:
    """Project one Observation into a human-readable receipt.

    OBSERVED RELATIONS are rendered only from H3 evidence. No missing
    TARGET/ACTION relationship is inferred. If source text is supplied,
    evidence locations are rendered with source context; context is display
    only and does not add a new observation.
    """
    relations = [e.matched for e in observation.evidence if e.axis == "H3"]
    lines = [
        "AI INPUT RECEIPT",
        f"MASK: {observation.mask}",
        "",
        "REQUEST",
        f"  {', '.join(observation.order.request) or '-'}",
        "",
        "ACTION",
        f"  {', '.join(observation.order.actions) or '-'}",
        "",
        "TARGET",
        f"  {', '.join(observation.order.targets) or '-'}",
        "",
        "OBSERVED RELATIONS",
    ]
    if relations:
        lines.extend(f"  {relation}" for relation in relations)
    else:
        lines.append("  -")
    if source is not None and observation.evidence:
        lines.extend(["", "EVIDENCE LOCATIONS"])
        for evidence in observation.evidence:
            context = _evidence_context(source, evidence)
            lines.append(
                f"  {evidence.axis}/{evidence.code} [{evidence.start}:{evidence.end}] {context!r}"
            )

    lines.extend([
        "",
        f"EVIDENCE_COUNT: {len(observation.evidence)}",
        f"TEXT_LENGTH: {observation.metrics['text_length']}",
        "JUDGMENT: NOT_PERFORMED",
    ])
    return "\n".join(lines)


def make_machine_receipt(observation: Observation) -> str:
    """Project the same Observation into a machine-readable receipt."""
    payload = {
        "receipt": {
            "kind": "AI_INPUT_RECEIPT",
            "judgment": "NOT_PERFORMED",
        },
        "observation": observation.to_dict(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
