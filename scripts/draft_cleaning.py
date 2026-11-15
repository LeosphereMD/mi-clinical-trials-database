"""Draft the registry-cleaning review files (SPEC.md "Registry cleaning", step 2a).

Usage:
    .venv\\Scripts\\python scripts\\draft_cleaning.py

Writes, in review/:
    drug_names.csv   DRUG/BIOLOGICAL interventions without an exact MeSH match,
                     with a suggested_generic (a suggestion only)
    sponsors.csv     every lead sponsor, with a draft clean name and group
    why_stopped.csv  every stopped trial, with a draft category

Rows that already have a decision are never changed. Rows without one get
fresh drafts; new items are added. Nothing is written to the database.
"""

import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from create_database import DB_PATH, connect
from review_files import REVIEW_DIR, has_decision, read_csv, write_csv

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_SUGGESTIONS = REVIEW_DIR / "drug_name_suggestions_claude.csv"
CLAUDE_SOURCE = "Claude, from general knowledge: check"

# ------------------------------------------------------------ helpers

def words(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def merge_with_existing(path, key_cols, new_rows, owner_cols):
    """Combine fresh drafts with the existing file without losing the owner's work."""
    existing = read_csv(path) if path.exists() else []
    old = {tuple(r.get(k, "") for k in key_cols): r for r in existing}
    out, counts, seen = [], Counter(), set()
    for row in new_rows:
        key = tuple("" if row.get(k) is None else str(row.get(k)) for k in key_cols)
        seen.add(key)
        prev = old.get(key)
        if prev and has_decision(prev):
            out.append(prev)
            counts["kept (already decided)"] += 1
        elif prev:
            for c in owner_cols:
                row[c] = prev.get(c, "")
            out.append(row)
            counts["draft refreshed"] += 1
        else:
            out.append(row)
            counts["new"] += 1
    for key, prev in old.items():
        if key not in seen:
            out.append(prev)
            counts["kept (no longer in the database)"] += 1
    return out, counts


# ------------------------------------------------------------ 1. drug names

SALT_WORDS = {"hydrochloride", "calcium", "sodium", "phosphate", "potassium",
              "mesylate", "maleate", "besylate", "citrate", "sulfate", "hydrate"}
PLACEBO = re.compile(r"plac(?:e)?bos?", re.IGNORECASE)
COMBINATION = re.compile(r"\+|\bplus\b|\band\b", re.IGNORECASE)


def base_name(mesh_term):
    """'Rosuvastatin Calcium' -> 'rosuvastatin' (salt word at the end removed)."""
    parts = mesh_term.split()
    while len(parts) > 1 and parts[-1].lower() in SALT_WORDS:
        parts.pop()
    return " ".join(parts).lower()


def suggest_generic(name, other_names, mesh_terms):
    text = f"{name} {other_names or ''}"
    if PLACEBO.search(text) and not COMBINATION.search(name):
        return "placebo", "placebo"
    tokens = words(text)
    found = []
    for term in mesh_terms:
        base = base_name(term)
        if words(base) and words(base) <= tokens and base not in found:
            found.append(base)
    if found:
        return " + ".join(found), "registry MeSH, partial match"
    return "", ""


def drug_rows(con):
    mesh = defaultdict(list)
    for nct_id, term in con.execute(
            "SELECT nct_id, mesh_term FROM intervention_mesh "
            "WHERE match_type = 'direct term' AND mesh_term IS NOT NULL"):
        mesh[nct_id].append(term)
    claude = {}
    if CLAUDE_SUGGESTIONS.exists():
        for r in read_csv(CLAUDE_SUGGESTIONS):
            claude[(r["nct_id"], r["intervention_name"])] = (
                r["suggested_generic"].strip(), r.get("note", "").strip())
    rows, exact = [], 0
    for nct_id, itype, name, other in con.execute(
            "SELECT nct_id, intervention_type, name, other_names FROM interventions "
            "WHERE intervention_type IN ('DRUG', 'BIOLOGICAL') ORDER BY nct_id, name"):
        if name and name.strip().lower() in {t.lower() for t in mesh[nct_id]}:
            exact += 1
            continue
        # Order: placebo, then Claude's file (which also corrects misleading
        # registry partial matches), then the registry partial match.
        suggestion, source = suggest_generic(name or "", other, mesh[nct_id])
        note = ""
        if source != "placebo" and (nct_id, name) in claude:
            claude_suggestion, note = claude[(nct_id, name)]
            if claude_suggestion:
                suggestion, source = claude_suggestion, CLAUDE_SOURCE
        rows.append({
            "nct_id": nct_id, "intervention_type": itype, "intervention_name": name,
            "other_names": other, "registry_mesh_terms": "; ".join(mesh[nct_id]),
            "suggested_generic": suggestion,
            "suggestion_source": source or "no suggestion",
            "suggestion_note": note,
            "decision": "", "corrected_generic": "", "comment": ""})
    return rows, exact


# ------------------------------------------------------------ 2. sponsors

LEGAL_ENDING = re.compile(
    r"[,\s]+(?:inc|llc|llp|ltd|co\.?,?\s*ltd|pte\.?\s*ltd|a/s|ab|ag|gmbh|s\.?a|corp|plc)\.?$",
    re.IGNORECASE)
NETWORK = re.compile(r"network|cooperative|consortium|society|investigator group|"
                     r"research group|\bfoundation\b", re.IGNORECASE)
GOVERNMENT = re.compile(r"\bregion\b|\bNHS\b|seguro social|social security|ministry",
                        re.IGNORECASE)
ACADEMIC = re.compile(r"universit|hospita|h[ôo]pita|ospedal|policlinic|clinic|"
                      r"medical cent|medical corporation|institut|academ|college|"
                      r"collegium|school|centro|centre|hospices|herzzentrum|"
                      r"research cent|assistance publique|medical sciences",
                      re.IGNORECASE)
COMPANY = re.compile(r"\b(?:inc|llc|llp|ltd|gmbh|a/s|pte)\b|pharma|therapeutics|"
                     r"bioscience|biopharm", re.IGNORECASE)


def strip_legal(name):
    previous = None
    while previous != name:
        previous, name = name, LEGAL_ENDING.sub("", name).strip()
    return name


def name_key(name):
    text = unicodedata.normalize("NFKD", strip_legal(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def draft_group(name, sponsor_class):
    if sponsor_class in ("NIH", "FED"):
        return "government", f"1: registry class {sponsor_class}"
    if NETWORK.search(name):
        return "research network or cooperative group", f"2: word '{NETWORK.search(name).group(0)}'"
    if GOVERNMENT.search(name):
        return "government", f"3: word '{GOVERNMENT.search(name).group(0)}'"
    if ACADEMIC.search(name):
        return "academic or hospital", f"4: word '{ACADEMIC.search(name).group(0)}'"
    if sponsor_class == "INDUSTRY":
        return "industry", "5: registry class INDUSTRY"
    if COMPANY.search(name):
        return "industry", f"5: word '{COMPANY.search(name).group(0)}'"
    if sponsor_class == "NETWORK":
        return "research network or cooperative group", "6: registry class NETWORK"
    if sponsor_class in ("OTHER", "OTHER_GOV"):
        return "individual investigator", "7: no organization word"
    return "", "no rule fits: owner decides"


def sponsor_rows(con):
    sponsors = con.execute(
        "SELECT lead_sponsor, sponsor_class, COUNT(*) FROM trials "
        "WHERE lead_sponsor IS NOT NULL GROUP BY 1, 2 ORDER BY 1").fetchall()
    by_key = defaultdict(Counter)
    for name, _, n in sponsors:
        by_key[name_key(name)][strip_legal(name)] += n
    clean = {k: sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0] for k, c in by_key.items()}
    keys = {name: name_key(name) for name, _, _ in sponsors}
    rows = []
    for name, sponsor_class, n in sponsors:
        k = keys[name]
        related = sorted({other for other, ok in keys.items() if other != name and ok != k
                          and (ok.startswith(k + " ") or k.startswith(ok + " "))})
        same = sorted(o for o, ok in keys.items() if o != name and ok == k)
        group, basis = draft_group(name, sponsor_class)
        rows.append({
            "lead_sponsor": name, "registry_sponsor_class": sponsor_class, "n_trials": n,
            "draft_name_clean": clean[k], "merged_with": "; ".join(same),
            "possible_same_as": "; ".join(related),
            "draft_group": group, "draft_basis": basis,
            "decision": "", "corrected_name_clean": "", "corrected_group": "",
            "comment": ""})
    return rows


# ------------------------------------------------------------ 3. why_stopped

CATEGORY_RULES = [
    ("safety", r"safety|adverse|harm|toxicit|side effect|bleeding"),
    ("new outside evidence", r"no longer relevant|outcome of the .*(?:study|trial)|"
                             r"results? of (?:the|another|other) .*(?:study|trial)|"
                             r"new (?:data|evidence)|other (?:study|trial)|publication of"),
    ("lack of efficacy or futility", r"futil|efficacy|did not meet|not effective|"
                                     r"no benefit|lack of benefit"),
    ("COVID-19", r"covid|pandemic|sars-cov"),
    ("slow enrollment", r"slow|recruit|accrual|low enrol|poor enrol|insufficient enrol"),
    ("funding or commercial reasons", r"fund|grant|financ|commercial|budget|market"),
    ("regulatory", r"clinical hold|regulat|\bfda\b|authorit|ethic"),
    ("other sponsor decision", r"sponsor|business|strateg|portfolio|organi[sz]ational"),
]
SEE_DESCRIPTION = re.compile(r"detailed description", re.IGNORECASE)
EXCEL_CELL_LIMIT = 30000


def draft_category(text):
    if not text:
        return "not stated", "no reason given"
    for category, pattern in CATEGORY_RULES:
        hit = re.search(pattern, text, re.IGNORECASE)
        if hit:
            return category, f"word '{hit.group(0)}'"
    return "unclear", "no keyword matched"


def why_stopped_rows(con):
    rows = []
    for nct_id, status, why, raw_file in con.execute(
            "SELECT nct_id, overall_status, why_stopped, raw_json_file FROM trials "
            "WHERE why_stopped IS NOT NULL "
            "OR overall_status IN ('TERMINATED', 'WITHDRAWN', 'SUSPENDED') ORDER BY nct_id"):
        description = ""
        search_text = why
        if why and SEE_DESCRIPTION.search(why):
            study = json.loads((ROOT / raw_file).read_text(encoding="utf-8"))
            description = (study["protocolSection"].get("descriptionModule", {})
                           .get("detailedDescription") or "")
            search_text = f"{why} {description}"
            if len(description) > EXCEL_CELL_LIMIT:
                description = description[:EXCEL_CELL_LIMIT] + " [cut here: full text in raw file]"
        category, basis = draft_category(search_text)
        rows.append({
            "nct_id": nct_id, "overall_status": status, "why_stopped": why,
            "detailed_description": description, "draft_category": category,
            "draft_basis": basis, "decision": "", "corrected_category": "", "comment": ""})
    return rows


# ------------------------------------------------------------ main

def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist. Run create_database.py and fetch_trials.py first.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    REVIEW_DIR.mkdir(exist_ok=True)
    con = connect()
    try:
        drugs, exact = drug_rows(con)
        sponsors = sponsor_rows(con)
        stopped = why_stopped_rows(con)
    except (sqlite3.Error, OSError, KeyError, ValueError) as e:
        print(f"STOPPED: {e}")
        print("Summary: records in 0, out 0, skipped 0 (stopped; no files written)")
        sys.exit(1)
    finally:
        con.close()

    files = [
        ("drug_names.csv", ["nct_id", "intervention_type", "intervention_name"], drugs,
         ["decision", "corrected_generic", "comment"]),
        ("sponsors.csv", ["lead_sponsor"], sponsors,
         ["decision", "corrected_name_clean", "corrected_group", "comment"]),
        ("why_stopped.csv", ["nct_id", "why_stopped"], stopped,
         ["decision", "corrected_category", "comment"]),
    ]
    total_in = total_out = 0
    for filename, key_cols, rows, owner_cols in files:
        path = REVIEW_DIR / filename
        merged, counts = merge_with_existing(path, key_cols, rows, owner_cols)
        write_csv(path, list(rows[0].keys()) if rows else owner_cols, merged)
        total_in += len(rows)
        total_out += len(merged)
        print(f"{filename}: {len(merged)} rows ({', '.join(f'{k} {v}' for k, v in counts.items())})")

    print()
    print(f"Drug names: {exact} exact MeSH matches (go in without review), "
          f"{len(drugs)} to review")
    print("  suggestions: " + ", ".join(f"{k} {v}" for k, v in
                                       Counter(r["suggestion_source"] for r in drugs).items()))
    print("Sponsor groups (draft): " + ", ".join(
        f"{k} {v}" for k, v in Counter(r["draft_group"] for r in sponsors).most_common()))
    merged_names = sum(1 for r in sponsors if r["merged_with"])
    print(f"Sponsor spellings merged: {merged_names} names; "
          f"flagged as possibly the same: {sum(1 for r in sponsors if r['possible_same_as'])}")
    print("why_stopped (draft): " + ", ".join(
        f"{k} {v}" for k, v in Counter(r["draft_category"] for r in stopped).most_common()))
    print(f"Summary: records in {total_in} (drafted from the database), "
          f"out {total_out} rows in review files, skipped 0")


if __name__ == "__main__":
    main()
