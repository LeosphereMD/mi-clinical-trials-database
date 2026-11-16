"""Build the registry hand-check sheet (SPEC.md "Registry hand-check", step 2b).

Usage:
    .venv\\Scripts\\python scripts\\draft_registry_check.py

Writes review/registry_check.xlsx: one row per trial and field, for the
project owner to compare with the trial's page on ClinicalTrials.gov.
Rows on the sheet:
  1. 10 random trials, with the key fields: phase, overall status, start date,
     enrollment (with type), lead sponsor, primary outcome, population, and
     timing after MI (the label, with its evidence quote and source).
  2. Every population label that came from text (title, conditions or
     eligibility), for the population field.
  3. A random 15% (rounded up) of the MeSH-based population labels.
A trial picked in more than one way appears once per field, with every reason.

Random draws: each trial gets a fixed random number from the seed, the draw's
name and its NCT ID, and the lowest ones are drawn. The same database gives the same sample, and
a new trial in a later download doesn't reshuffle the others.

Rows that already have a decision are never changed. Nothing is written to the
database; load_registry_check.py loads the decisions.
"""

import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from create_database import DB_PATH, connect
from draft_cleaning import EXCEL_CELL_LIMIT
from fetch_trials import (ACS_MESH, NSTEMI_MESH, NSTEMI_WORDS, STEMI_MESH, STEMI_WORDS,
                          inclusion_criteria, population)
from review_files import REVIEW_DIR

ROOT = Path(__file__).resolve().parent.parent
SHEET_FILE = REVIEW_DIR / "registry_check.xlsx"
SEED = 20261116
N_RANDOM_TRIALS = 10
MESH_SAMPLE_SHARE = 0.15

REASON_RANDOM = "random trial"
REASON_TEXT = "text-based population"
REASON_MESH = "MeSH population sample"
DECISIONS = ["approve", "correct", "changed since download"]

# Fields in the order they appear for each trial.
FIELDS = ["phase", "overall status", "start date", "enrollment", "lead sponsor",
          "primary outcome", "population", "timing after MI"]

COLUMNS = ["nct_id", "ctgov_link", "field", "db_value", "population_source",
           "matching_words", "where_found", "selection_reason", "download_date",
           "decision", "corrected_value", "comment", "fetch_run_id"]
OWNER_COLUMNS = ["decision", "corrected_value", "comment"]
WIDTHS = {"nct_id": 13, "ctgov_link": 13, "field": 15, "db_value": 45,
          "population_source": 12, "matching_words": 25, "where_found": 45,
          "selection_reason": 24, "download_date": 12, "decision": 20,
          "corrected_value": 30, "comment": 30, "fetch_run_id": 8}
SNIPPET_CHARS = 60


def sample_order(draw_name, nct_id):
    """A fixed random number for this trial, from the seed, the draw and its NCT ID.
    Each draw has its own numbers, so the two draws are independent."""
    return hashlib.sha256(f"{SEED}-{draw_name}-{nct_id}".encode()).hexdigest()


def draw(draw_name, nct_ids, n):
    return set(sorted(nct_ids, key=lambda i: sample_order(draw_name, i))[:n])


def one_line(text):
    return " ".join((text or "").split())


def with_type(value, value_type):
    """'2015-03 (actual)'; just the value if the registry gives no type; blank if no value."""
    if value is None or value == "":
        return ""
    return f"{value} ({value_type.lower()})" if value_type else str(value)


def primary_outcome_text(outcomes):
    """All registered primary outcomes in one cell, numbered, each with its time frame."""
    parts = []
    for i, (measure, time_frame) in enumerate(outcomes, 1):
        text = one_line(measure)
        if time_frame:
            text += f" [time frame: {one_line(time_frame)}]"
        parts.append(f"{i}) {text}" if len(outcomes) > 1 else text)
    text = "\n".join(parts)
    if len(text) > EXCEL_CELL_LIMIT:
        text = text[:EXCEL_CELL_LIMIT] + " [cut here: full text in raw file]"
    return text


def hits_with_snippets(text):
    """(matching words, snippets) of the STEMI / NSTEMI words in a text."""
    found = []
    for m in NSTEMI_WORDS.finditer(text):
        found.append((m.start(), m.end()))
    masked = NSTEMI_WORDS.sub(lambda m: " " * len(m.group()), text)
    for m in STEMI_WORDS.finditer(masked):
        found.append((m.start(), m.end()))
    found.sort()
    words, snippets = [], []
    for start, end in found:
        word = text[start:end]
        if word.lower() not in (w.lower() for w in words):
            words.append(word)
            a, b = max(0, start - SNIPPET_CHARS), min(len(text), end + SNIPPET_CHARS)
            snippets.append(("..." if a else "") + one_line(text[a:b])
                            + ("..." if b < len(text) else ""))
    return "; ".join(words), "\n".join(snippets)


def population_details(study, label, source):
    """(matching words, where found) explaining the population label.
    Returns None for the words if the label from the raw file differs from the database."""
    raw_label, raw_source = population(study)
    if (raw_label, raw_source) != (label, source):
        return None, f"raw file gives {raw_label} ({raw_source})"
    p = study["protocolSection"]
    meshes = sorted({m.get("term") for m in study.get("derivedSection", {})
                     .get("conditionBrowseModule", {}).get("meshes", []) if m.get("term")})
    if source == "mesh":
        deciding = [m for m in meshes if m in ACS_MESH | {STEMI_MESH, NSTEMI_MESH}]
        if deciding:
            return "MeSH: " + "; ".join(deciding), "condition MeSH terms on the trial page"
        return ("MeSH: " + "; ".join(meshes),
                "no STEMI / NSTEMI words in the title, conditions or inclusion criteria")
    ident = p.get("identificationModule", {})
    if source == "title":
        text = " | ".join(t for t in (ident.get("briefTitle"), ident.get("officialTitle")) if t)
    elif source == "conditions":
        text = " | ".join(p.get("conditionsModule", {}).get("conditions", []))
    else:
        text = inclusion_criteria(p.get("eligibilityModule", {}).get("eligibilityCriteria"))
    return hits_with_snippets(text or "")


def build_rows(con):
    """(new sheet rows, statistics) from the database and raw files."""
    trials = con.execute(
        "SELECT t.nct_id, phase_label, overall_status, start_date, start_date_type, "
        "enrollment, enrollment_type, lead_sponsor, population, population_source, "
        "raw_json_file, last_seen_run, f.run_date, "
        "timing_after_mi, timing_after_mi_evidence, timing_after_mi_source "
        "FROM trials t LEFT JOIN fetch_runs f ON f.run_id = t.last_seen_run "
        "ORDER BY t.nct_id").fetchall()
    outcomes = {}
    for nct_id, measure, time_frame in con.execute(
            "SELECT nct_id, measure, time_frame FROM registered_outcomes "
            "WHERE outcome_type = 'primary' ORDER BY nct_id, registered_outcome_id"):
        outcomes.setdefault(nct_id, []).append((measure, time_frame))

    all_ids = [t[0] for t in trials]
    text_ids = [t[0] for t in trials if t[9] in ("title", "conditions", "eligibility")]
    mesh_ids = [t[0] for t in trials if t[9] == "mesh"]
    n_mesh = math.ceil(len(mesh_ids) * MESH_SAMPLE_SHARE)
    random_ids = draw(REASON_RANDOM, all_ids, N_RANDOM_TRIALS)
    mesh_sample = draw(REASON_MESH, mesh_ids, n_mesh)

    stats = Counter()
    rows = []
    for (nct_id, phase, status, start, start_type, enrollment, enrollment_type, sponsor,
         pop, pop_source, raw_file, run_id, run_date,
         timing, timing_evidence, timing_source) in trials:
        pop_reasons = [r for r, ids in ((REASON_RANDOM, random_ids),
                                        (REASON_TEXT, text_ids),
                                        (REASON_MESH, mesh_sample)) if nct_id in ids]
        if not pop_reasons:
            continue
        values = {}
        if nct_id in random_ids:
            values = {"phase": phase or "", "overall status": status or "",
                      "start date": with_type(start, start_type),
                      "enrollment": with_type(enrollment, enrollment_type),
                      "lead sponsor": sponsor or "",
                      "primary outcome": primary_outcome_text(outcomes.get(nct_id, [])),
                      "timing after MI": timing or ""}
        values["population"] = pop or ""

        words, where = "", ""
        raw_path = ROOT / raw_file if raw_file else None
        if raw_path and raw_path.exists():
            study = json.loads(raw_path.read_text(encoding="utf-8"))
            words, where = population_details(study, pop, pop_source)
            if words is None:
                stats["population differs between raw file and database"] += 1
                words = ""
        else:
            stats["raw file missing (no matching words shown)"] += 1
            where = "raw file missing"

        for field in FIELDS:
            if field not in values:
                continue
            is_pop = field == "population"
            if field == "timing after MI":
                timing_where = "; ".join(x for x in (
                    f"evidence: {one_line(timing_evidence)}" if timing_evidence else "",
                    f"source: {timing_source}" if timing_source else "") if x)
            rows.append({
                "nct_id": nct_id, "field": field, "db_value": values[field],
                "population_source": (pop_source or "") if is_pop else "",
                "matching_words": words if is_pop else "",
                "where_found": where if is_pop else (
                    timing_where if field == "timing after MI" else ""),
                "selection_reason": " + ".join(pop_reasons) if is_pop else REASON_RANDOM,
                "download_date": (run_date or "")[:10], "fetch_run_id": run_id,
                "decision": "", "corrected_value": "", "comment": ""})
    stats["trials in database"] = len(trials)
    stats["random trials"] = len(random_ids)
    stats["text-based labels"] = len(text_ids)
    stats["MeSH labels"] = len(mesh_ids)
    stats["MeSH labels drawn"] = len(mesh_sample)
    return rows, stats


def read_sheet(path):
    """Rows of an existing sheet as dicts (empty list if there is no file)."""
    if not path.exists():
        return []
    ws = load_workbook(path)["Checks"]
    header = [c.value for c in ws[1]]
    out = []
    for cells in ws.iter_rows(min_row=2, values_only=True):
        row = {h: ("" if v is None else str(v)) for h, v in zip(header, cells) if h}
        if row.get("nct_id"):
            out.append(row)
    return out


def merge(existing, new_rows):
    """Keep the owner's work. A row with a decision stays exactly as it is. A row
    without one gets fresh values but keeps a comment or corrected value the owner
    typed. A row no longer selected is kept only if the owner wrote something."""
    old = {(r["nct_id"], r["field"]): r for r in existing}
    out, counts, seen = [], Counter(), set()
    for row in new_rows:
        key = (row["nct_id"], row["field"])
        seen.add(key)
        prev = old.get(key)
        if prev and prev.get("decision", "").strip():
            out.append(prev)
            counts["kept with decision"] += 1
            continue
        if prev:
            for c in OWNER_COLUMNS:
                if prev.get(c, "").strip():
                    row[c] = prev[c]
            counts["refreshed, no decision yet"] += 1
        else:
            counts["new"] += 1
        out.append(row)
    for key, prev in old.items():
        if key in seen:
            continue
        if any(prev.get(c, "").strip() for c in OWNER_COLUMNS):
            out.append(prev)
            counts["kept: no longer selected, but has owner input"] += 1
        else:
            counts["dropped: no longer selected"] += 1
    out.sort(key=lambda r: (r["nct_id"], FIELDS.index(r["field"])
                            if r["field"] in FIELDS else len(FIELDS)))
    return out, counts


def write_sheet(path, rows, stats):
    wb = Workbook()
    about = wb.active
    about.title = "About"
    lines = [
        ("Registry hand-check (SPEC.md step 2b)", True),
        (f"Sheet made on {date.today().isoformat()} by scripts/draft_registry_check.py", False),
        (f"Random seed: {SEED}", True),
        ("", False),
        ("What is on the 'Checks' tab", True),
        (f"- {stats['random trials']} random trials, with the key fields (incl. timing after MI)",
         False),
        (f"- every population label that came from text ({stats['text-based labels']} trials)",
         False),
        (f"- a random 15% of the MeSH-based labels ({stats['MeSH labels drawn']} of "
         f"{stats['MeSH labels']}, rounded up)", False),
        ("A trial picked in more than one way appears once per field, with every reason.",
         False),
        ("", False),
        ("How to check", True),
        ("1. Click the link in 'ctgov_link' to open the trial's page.", False),
        ("2. Compare 'db_value' with what the page shows.", False),
        ("3. Pick a decision: approve (matches), correct (database is wrong: type the right "
         "value in 'corrected_value'), or changed since download (the page was updated after "
         "the download date; not an error).", False),
        ("4. Population rows: 'population_source' says where the label came from, "
         "'matching_words' the words or MeSH terms that set it, and 'where_found' the text "
         "around them. Labels follow SPEC.md \"Population label\".", False),
        ("4b. Timing after MI rows: compare the label with the inclusion criteria on the "
         "page (acute = within 7 days or during the index hospitalisation; recent = latest allowed "
         "8 days to 6 months; prior = more than 6 months or history of MI). 'where_found' "
         "holds the evidence quote and the label's source.", False),
        ("5. Save the file (keep it as .xlsx), close Excel, and run "
         "scripts/load_registry_check.py.", False),
        ("", False),
        ("Codes used in db_value", True),
        ("Phase: PHASE3 = Phase 3; PHASE2/PHASE3 = Phase 2/Phase 3. Status and type are in "
         "capitals as the registry stores them (e.g. COMPLETED, actual / estimated).", False),
        ("Start date with no type in brackets: the registry gives no actual/estimated label.",
         False),
        ("Primary outcome: every registered primary outcome, numbered, with its time frame.",
         False),
    ]
    for i, (text, bold) in enumerate(lines, 1):
        cell = about.cell(row=i, column=1, value=text)
        cell.font = Font(bold=bold)
    about.column_dimensions["A"].width = 120

    ws = wb.create_sheet("Checks")
    ws.append(COLUMNS)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    owner_fill = PatternFill("solid", fgColor="FFF2CC")
    for i, name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True)
        cell.fill = owner_fill if name in OWNER_COLUMNS else head_fill
        ws.column_dimensions[cell.column_letter].width = WIDTHS[name]
    for r, row in enumerate(rows, 2):
        for i, name in enumerate(COLUMNS, 1):
            value = row.get(name, "")
            if name == "ctgov_link":
                value = row["nct_id"]
            if name == "fetch_run_id" and str(value).isdigit():
                value = int(value)
            cell = ws.cell(row=r, column=i, value=value if value != "" else None)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if name == "ctgov_link":
                cell.hyperlink = f"https://clinicaltrials.gov/study/{row['nct_id']}"
                cell.font = Font(color="0563C1", underline="single")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"',
                        allow_blank=True)
    col = ws.cell(row=1, column=COLUMNS.index("decision") + 1).column_letter
    dv.add(f"{col}2:{col}{max(len(rows) + 1, 2)}")
    ws.add_data_validation(dv)
    wb.active = 1
    wb.save(path)


def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    con = connect()
    try:
        new_rows, stats = build_rows(con)
    except sqlite3.Error as e:
        print(f"STOPPED: {e}")
        print("Summary: records in 0, out 0, skipped 0 (stopped; no file written)")
        sys.exit(1)
    finally:
        con.close()

    try:
        existing = read_sheet(SHEET_FILE)
    except (KeyError, OSError) as e:
        print(f"STOPPED: could not read the existing {SHEET_FILE.name} ({e}). "
              "Nothing was changed.")
        print("Summary: no file written")
        sys.exit(1)
    merged, counts = merge(existing, new_rows)
    try:
        write_sheet(SHEET_FILE, merged, stats)
    except PermissionError:
        print(f"STOPPED: {SHEET_FILE} is open in another program (probably Excel). "
              "Save and close it, then run this script again.")
        print("Summary: no file written")
        sys.exit(1)

    n_trials = stats["trials in database"]
    picked = len({r["nct_id"] for r in new_rows})
    print(f"Trials in the database: {n_trials} (seed {SEED})")
    print(f"Selected: {stats['random trials']} random trials; "
          f"{stats['text-based labels']} text-based population labels; "
          f"{stats['MeSH labels drawn']} of {stats['MeSH labels']} MeSH labels")
    print("Rows by field: " + ", ".join(
        f"{k} {v}" for k, v in Counter(r["field"] for r in merged).items()))
    for problem in ("population differs between raw file and database",
                    "raw file missing (no matching words shown)"):
        if stats[problem]:
            print(f"WARNING: {problem}: {stats[problem]} trials")
    print(f"{SHEET_FILE.name}: {len(merged)} rows "
          f"({', '.join(f'{k} {v}' for k, v in counts.items())})")
    print(f"Summary: records in {n_trials} trials, out {len(merged)} rows for "
          f"{picked} trials, skipped {n_trials - picked} trials (not selected for the check)")


if __name__ == "__main__":
    main()
