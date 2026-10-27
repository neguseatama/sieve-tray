"""XML adapter: a flat table as ``<table><row><f name="col">value</f>...</row></table>``.

The column name lives in a ``name`` attribute because CSV/JSON column names are arbitrary
strings and must not be forced into XML element names.  Security stance: a DOCTYPE
declaration is rejected outright (it is the only place the entities behind entity-expansion
attacks such as "billion laughs" can be defined), and so are namespaces.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat

from .model import InputError

# Characters XML 1.0 cannot represent at all (tab, LF, CR and the standard ranges are fine).
_XML_ILLEGAL = re.compile(r"[^\t\n\r\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")


def _reject_doctype(*_args: object) -> None:
    raise InputError("the input XML must not declare a DOCTYPE (entity expansion is rejected)")


def _parse(data: bytes) -> ET.Element:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("the input is not valid UTF-8") from None
    # expat directly, so that a DOCTYPE can be rejected before any entity is expanded
    # (ET.XMLParser does not expose its expat handle on every build).
    parser = expat.ParserCreate()
    parser.buffer_text = True
    builder = ET.TreeBuilder()
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = _reject_doctype
    try:
        parser.Parse(text, True)
    except InputError:
        raise
    except expat.ExpatError as exc:
        raise InputError(f"the input is not valid XML ({exc})") from None
    root = builder.close()
    for elem in root.iter():
        if ":" in elem.tag:
            raise InputError("namespaced XML is not supported (remove the xmlns declarations)")
        for attr in elem.attrib:
            if attr == "xmlns" or attr.startswith("xmlns:"):
                raise InputError("namespaced XML is not supported (remove the xmlns declarations)")
    if root.text and root.text.strip():
        raise InputError("unexpected text under the root element")
    return root


def read_xml(data: bytes) -> tuple[list[str], list[list[str]]]:
    root = _parse(data)
    records = list(root)
    if not records:
        raise InputError("the input has no header row")
    header: list[str] = []
    rows: list[list[str]] = []
    for ri, rec in enumerate(records, start=1):
        if rec.attrib:
            raise InputError(f"record {ri} carries unexpected attributes")
        if rec.tail and rec.tail.strip():
            raise InputError(f"unexpected text around record {ri}")
        cells: dict[str, str] = {}
        for field in rec:
            if len(field):
                raise InputError(f"a field in record {ri} is nested; a cell must be plain text")
            name = field.attrib.get("name")
            if name is None:
                raise InputError(f"a field in record {ri} has no 'name' attribute")
            extra = set(field.attrib) - {"name"}
            if extra:
                raise InputError(f"field '{name}' in record {ri} carries unexpected "
                                 f"attributes: {', '.join(sorted(extra))}")
            if name in cells:
                raise InputError(f"record {ri} has field '{name}' twice")
            cells[name] = field.text if field.text is not None else ""
        if ri == 1:
            header = list(cells)
            if not header:
                raise InputError("the input has no header row")
        elif set(cells) != set(header):
            missing = ", ".join(sorted(set(header) - set(cells))) or "-"
            extra = ", ".join(sorted(set(cells) - set(header))) or "-"
            raise InputError(f"record {ri} does not have the columns of record 1 "
                             f"(missing: {missing}; unexpected: {extra})")
        rows.append([cells[h] for h in header])
    return header, rows


def write_xml(header: list[str], rows: list[list[str]]) -> bytes:
    for i, name in enumerate(header, start=1):
        if _XML_ILLEGAL.search(name):
            raise InputError(f"column {i} has a name that XML 1.0 cannot represent")
    for ri, row in enumerate(rows, start=1):
        for name, value in zip(header, row):
            if _XML_ILLEGAL.search(value):
                raise InputError(f"row {ri}, column '{name}': the value contains a character "
                                 f"that XML 1.0 cannot represent")
    root = ET.Element("table")
    for row in rows:
        rec = ET.SubElement(root, "row")
        for name, value in zip(header, row):
            ET.SubElement(rec, "f", {"name": name}).text = value
    ET.indent(root, space="  ")
    return ("<?xml version='1.0' encoding='UTF-8'?>\n"
            + ET.tostring(root, encoding="unicode") + "\n").encode("utf-8")
