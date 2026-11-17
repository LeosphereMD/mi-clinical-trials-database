"""Pipeline step 8: load the extracted values and the owner's review decisions into SQLite.

Usage:  .venv\\Scripts\\python scripts\\load_reviewed_results.py

Reads (never writes):
  review/review_sheet.xlsx (the owner's my_decision / corrected_value / my_note),
  review/paper_list.csv (paper details), and through scripts/build_review_sheet.py
  the agent outputs and checks/<NCT>_quote_check.csv (rebuilt in memory, so each sheet
  row is matched back to its value by trial, paper, comparison, arm, outcome, field and
  the value shown).
Writes data/ami_trials.db:
  publications + trial_publications (main results papers),
  extracted_values (inserted, or updated in place by its fixed identity: nct_id +
    publication_id + arm + comparison + outcome + field + item_no; SPEC table 8;
    item_no numbers the rows of one field in the agent's order, e.g. one row per MACE
    component, and is 1 for a single row),
  review_decisions (one new row per sheet decision; a decision identical to one already
    stored for that value is skipped, so re-running adds nothing), then the owner's
    later decisions in LATER_DECISIONS (each added once, after the sheet's).

Decision mapping (decision 11): sheet "correct" -> approve; "wrong" with a corrected
value -> correct; "wrong" without one -> reject. "unclear" is not a SPEC decision: it is
not stored, and the value stays not reviewed. An empty my_decision = not reviewed.

review_reason (owner, 2026-11-17): flagged (flagged on the sheet the owner reviewed) /
critical value (decision 10: primary effect measure, effect value, 95% CI, p-value;
total randomized and per-arm N randomized) / remaining.

Label check (decision 32, owner condition 2026-11-17): every value's arm and each side of
its comparison must be a registry arm label, a " + " join of registry arm labels, or,
for a decision-31 factorial trial, a factor group / comparison name of that paper.
Any value that fails is refused (not loaded) and listed.

Missing data stays empty; nothing is guessed.
"""
import csv
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_review_sheet as brs  # noqa: E402
from create_database import connect  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "review" / "review_sheet.xlsx"

CRITICAL_PRIMARY = {"effect measure", "effect value", "95% CI lower", "95% CI upper", "p-value"}
CRITICAL_TRIAL = {"total randomized", "N randomized"}

# Owner-confirmed fixes of a sheet entry, applied only while the sheet still holds the old
# value: (nct, arm, outcome, field, value on sheet) -> (value to store, comment added).
OWNER_FIXES = {
    ("NCT03473223", "CSL112", "trial", "N randomized", "9107"):
        ("9112", "sheet had 9107 (CSL112 and placebo swapped); paper gives CSL112 9112 "
                 "(abstract, p4, Tables 1-2); swap fixed with the owner's OK, 2026-11-17"),
    ("NCT03473223", "Placebo", "trial", "N randomized", "9112"):
        ("9107", "sheet had 9112 (CSL112 and placebo swapped); paper gives placebo 9107 "
                 "(abstract, p4, Tables 1-2); swap fixed with the owner's OK, 2026-11-17"),
}


# Decisions the owner made after the sheet, added once each, after the sheet decisions
# (decisions are never edited or deleted; the latest counts). Key: (nct, arm, outcome,
# field); value: (decision, corrected_value, comment, decided_at).
REVERT_34 = ("approve", None, "owner reverted: decision 34, post-exclusion counts belong in N analysed; per-arm split of all randomized not reported", "2026-11-17 16:00:00")
LATER_DECISIONS = {
    ("NCT03473223", "CSL112", "trial", "N randomized"): REVERT_34,
    ("NCT03473223", "Placebo", "trial", "N randomized"): REVERT_34,
    ("NCT02525939", "Dalcetrapib", "trial", "N randomized"): REVERT_34,
    ("NCT02525939", "Placebo", "trial", "N randomized"): REVERT_34,
}


def s(x):
    """Cell or JSON value as text; empty stays None (never invented)."""
    if x is None:
        return None
    x = str(x).strip()
    return x or None


def is_critical(v):
    if v["outcome"].startswith("primary") and (v["field"] in CRITICAL_PRIMARY
                                               or v["field"].startswith("p-value (")):
        return True
    return v["outcome"] == "trial" and v["field"] in CRITICAL_TRIAL


def label_ok(label, registry, factor_names):
    """Whole registry label first, then a ' + ' join of registry labels (decision 32);
    for factorial trials also a factor group of the paper (case-insensitive)."""
    label = label.strip()
    if label in registry:
        return True
    parts = [p.strip() for p in label.split(" + ")]
    if len(parts) > 1 and all(p in registry for p in parts):
        return True
    return label.lower() in factor_names


def add_decision(con, vid, decision, corrected, note, decided_at, shown):
    """Insert a decision unless the same one is already stored for this value
    (anywhere in its history, so a re-run never re-adds an overruled decision)."""
    if con.execute(
            "SELECT 1 FROM review_decisions WHERE value_id = ? AND decision = ? "
            "AND corrected_value IS ? AND comment IS ? AND value_shown IS ?",
            (vid, decision, corrected, note, shown)).fetchone():
        return False
    con.execute(
        "INSERT INTO review_decisions (value_id, decision, corrected_value, comment, "
        "decided_at, value_shown) VALUES (?, ?, ?, ?, ?, ?)",
        (vid, decision, corrected, note, decided_at, shown))
    return True


def check_labels(v, registry, factorial_comp):
    """Return '' if the arm and comparison labels pass, else the reason."""
    factor_names = set()
    if factorial_comp:
        factor_names = {p.strip().lower() for p in factorial_comp.split(" vs ")}
    arm, comp = v.get("arm"), v.get("comparison")
    if arm and not label_ok(arm, registry, factor_names):
        return f"arm label not a registry arm / '+' join / factor group: {arm}"
    if comp:
        if factorial_comp:
            if comp.strip().lower() != factorial_comp.strip().lower():
                return f"factorial comparison is not the paper's comparison name: {comp}"
        else:
            for side in comp.split(" vs "):
                if not label_ok(side, registry, set()):
                    return f"comparison side not a registry arm / '+' join: {side}"
    return ""


def read_sheet():
    wb = load_workbook(SHEET, read_only=True, data_only=True)
    ws = wb["review"]
    it = ws.iter_rows(values_only=True)
    head = [str(h) for h in next(it)]
    return [dict(zip(head, r)) for r in it if any(c is not None for c in r)]


def sheet_key(r):
    return tuple(s(r.get(k)) for k in ("trial", "paper", "comparison", "arm", "outcome",
                                       "field", "extracted_value"))


def main():
    if (SHEET.parent / f"~${SHEET.name}").exists():
        sys.exit(f"STOP: {SHEET.name} is open in Excel. Close it and re-run.")
    decided_at = datetime.fromtimestamp(SHEET.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    order, rows, values_in, _ = brs.build_rows()
    sheet = read_sheet()
    built = {}
    for r in rows:
        built.setdefault(sheet_key(r), []).append(r)
    dup = [k for k, v in built.items() if len(v) > 1]
    if dup:
        sys.exit(f"STOP: {len(dup)} values cannot be told apart on the sheet, e.g. {dup[0]}")
    unmatched = [r.get("row") for r in sheet if sheet_key(r) not in built]
    if unmatched or len(sheet) != len(rows):
        sys.exit(f"STOP: sheet and agent outputs differ ({len(sheet)} sheet rows, "
                 f"{len(rows)} values; unmatched sheet rows: {unmatched[:20]}). "
                 "Rebuild the sheet or check the outputs; nothing was loaded.")

    papers = {}
    with open(ROOT / "review" / "paper_list.csv", encoding="utf-8-sig") as f:
        for p in csv.DictReader(f):
            papers[(p["nct_id"], p["pmid"])] = p

    con = connect()
    skipped = Counter()
    refused = []
    pub_ids, n_pub_new = {}, 0
    ev_new = ev_upd = ev_same = 0
    dec = Counter()
    review_counts = Counter()
    try:
        # --- papers ---
        inputs = {}
        for nct in order:
            inp = brs.load(f"extractions/inputs/{nct}.json") or {}
            inputs[nct] = inp
            for p in inp.get("papers", []):
                meta = papers.get((nct, p["pmid"]), {})
                doi = s((meta.get("doi_link") or "").replace("https://doi.org/", ""))
                year = s(meta.get("year"))
                row = con.execute("SELECT publication_id FROM publications WHERE pmid = ?",
                                  (p["pmid"],)).fetchone()
                if row:
                    pid = row[0]
                else:
                    pid = con.execute(
                        "INSERT INTO publications (pmid, doi, title, journal, year) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (p["pmid"], doi, s(meta.get("title")) or s(p.get("title")),
                         s(meta.get("journal")), int(year) if year else None)).lastrowid
                    n_pub_new += 1
                pub_ids[(nct, p["pmid"])] = pid
                found = meta.get("found_by") or ""
                found_via = ("registry reference" if "registry" in found
                             else "PubMed search" if "PubMed" in found else None)
                con.execute(
                    "INSERT OR IGNORE INTO trial_publications "
                    "(nct_id, publication_id, role, found_via, pdf_file) "
                    "VALUES (?, ?, 'main results', ?, ?)",
                    (nct, pid, found_via, Path(p["file"]).name))

        # item_no: rows sharing nct + paper + arm + comparison + outcome + field are
        # numbered 1, 2, 3 in the order the extractor wrote them.
        item_no, seen = {}, Counter()
        for r in sorted(rows, key=lambda r: (r["_nct"], r["_sort"][2])):
            v = r["_v"]
            k = (r["_nct"], v.get("pmid"), v.get("arm") or "", v.get("comparison") or "",
                 v["outcome"], v["field"])
            seen[k] += 1
            item_no[id(r)] = seen[k]
        n_multi = sum(1 for n in seen.values() if n > 1)

        registry = {nct: {r[0] for r in con.execute(
            "SELECT arm_label FROM arms WHERE nct_id = ?", (nct,))} for nct in order}

        # --- values and decisions ---
        for sr in sheet:
            r = built[sheet_key(sr)][0]
            nct, v, c, qe, s1 = r["_nct"], r["_v"], r["_c"], r["_qe"], r["_s1"]
            inp = inputs[nct]
            fact_comp = None
            if inp.get("factorial"):
                fact_comp = next((p.get("comparison") for p in inp.get("papers", [])
                                  if p.get("pmid") == v.get("pmid")), None)
            why = check_labels(v, registry[nct], fact_comp)
            if why:
                refused.append(f"sheet row {sr.get('row')} {nct}: {why}")
                skipped["refused by the label check"] += 1
                continue
            pid = pub_ids.get((nct, v.get("pmid")))
            if pid is None:
                skipped["paper not in the extractor input"] += 1
                continue

            if s(sr.get("flagged")) == "yes":
                reason = "flagged"
            elif is_critical(v):
                reason = "critical value"
            else:
                reason = "remaining"
            qres = {"PASS": "pass", "FAIL": "fail"}.get((qe or {}).get("result"), "not run")
            imatch = 1 if s1 == "match" else 0 if s1.startswith("MISMATCH") else None
            vals = dict(
                extracted_value=s(v.get("value")), quote=s(v.get("quote")),
                page=s(v.get("page")), not_reported=1 if v.get("not_reported") else 0,
                confidence=s(v.get("confidence")),
                verifier_value=s((c or {}).get("verifier_value")),
                verifier_quote=s((c or {}).get("verifier_quote")),
                verifier_page=s((c or {}).get("verifier_page")),
                verifier_verdict=s((c or {}).get("verdict")),
                verifier_reason=s((c or {}).get("reason")),
                independent_match=imatch, code_check_result=qres,
                code_check_note=s((qe or {}).get("reason")), review_reason=reason)
            ino = item_no[id(r)]
            ident = (nct, pid, v.get("arm") or "", v.get("comparison") or "",
                     v["outcome"], v["field"], ino)
            row = con.execute(
                "SELECT value_id, extracted_value, review_reason FROM extracted_values "
                "WHERE nct_id = ? AND publication_id = ? AND COALESCE(arm, '') = ? "
                "AND COALESCE(comparison, '') = ? AND outcome = ? AND field = ? "
                "AND item_no = ?",
                ident).fetchone()
            if row:
                vid = row[0]
                if row[2] == "value changed after decision" and row[1] == vals["extracted_value"]:
                    vals.pop("review_reason")  # still waiting for a new decision
                current = con.execute(
                    f"SELECT {', '.join(vals)} FROM extracted_values WHERE value_id = ?",
                    (vid,)).fetchone()
                if tuple(current) == tuple(vals.values()):
                    ev_same += 1
                else:
                    sets = ", ".join(f"{k} = ?" for k in vals)
                    con.execute(f"UPDATE extracted_values SET {sets} WHERE value_id = ?",
                                (*vals.values(), vid))
                    ev_upd += 1
            else:
                cols = ["nct_id", "publication_id", "arm", "comparison", "outcome", "field",
                        "item_no", *vals]
                vid = con.execute(
                    f"INSERT INTO extracted_values ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))})",
                    (nct, pid, v.get("arm"), v.get("comparison"), v["outcome"], v["field"],
                     ino, *vals.values())).lastrowid
                ev_new += 1

            # decision
            my = (s(sr.get("my_decision")) or "").lower()
            shown = s(sr.get("extracted_value"))
            corrected = s(sr.get("corrected_value"))
            note = s(sr.get("my_note"))
            if not my:
                review_counts["not reviewed"] += 1
                continue
            if my == "unclear":
                review_counts["unclear (not stored, stays not reviewed)"] += 1
                continue
            if my == "correct":
                decision, corrected = "approve", None
            elif my == "wrong":
                decision = "correct" if corrected else "reject"
            else:
                skipped[f"unknown my_decision '{my}'"] += 1
                continue
            fix = OWNER_FIXES.get((nct, v.get("arm"), v["outcome"], v["field"], corrected))
            if fix:
                corrected = fix[0]
                note = f"{note}; {fix[1]}" if note else fix[1]
                dec["owner-confirmed fix applied"] += 1
            review_counts["reviewed"] += 1
            if add_decision(con, vid, decision, corrected, note, decided_at, shown):
                dec[decision] += 1
                if shown != vals["extracted_value"]:
                    dec["stored, but value changed since the sheet (back to review)"] += 1
            else:
                dec["already stored (skipped)"] += 1
            later = LATER_DECISIONS.get((nct, v.get("arm"), v["outcome"], v["field"]))
            if later:
                d2, c2, n2, t2 = later
                if add_decision(con, vid, d2, c2, n2, t2, vals["extracted_value"]):
                    dec[f"later owner decision ({d2})"] += 1
                else:
                    dec["later owner decision already stored (skipped)"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        stale = con.execute("SELECT COUNT(*) FROM extracted_values "
                            "WHERE review_reason = 'value changed after decision'").fetchone()[0]
        final_set = con.execute("SELECT COUNT(*) FROM extracted_values "
                                "WHERE final_value IS NOT NULL").fetchone()[0]
        con.close()

    print("=== Summary ===")
    print(f"Trials:                    {len(order)}")
    print(f"Sheet rows in:             {len(sheet)}   (agent values in: {values_in})")
    print(f"Papers:                    {len(pub_ids)} linked ({n_pub_new} new in publications)")
    print(f"Values out:                {ev_new} inserted, {ev_upd} updated, {ev_same} unchanged")
    print(f"  fields with several numbered rows (item_no): {n_multi}")
    for k in ("reviewed", "not reviewed", "unclear (not stored, stays not reviewed)"):
        print(f"  {k}: {review_counts[k]}")
    print("Decisions out:             " + ", ".join(f"{k} {n}" for k, n in dec.items()))
    print(f"Values with a final value: {final_set}; waiting after a value change: {stale}")
    print(f"Skipped:                   {sum(skipped.values())}")
    for k, n in skipped.items():
        print(f"  {k}: {n}")
    for line in refused:
        print(f"  {line}")


if __name__ == "__main__":
    main()
