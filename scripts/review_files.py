"""Reading and writing the review CSV files in review/ (shared by the cleaning scripts)."""

import csv
from pathlib import Path

REVIEW_DIR = Path(__file__).resolve().parent.parent / "review"
DECISIONS = {"approve", "correct"}


def read_csv(path):
    """Read a review CSV. Accepts UTF-8 (with or without BOM) or the Windows
    encoding, and commas or semicolons (Excel uses either, depending on settings)."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delimiter))


def write_csv(path, columns, rows):
    """Write a review CSV as UTF-8 with BOM, so Excel shows accents correctly."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})


def decision_of(row):
    """'approve', 'correct', '' (not reviewed yet), or the unknown text as given."""
    return (row.get("decision") or "").strip().lower()


def has_decision(row):
    return decision_of(row) != ""
