"""Find candidate results papers (SPEC.md pipeline step 3, decisions 8 and 28).

Usage:
    .venv\\Scripts\\python scripts\\find_papers.py

Goes down the completed and terminated trials from the largest registry
enrollment to the smallest, until TARGET trials have a proposed main results
paper. For each trial:
  1. the registry's RESULT references (from the raw JSON in data/raw/);
  2. a PubMed search by NCT number (E-utilities esearch: "<NCT>[si] OR <NCT>").
Every paper found gets its PubMed metadata (esummary: title, journal, year,
DOI, publication types). Metadata only: nothing is downloaded, at most 3
requests per second, no login, no personal details sent.

Each paper is flagged when its title suggests a design paper, sub-study or
secondary analysis, its PubMed type is not an original article, or it was
published before the trial's primary completion year (it can't report the
results). The proposed main results paper is the earliest unflagged paper
with a trial publication type (Randomized Controlled Trial / Clinical Trial);
a trial with none is skipped and the next largest is used. Another unflagged
trial paper in the same journal and year is noted as a possible second main
paper (e.g. a factorial trial). The proposal is a draft: the
project owner confirms each one in review/paper_list.csv (decision column).

Writes review/paper_list.csv (one row per paper; the proposed main paper
first, with the file name to save it as). Nothing is written to the database.
"""

import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import requests

from create_database import DB_PATH, connect
from draft_cleaning import merge_with_existing
from review_files import REVIEW_DIR, write_csv

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = REVIEW_DIR / "paper_list.csv"
TARGET = 10                      # decision 28
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = {"tool": "trial-db-script"}   # generic name, no contact details
PAUSE = 0.35                     # seconds between requests: under 3 per second

COLUMNS = ["nct_id", "acronym", "enrollment", "timing_after_mi", "pmid", "title", "journal",
           "year", "doi_link", "found_by", "pubmed_types", "flag", "proposed_main",
           "file_name", "note", "decision", "comment"]
KEY = ["nct_id", "pmid"]
OWNER_COLUMNS = ["decision", "comment"]
# Factorial trials with one main results paper per comparison (owner decision
# 2026-11-16, SPEC decision 31): {nct_id: {pmid: (file name, note)}}. Each paper
# is linked to its own registered primary outcome(s).
FACTORIAL_MAIN_PAPERS = {
    "NCT03048825": {
        "39555814": ("NCT03048825.pdf",
                     "factorial trial: main paper for the spironolactone comparison; registered "
                     "primary outcomes #650, #651. #648 not assessed (stent performance-goal "
                     "comparison; no drug paper covers it)"),
        "39555823": ("NCT03048825_colchicine.pdf",
                     "factorial trial: main paper for the colchicine comparison; registered "
                     "primary outcome #649"),
    },
}

FLAG_WORDS = re.compile(
    r"\b(design|rationale|protocol|baseline characteristics|sub-?stud(y|ies)|secondary|"
    r"post[- ]?hoc|sub-?analys[ie]s|subgroups?|insights?|pre-?specified|cost|economic|"
    r"statistical analysis plan|methodology|analysis (of|from) the|sex differences|"
    r"exploratory|pre-?defined|"
    r"in women|by sex|pharmacokinetic|genetic|biomarkers?)\b", re.IGNORECASE)
NOT_ORIGINAL = {"Review", "Editorial", "Comment", "Letter", "News", "Published Erratum",
                "Systematic Review", "Meta-Analysis"}
TRIAL_TYPES = re.compile(r"Randomized Controlled Trial|Clinical Trial", re.IGNORECASE)


class StopError(Exception):
    pass


def get(endpoint, params):
    """One E-utilities request, with up to 3 tries; pauses to stay under 3 per second."""
    for attempt in range(3):
        time.sleep(PAUSE)
        try:
            r = requests.get(EUTILS + endpoint, params={**TOOL, **params}, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise StopError(f"PubMed did not answer ({last}). Nothing was written.")


def pubmed_search(nct_id):
    data = get("esearch.fcgi", {"db": "pubmed", "term": f"{nct_id}[si] OR {nct_id}",
                                "retmode": "json", "retmax": 100})
    return data["esearchresult"]["idlist"]


def pubmed_summaries(pmids):
    """{pmid: summary} for a list of PMIDs (batches of 100)."""
    out = {}
    for i in range(0, len(pmids), 100):
        data = get("esummary.fcgi", {"db": "pubmed", "id": ",".join(pmids[i:i + 100]),
                                     "retmode": "json"})["result"]
        for pmid in data.get("uids", []):
            out[pmid] = data[pmid]
    return out


def flag_of(title, types, year, completion_year):
    reasons = []
    if year and completion_year and year < completion_year:
        reasons.append(f"published {year}, before the trial's primary completion ({completion_year})")
    hit = FLAG_WORDS.search(title or "")
    if hit:
        reasons.append(f"title suggests design / sub-study / secondary analysis ('{hit.group(0)}')")
    other = sorted(set(types) & NOT_ORIGINAL)
    if other:
        reasons.append("not an original article (" + ", ".join(other) + ")")
    return "; ".join(reasons)


def main():
    if not DB_PATH.exists():
        raise StopError(f"{DB_PATH} does not exist.")
    con = connect()
    try:
        trials = con.execute(
            "SELECT nct_id, enrollment, timing_after_mi, raw_json_file FROM trials "
            "WHERE overall_status IN ('COMPLETED', 'TERMINATED') "
            "ORDER BY enrollment DESC, nct_id").fetchall()
    finally:
        con.close()

    rows, picked, skipped, stats = [], [], [], Counter()
    requests_made = 0
    for nct_id, enrollment, timing, raw_file in trials:
        if len(picked) == TARGET:
            break
        protocol = json.loads((ROOT / raw_file).read_text(encoding="utf-8"))["protocolSection"]
        acronym = protocol.get("identificationModule", {}).get("acronym") or ""
        completion_year = (protocol.get("statusModule", {}).get("primaryCompletionDateStruct", {})
                           .get("date") or "")[:4]
        registry = [r["pmid"] for r in protocol.get("referencesModule", {}).get("references", [])
                    if r.get("type") == "RESULT" and r.get("pmid")]
        searched = pubmed_search(nct_id)
        requests_made += 1
        pmids = list(dict.fromkeys(registry + searched))
        summaries = pubmed_summaries(pmids) if pmids else {}
        requests_made += (len(pmids) + 99) // 100
        papers = []
        for pmid in pmids:
            s = summaries.get(pmid)
            if not s:
                stats["PMID without a PubMed summary (left out)"] += 1
                continue
            types = s.get("pubtype", [])
            doi = next((a["value"] for a in s.get("articleids", []) if a.get("idtype") == "doi"), "")
            found_by = " + ".join(x for x, ok in (("registry RESULT reference", pmid in registry),
                                                  ("PubMed NCT search", pmid in searched)) if ok)
            papers.append({
                "nct_id": nct_id, "acronym": acronym, "enrollment": enrollment,
                "timing_after_mi": timing or "", "pmid": pmid, "title": s.get("title", ""),
                "journal": s.get("source", ""), "year": (s.get("pubdate") or "")[:4],
                "doi_link": f"https://doi.org/{doi}" if doi else "", "found_by": found_by,
                "pubmed_types": "; ".join(types),
                "flag": flag_of(s.get("title"), types, (s.get("pubdate") or "")[:4],
                                completion_year),
                "proposed_main": "", "file_name": "", "note": "", "decision": "", "comment": ""})
        candidates = [p for p in papers if not p["flag"] and TRIAL_TYPES.search(p["pubmed_types"])]
        if not candidates:
            skipped.append((nct_id, acronym, enrollment, len(papers)))
            continue
        main_paper = min(candidates, key=lambda p: (p["year"] or "9999",
                                                    "registry" not in p["found_by"], p["pmid"]))
        main_paper["proposed_main"] = "yes"
        main_paper["file_name"] = f"{nct_id}.pdf"
        for p in candidates:
            if p is not main_paper and (p["journal"], p["year"]) == (main_paper["journal"],
                                                                      main_paper["year"]):
                p["note"] = (f"possible second main paper (same journal and year as PMID "
                             f"{main_paper['pmid']}, e.g. a factorial trial): owner decides")
                main_paper["note"] = f"see also PMID {p['pmid']} (possible second main paper)"
                stats["possible second main papers"] += 1
        if nct_id in FACTORIAL_MAIN_PAPERS:
            # Owner decision: one factorial trial, one main paper per comparison.
            for p in papers:
                setting = FACTORIAL_MAIN_PAPERS[nct_id].get(p["pmid"])
                p["proposed_main"], p["file_name"] = ("yes", setting[0]) if setting else ("", "")
                p["note"] = setting[1] if setting else p["note"]
            stats["factorial trials (two main papers)"] += 1
        papers.sort(key=lambda p: (p["proposed_main"] != "yes", p["year"], p["pmid"]))
        rows.extend(papers)
        picked.append((nct_id, acronym, enrollment, timing, len(papers)))
        stats["papers listed"] += len(papers)
        stats["flagged papers"] += sum(1 for p in papers if p["flag"])

    merged, counts = merge_with_existing(OUT_FILE, KEY, rows, OWNER_COLUMNS)
    order = {nct: i for i, (nct, *_rest) in enumerate(picked)}
    merged.sort(key=lambda r: (order.get(r["nct_id"], len(order)), r.get("proposed_main") != "yes",
                               r.get("year", ""), r.get("pmid", "")))
    try:
        write_csv(OUT_FILE, COLUMNS, merged)
    except PermissionError:
        raise StopError(f"{OUT_FILE} is open in another program (probably Excel). "
                        "Save and close it, then run this script again.")

    print(f"Completed or terminated trials: {len(trials)}; checked from the largest down: "
          f"{len(picked) + len(skipped)}")
    for i, (nct_id, acronym, enrollment, timing, n) in enumerate(picked, 1):
        main_row = next(r for r in rows if r["nct_id"] == nct_id and r["proposed_main"] == "yes")
        print(f"  {i:2}. {nct_id} {acronym or '-'} (n={enrollment}, {timing or 'no timing'}): "
              f"{n} papers; main PMID {main_row['pmid']} ({main_row['journal']} {main_row['year']})")
    for nct_id, acronym, enrollment, n in skipped:
        print(f"  skipped {nct_id} {acronym or '-'} (n={enrollment}): no unflagged trial paper "
              f"among {n} found")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"PubMed requests: {requests_made} (metadata only)")
    print(f"{OUT_FILE.name}: {len(merged)} rows ({', '.join(f'{k} {v}' for k, v in counts.items())})")
    print(f"Summary: records in {len(picked) + len(skipped)} trials checked, out {len(picked)} "
          f"trials with a proposed main paper ({len(merged)} paper rows), skipped {len(skipped)} "
          "(no main results paper found)")


if __name__ == "__main__":
    try:
        main()
    except (StopError, sqlite3.Error, OSError) as e:
        print(f"STOPPED: {e}")
        print("Summary: stopped on error; see the message above.")
        sys.exit(1)
