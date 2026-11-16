"""Draft the timing-after-MI review file (SPEC.md "Timing after MI").

Usage:
    .venv\\Scripts\\python scripts\\draft_timing.py

Reads Claude's draft label for each trial from
review/timing_suggestions_claude.csv (acute / recent / prior, or blank when
the inclusion criteria name no index MI), checks that each draft's evidence
quote appears word for word in the trial's inclusion criteria, and writes
review/timing_after_mi.csv with the rows the project owner checks:
  - every draft that is not "acute" (including blank: no index MI found)
  - every uncertain draft
  - every trial without a draft, or whose evidence quote is not found (e.g.
    the registry text changed)
Sure "acute" drafts with a found quote go into the database without review
(load_timing.py).

Rows that already have a decision are never changed. Nothing is written to
the database.
"""

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from create_database import DB_PATH, connect
from draft_cleaning import merge_with_existing, trial_link
from fetch_trials import inclusion_criteria
from review_files import REVIEW_DIR, read_csv, write_csv

ROOT = Path(__file__).resolve().parent.parent
SUGGESTIONS = REVIEW_DIR / "timing_suggestions_claude.csv"
REVIEW_FILE = REVIEW_DIR / "timing_after_mi.csv"
LABELS = {"acute", "recent", "prior"}
CONTEXT_CHARS = 120

REASON_NON_ACUTE = "not acute"
REASON_NO_INDEX = "no index MI in inclusion criteria"
REASON_UNCERTAIN = "uncertain draft"
REASON_NO_DRAFT = "no draft yet"
REASON_QUOTE = "evidence quote not found"
REASON_ORDER = {REASON_NON_ACUTE: 0, REASON_UNCERTAIN: 1, REASON_NO_INDEX: 2, REASON_QUOTE: 3,
                REASON_NO_DRAFT: 4}

COLUMNS = ["review_reason", "ctgov_link", "title", "draft_timing", "draft_confidence",
           "evidence", "draft_note", "decision", "corrected_timing", "comment",
           "evidence_context", "nct_id"]
OWNER_COLUMNS = ["decision", "corrected_timing", "comment"]


def one_line(text):
    return " ".join((text or "").split())


def inclusion_text(raw_file):
    """Inclusion criteria on one line (whole eligibility text if there is no
    'Exclusion Criteria' heading), or None if the raw file is missing."""
    path = ROOT / raw_file if raw_file else None
    if not path or not path.exists():
        return None
    p = json.loads(path.read_text(encoding="utf-8"))["protocolSection"]
    elig = p.get("eligibilityModule", {}).get("eligibilityCriteria") or ""
    inc = inclusion_criteria(elig)
    return one_line(inc if inc is not None else elig)


def check_quote(text, quote):
    """(found, context): the quote with some text around it, so the owner can read it."""
    quote = one_line(quote)
    if not quote:
        return True, ""
    if not text or quote not in text:
        return False, ""
    i = text.index(quote)
    a, b = max(0, i - CONTEXT_CHARS), min(len(text), i + len(quote) + CONTEXT_CHARS)
    return True, ("..." if a else "") + text[a:b] + ("..." if b < len(text) else "")


def load_suggestions():
    if not SUGGESTIONS.exists():
        return {}
    return {r["nct_id"]: r for r in read_csv(SUGGESTIONS)}


def drafts(con):
    """[(nct_id, title, suggestion or None, quote found, context, reason or None)]."""
    suggestions = load_suggestions()
    out = []
    for nct_id, title, raw_file in con.execute(
            "SELECT nct_id, title, raw_json_file FROM trials ORDER BY nct_id"):
        s = suggestions.get(nct_id)
        text = inclusion_text(raw_file)
        found, context = check_quote(text, s["evidence"]) if s else (False, "")
        if s is None:
            reason = REASON_NO_DRAFT
        elif not found:
            reason = REASON_QUOTE
        elif not s["suggested_timing"]:
            reason = REASON_NO_INDEX
        elif s["suggested_timing"] != "acute":
            reason = REASON_NON_ACUTE
        elif s["confidence"] != "sure":
            reason = REASON_UNCERTAIN
        else:
            reason = None
        out.append((nct_id, title, s, found, context, reason))
    return out


def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    con = connect()
    try:
        items = drafts(con)
    except sqlite3.Error as e:
        print(f"STOPPED: {e}")
        print("Summary: records in 0, out 0, skipped 0 (stopped; no file written)")
        sys.exit(1)
    finally:
        con.close()

    bad_labels = [n for n, _, s, _, _, _ in items
                  if s and s["suggested_timing"] and s["suggested_timing"] not in LABELS]
    if bad_labels:
        print(f"STOPPED: unknown label in {SUGGESTIONS.name} for {', '.join(bad_labels)}")
        print("Summary: no file written")
        sys.exit(1)

    rows = []
    for nct_id, title, s, found, context, reason in items:
        if reason is None:
            continue
        rows.append({
            "review_reason": reason, "ctgov_link": trial_link(nct_id), "title": title,
            "draft_timing": s["suggested_timing"] if s else "",
            "draft_confidence": s["confidence"] if s else "",
            "evidence": s["evidence"] if s else "", "draft_note": s["note"] if s else "",
            "decision": "", "corrected_timing": "", "comment": "",
            "evidence_context": context, "nct_id": nct_id})
    rows.sort(key=lambda r: (REASON_ORDER[r["review_reason"]], r["draft_timing"] or "z",
                             r["nct_id"]))
    merged, counts = merge_with_existing(REVIEW_FILE, ["nct_id"], rows, OWNER_COLUMNS)
    try:
        write_csv(REVIEW_FILE, COLUMNS, merged)
    except PermissionError:
        print(f"STOPPED: {REVIEW_FILE} is open in another program (probably Excel). "
              "Save and close it, then run this script again.")
        print("Summary: no file written")
        sys.exit(1)

    counts = {k.replace("no longer in the database", "no longer selected for review"): v
              for k, v in counts.items()}
    n_auto = sum(1 for i in items if i[5] is None)
    print(f"Trials in the database: {len(items)}")
    print("Claude's drafts: " + ", ".join(
        f"{k or 'blank (no index MI)'} {v}" for k, v in
        Counter(s["suggested_timing"] for _, _, s, _, _, _ in items if s).most_common()))
    print("On the review sheet: " + ", ".join(
        f"{k} {v}" for k, v in Counter(r["review_reason"] for r in rows).most_common()))
    print(f"Sure acute drafts with the quote found (go in without review): {n_auto}")
    print(f"{REVIEW_FILE.name}: {len(merged)} rows "
          f"({', '.join(f'{k} {v}' for k, v in counts.items())})")
    print(f"Summary: records in {len(items)} trials, out {len(merged)} rows in the review "
          f"file, skipped {n_auto} (sure acute drafts, loaded without review)")


if __name__ == "__main__":
    main()
