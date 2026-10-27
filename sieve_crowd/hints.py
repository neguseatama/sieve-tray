"""Hints for `inspect`: a *suggestion* per column, never applied automatically."""
from __future__ import annotations

import re

_ID = {"name", "email", "mail", "phone", "tel", "mobile", "address", "ssn", "passport", "firstname", "lastname",
       "氏名", "名前", "姓", "メール", "電話", "携帯", "住所", "マイナンバー", "免許", "会員番号", "顧客番号"}
_QI = {"age", "zip", "zipcode", "postal", "postcode", "sex", "gender", "birth", "birthday", "birthdate", "dob",
       "city", "prefecture", "pref", "occupation", "job", "年齢", "郵便", "性別", "生年月日", "誕生",
       "市区町村", "都道府県", "職業"}
_POSTAL = {"zip", "zipcode", "postal", "postcode", "郵便"}
_SENSITIVE = {"diagnosis", "disease", "illness", "salary", "income", "religion", "病名", "診断", "病歴", "給与",
              "年収", "収入", "信条", "宗教"}


def _matches(name: str, words: set[str]) -> bool:
    low = name.lower()
    tokens = set(re.split(r"[^a-z0-9]+", low)) - {""}
    return any((w in tokens) if w.isascii() else (w in name) for w in words)


def hint(name: str, info: dict, n: int) -> tuple[str | None, str, str]:
    """(suggested role or None, English text, Japanese text)."""
    if _matches(name, _ID):
        return "id", "looks like a direct identifier: usually role id", "直接識別子のようです。通常は役割 id"
    if _matches(name, _SENSITIVE):
        return "sensitive", "looks sensitive: usually role sensitive", "機微な情報のようです。通常は役割 sensitive"
    if _matches(name, _QI):
        if _matches(name, _POSTAL):
            extra, extra_ja = " (postal codes: type prefix)", "（郵便番号：type prefix）"
        else:
            extra = {"integer": " (numbers: type numeric)", "date": " (dates: type date)"}.get(info["shape"], "")
            extra_ja = {"integer": "（数値：type numeric）", "date": "（日付：type date）"}.get(info["shape"], "")
        return "qi", "an outsider may already know this: usually role qi" + extra, \
            "部外者がすでに知っているかもしれない情報です。通常は役割 qi" + extra_ja
    if n >= 20 and info["unique_ratio"] >= 0.95:
        return "id", "every value is different: usually role id or drop", "値がすべて異なります。通常は役割 id か drop"
    return None, "no hint", "ヒントなし"
