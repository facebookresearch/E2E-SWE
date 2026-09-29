#!/usr/bin/env python3
"""Emit quickfix.field.* Java classes from FIX data-dictionary XMLs.

Replaces the quickfixj-codegenerator Maven plugin. The plugin walks every <field> element
under <fields> in each dictionary XML and emits a trivial typed subclass of the appropriate
Field<T> base (StringField, IntField, DoubleField, CharField, BooleanField,
UtcTimeStampField, UtcDateOnlyField, UtcTimeOnlyField), populated with:
  - a public static final int FIELD = <tag>;
  - a no-arg constructor
  - a typed-value constructor
  - static constants for each <value enum="..." description="..."> child

We only need the ~50 field classes the shipped reference (base + core subset) actually imports.
Callers pass the list explicitly via --only "Name1 Name2 ..." to avoid emitting the full 900+.

Usage:
    python3 generate_fields.py --xml FIX44.xml --xml FIXT11.xml --out /app/src/quickfix/field \\
        --only "MsgType HeartBtInt SendingTime ApplVerID ..."
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# FIX type -> (Java field base class, Java value type for the typed constructor).
# `None` for value_type means no typed constructor (only the no-arg default is emitted).
TYPE_MAP = {
    "STRING":               ("StringField",        "String"),
    "MULTIPLECHARVALUE":    ("StringField",        "String"),
    "MULTIPLEVALUESTRING":  ("StringField",        "String"),
    "MULTIPLESTRINGVALUE":  ("StringField",        "String"),
    "CURRENCY":             ("StringField",        "String"),
    "EXCHANGE":             ("StringField",        "String"),
    "COUNTRY":              ("StringField",        "String"),
    "LANGUAGE":             ("StringField",        "String"),
    "LOCALMKTDATE":         ("StringField",        "String"),
    "MONTHYEAR":            ("StringField",        "String"),
    "TZTIMEONLY":           ("StringField",        "String"),
    "TZTIMESTAMP":          ("StringField",        "String"),
    "XMLDATA":              ("StringField",        "String"),
    "DATA":                 ("StringField",        "String"),
    "INT":                  ("IntField",           "int"),
    "LENGTH":               ("IntField",           "int"),
    "SEQNUM":               ("IntField",           "int"),
    "TAGNUM":               ("IntField",           "int"),
    "NUMINGROUP":           ("IntField",           "int"),
    "DAYOFMONTH":           ("IntField",           "int"),
    "PRICE":                ("DoubleField",        "double"),
    "QTY":                  ("DoubleField",        "double"),
    "AMT":                  ("DoubleField",        "double"),
    "FLOAT":                ("DoubleField",        "double"),
    "PERCENTAGE":           ("DoubleField",        "double"),
    "PRICEOFFSET":          ("DoubleField",        "double"),
    "CHAR":                 ("CharField",          "char"),
    "BOOLEAN":              ("BooleanField",       "boolean"),
    "UTCTIMESTAMP":         ("UtcTimeStampField",  "LocalDateTime"),
    "UTCDATEONLY":          ("UtcDateOnlyField",   "LocalDate"),
    "UTCDATE":              ("UtcDateOnlyField",   "LocalDate"),
    "UTCTIMEONLY":          ("UtcTimeOnlyField",   "LocalTime"),
}

# Sanitize an XML <value description="..."> into a legal Java identifier constant name.
def sanitize(desc: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in desc).upper()
    if out and out[0].isdigit():
        out = "_" + out
    return out or "UNKNOWN"

# Emit a single class body (returns the .java source text).
def emit(name: str, tag: int, ftype: str, values: list[tuple[str, str]]) -> str:
    if ftype not in TYPE_MAP:
        raise ValueError(f"Unsupported FIX type '{ftype}' for field '{name}'")
    base, jtype = TYPE_MAP[ftype]
    imports = ["quickfix." + base]
    if jtype == "LocalDateTime":
        imports += ["java.time.LocalDateTime"]
    elif jtype == "LocalDate":
        imports += ["java.time.LocalDate"]
    elif jtype == "LocalTime":
        imports += ["java.time.LocalTime"]
    lines = ["/* Generated Java Source File */", "package quickfix.field;"]
    for imp in imports:
        lines.append(f"import {imp};")
    lines.append("")
    lines.append(f"public class {name} extends {base} {{")
    lines.append("    static final long serialVersionUID = 552892318L;")
    lines.append("")
    lines.append(f"    public static final int FIELD = {tag};")

    for enum_val, desc in values:
        const = sanitize(desc)
        if jtype == "boolean":
            bval = "true" if enum_val in ("Y", "true", "1") else "false"
            lines.append(f"    public static final boolean {const} = {bval};")
        elif jtype == "int":
            lines.append(f"    public static final int {const} = {enum_val};")
        elif jtype == "char":
            lines.append(f"    public static final char {const} = '{enum_val}';")
        else:
            escaped = enum_val.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'    public static final String {const} = "{escaped}";')

    lines.append("")
    lines.append(f"    public {name}() {{ super({tag}); }}")
    if jtype:
        # Boxed-wrapper convenience overload for primitives (matches upstream shape).
        if jtype == "int":
            lines.append(f"    public {name}(Integer data) {{ super({tag}, data); }}")
        elif jtype == "boolean":
            lines.append(f"    public {name}(Boolean data) {{ super({tag}, data); }}")
        elif jtype == "char":
            lines.append(f"    public {name}(Character data) {{ super({tag}, data); }}")
        elif jtype == "double":
            lines.append(f"    public {name}(Double data) {{ super({tag}, data); }}")
        lines.append(f"    public {name}({jtype} data) {{ super({tag}, data); }}")
    lines.append("}")
    return "\n".join(lines) + "\n"


# Fallbacks for fields the CORE subset imports but the modern dictionaries don't define
# (they were retired between FIX 4.4 and 5.0). Keeping them here lets us ship only the modern
# dictionaries (FIX44, FIXT11, FIX50SP2) instead of the full 9-file set.
LEGACY_FIELDS = {
    "OnBehalfOfSendingTime": (370, "UTCTIMESTAMP", []),
}


def collect_fields(xml_paths: list[Path]) -> dict:
    """Merge <field> elements across dictionaries by (name).
    Later dictionaries add fields that earlier ones lack (e.g., ApplVerID is in FIXT11 only)."""
    fields = dict(LEGACY_FIELDS)
    for path in xml_paths:
        root = ET.parse(path).getroot()
        for f in root.findall(".//fields/field"):
            name = f.attrib["name"]
            tag = int(f.attrib["number"])
            ftype = f.attrib["type"].upper()
            values = [(v.attrib["enum"], v.attrib.get("description", v.attrib["enum"]))
                      for v in f.findall("value")]
            if name not in fields or name in LEGACY_FIELDS:
                fields[name] = (tag, ftype, values)
    return fields


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", action="append", required=True,
                    help="Path to a FIX data-dictionary XML (repeatable)")
    ap.add_argument("--out", required=True, help="Output directory for .java files")
    ap.add_argument("--only", required=True,
                    help="Space-separated list of field-class names to emit")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    all_fields = collect_fields([Path(p) for p in args.xml])
    wanted = args.only.split()
    missing = [n for n in wanted if n not in all_fields]
    if missing:
        print(f"ERROR: fields not found in any dictionary: {missing}", file=sys.stderr)
        sys.exit(1)

    for name in wanted:
        tag, ftype, values = all_fields[name]
        (out_dir / f"{name}.java").write_text(emit(name, tag, ftype, values))

    print(f"Wrote {len(wanted)} field classes to {out_dir}")


if __name__ == "__main__":
    main()
